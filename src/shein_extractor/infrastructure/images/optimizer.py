from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError


DEFAULT_MAX_DIMENSION = 512
DEFAULT_JPEG_QUALITY = 78


def optimize_product_image(
    content: bytes,
    *,
    max_dimension: int = DEFAULT_MAX_DIMENSION,
    jpeg_quality: int = DEFAULT_JPEG_QUALITY,
) -> bytes:
    if max_dimension < 1:
        raise ValueError("max_dimension must be at least 1")
    if not 1 <= jpeg_quality <= 95:
        raise ValueError("jpeg_quality must be between 1 and 95")

    try:
        with Image.open(BytesIO(content)) as source:
            image = ImageOps.exif_transpose(source)
            image.thumbnail(
                (max_dimension, max_dimension),
                Image.Resampling.LANCZOS,
            )
            normalized = _flatten_to_rgb(image)
            output = BytesIO()
            normalized.save(
                output,
                format="JPEG",
                quality=jpeg_quality,
                optimize=True,
                progressive=True,
            )
    except (OSError, UnidentifiedImageError):
        return content

    optimized = output.getvalue()
    return optimized if len(optimized) < len(content) else content


def _flatten_to_rgb(image: Image.Image) -> Image.Image:
    if image.mode in {"RGBA", "LA"} or (
        image.mode == "P" and "transparency" in image.info
    ):
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, "white")
        background.paste(rgba, mask=rgba.getchannel("A"))
        return background
    return image.convert("RGB")
