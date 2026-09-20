"""Image normalisation: everything that reaches a clipboard is PNG."""

from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError


class ImageError(ValueError):
    pass


def to_png(data: bytes) -> bytes:
    """Decode any Pillow-readable image (JPEG from Telegram, HEIC-converted
    PNG, WebP, ...) into PNG bytes, applying EXIF orientation."""
    try:
        with Image.open(BytesIO(data)) as image:
            image = ImageOps.exif_transpose(image) or image
            if image.mode not in ("RGB", "RGBA"):
                image = image.convert("RGBA" if _has_alpha(image) else "RGB")
            out = BytesIO()
            image.save(out, format="PNG")
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ImageError(f"cannot decode image: {type(exc).__name__}") from exc
    return out.getvalue()


def _has_alpha(image: Image.Image) -> bool:
    if "A" in image.getbands():
        return True
    return image.mode == "P" and "transparency" in image.info


def looks_like_image(data: bytes) -> bool:
    try:
        with Image.open(BytesIO(data)) as image:
            image.verify()
        return True
    except Exception:
        return False
