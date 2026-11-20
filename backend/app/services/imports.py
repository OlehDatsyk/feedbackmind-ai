"""Guided CSV / XLSX / JSON import: upload -> inspect columns -> map -> validate/preview -> confirm -> process.

Safety:
* Only .csv, .xlsx and .json are accepted (.xlsm/.xls are rejected). XLSX files are opened with openpyxl in
  read-only, values-only mode: macros, formulas and embedded objects are never executed.
* Size and row limits are enforced before parsing.
* Every rejected row is stored with its row number and reason, and can be downloaded - nothing is silently dropped.
* Processing inserts all valid rows in a single transaction, so a failed import leaves no partial data.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import re
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from charset_normalizer import from_bytes
from dateutil import parser as dateparser
from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.base import utcnow
from app.db.session import SessionLocal
from app.models import FeedbackRecord, ImportJob, ImportRowError, Job, Workspace
from app.services import jobs
from app.services.activity import log_activity
from app.services.analysis import active_topics
from app.services.feedback import NewFeedback, create_record, get_or_create_product, get_or_create_source, get_or_create_tags
from app.services.filters import tz_of
from app.services.textutil import clean_filename, content_hash, normalise_text

logger = logging.getLogger("feedbackmind.imports")

FIELDS: dict[str, dict] = {
    "text": {
        "label": "Feedback text",
        "required": True,
        "hints": [
            "feedback",
            "comment",
            "comments",
            "review",
            "review_text",
            "text",
            "message",
            "body",
            "content",
            "response",
            "verbatim",
            "description",
            "answer",
        ],
    },
    "received_at": {
        "label": "Date received",
        "required": False,
        "hints": ["date", "received", "received_at", "created", "created_at", "submitted", "submitted_at", "timestamp", "time", "review_date"],
    },
    "rating": {"label": "Rating", "required": False, "hints": ["rating", "stars", "score", "csat", "nps", "star_rating"]},
    "product": {"label": "Product / service", "required": False, "hints": ["product", "product_name", "service", "item", "sku", "plan_name"]},
    "source": {"label": "Source / channel", "required": False, "hints": ["source", "channel", "platform", "origin"]},
    "customer_ref": {
        "label": "Customer reference",
        "required": False,
        "hints": ["customer", "customer_id", "customer_ref", "user_id", "account", "account_id"],
    },
    "customer_segment": {"label": "Customer segment", "required": False, "hints": ["segment", "tier", "plan", "region", "customer_type"]},
    "title": {"label": "Title / subject", "required": False, "hints": ["title", "subject", "headline", "summary"]},
    "language": {"label": "Language", "required": False, "hints": ["language", "lang", "locale"]},
    "tags": {"label": "Tags (comma-separated)", "required": False, "hints": ["tags", "labels", "category", "categories"]},
    "external_id": {"label": "External ID", "required": False, "hints": ["id", "review_id", "ticket_id", "response_id", "external_id"]},
}

MAX_TEXT = 20_000
PREVIEW_ROWS = 20


def _bad(msg: str) -> HTTPException:
    return HTTPException(status.HTTP_400_BAD_REQUEST, msg)


# ----------------------------------------------------------------------------- parsing


@dataclass
class Parsed:
    columns: list[str]
    rows: list[list[Any]]
    encoding: str | None = None
    sheet_name: str | None = None
    row_errors: dict[int, str] = field(default_factory=dict)  # 1-based data row -> structural problem


def _dedupe_headers(raw: list[Any]) -> list[str]:
    out: list[str] = []
    for i, h in enumerate(raw):
        name = normalise_text(str(h)) if h is not None else ""
        name = name or f"Column {i + 1}"
        base, n = name, 2
        while name in out:
            name = f"{base} ({n})"
            n += 1
        out.append(name[:120])
    return out


SUPPORTED_ENCODINGS = ("utf-8", "utf-16", "cp1252", "latin-1", "cp1250", "cp1251", "iso-8859-15", "shift_jis", "gb18030")


def _decode(content: bytes, encoding: str | None = None) -> tuple[str, str]:
    """Decode text predictably: explicit choice > BOM > UTF-8 > Windows-1252 > statistical detection.

    Short files cannot be detected reliably (e.g. Windows-1250 vs 1252), so the encoding used is reported back and
    the user can re-upload with an explicit encoding.
    """
    if encoding:
        try:
            return content.decode(encoding), encoding
        except (UnicodeDecodeError, LookupError) as exc:
            raise _bad(f"The file could not be decoded as {encoding}.") from exc
    if content.startswith((b"\xff\xfe", b"\xfe\xff")):
        return content.decode("utf-16"), "utf-16"
    try:
        return content.decode("utf-8-sig"), "utf-8"
    except UnicodeDecodeError:
        pass
    try:
        return content.decode("cp1252"), "cp1252"
    except UnicodeDecodeError:
        pass
    best = from_bytes(content).best()
    if best is None or best.encoding is None:
        raise _bad("Could not detect the file's text encoding. Save it as UTF-8 and try again.")
    return str(best), best.encoding


def parse_csv(content: bytes, encoding: str | None = None) -> Parsed:
    """Parse with the standard csv module so that malformed rows are reported, never silently reshaped."""
    text, encoding = _decode(content, encoding)
    sample = text[:20_000]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;	|")
        sep = dialect.delimiter
    except csv.Error:
        sep = ","
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=sep, quotechar='"', doublequote=True, skipinitialspace=False, strict=False)
    header: list[str] | None = None
    rows: list[list[Any]] = []
    row_errors: dict[int, str] = {}
    limit = get_settings().max_import_rows
    try:
        for raw in reader:
            if header is None:
                if not any(c.strip() for c in raw):
                    continue
                header = raw
                continue
            if not any(c.strip() for c in raw):
                continue  # blank line
            width = len(header)
            if len(raw) > width and any(c.strip() for c in raw[width:]):
                row_errors[len(rows) + 1] = (
                    f"Row has {len(raw)} fields but the header has {width} (an unquoted delimiter in the text?). Quote text fields that contain '{sep}'."
                )
            rows.append((raw + [""] * width)[:width])
            if len(rows) > limit:
                raise _bad(f"The file has more than {limit:,} data rows. Split it into smaller files.")
    except csv.Error as exc:
        raise _bad(f"The CSV file could not be parsed: {str(exc)[:200]}") from exc
    if header is None:
        raise _bad("The CSV file is empty.")
    return Parsed(columns=_dedupe_headers(header), rows=rows, encoding=encoding, row_errors=row_errors)


def parse_xlsx(content: bytes, encoding: str | None = None) -> Parsed:  # noqa: ARG001 - XLSX is always UTF-8 XML
    if not content.startswith(b"PK\x03\x04"):
        raise _bad("The file is not a valid .xlsx workbook.")
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            names = zf.namelist()
            if any(n.lower().endswith("vbaproject.bin") for n in names):
                raise _bad("Workbooks containing macros are not accepted. Save the file as a plain .xlsx without macros.")
            total = sum(i.file_size for i in zf.infolist())
            if total > 400 * 1024 * 1024:  # zip bomb guard
                raise _bad("The workbook expands to an unexpectedly large size and was rejected.")
    except zipfile.BadZipFile as exc:
        raise _bad("The file is not a valid .xlsx workbook.") from exc
    from openpyxl import load_workbook

    try:
        wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True, keep_links=False)
    except Exception as exc:  # noqa: BLE001 - openpyxl raises many types for malformed files
        raise _bad("The workbook could not be opened. Re-save it as .xlsx and try again.") from exc
    try:
        ws = wb.worksheets[0]
        it = ws.iter_rows(values_only=True)
        header: list[Any] | None = None
        rows: list[list[Any]] = []
        limit = get_settings().max_import_rows
        for row in it:
            values = list(row)
            if header is None:
                if all(v is None or str(v).strip() == "" for v in values):
                    continue
                header = values
                continue
            if all(v is None or (isinstance(v, str) and not v.strip()) for v in values):
                continue
            rows.append(values)
            if len(rows) > limit:
                raise _bad(f"The file has more than {limit:,} data rows. Split it into smaller files.")
        if header is None:
            raise _bad("The first worksheet is empty.")
        columns = _dedupe_headers(header)
        width = len(columns)
        rows = [(r + [None] * width)[:width] for r in rows]
        return Parsed(columns=columns, rows=rows, sheet_name=ws.title)
    finally:
        wb.close()


def parse_json(content: bytes, encoding: str | None = None) -> Parsed:
    text, _ = _decode(content, encoding)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise _bad(f"Invalid JSON: {exc.msg} (line {exc.lineno}).") from exc
    if isinstance(data, dict):
        data = data.get("records") or data.get("feedback") or data.get("data")
    if not isinstance(data, list) or not data:
        raise _bad('JSON must be an array of objects, or an object with a "records" array.')
    columns: list[str] = []
    for item in data:
        if not isinstance(item, dict):
            raise _bad("Every JSON record must be an object.")
        for k in item:
            if str(k) not in columns:
                columns.append(str(k))
    rows = []
    for item in data:
        row = []
        for c in columns:
            v = item.get(c)
            row.append(", ".join(map(str, v)) if isinstance(v, list) else (json.dumps(v) if isinstance(v, dict) else v))
        rows.append(row)
    return Parsed(columns=_dedupe_headers(columns), rows=rows, encoding="utf-8")


def detect_type(filename: str) -> str:
    lower = filename.lower()
    if lower.endswith(".csv"):
        return "csv"
    if lower.endswith(".xlsx"):
        return "xlsx"
    if lower.endswith(".json"):
        return "json"
    if lower.endswith((".xls", ".xlsm", ".xlsb")):
        raise _bad("Legacy or macro-enabled Excel files are not supported. Save the sheet as .xlsx (or .csv).")
    raise _bad("Unsupported file type. Upload a .csv, .xlsx or .json file.")


def parse_file(file_type: str, content: bytes, encoding: str | None = None) -> Parsed:
    parsed = {"csv": parse_csv, "xlsx": parse_xlsx, "json": parse_json}[file_type](content, encoding)
    if not parsed.rows:
        raise _bad("The file contains a header but no data rows.")
    if len(parsed.rows) > get_settings().max_import_rows:
        raise _bad(f"The file has more than {get_settings().max_import_rows:,} data rows. Split it into smaller files.")
    return parsed


def suggest_mapping(columns: list[str]) -> dict[str, str]:
    norm = {c: re.sub(r"[^a-z0-9]+", "_", c.lower()).strip("_") for c in columns}
    mapping: dict[str, str] = {}
    used: set[str] = set()
    for fld, meta in FIELDS.items():
        for hint in meta["hints"]:
            match = next((c for c in columns if c not in used and norm[c] == hint), None)
            if match is None:
                match = next((c for c in columns if c not in used and hint in norm[c].split("_")), None)
            if match:
                mapping[fld] = match
                used.add(match)
                break
    return mapping


# ----------------------------------------------------------------------------- upload


def create_upload(
    db: Session, workspace_id: uuid.UUID, user_id: uuid.UUID, filename: str, content: bytes, encoding: str | None = None
) -> tuple[ImportJob, Parsed]:
    settings = get_settings()
    if not content:
        raise _bad("The uploaded file is empty.")
    if len(content) > settings.max_import_bytes:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, f"File is larger than the {settings.max_import_mb} MB limit.")
    safe_name = clean_filename(filename, "import")
    file_type = detect_type(safe_name)
    if encoding and encoding not in SUPPORTED_ENCODINGS:
        raise _bad(f"Unsupported encoding. Choose one of: {', '.join(SUPPORTED_ENCODINGS)}.")
    parsed = parse_file(file_type, content, encoding or None)
    job = ImportJob(
        workspace_id=workspace_id,
        file_name=safe_name,
        file_type=file_type,
        file_size=len(content),
        file_bytes=content,
        encoding=parsed.encoding,
        options={"encoding": encoding} if encoding else {},
        sheet_name=parsed.sheet_name,
        columns=parsed.columns,
        mapping=suggest_mapping(parsed.columns),
        status="uploaded",
        total_rows=len(parsed.rows),
        created_by_id=user_id,
    )
    db.add(job)
    db.flush()
    return job, parsed


def load_parsed(db: Session, job: ImportJob) -> Parsed:
    content = db.scalar(select(ImportJob.file_bytes).where(ImportJob.id == job.id))
    if not content:
        raise _bad("The uploaded file is no longer available (the import was already processed). Upload it again.")
    return parse_file(job.file_type, content, (job.options or {}).get("encoding") or (job.encoding if job.file_type != "xlsx" else None))


# ----------------------------------------------------------------------------- validation


@dataclass
class ImportOptions:
    date_order: str = "auto"  # auto | dayfirst | monthfirst
    missing_date: str = "reject"  # reject | use_import_time
    rating_scale: float = 5.0
    default_source: str | None = None
    default_product: str | None = None
    skip_duplicates: bool = True

    @classmethod
    def from_dict(cls, d: dict | None) -> ImportOptions:
        d = d or {}
        opts = cls()
        if d.get("date_order") in ("auto", "dayfirst", "monthfirst"):
            opts.date_order = d["date_order"]
        if d.get("missing_date") in ("reject", "use_import_time"):
            opts.missing_date = d["missing_date"]
        try:
            scale = float(d.get("rating_scale", 5))
            if scale in (5.0, 10.0, 100.0, 1.0):
                opts.rating_scale = scale
        except (TypeError, ValueError):
            pass
        opts.default_source = (normalise_text(str(d["default_source"]))[:200] or None) if d.get("default_source") else None
        opts.default_product = (normalise_text(str(d["default_product"]))[:200] or None) if d.get("default_product") else None
        opts.skip_duplicates = bool(d.get("skip_duplicates", True))
        return opts

    def to_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class RowResult:
    row_number: int
    raw: dict
    values: dict = field(default_factory=dict)
    error: str | None = None
    duplicate_of: str | None = None
    digest: str | None = None


def _cell(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def parse_date(value: Any, opts: ImportOptions, tz, now: datetime) -> datetime:
    if isinstance(value, datetime):
        dt = value
    elif hasattr(value, "year") and hasattr(value, "month") and hasattr(value, "day"):  # date
        dt = datetime(value.year, value.month, value.day)
    else:
        s = _cell(value)
        if not s:
            raise ValueError("missing date")
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}([T ].*)?", s):
            dt = dateparser.isoparse(s)
        else:
            dayfirst = opts.date_order == "dayfirst"
            if opts.date_order == "auto":
                m = _DMY.match(s)
                if m and int(m.group(1)) <= 12 and int(m.group(2)) <= 12 and m.group(1) != m.group(2):
                    raise ValueError(f"ambiguous date '{s}' (day/month order unknown - choose a date format in the import options)")
                dayfirst = bool(m and int(m.group(1)) > 12)
            dt = dateparser.parse(s, dayfirst=dayfirst, fuzzy=False)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    dt = dt.astimezone(UTC)
    if dt.year < 1990:
        raise ValueError("date is before 1990")
    if dt > now + timedelta(days=1):
        raise ValueError("date is in the future")
    return dt


_DMY = re.compile(r"^(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})")


def infer_date_order(values: list[Any]) -> str:
    """Infer day/month order for the whole file from unambiguous values (e.g. 25/03/2026 => day first)."""
    day_first = month_first = False
    for v in values:
        if not isinstance(v, str):
            continue
        m = _DMY.match(v.strip())
        if not m:
            continue
        a, b = int(m.group(1)), int(m.group(2))
        if a > 12 >= b:
            day_first = True
        elif b > 12 >= a:
            month_first = True
    if day_first and not month_first:
        return "dayfirst"
    if month_first and not day_first:
        return "monthfirst"
    return "auto"


def validate_rows(db: Session, job: ImportJob, parsed: Parsed, mapping: dict[str, str], opts: ImportOptions) -> list[RowResult]:
    workspace = db.get(Workspace, job.workspace_id)
    tz = tz_of(workspace.timezone if workspace else "UTC")
    now = utcnow()
    col_index = {c: i for i, c in enumerate(parsed.columns)}
    if "text" not in mapping or mapping["text"] not in col_index:
        raise _bad("Map a column to the required 'Feedback text' field.")
    for fld, col in mapping.items():
        if fld not in FIELDS:
            raise _bad(f"Unknown field '{fld}'.")
        if col not in col_index:
            raise _bad(f"Column '{col}' does not exist in the file.")

    def get(row: list[Any], fld: str) -> Any:
        col = mapping.get(fld)
        return row[col_index[col]] if col else None

    if opts.date_order == "auto" and "received_at" in mapping:
        opts = ImportOptions(**{**opts.to_dict(), "date_order": infer_date_order([get(r, "received_at") for r in parsed.rows])})

    results: list[RowResult] = []
    seen_hashes: dict[str, int] = {}
    seen_external: dict[str, int] = {}
    for i, row in enumerate(parsed.rows, start=1):
        raw = {c: _cell(row[j]) if j < len(row) else "" for c, j in col_index.items()}
        r = RowResult(row_number=i, raw=raw)
        results.append(r)
        if i in parsed.row_errors:
            r.error = parsed.row_errors[i]
            continue
        text = normalise_text(_cell(get(row, "text")))
        if not text:
            r.error = "Feedback text is empty."
            continue
        if len(text) > MAX_TEXT:
            r.error = f"Feedback text is longer than {MAX_TEXT:,} characters."
            continue
        # Keep the original line breaks in the stored text.
        original = _cell(get(row, "text")).strip()
        r.values["text"] = original
        raw_date = get(row, "received_at") if "received_at" in mapping else None
        if raw_date is None or _cell(raw_date) == "":
            if opts.missing_date == "use_import_time":
                r.values["received_at"] = now
                r.values["date_defaulted"] = True
            else:
                r.error = "Date is missing (choose 'use import time' in the options to accept rows without a date)."
                continue
        else:
            try:
                r.values["received_at"] = parse_date(raw_date, opts, tz, now)
            except (ValueError, OverflowError, TypeError) as exc:
                r.error = f"Invalid date: {exc}"[:300]
                continue
        if "rating" in mapping and _cell(get(row, "rating")) != "":
            try:
                rating = float(_cell(get(row, "rating")).replace(",", "."))
            except ValueError:
                r.error = f"Rating '{_cell(get(row, 'rating'))}' is not a number."
                continue
            if rating < 0 or rating > opts.rating_scale:
                r.error = f"Rating {rating:g} is outside the 0-{opts.rating_scale:g} scale."
                continue
            r.values["rating"] = rating
        for fld, limit in (
            ("product", 200),
            ("source", 200),
            ("customer_ref", 200),
            ("customer_segment", 120),
            ("title", 300),
            ("language", 16),
            ("external_id", 200),
        ):
            if fld in mapping:
                v = normalise_text(_cell(get(row, fld)))
                if len(v) > limit:
                    r.error = f"{FIELDS[fld]['label']} is longer than {limit} characters."
                    break
                if v:
                    r.values[fld] = v
        if r.error:
            continue
        if "tags" in mapping:
            r.values["tags"] = [t for t in (normalise_text(x) for x in re.split(r"[,;|]", _cell(get(row, "tags")))) if t][:20]
        product_name = r.values.get("product") or opts.default_product
        # Product IDs are not known before processing; hash on the product *name* for preview, re-hashed on insert.
        r.digest = content_hash(text, None, r.values["received_at"], r.values.get("customer_ref")) + "|" + (product_name or "").casefold()
        ext = r.values.get("external_id")
        if ext:
            if ext in seen_external:
                r.duplicate_of = f"row {seen_external[ext]} (same external ID)"
                continue
            seen_external[ext] = i
        if r.digest in seen_hashes:
            r.duplicate_of = f"row {seen_hashes[r.digest]} in this file"
            continue
        seen_hashes[r.digest] = i

    _mark_existing_duplicates(db, job.workspace_id, results, opts)
    return results


def _mark_existing_duplicates(db: Session, workspace_id: uuid.UUID, results: list[RowResult], opts: ImportOptions) -> None:
    from app.models import Product

    products = {p.name.casefold(): p.id for p in db.scalars(select(Product).where(Product.workspace_id == workspace_id))}
    candidates = [r for r in results if r.error is None and r.duplicate_of is None]
    by_hash: dict[str, RowResult] = {}
    for r in candidates:
        pname = (r.values.get("product") or opts.default_product or "").casefold()
        pid = products.get(pname) if pname else None
        if pname and pid is None:
            continue  # product does not exist yet -> no existing record can match
        by_hash[content_hash(r.values["text"], pid, r.values["received_at"], r.values.get("customer_ref"))] = r
    keys = list(by_hash)
    for i in range(0, len(keys), 500):
        chunk = keys[i : i + 500]
        for h in db.scalars(select(FeedbackRecord.content_hash).where(FeedbackRecord.workspace_id == workspace_id, FeedbackRecord.content_hash.in_(chunk))):
            by_hash[h].duplicate_of = "an existing feedback record"
    ext_rows = {r.values["external_id"]: r for r in candidates if r.values.get("external_id") and r.duplicate_of is None}
    ext_keys = list(ext_rows)
    for i in range(0, len(ext_keys), 500):
        chunk = ext_keys[i : i + 500]
        for e in db.scalars(select(FeedbackRecord.external_id).where(FeedbackRecord.workspace_id == workspace_id, FeedbackRecord.external_id.in_(chunk))):
            ext_rows[e].duplicate_of = "an existing record with the same external ID"


def summarise(results: list[RowResult], opts: ImportOptions) -> dict:
    valid = [r for r in results if r.error is None and (r.duplicate_of is None or not opts.skip_duplicates)]
    invalid = [r for r in results if r.error is not None]
    dups = [r for r in results if r.error is None and r.duplicate_of is not None]
    defaulted = sum(1 for r in valid if r.values.get("date_defaulted"))
    return {
        "total_rows": len(results),
        "valid_rows": len(valid),
        "invalid_rows": len(invalid),
        "duplicate_rows": len(dups),
        "date_defaulted_rows": defaulted,
        "duplicates_will_be": "skipped" if opts.skip_duplicates else "imported",
        "preview": [
            {
                "row_number": r.row_number,
                **{k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in r.values.items() if k != "date_defaulted"},
                "product": r.values.get("product") or opts.default_product,
                "source": r.values.get("source") or opts.default_source,
                "duplicate_of": r.duplicate_of,
            }
            for r in valid[:PREVIEW_ROWS]
        ],
        "errors": [{"row_number": r.row_number, "error_type": "invalid", "message": r.error, "raw": r.raw} for r in invalid[:50]]
        + [{"row_number": r.row_number, "error_type": "duplicate", "message": f"Duplicate of {r.duplicate_of}", "raw": r.raw} for r in dups[:50]],
    }


def validate_job(db: Session, job: ImportJob, mapping: dict[str, str], options: dict | None) -> dict:
    if job.status not in ("uploaded", "validated"):
        raise HTTPException(status.HTTP_409_CONFLICT, f"This import is already {job.status}.")
    opts = ImportOptions.from_dict(options)
    mapping = {k: v for k, v in mapping.items() if v}
    parsed = load_parsed(db, job)
    results = validate_rows(db, job, parsed, mapping, opts)
    summary = summarise(results, opts)
    job.mapping = mapping
    job.options = {**opts.to_dict(), **({"encoding": job.options["encoding"]} if (job.options or {}).get("encoding") else {})}
    job.status = "validated"
    job.total_rows = summary["total_rows"]
    job.valid_rows = summary["valid_rows"]
    job.invalid_rows = summary["invalid_rows"]
    job.duplicate_rows = summary["duplicate_rows"]
    return summary


def confirm_job(db: Session, job: ImportJob, user_id: uuid.UUID) -> Job:
    if job.status != "validated":
        raise HTTPException(status.HTTP_409_CONFLICT, "Validate the column mapping before confirming the import.")
    if job.valid_rows == 0:
        raise _bad("There are no valid rows to import. Fix the file or the mapping and try again.")
    q = jobs.enqueue(db, "import_process", job.workspace_id, {"import_id": str(job.id)}, user_id)
    job.status = "queued"
    job.job_id = q.id
    return q


# ----------------------------------------------------------------------------- processing


def _set_progress(job_id: uuid.UUID, pct: int) -> None:
    # Separate short transaction so progress is visible while the import transaction is still open.
    try:
        with SessionLocal() as s:
            # Also renew the lease so a long import is never re-claimed by another worker while still running.
            lease = timedelta(seconds=get_settings().job_lease_seconds)
            s.execute(update(Job).where(Job.id == job_id).values(progress=pct, locked_until=utcnow() + lease))
            s.commit()
    except Exception:  # noqa: BLE001 - progress is best effort
        logger.debug("Could not update import progress.")


@jobs.handler("import_process")
def process_import(db: Session, job: Job) -> dict:
    imp = db.get(ImportJob, uuid.UUID(job.payload["import_id"]))
    if imp is None:
        raise jobs.PermanentJobError("Import no longer exists.")
    if imp.status in ("completed", "completed_with_errors"):
        return {"imported_rows": imp.imported_rows, "note": "already processed"}
    workspace_id = imp.workspace_id
    opts = ImportOptions.from_dict(imp.options)
    try:
        parsed = load_parsed(db, imp)
        results = validate_rows(db, imp, parsed, imp.mapping, opts)
    except HTTPException as exc:
        raise jobs.PermanentJobError(str(exc.detail)) from exc
    imp.status = "processing"
    topics = active_topics(db, workspace_id)
    default_source = get_or_create_source(db, workspace_id, opts.default_source or f"{imp.file_type.upper()} import", "import")
    product_cache: dict[str, Any] = {}
    source_cache: dict[str, Any] = {}
    imported = 0
    to_import = [r for r in results if r.error is None and (r.duplicate_of is None or not opts.skip_duplicates)]
    total = max(1, len(to_import))
    for n, r in enumerate(to_import, start=1):
        v = r.values
        pname = v.get("product") or opts.default_product
        if pname and pname.casefold() not in product_cache:
            product_cache[pname.casefold()] = get_or_create_product(db, workspace_id, pname)
        sname = v.get("source")
        if sname and sname.casefold() not in source_cache:
            source_cache[sname.casefold()] = get_or_create_source(db, workspace_id, sname, "import")
        create_record(
            db,
            workspace_id,
            NewFeedback(
                text=v["text"],
                received_at=v["received_at"],
                title=v.get("title"),
                source=source_cache.get(sname.casefold()) if sname else default_source,
                product=product_cache.get(pname.casefold()) if pname else None,
                customer_ref=v.get("customer_ref"),
                customer_segment=v.get("customer_segment"),
                language=v.get("language"),
                rating=v.get("rating"),
                rating_max=opts.rating_scale if v.get("rating") is not None else None,
                external_id=v.get("external_id"),
                tags=get_or_create_tags(db, workspace_id, v.get("tags") or []) if v.get("tags") else None,
                import_job_id=imp.id,
            ),
            imp.created_by_id,
            topics,
            flush=False,
        )
        imported += 1
        if n % 500 == 0:
            db.flush()
        if n % 2000 == 0:
            _set_progress(job.id, int(90 * n / total))
    for r in results:
        if r.error is not None:
            db.add(ImportRowError(import_job_id=imp.id, row_number=r.row_number, error_type="invalid", message=r.error, raw_data=r.raw))
        elif r.duplicate_of is not None:
            db.add(
                ImportRowError(
                    import_job_id=imp.id,
                    row_number=r.row_number,
                    error_type="duplicate",
                    message=f"Duplicate of {r.duplicate_of}" + ("" if opts.skip_duplicates else " (imported anyway)"),
                    raw_data=r.raw,
                )
            )
    summary = summarise(results, opts)
    imp.imported_rows = imported
    imp.total_rows = summary["total_rows"]
    imp.valid_rows = summary["valid_rows"]
    imp.invalid_rows = summary["invalid_rows"]
    imp.duplicate_rows = summary["duplicate_rows"]
    imp.status = "completed_with_errors" if (summary["invalid_rows"] or summary["duplicate_rows"]) else "completed"
    imp.completed_at = utcnow()
    imp.file_bytes = None  # raw upload no longer needed; rejected rows are kept in import_row_errors
    log_activity(
        db,
        workspace_id,
        imp.created_by_id,
        "import.completed",
        f"Imported {imported} of {summary['total_rows']} rows from {imp.file_name}",
        "import",
        imp.id,
        {"invalid": summary["invalid_rows"], "duplicates": summary["duplicate_rows"]},
    )
    jobs.enqueue(db, "alerts_evaluate", workspace_id, {"reason": "import"})
    return {"imported_rows": imported, "invalid_rows": summary["invalid_rows"], "duplicate_rows": summary["duplicate_rows"]}


@jobs.on_failure("import_process")
def _import_failed(db: Session, job: Job) -> None:
    imp = db.get(ImportJob, uuid.UUID(job.payload["import_id"]))
    if imp is not None and imp.status not in ("completed", "completed_with_errors"):
        imp.status = "failed"
        imp.error_message = job.error or "Import failed."
        imp.completed_at = utcnow()


def rejected_rows_csv(db: Session, imp: ImportJob) -> bytes:
    from app.services.textutil import safe_cell

    errors = db.scalars(select(ImportRowError).where(ImportRowError.import_job_id == imp.id).order_by(ImportRowError.row_number)).all()
    buf = io.StringIO()
    w = csv.writer(buf)
    cols = list(imp.columns or [])
    w.writerow(["row_number", "error_type", "reason", *cols])
    for e in errors:
        w.writerow([e.row_number, e.error_type, safe_cell(e.message), *[safe_cell(e.raw_data.get(c, "")) for c in cols]])
    return ("﻿" + buf.getvalue()).encode("utf-8")
