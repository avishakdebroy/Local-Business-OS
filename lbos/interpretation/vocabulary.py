"""Words a Bangladeshi shop actually writes on paper, in Bengali and English.

Matching is done on casefolded text with Bengali digits already normalised, so
every entry here is lowercase.
"""

from __future__ import annotations

import re
from functools import lru_cache

# --- Document classification ------------------------------------------------

MONEY_WORDS: tuple[str, ...] = (
    "total", "subtotal", "sub total", "grand total", "amount", "payable",
    "net", "bill", "invoice", "receipt", "cash memo", "memo", "vat", "tax",
    "price", "taka", "tk", "bdt", "৳", "paid", "payment", "due", "discount",
    "মোট", "সর্বমোট", "টাকা", "ভ্যাট", "কর", "দাম", "মূল্য", "বিল", "রসিদ",
    "চালান", "ক্যাশ", "পরিশোধ", "বাকি", "বকেয়া", "ছাড়",
)

SALE_WORDS: tuple[str, ...] = (
    "sold", "sale", "sales", "customer", "client", "buyer", "invoice to",
    "sold to", "বিক্রি", "বিক্রয়", "ক্রেতা", "খদ্দের", "বেচা", "বিক্রী",
)

PURCHASE_WORDS: tuple[str, ...] = (
    "purchase", "purchased", "bought", "buy", "supplier", "vendor", "paid to",
    "bill from", "expense", "spent", "rent", "salary", "wages", "utility",
    "electricity", "recharge",
    "ক্রয়", "কিনলাম", "কিনেছি", "কেনা", "সরবরাহকারী", "খরচ", "ভাড়া", "বেতন",
    "মজুরি", "বিদ্যুৎ", "পরিশোধ করলাম",
)

STOCK_WORDS: tuple[str, ...] = (
    "stock", "inventory", "qty", "quantity", "restock", "received", "receive",
    "issued", "damaged", "wastage", "opening stock", "closing stock", "godown",
    "স্টক", "মজুদ", "মজুত", "পরিমাণ", "মাল", "মালামাল", "গুদাম", "নষ্ট", "ফেরত",
)

# --- Field cues -------------------------------------------------------------

TOTAL_WORDS: tuple[str, ...] = (
    "grand total", "grand-total", "net payable", "net total", "net amount",
    "total amount", "total payable", "total", "payable", "amount due",
    "সর্বমোট", "মোট", "সমষ্টি", "পরিশোধযোগ্য",
)

VAT_WORDS: tuple[str, ...] = (
    "vat", "tax", "gst", "ভ্যাট", "কর", "মূসক",
)

PARTY_LABELS: tuple[str, ...] = (
    "vendor", "supplier", "customer", "client", "party", "shop", "store",
    "seller", "buyer", "from", "to", "name", "m/s", "messrs",
    "দোকান", "ক্রেতা", "বিক্রেতা", "নাম", "সরবরাহকারী", "প্রতিষ্ঠান",
)

# Mapping from cue word to the payment method stored on the entry.
# Note: "নগদ" is the ordinary Bengali word for cash *and* the brand name of the
# Nagad wallet. It is read as cash; the Latin spelling "nagad" is read as the
# wallet, which is how people actually write it down.
PAYMENT_WORDS: dict[str, str] = {
    "cash": "cash", "নগদ": "cash", "ক্যাশ": "cash", "cash memo": "cash",
    "bkash": "bkash", "bikash": "bkash", "বিকাশ": "bkash",
    "nagad": "nagad", "nogod": "nagad",
    "rocket": "rocket", "রকেট": "rocket",
    "card": "card", "visa": "card", "mastercard": "card", "কার্ড": "card",
    "bank": "bank", "cheque": "bank", "check": "bank", "transfer": "bank",
    "ব্যাংক": "bank", "চেক": "bank",
    "due": "due", "credit": "due", "baki": "due", "বাকি": "due", "বকেয়া": "due",
}

# Expense/income categories, cheap keyword mapping. Anything unmatched stays
# empty rather than being guessed.
CATEGORY_WORDS: dict[str, str] = {
    "rent": "rent", "ভাড়া": "rent",
    "salary": "salary", "wages": "salary", "বেতন": "salary", "মজুরি": "salary",
    "electricity": "utilities", "current bill": "utilities", "বিদ্যুৎ": "utilities",
    "water": "utilities", "পানি": "utilities", "gas": "utilities", "গ্যাস": "utilities",
    "internet": "utilities", "wifi": "utilities", "ইন্টারনেট": "utilities",
    "transport": "transport", "delivery": "transport", "courier": "transport",
    "rickshaw": "transport", "van": "transport", "ডেলিভারি": "transport",
    "stationery": "supplies", "supplies": "supplies", "packaging": "supplies",
    "tea": "food", "snack": "food", "চা": "food", "নাস্তা": "food",
    "repair": "maintenance", "maintenance": "maintenance", "মেরামত": "maintenance",
}

# --- Stock movement direction ----------------------------------------------

STOCK_IN_WORDS: tuple[str, ...] = (
    "received", "receive", "recieved", "got", "in", "inward", "added", "add",
    "purchase", "purchased", "bought", "restock", "restocked", "return",
    "returned", "opening",
    "পেলাম", "এসেছে", "এলো", "ঢুকলো", "জমা", "যোগ", "কিনলাম", "ফেরত",
)

STOCK_OUT_WORDS: tuple[str, ...] = (
    "sold", "sale", "out", "outward", "issued", "issue", "used", "damaged",
    "wastage", "waste", "broken", "expired", "loss",
    "বিক্রি", "গেল", "বের", "নষ্ট", "খরচ", "ব্যবহার",
)


# --- Matching ---------------------------------------------------------------
#
# Matching is boundary-aware. A plain substring search finds "in" inside
# "miniket" and "bill" inside "billing", which silently corrupts both the
# document type and the item name.


def _is_word_char(ch: str) -> bool:
    return bool(re.match(r"\w", ch, re.UNICODE))


@lru_cache(maxsize=2048)
def _pattern(word: str) -> re.Pattern[str]:
    """Anchor each end of ``word`` only where a word boundary makes sense.

    Cues such as "৳" begin with a non-word character and are typically written
    flush against a digit, so anchoring that side would never match.
    """
    left = r"(?<!\w)" if word and _is_word_char(word[0]) else ""
    right = r"(?!\w)" if word and _is_word_char(word[-1]) else ""
    return re.compile(left + re.escape(word) + right, re.UNICODE)


def contains(folded_text: str, word: str) -> bool:
    return _pattern(word).search(folded_text) is not None


def spans(folded_text: str, word: str) -> list[tuple[int, int]]:
    """Every position at which ``word`` occurs as a whole token."""
    return [m.span() for m in _pattern(word).finditer(folded_text)]


def hits(folded_text: str, words: tuple[str, ...]) -> list[str]:
    """Return which of ``words`` appear in already-folded text."""
    return [w for w in words if contains(folded_text, w)]


def first_mapped(folded_text: str, mapping: dict[str, str]) -> str | None:
    """Return the mapped value for the earliest-appearing key, or None.

    Longer keys win a tie so "cash memo" is not shadowed by "cash".
    """
    best: tuple[int, int, str] | None = None
    for key, value in mapping.items():
        match = _pattern(key).search(folded_text)
        if match is None:
            continue
        candidate = (match.start(), -len(key), value)
        if best is None or candidate < best:
            best = candidate
    return best[2] if best else None
