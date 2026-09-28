"""Coordinate-preserving field-book derivatives; original pixels remain authoritative."""

from __future__ import annotations

import numpy as np
from PIL import Image


def suppress_grid(image: Image.Image) -> Image.Image:
    """Lighten colored ruled lines only; retain dark pencil/ink and page geometry.

    A colored pixel must belong to a long horizontal/vertical run. Isolated colored
    notes are retained. The original is always used for semantic vision/review.
    """
    pixels = np.asarray(image.convert("RGB"), dtype=np.uint8)
    lo = pixels.min(axis=2)
    hi = pixels.max(axis=2)
    chroma = hi.astype(np.int16) - lo.astype(np.int16)
    colored = (chroma > 25) & (lo > 90) & (hi > 155)
    rows = colored.mean(axis=1) > 0.18
    columns = colored.mean(axis=0) > 0.18
    mask = colored & (rows[:, None] | columns[None, :])
    result = pixels.copy()
    result[mask] = 255
    return Image.fromarray(result)


def structure_context_bbox(bbox, *, min_width=440, min_height=360):
    """Expand a normalized ID locator to include neighboring structure/pipe notes.

    This is a context window, not an inferred structure boundary or pipe association.
    Adjacent IDs must still pass the independent exact-ID and review gates.
    """
    if not bbox or len(bbox) != 4:
        return None
    x1, y1, x2, y2 = [max(0, min(1000, int(v))) for v in bbox]
    x1, x2 = sorted((x1, x2))
    y1, y2 = sorted((y1, y2))
    width = min(1000, max(min_width, x2 - x1))
    height = min(1000, max(min_height, y2 - y1))
    left = max(0, min(1000 - width, (x1 + x2 - width) // 2))
    top = max(0, min(1000 - height, (y1 + y2 - height) // 2))
    return [left, top, left + width, top + height]
