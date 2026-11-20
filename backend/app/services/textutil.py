"""Small text helpers shared by imports, duplicate detection and analysis."""

from __future__ import annotations

import hashlib
import re
import unicodedata
import uuid
from datetime import date, datetime

_WS = re.compile(r"\s+")
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def normalise_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    return _WS.sub(" ", text).strip()


def content_hash(text: str, product_id: uuid.UUID | None, received: datetime | date | None, customer_ref: str | None = None) -> str:
    """Duplicate key: same normalised text, same product, same calendar day (UTC) and same customer reference.

    Intentionally conservative so that two different customers writing "Great service" on the same day are not
    merged, while re-importing the same file is detected.
    """
    day = ""
    if received is not None:
        day = received.date().isoformat() if isinstance(received, datetime) else received.isoformat()
    key = "\x1f".join([normalise_text(text).casefold(), str(product_id or ""), day, (customer_ref or "").strip().casefold()])
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def safe_cell(value: object) -> object:
    """Neutralise spreadsheet formula injection in exported cells (CSV/XLSX)."""
    if isinstance(value, str) and value.startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value


def clean_filename(name: str, default: str = "upload") -> str:
    base = name.replace("\\", "/").rsplit("/", 1)[-1]
    base = re.sub(r"[^A-Za-z0-9._ -]", "_", base).strip(" .")
    return (base or default)[:200]


def truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def contains_quote(text: str, quote: str) -> bool:
    """True if ``quote`` appears in ``text`` (whitespace/case-insensitive). Used to reject invented quotes."""
    q = normalise_text(quote).casefold().strip(" \"'“”‘’.…")
    if len(q) < 3:
        return False
    return q in normalise_text(text).casefold()
