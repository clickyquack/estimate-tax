"""Tax period and payment import helpers."""

import csv
import io
import re
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation


def normalize_tax_period_storage(raw: str) -> tuple[str, int]:
    """
    Accept YYYY (4 digits) or YYYYMM (6 digits). Year-only is stored as YYYY00 for export MM=00.
    Returns (stored_6_digit_string, tax_year_int).
    """
    d = re.sub(r"\D+", "", (raw or "").strip())
    if len(d) == 4 and d.isdigit():
        return d + "00", int(d)
    if len(d) == 6 and d.isdigit():
        y = int(d[:4])
        mm = int(d[4:6])
        if mm == 0:
            return d, y
        if 1 <= mm <= 12:
            return d, y
    raise ValueError("Tax Period must be YYYY or YYYYMM (use YYYY for annual, exported as YYYY00).")


def map_csv_tax_type_to_code(value: str) -> str:
    """Derive 5-digit tax type *code* from the CSV Tax Type cell (e.g. ES -> 10406). Separate from storing the label."""
    v = (value or "").strip().upper()
    if not v:
        return ""
    if re.fullmatch(r"\d{5}", v):
        return v
    if v == "ES":
        return "10406"
    digits = re.sub(r"\D+", "", v)
    if len(digits) >= 5:
        return digits[:5]
    return ""


def parse_flexible_date(s: str) -> date:
    s = (s or "").strip()
    if not s:
        raise ValueError("empty date")
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%Y/%m/%d", "%d-%b-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unrecognized date: {s}")


def parse_flexible_time(s: str) -> time:
    s = (s or "").strip()
    if not s:
        return time(12, 0)
    for fmt in ("%H:%M", "%H:%M:%S", "%I:%M %p", "%I:%M:%S %p"):
        try:
            return datetime.strptime(s, fmt).time()
        except ValueError:
            continue
    raise ValueError(f"unrecognized time: {s}")


def normalize_payment_input_method(value: str) -> str:
    v = (value or "").strip()
    if not v:
        return "B"
    if len(v) == 1:
        return v.upper()[:1]
    m = v.lower()
    if m.startswith("batch"):
        return "B"
    if m.startswith("phone"):
        return "P"
    if m.startswith("credit"):
        return "C"
    return v[0].upper()


def parse_csv_payment_rows(text: str):
    """Yield rows (list of 19 strings) from CSV text."""
    f = io.StringIO(text)
    reader = csv.reader(f)
    for row in reader:
        if not row or all(not (c or "").strip() for c in row):
            continue
        yield row


def parse_decimal_amount(s: str) -> Decimal:
    s = (s or "").strip().replace(",", "")
    if not s:
        raise ValueError("empty amount")
    try:
        return Decimal(s)
    except InvalidOperation as e:
        raise ValueError("invalid amount") from e
