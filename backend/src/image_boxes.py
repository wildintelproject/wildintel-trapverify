"""Draw the bounding boxes of the observation being verified onto a photo.

Boxes follow CamtrapDP (``bboxX``, ``bboxY``, ``bboxWidth``, ``bboxHeight``):
the top-left corner and size of the box relative to the image, from 0 to 1.
They are drawn into the pixels of the image sent to the browser, so they follow
the image through scaling, zoom, rotation, the inversion filter and fullscreen.
"""
import io
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

_PRIMARY = (255, 159, 10)      # amber: the box of the observation being verified
_SECONDARY = (255, 214, 102)   # lighter: other boxes of the same species in the photo
_OUTLINE = (0, 0, 0)           # dark halo so the box shows on bright and dark photos


def draw_boxes(img: Image.Image, boxes: list[list[float]]) -> Image.Image:
    """Return ``img`` (RGB) with ``boxes`` drawn; the first box is the main one."""
    img = img.convert("RGB")
    w, h = img.size
    thick = max(2, round(0.004 * max(w, h)))
    draw = ImageDraw.Draw(img)
    for i, (x, y, bw, bh) in enumerate(boxes):
        x0, y0 = round(x * w), round(y * h)
        x1, y1 = min(round((x + bw) * w), w - 1), min(round((y + bh) * h), h - 1)
        t = thick if i == 0 else max(1, thick // 2)
        draw.rectangle([x0 - t, y0 - t, x1 + t, y1 + t], outline=_OUTLINE, width=t)
        draw.rectangle([x0, y0, x1, y1], outline=_PRIMARY if i == 0 else _SECONDARY, width=t)
    return img


@lru_cache(maxsize=32)
def _render(path: str, mtime_ns: int, boxes: tuple[tuple[float, ...], ...]) -> tuple[bytes, str]:
    with Image.open(path) as src:
        is_png = (src.format or "").upper() == "PNG"
        img = ImageOps.exif_transpose(src)           # same orientation the browser shows
        out = draw_boxes(img, [list(b) for b in boxes])
    buf = io.BytesIO()
    if is_png:
        out.save(buf, format="PNG")
        return buf.getvalue(), "image/png"
    out.save(buf, format="JPEG", quality=90, subsampling=0)
    return buf.getvalue(), "image/jpeg"


def render_with_boxes(path: Path, boxes: list[list[float]]) -> tuple[bytes, str]:
    """Photo with its boxes drawn, as ``(bytes, media_type)``; recent results are cached."""
    return _render(str(path), path.stat().st_mtime_ns, tuple(tuple(b) for b in boxes))
