"""Reading a barcode out of a photograph.

Decoding happens on the laptop, not in the phone browser. A browser can only
open the camera for live scanning over HTTPS, which would mean certificates a
shopkeeper cannot be asked to install. Taking a photo through the ordinary file
picker needs no such thing, so the phone sends a picture and the laptop reads it.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

MAX_IMAGE_BYTES = 12 * 1024 * 1024


@dataclass(frozen=True)
class Decoded:
    text: str
    format: str


def check_digit_ok(code: str) -> bool:
    """Validate an EAN-13/EAN-8/UPC-A check digit."""
    if not code.isdigit() or len(code) not in (8, 12, 13):
        return False
    body, check = code[:-1], int(code[-1])
    # Weights alternate 3,1 from the right-hand end of the body.
    total = sum(int(c) * (3 if (len(body) - i) % 2 == 1 else 1) for i, c in enumerate(body))
    return (10 - total % 10) % 10 == check


def decode(image_bytes: bytes) -> list[Decoded]:
    """Every barcode found in an image. Never raises."""
    if not image_bytes or len(image_bytes) > MAX_IMAGE_BYTES:
        return []
    try:
        import numpy as np
        import zxingcpp
        from PIL import Image, ImageOps

        with Image.open(io.BytesIO(image_bytes)) as raw:
            # Phone photos carry an orientation tag; without this a portrait
            # shot arrives rotated and nothing decodes.
            image = ImageOps.exif_transpose(raw).convert("L")
            # Full-resolution phone photos are slow to scan and no more accurate.
            image.thumbnail((1600, 1600))
            results = zxingcpp.read_barcodes(np.array(image))
    except Exception:
        return []

    return [Decoded(text=r.text, format=r.format.name) for r in results if r.text]


def first_product_code(image_bytes: bytes) -> Decoded | None:
    """The most plausible retail barcode in a photo.

    Retail formats win over QR, and a valid check digit wins over a garbled read,
    so a poster in the background cannot outrank the product in the operator's hand.
    """
    retail = {"EAN13", "EAN8", "UPCA", "UPCE"}
    candidates = decode(image_bytes)
    if not candidates:
        return None
    return sorted(
        candidates,
        key=lambda d: (d.format not in retail, not check_digit_ok(d.text), len(d.text)),
    )[0]
