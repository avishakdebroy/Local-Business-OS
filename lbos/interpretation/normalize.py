"""Text tidying shared by every extractor."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from lbos.domain.numerals import to_ascii_digits

_SPACES = re.compile(r"[ \t  -​]+")
_BLANK_LINES = re.compile(r"\n{3,}")


def clean(text: str) -> str:
    """Normalise unicode, Bengali digits and whitespace without losing lines."""
    if not text:
        return ""
    out = unicodedata.normalize("NFKC", text)
    out = to_ascii_digits(out)
    out = out.replace("\r\n", "\n").replace("\r", "\n")
    out = "\n".join(_SPACES.sub(" ", line).strip() for line in out.split("\n"))
    return _BLANK_LINES.sub("\n\n", out).strip()


@dataclass(frozen=True)
class Analysis:
    """A document viewed the several ways the extractors need it."""

    raw: str
    text: str
    folded: str
    lines: tuple[str, ...]
    folded_lines: tuple[str, ...]

    @property
    def is_empty(self) -> bool:
        return not self.text


def analyse(text: str) -> Analysis:
    cleaned = clean(text)
    lines = tuple(line for line in cleaned.split("\n") if line.strip())
    return Analysis(
        raw=text or "",
        text=cleaned,
        folded=cleaned.casefold(),
        lines=lines,
        folded_lines=tuple(line.casefold() for line in lines),
    )
