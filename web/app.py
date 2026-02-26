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
    if request.method == "POST" and request.url.path in {"/merge", "/api/merge"}:
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

    return TEMPLATES.TemplateResponse(
        request=request,
        name="result.html",
        context={
            "token": result["token"],
            "download_url": result["download_url"],
            "expires_at": result["expires_at_human"],
            "size_kb": round(result["size"] / 1024, 2),
            "one_shot": SETTINGS.one_shot_download,
        },
    )


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
    }
    if form_values:
        values.update(form_values)

    return TEMPLATES.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "error_message": error_message,
            "values": values,
            "max_file_mb": SETTINGS.max_file_mb,
            "ttl_seconds": SETTINGS.download_ttl_seconds,
        },
    )


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


async def _read_pdf_upload(upload: UploadFile, *, label: str) -> bytes:
    if upload.content_type != "application/pdf":
        raise UserInputError(f"{label}: invalid MIME type. Only application/pdf is accepted.")

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


def _sanitize_filename_component(filename: str) -> str:
    base = Path(filename).stem.strip().lower()
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "-", base).strip("-")
    return cleaned or "pdf"
