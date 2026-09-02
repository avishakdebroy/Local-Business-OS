"""Stock quantities as integer thousandths.

Shops weigh things: 2.5 kg of rice, 0.75 litre of oil. Storing quantities as
floats and summing them across thousands of stock movements drifts the same way
money does, so quantities are integer milli-units everywhere below the UI.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from lbos.domain.numerals import to_ascii_digits

MILLI = 1000
_MILLI_Q = Decimal("0.001")
_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")

# Units a shop actually writes down, mapped to a canonical spelling.
UNIT_ALIASES = {
    "pc": "pcs", "pcs": "pcs", "piece": "pcs", "pieces": "pcs", "no": "pcs",
    "nos": "pcs", "unit": "pcs", "units": "pcs", "পিস": "pcs", "টি": "pcs",
    "kg": "kg", "kgs": "kg", "kilo": "kg", "kilos": "kg", "kilogram": "kg",
    "kilograms": "kg", "কেজি": "kg", "কিলো": "kg",
    "g": "g", "gm": "g", "gms": "g", "gram": "g", "grams": "g", "গ্রাম": "g",
    "l": "l", "ltr": "l", "litre": "l", "liter": "l", "litres": "l",
    "liters": "l", "লিটার": "l",
    "ml": "ml", "মিলি": "ml",
    "dozen": "dozen", "dz": "dozen", "ডজন": "dozen",
    "box": "box", "boxes": "box", "carton": "box", "ctn": "box", "বক্স": "box",
    "packet": "packet", "pkt": "packet", "pack": "packet", "প্যাকেট": "packet",
    "bag": "bag", "sack": "bag", "বস্তা": "bag",
    "bottle": "bottle", "btl": "bottle", "বোতল": "bottle",
}
DEFAULT_UNIT = "pcs"


def canonical_unit(unit: str | None) -> str:
    if not unit:
        return DEFAULT_UNIT
    key = to_ascii_digits(str(unit)).strip().lower().rstrip(".")
    return UNIT_ALIASES.get(key, key or DEFAULT_UNIT)


def to_milli(value: str | int | float | Decimal | None) -> int | None:
    """Convert a major-unit quantity to integer thousandths, or None."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value * MILLI
    if isinstance(value, float):
        dec = Decimal(str(value))
    elif isinstance(value, Decimal):
        dec = value
    else:
        cleaned = to_ascii_digits(str(value)).replace(",", "")
        match = _NUMBER.search(cleaned)
        if not match:
            return None
        try:
            dec = Decimal(match.group(0))
        except InvalidOperation:
            return None
    return int(dec.quantize(_MILLI_Q, rounding=ROUND_HALF_UP) * MILLI)


def from_milli(milli: int) -> Decimal:
    return (Decimal(milli) / MILLI).quantize(_MILLI_Q)


def format_milli(milli: int, unit: str | None = None) -> str:
    """Render thousandths without trailing noise: 2500 -> '2.5', 3000 -> '3'."""
    text = format(from_milli(milli).normalize(), "f")
    if unit:
        return f"{text} {canonical_unit(unit)}"
    return text
