"""Bengali/Devanagari numeral handling.

Receipts printed in Bangladesh mix ASCII and Bengali digits freely, and OCR
returns whatever was on the paper. Everything downstream assumes ASCII, so
normalisation happens once, here.
"""

from __future__ import annotations

# U+09E6..U+09EF Bengali digits, U+0966..U+096F Devanagari digits.
_BENGALI = "০১২৩৪৫৬৭৮৯"
_DEVANAGARI = "०१२३४५६७८९"
_ASCII = "0123456789"

_DIGIT_MAP = str.maketrans(
    _BENGALI + _DEVANAGARI,
    _ASCII + _ASCII,
)

# Bengali/Arabic decimal and thousands separators seen on printed receipts.
_SEPARATOR_MAP = str.maketrans(
    {
        "٫": ".",  # Arabic decimal separator
        "٬": ",",  # Arabic thousands separator
        " ": " ",  # thin space
        " ": " ",  # non-breaking space
    }
)


def to_ascii_digits(text: str) -> str:
    """Return ``text`` with Bengali/Devanagari digits rewritten as ASCII."""
    if not text:
        return ""
    return text.translate(_DIGIT_MAP).translate(_SEPARATOR_MAP)


def to_bengali_digits(text: str) -> str:
    """Return ``text`` with ASCII digits rewritten as Bengali. For display only."""
    return text.translate(str.maketrans(_ASCII, _BENGALI))
