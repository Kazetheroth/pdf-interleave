from __future__ import annotations

from io import BytesIO
from pathlib import Path


class ImagePdfError(ValueError):
    """Raised when image-to-PDF conversion fails."""


def write_images_pdf(
    *,
    image_paths: list[Path],
    output_path: Path,
    auto_orient: bool,
) -> None:
    output_bytes = write_images_pdf_to_bytes(
        image_items=[(path.name, path.read_bytes()) for path in image_paths],
        auto_orient=auto_orient,
    )

    with output_path.open("wb") as output_file:
        output_file.write(output_bytes)


def write_images_pdf_to_bytes(
    *,
    image_items: list[tuple[str, bytes]],
    auto_orient: bool,
) -> bytes:
    if len(image_items) < 1:
        raise ImagePdfError("At least one image is required.")

    try:
        from PIL import Image, ImageOps, UnidentifiedImageError
    except ModuleNotFoundError as exc:
        if exc.name == "PIL":
            raise ImagePdfError("Missing dependency 'Pillow'.") from exc
        raise

    pages = []
    try:
        for index, (name, data) in enumerate(image_items, start=1):
            try:
                image = Image.open(BytesIO(data))
                image.load()
            except UnidentifiedImageError as exc:
                raise ImagePdfError(f"Image {index}: unsupported or invalid image '{name}'.") from exc
            except Exception as exc:  # noqa: BLE001
                raise ImagePdfError(f"Image {index}: failed to read image '{name}': {exc}") from exc

            if auto_orient:
                image = ImageOps.exif_transpose(image)

            if image.mode in {"RGBA", "LA"} or (image.mode == "P" and "transparency" in image.info):
                background = Image.new("RGB", image.size, "white")
                alpha = image.convert("RGBA").getchannel("A")
                background.paste(image.convert("RGB"), mask=alpha)
                image = background
            elif image.mode != "RGB":
                image = image.convert("RGB")

            pages.append(image)

        output = BytesIO()
        first_page, remaining_pages = pages[0], pages[1:]
        first_page.save(output, format="PDF", save_all=True, append_images=remaining_pages)
        return output.getvalue()
    finally:
        for page in pages:
            page.close()
