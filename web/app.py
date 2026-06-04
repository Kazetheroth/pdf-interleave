from __future__ import annotations

import asyncio
import re
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from starlette.formparsers import MultiPartParser

from core.pagerange import PageRangeError, build_page_sequence
from core.validate import ValidationError, validate_no_duplicates
from web.config import load_settings
from web.rate_limit import RateLimiter
from web.store import RamTokenStore, StoreFullError


class UserInputError(ValueError):
    """Raised for user-correctable request validation issues."""


SETTINGS = load_settings()
STORE = RamTokenStore(max_entries=SETTINGS.max_active_jobs)
RATE_LIMITER = RateLimiter()
MERGE_SEMAPHORE = asyncio.Semaphore(SETTINGS.max_active_jobs)

# Keep multipart bodies in RAM for expected request sizes.
if hasattr(MultiPartParser, "max_file_size"):
    MultiPartParser.max_file_size = SETTINGS.multipart_memory_limit_bytes

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

TRANSLATIONS = {
    "en": {
        "page_title": "PDF Interleave",
        "result_title": "PDF Interleave Result",
        "meta_prefix": "RAM-only output, link TTL",
        "meta_middle": "max",
        "meta_suffix": "MB per file, up to",
        "meta_end": "files.",
        "tab_interleave": "Interleave 2 PDFs",
        "tab_concat": "Merge N PDFs",
        "tab_images": "Images to PDF",
        "operation_label": "PDF operation",
        "pdf_a": "PDF A",
        "pdf_b": "PDF B",
        "order_a": "Order A",
        "order_b": "Order B",
        "order_asc": "Ascending",
        "order_desc": "Descending",
        "order_range": "Range",
        "order_list": "List",
        "order_slice": "Slice",
        "pages_a": "Pages A (optional for asc/desc)",
        "pages_b": "Pages B (optional for asc/desc)",
        "start": "Start",
        "policy": "Policy",
        "policy_append": "Append",
        "policy_truncate": "Truncate",
        "policy_error": "Error",
        "strict": "Strict mode (reject duplicate pages)",
        "merge_button": "Merge PDFs",
        "pdfs": "PDFs",
        "images": "Images",
        "output_order": "Output follows the order shown above.",
        "image_output_order": "The PDF follows the image order shown above.",
        "auto_orient": "Auto-orient images from EXIF data",
        "create_pdf_button": "Create PDF",
        "up_button": "Up",
        "down_button": "Dn",
        "remove_button": "Remove",
        "result_ready": "Merged PDF Ready",
        "size": "Size",
        "size_unit": "KB",
        "expires_at": "Expires at",
        "one_shot_policy": "Link policy: one-shot download enabled.",
        "reusable_policy": "Link policy: reusable until expiration.",
        "download": "Download PDF",
        "back": "Back",
        "token": "Token",
    },
    "fr": {
        "page_title": "PDF Interleave",
        "result_title": "Résultat PDF Interleave",
        "meta_prefix": "Sortie en RAM uniquement, lien valable",
        "meta_middle": "max",
        "meta_suffix": "Mo par fichier, jusqu'à",
        "meta_end": "fichiers.",
        "tab_interleave": "Entrelacer 2 PDFs",
        "tab_concat": "Fusionner N PDFs",
        "tab_images": "Images vers PDF",
        "operation_label": "Opération PDF",
        "pdf_a": "PDF A",
        "pdf_b": "PDF B",
        "order_a": "Ordre A",
        "order_b": "Ordre B",
        "order_asc": "Croissant",
        "order_desc": "Décroissant",
        "order_range": "Plage",
        "order_list": "Liste",
        "order_slice": "Tranche",
        "pages_a": "Pages A (optionnel pour asc/desc)",
        "pages_b": "Pages B (optionnel pour asc/desc)",
        "start": "Départ",
        "policy": "Politique",
        "policy_append": "Ajouter le reste",
        "policy_truncate": "Tronquer",
        "policy_error": "Erreur",
        "strict": "Mode strict (refuser les pages en double)",
        "merge_button": "Fusionner les PDFs",
        "pdfs": "PDFs",
        "images": "Images",
        "output_order": "La sortie suit l'ordre affiché ci-dessus.",
        "image_output_order": "Le PDF suit l'ordre des images affiché ci-dessus.",
        "auto_orient": "Orientation automatique depuis les données EXIF",
        "create_pdf_button": "Créer le PDF",
        "up_button": "Haut",
        "down_button": "Bas",
        "remove_button": "Supprimer",
        "result_ready": "PDF fusionné prêt",
        "size": "Taille",
        "size_unit": "Ko",
        "expires_at": "Expire le",
        "one_shot_policy": "Politique du lien : téléchargement unique activé.",
        "reusable_policy": "Politique du lien : réutilisable jusqu'à expiration.",
        "download": "Télécharger le PDF",
        "back": "Retour",
        "token": "Jeton",
    },
}


@asynccontextmanager
async def lifespan(_: FastAPI):
    task = asyncio.create_task(_cleanup_loop())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


app = FastAPI(title="PDF Interleave Web", lifespan=lifespan)


async def _cleanup_loop() -> None:
    while True:
        STORE.purge_expired()
        await asyncio.sleep(SETTINGS.cleanup_interval_seconds)


@app.middleware("http")
async def add_no_cache_and_limit_request_size(request: Request, call_next):
    if request.method == "POST" and request.url.path in {
        "/merge",
        "/concat",
        "/images",
        "/api/merge",
        "/api/concat",
        "/api/images",
    }:
        content_length = request.headers.get("content-length")
        if content_length is None:
            return JSONResponse(status_code=411, content={"detail": "Content-Length header required."})
        try:
            size = int(content_length)
        except ValueError:
            return JSONResponse(status_code=400, content={"detail": "Invalid Content-Length header."})
        if size > SETTINGS.max_request_bytes:
            return JSONResponse(status_code=413, content={"detail": "Request too large."})

    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return response


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return _render_index(request=request)


@app.post("/merge", response_class=HTMLResponse)
async def merge_ui(
    request: Request,
    file_a: UploadFile = File(...),
    file_b: UploadFile = File(...),
    order_a: str = Form("asc"),
    order_b: str = Form("asc"),
    pages_a: str | None = Form(default=None),
    pages_b: str | None = Form(default=None),
    start: str = Form("A"),
    policy: str = Form("append"),
    strict: str | None = Form(default=None),
):
    _enforce_rate_limit(request, kind="merge")
    try:
        result = await _process_merge(
            request=request,
            file_a=file_a,
            file_b=file_b,
            order_a=order_a,
            order_b=order_b,
            pages_a=pages_a,
            pages_b=pages_b,
            start=start,
            policy=policy,
            strict=(strict is not None),
        )
    except UserInputError as exc:
        return _render_index(
            request=request,
            error_message=str(exc),
            form_values={
                "order_a": order_a,
                "order_b": order_b,
                "pages_a": pages_a or "",
                "pages_b": pages_b or "",
                "start": start,
                "policy": policy,
                "strict": strict is not None,
            },
        )

    return _render_result(request=request, result=result)


@app.post("/concat", response_class=HTMLResponse)
async def concat_ui(
    request: Request,
    files: list[UploadFile] = File(...),
    order: str | None = Form(default=None),
):
    _enforce_rate_limit(request, kind="merge")
    try:
        result = await _process_concat(
            request=request,
            files=files,
            order=order,
        )
    except UserInputError as exc:
        return _render_index(
            request=request,
            error_message=str(exc),
            form_values={"mode": "concat"},
        )

    return _render_result(request=request, result=result)


@app.post("/images", response_class=HTMLResponse)
async def images_ui(
    request: Request,
    files: list[UploadFile] = File(...),
    order: str | None = Form(default=None),
    auto_orient: str | None = Form(default=None),
):
    _enforce_rate_limit(request, kind="merge")
    try:
        result = await _process_images(
            request=request,
            files=files,
            order=order,
            auto_orient=(auto_orient is not None),
        )
    except UserInputError as exc:
        return _render_index(
            request=request,
            error_message=str(exc),
            form_values={"mode": "images"},
        )

    return _render_result(request=request, result=result)


@app.get("/download/{token}", name="download_file")
async def download_file(request: Request, token: str):
    _enforce_rate_limit(request, kind="download")
    entry = STORE.pop_valid(token) if SETTINGS.one_shot_download else STORE.get_valid(token)
    if entry is None:
        raise HTTPException(status_code=404, detail="Link expired.")

    headers = {"Content-Disposition": f'attachment; filename="{entry.filename}"'}
    return StreamingResponse(BytesIO(entry.bytes), media_type="application/pdf", headers=headers)


@app.post("/api/merge")
async def merge_api(
    request: Request,
    file_a: UploadFile = File(...),
    file_b: UploadFile = File(...),
    order_a: str = Form("asc"),
    order_b: str = Form("asc"),
    pages_a: str | None = Form(default=None),
    pages_b: str | None = Form(default=None),
    start: str = Form("A"),
    policy: str = Form("append"),
    strict: bool = Form(False),
):
    _enforce_rate_limit(request, kind="merge")
    try:
        result = await _process_merge(
            request=request,
            file_a=file_a,
            file_b=file_b,
            order_a=order_a,
            order_b=order_b,
            pages_a=pages_a,
            pages_b=pages_b,
            start=start,
            policy=policy,
            strict=strict,
        )
    except UserInputError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return JSONResponse(
        {
            "token": result["token"],
            "download_url": result["download_url"],
            "expires_at": result["expires_at_iso"],
            "size": result["size"],
        }
    )


@app.post("/api/concat")
async def concat_api(
    request: Request,
    files: list[UploadFile] = File(...),
    order: str | None = Form(default=None),
):
    _enforce_rate_limit(request, kind="merge")
    try:
        result = await _process_concat(
            request=request,
            files=files,
            order=order,
        )
    except UserInputError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return JSONResponse(
        {
            "token": result["token"],
            "download_url": result["download_url"],
            "expires_at": result["expires_at_iso"],
            "size": result["size"],
        }
    )


@app.post("/api/images")
async def images_api(
    request: Request,
    files: list[UploadFile] = File(...),
    order: str | None = Form(default=None),
    auto_orient: bool = Form(True),
):
    _enforce_rate_limit(request, kind="merge")
    try:
        result = await _process_images(
            request=request,
            files=files,
            order=order,
            auto_orient=auto_orient,
        )
    except UserInputError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return JSONResponse(
        {
            "token": result["token"],
            "download_url": result["download_url"],
            "expires_at": result["expires_at_iso"],
            "size": result["size"],
        }
    )


@app.get("/api/status/{token}")
async def status_api(token: str):
    entry = STORE.get_valid(token)
    if entry is None:
        raise HTTPException(status_code=404, detail="Link expired.")
    return {
        "active": True,
        "expires_at": datetime.fromtimestamp(entry.expires_at, tz=timezone.utc).isoformat(),
        "size": entry.size,
        "filename": entry.filename,
    }


@app.delete("/api/token/{token}")
async def delete_token_api(token: str):
    return {"deleted": STORE.delete(token)}


def _render_index(
    *,
    request: Request,
    error_message: str | None = None,
    form_values: dict[str, object] | None = None,
):
    values = {
        "order_a": "asc",
        "order_b": "asc",
        "pages_a": "",
        "pages_b": "",
        "start": "A",
        "policy": "append",
        "strict": False,
        "auto_orient": True,
        "mode": "interleave",
    }
    if form_values:
        values.update(form_values)

    return TEMPLATES.TemplateResponse(
        request=request,
        name="index.html",
        context={
            **_language_context(request),
            "error_message": error_message,
            "values": values,
            "max_file_mb": SETTINGS.max_file_mb,
            "max_upload_files": SETTINGS.max_upload_files,
            "ttl_seconds": SETTINGS.download_ttl_seconds,
        },
    )


def _render_result(*, request: Request, result: dict[str, object]):
    return TEMPLATES.TemplateResponse(
        request=request,
        name="result.html",
        context={
            **_language_context(request),
            "token": result["token"],
            "download_url": result["download_url"],
            "expires_at": result["expires_at_human"],
            "size_kb": round(result["size"] / 1024, 2),
            "one_shot": SETTINGS.one_shot_download,
        },
    )


def _language_context(request: Request) -> dict[str, object]:
    lang = _preferred_language(request.headers.get("accept-language", ""))
    return {
        "lang": lang,
        "t": TRANSLATIONS[lang],
    }


def _preferred_language(accept_language: str) -> str:
    candidates: list[tuple[float, int, str]] = []
    for index, raw_part in enumerate(accept_language.split(",")):
        part = raw_part.strip()
        if not part:
            continue

        language, _, raw_params = part.partition(";")
        q = 1.0
        for raw_param in raw_params.split(";"):
            key, _, value = raw_param.strip().partition("=")
            if key == "q":
                try:
                    q = float(value)
                except ValueError:
                    q = 0.0
        candidates.append((q, -index, language.lower()))

    for _, _, language in sorted(candidates, reverse=True):
        base_language = language.split("-", 1)[0]
        if base_language in TRANSLATIONS:
            return base_language
    return "en"


def _enforce_rate_limit(request: Request, *, kind: str) -> None:
    ip = _client_ip(request)
    if kind == "merge":
        limit = SETTINGS.rate_limit_merge_per_min
    elif kind == "download":
        limit = SETTINGS.rate_limit_download_per_min
    else:
        raise RuntimeError(f"Unsupported rate-limit kind: {kind}")

    allowed = RATE_LIMITER.allow(key=f"{kind}:{ip}", limit=limit, window_seconds=60)
    if not allowed:
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Try again in one minute.")


def _client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def _process_merge(
    *,
    request: Request,
    file_a: UploadFile,
    file_b: UploadFile,
    order_a: str,
    order_b: str,
    pages_a: str | None,
    pages_b: str | None,
    start: str,
    policy: str,
    strict: bool,
) -> dict[str, object]:
    try:
        from core.merge import MergeError, build_interleave_plan, load_reader_from_bytes, write_interleaved_pdf_to_bytes
    except ModuleNotFoundError as exc:
        if exc.name == "pypdf":
            raise UserInputError("Server is missing dependency 'pypdf'.") from exc
        raise

    data_a = await _read_pdf_upload(file_a, label="A")
    data_b = await _read_pdf_upload(file_b, label="B")

    async with MERGE_SEMAPHORE:
        try:
            reader_a = load_reader_from_bytes(data_a, label="A")
            reader_b = load_reader_from_bytes(data_b, label="B")

            sequence_a = build_page_sequence(
                order=order_a,
                pages_expr=pages_a,
                total_pages=len(reader_a.pages),
                source_label="A",
            )
            sequence_b = build_page_sequence(
                order=order_b,
                pages_expr=pages_b,
                total_pages=len(reader_b.pages),
                source_label="B",
            )

            if strict:
                validate_no_duplicates(sequence_a.one_based, label="A")
                validate_no_duplicates(sequence_b.one_based, label="B")

            plan = build_interleave_plan(
                sequence_a.zero_based,
                sequence_b.zero_based,
                start=start,
                policy=policy,
            )
            output_bytes = write_interleaved_pdf_to_bytes(
                reader_a=reader_a,
                reader_b=reader_b,
                plan=plan,
            )
        except (MergeError, PageRangeError, ValidationError) as exc:
            raise UserInputError(str(exc)) from exc

    if len(output_bytes) > SETTINGS.max_output_bytes:
        raise UserInputError("Merged output exceeds RAM policy size limit.")

    filename = _build_output_filename(file_a.filename, file_b.filename)
    try:
        token, entry = STORE.put(
            pdf_bytes=output_bytes,
            filename=filename,
            ttl_seconds=SETTINGS.download_ttl_seconds,
        )
    except StoreFullError as exc:
        raise UserInputError(str(exc)) from exc

    download_url = str(request.url_for("download_file", token=token))
    expires_at_dt = datetime.fromtimestamp(entry.expires_at, tz=timezone.utc)
    return {
        "token": token,
        "download_url": download_url,
        "expires_at_human": expires_at_dt.strftime("%Y-%m-%d %H:%M:%S UTC"),
        "expires_at_iso": expires_at_dt.isoformat(),
        "size": entry.size,
    }


async def _process_concat(
    *,
    request: Request,
    files: list[UploadFile],
    order: str | None,
) -> dict[str, object]:
    try:
        from core.merge import MergeError, load_reader_from_bytes, write_concatenated_pdf_to_bytes
    except ModuleNotFoundError as exc:
        if exc.name == "pypdf":
            raise UserInputError("Server is missing dependency 'pypdf'.") from exc
        raise

    if len(files) < 2:
        raise UserInputError("Concatenation requires at least two PDF files.")
    if len(files) > SETTINGS.max_upload_files:
        raise UserInputError(f"Concatenation accepts at most {SETTINGS.max_upload_files} PDF files.")

    ordered_indexes = _parse_concat_order(order, file_count=len(files))
    ordered_files = [files[index] for index in ordered_indexes]
    data_items = [
        await _read_pdf_upload(upload, label=f"PDF {index}")
        for index, upload in enumerate(ordered_files, start=1)
    ]

    async with MERGE_SEMAPHORE:
        try:
            readers = [
                load_reader_from_bytes(data, label=f"PDF {index}")
                for index, data in enumerate(data_items, start=1)
            ]
            output_bytes = write_concatenated_pdf_to_bytes(readers=readers)
        except MergeError as exc:
            raise UserInputError(str(exc)) from exc

    if len(output_bytes) > SETTINGS.max_output_bytes:
        raise UserInputError("Merged output exceeds RAM policy size limit.")

    filename = _build_concat_output_filename([file.filename for file in ordered_files])
    try:
        token, entry = STORE.put(
            pdf_bytes=output_bytes,
            filename=filename,
            ttl_seconds=SETTINGS.download_ttl_seconds,
        )
    except StoreFullError as exc:
        raise UserInputError(str(exc)) from exc

    download_url = str(request.url_for("download_file", token=token))
    expires_at_dt = datetime.fromtimestamp(entry.expires_at, tz=timezone.utc)
    return {
        "token": token,
        "download_url": download_url,
        "expires_at_human": expires_at_dt.strftime("%Y-%m-%d %H:%M:%S UTC"),
        "expires_at_iso": expires_at_dt.isoformat(),
        "size": entry.size,
    }


async def _process_images(
    *,
    request: Request,
    files: list[UploadFile],
    order: str | None,
    auto_orient: bool,
) -> dict[str, object]:
    try:
        from core.image_pdf import ImagePdfError, write_images_pdf_to_bytes
    except ModuleNotFoundError as exc:
        if exc.name == "PIL":
            raise UserInputError("Server is missing dependency 'Pillow'.") from exc
        raise

    if len(files) < 1:
        raise UserInputError("At least one image is required.")
    if len(files) > SETTINGS.max_upload_files:
        raise UserInputError(f"Image-to-PDF accepts at most {SETTINGS.max_upload_files} image files.")

    ordered_indexes = _parse_concat_order(order, file_count=len(files))
    ordered_files = [files[index] for index in ordered_indexes]
    image_items = [
        (
            upload.filename or f"image-{index}",
            await _read_image_upload(upload, label=f"Image {index}"),
        )
        for index, upload in enumerate(ordered_files, start=1)
    ]

    async with MERGE_SEMAPHORE:
        try:
            output_bytes = write_images_pdf_to_bytes(
                image_items=image_items,
                auto_orient=auto_orient,
            )
        except ImagePdfError as exc:
            raise UserInputError(str(exc)) from exc

    if len(output_bytes) > SETTINGS.max_output_bytes:
        raise UserInputError("Generated PDF exceeds RAM policy size limit.")

    filename = _build_images_output_filename([file.filename for file in ordered_files])
    try:
        token, entry = STORE.put(
            pdf_bytes=output_bytes,
            filename=filename,
            ttl_seconds=SETTINGS.download_ttl_seconds,
        )
    except StoreFullError as exc:
        raise UserInputError(str(exc)) from exc

    download_url = str(request.url_for("download_file", token=token))
    expires_at_dt = datetime.fromtimestamp(entry.expires_at, tz=timezone.utc)
    return {
        "token": token,
        "download_url": download_url,
        "expires_at_human": expires_at_dt.strftime("%Y-%m-%d %H:%M:%S UTC"),
        "expires_at_iso": expires_at_dt.isoformat(),
        "size": entry.size,
    }


def _parse_concat_order(order: str | None, *, file_count: int) -> list[int]:
    if order is None or not order.strip():
        return list(range(file_count))

    try:
        indexes = [int(part.strip()) for part in order.split(",") if part.strip()]
    except ValueError as exc:
        raise UserInputError("Invalid PDF order.") from exc

    if len(indexes) != file_count or sorted(indexes) != list(range(file_count)):
        raise UserInputError("Invalid PDF order.")
    return indexes


async def _read_pdf_upload(upload: UploadFile, *, label: str) -> bytes:
    if upload.content_type != "application/pdf":
        raise UserInputError(f"{label}: invalid MIME type. Only application/pdf is accepted.")

    data = await upload.read()
    if not data:
        raise UserInputError(f"{label}: empty file.")
    if len(data) > SETTINGS.max_file_bytes:
        raise UserInputError(f"{label}: file too large. Max size is {SETTINGS.max_file_mb} MB.")
    return data


async def _read_image_upload(upload: UploadFile, *, label: str) -> bytes:
    if upload.content_type is not None and not upload.content_type.startswith("image/"):
        raise UserInputError(f"{label}: invalid MIME type. Only image files are accepted.")

    data = await upload.read()
    if not data:
        raise UserInputError(f"{label}: empty file.")
    if len(data) > SETTINGS.max_file_bytes:
        raise UserInputError(f"{label}: file too large. Max size is {SETTINGS.max_file_mb} MB.")
    return data


def _build_output_filename(name_a: str | None, name_b: str | None) -> str:
    part_a = _sanitize_filename_component(name_a or "a.pdf")
    part_b = _sanitize_filename_component(name_b or "b.pdf")
    return f"{part_a}_{part_b}_interleaved.pdf"


def _build_concat_output_filename(names: list[str | None]) -> str:
    if not names:
        return "merged.pdf"

    first = _sanitize_filename_component(names[0] or "first.pdf")
    last = _sanitize_filename_component(names[-1] or "last.pdf")
    return f"{first}_{last}_{len(names)}-pdfs_merged.pdf"


def _build_images_output_filename(names: list[str | None]) -> str:
    if not names:
        return "images.pdf"

    first = _sanitize_filename_component(names[0] or "first-image")
    last = _sanitize_filename_component(names[-1] or "last-image")
    return f"{first}_{last}_{len(names)}-images.pdf"


def _sanitize_filename_component(filename: str) -> str:
    base = Path(filename).stem.strip().lower()
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "-", base).strip("-")
    return cleaned or "pdf"
