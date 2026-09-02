"""Money as integer minor units.

Amounts are stored and summed as paisa (1/100 taka) integers. Floats are never
used for money: summing float receipts drifts, and a bookkeeping total that
drifts is worse than no total at all.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from lbos.domain.numerals import to_ascii_digits

DEFAULT_CURRENCY = "BDT"
CURRENCY_SYMBOLS = {"BDT": "৳"}  # ৳

_CENT = Decimal("0.01")

# Currency words/symbols that may sit either side of the number.
_NOISE = re.compile(
    r"(?:৳|৲|৳|tk\.?|taka|bdt|টাকা|/-|:-)",
    re.IGNORECASE,
)
# Grouped form requires at least one separator, otherwise the alternation
# would clip "12345678" down to its first three digits.
_NUMBER = re.compile(r"-?\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|-?\d+(?:\.\d+)?")


@dataclass(frozen=True, order=True)
class Money:
    """An exact amount. ``paisa`` is the whole amount in minor units."""

    paisa: int
    currency: str = DEFAULT_CURRENCY

    def __post_init__(self) -> None:
        if not isinstance(self.paisa, int) or isinstance(self.paisa, bool):
            raise TypeError("Money.paisa must be an int (minor units)")

    # --- Construction ---

    @classmethod
    def zero(cls, currency: str = DEFAULT_CURRENCY) -> "Money":
        return cls(0, currency)

    @classmethod
    def from_taka(cls, value: str | int | float | Decimal, currency: str = DEFAULT_CURRENCY) -> "Money":
        """Build from a major-unit amount, rounding half-up to the paisa."""
        if isinstance(value, float):
            # str() first so 0.1 + 0.2 style artefacts do not survive the cast.
            dec = Decimal(str(value))
        elif isinstance(value, Decimal):
            dec = value
        elif isinstance(value, int):
            dec = Decimal(value)
        else:
            parsed = parse_taka_decimal(str(value))
            if parsed is None:
                raise ValueError(f"not a monetary amount: {value!r}")
            dec = parsed
        return cls(int(dec.quantize(_CENT, rounding=ROUND_HALF_UP) * 100), currency)

    # --- Arithmetic ---

    def _check(self, other: "Money") -> None:
        if self.currency != other.currency:
            raise ValueError(f"cannot mix {self.currency} and {other.currency}")

    def __add__(self, other: "Money") -> "Money":
        self._check(other)
        return Money(self.paisa + other.paisa, self.currency)

    def __sub__(self, other: "Money") -> "Money":
        self._check(other)
        return Money(self.paisa - other.paisa, self.currency)

    def __neg__(self) -> "Money":
        return Money(-self.paisa, self.currency)

    # --- Presentation ---

    @property
    def taka(self) -> Decimal:
        return (Decimal(self.paisa) / 100).quantize(_CENT)

    def format(self, symbol: bool = True) -> str:
        return format_paisa(self.paisa, currency=self.currency, symbol=symbol)

    def __str__(self) -> str:
        return self.format()


def group_bd(digits: str) -> str:
    """Group an integer digit string the South Asian way: 12,34,567 not 1,234,567."""
    if len(digits) <= 3:
        return digits
    head, tail = digits[:-3], digits[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return ",".join(parts + [tail])


def format_paisa(paisa: int, currency: str = DEFAULT_CURRENCY, symbol: bool = True) -> str:
    """Render minor units as ``৳12,34,567.89``."""
    sign = "-" if paisa < 0 else ""
    whole, frac = divmod(abs(paisa), 100)
    body = f"{group_bd(str(whole))}.{frac:02d}"
    prefix = CURRENCY_SYMBOLS.get(currency, currency + " ") if symbol else ""
    return f"{sign}{prefix}{body}"


def parse_taka_decimal(text: str) -> Decimal | None:
    """Extract a major-unit Decimal from free text, or None if there isn't one.

    Handles Bengali digits, ৳/Tk/টাka prefixes and suffixes, ``1,250.50``
    grouping and trailing ``/-``.
    """
    if text is None:
        return None
    cleaned = _NOISE.sub(" ", to_ascii_digits(str(text)))
    match = _NUMBER.search(cleaned)
    if not match:
        return None
    try:
        return Decimal(match.group(0).replace(",", ""))
    except InvalidOperation:
        return None


def parse_money(text: str, currency: str = DEFAULT_CURRENCY) -> Money | None:
    """Extract a Money from free text, or None if no amount is present."""
    dec = parse_taka_decimal(text)
    if dec is None:
        return None
    return Money(int(dec.quantize(_CENT, rounding=ROUND_HALF_UP) * 100), currency)
