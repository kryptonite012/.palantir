"""Type inference and value normalization.

Normalization never mutates the original value; callers store both. Each
conversion returns ``(value, error)`` so validation can report precisely
which values failed and why.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_NULL_TOKENS = ["", "na", "n/a", "null", "none", "nil", "-", "--", "?", "unknown"]

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+'-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
UNIT_RE = re.compile(r"^\s*(-?[\d][\d.,]*)\s*([A-Za-z%°µ][A-Za-z%°µ/²³]*)\s*$")
_WS = re.compile(r"\s+")
_TRUE = {"true", "t", "yes", "y", "1"}
_FALSE = {"false", "f", "no", "n", "0"}

_DT_FORMATS = [
    "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M%z", "%Y-%m-%dT%H:%M:%S.%f",
    "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S%z", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M",
    "%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d %b %Y %H:%M", "%d %B %Y %H:%M",
]
_DATE_FORMATS = ["%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%d.%m.%Y", "%d %b %Y", "%d %B %Y", "%b %d, %Y", "%B %d, %Y", "%Y%m%d"]

ALGORITHM_VERSION = "normalize-1.0"


def get_zone(name: str | None) -> ZoneInfo | timezone:
    if not name or name.upper() == "UTC":
        return timezone.utc
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError(f"Unknown time zone {name!r}")


def is_null(value: Any, null_tokens: list[str]) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and value != value:
        return True
    if isinstance(value, str) and value.strip().lower() in null_tokens:
        return True
    return False


def parse_datetime(value: Any, tz_name: str | None = None, fmt: str | None = None) -> tuple[str | None, str | None]:
    """Return ISO-8601 UTC string. Naive values are interpreted in ``tz_name``."""
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        dt = datetime(value.year, value.month, value.day)
    else:
        s = str(value).strip()
        if s.endswith("Z"):
            s = s[:-1] + "+0000"
        dt = None
        if re.fullmatch(r"\d{10}(\.\d+)?", s):
            dt = datetime.fromtimestamp(float(s), tz=timezone.utc)
        formats = [fmt] if fmt else _DT_FORMATS + _DATE_FORMATS
        if dt is None:
            for f in formats:
                try:
                    dt = datetime.strptime(s, f)
                    break
                except ValueError:
                    continue
        if dt is None:
            try:
                dt = datetime.fromisoformat(s)
            except ValueError:
                return None, f"unparseable timestamp {value!r}"
    try:
        zone = get_zone(tz_name)
    except ValueError as exc:
        return None, str(exc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=zone)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"), None


def parse_date(value: Any, fmt: str | None = None) -> tuple[str | None, str | None]:
    if isinstance(value, datetime):
        return value.date().isoformat(), None
    if isinstance(value, date):
        return value.isoformat(), None
    s = str(value).strip()
    for f in [fmt] if fmt else _DATE_FORMATS + ["%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"]:
        try:
            return datetime.strptime(s, f).date().isoformat(), None
        except ValueError:
            continue
    return None, f"unparseable date {value!r}"


def _number_text(value: Any) -> str:
    s = str(value).strip().replace(" ", "").replace(" ", "")
    s = re.sub(r"^[$€£¥]", "", s)
    if re.fullmatch(r"-?\d{1,3}(,\d{3})+(\.\d+)?", s):
        s = s.replace(",", "")
    elif re.fullmatch(r"-?\d{1,3}(\.\d{3})+(,\d+)?", s):
        s = s.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"-?\d+,\d+", s):
        s = s.replace(",", ".")
    return s


def convert(value: Any, spec: dict[str, Any], default_tz: str | None) -> tuple[Any, str | None]:
    t = spec.get("type", "string")
    if t in {"string", "identifier"}:
        s = _WS.sub(" ", str(value)).strip() if spec.get("collapse_whitespace", True) else str(value)
        case = spec.get("case")
        if case == "lower":
            s = s.lower()
        elif case == "upper":
            s = s.upper()
        elif case == "title":
            s = s.title()
        pattern = spec.get("pattern")
        if pattern and not re.fullmatch(pattern, s):
            return s, f"value {s!r} does not match pattern {pattern}"
        return s, None
    if t == "integer":
        try:
            f = float(_number_text(value))
        except ValueError:
            return None, f"not an integer: {value!r}"
        if f != int(f):
            return None, f"not an integer: {value!r}"
        return int(f), None
    if t in {"float", "latitude", "longitude"}:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            f = float(value)
        else:
            m = UNIT_RE.match(str(value)) if t == "float" else None
            txt = m.group(1) if m else str(value)
            try:
                f = float(_number_text(txt))
            except ValueError:
                return None, f"not a number: {value!r}"
        if t == "latitude" and not -90 <= f <= 90:
            return None, f"latitude out of range: {f}"
        if t == "longitude" and not -180 <= f <= 180:
            return None, f"longitude out of range: {f}"
        return f, None
    if t == "boolean":
        s = str(value).strip().lower()
        if s in _TRUE:
            return True, None
        if s in _FALSE:
            return False, None
        return None, f"not a boolean: {value!r}"
    if t == "datetime":
        return parse_datetime(value, spec.get("timezone") or default_tz, spec.get("format"))
    if t == "date":
        return parse_date(value, spec.get("format"))
    if t == "email":
        s = str(value).strip().lower()
        return (s, None) if EMAIL_RE.match(s) else (s, f"invalid email: {value!r}")
    if t == "phone":
        raw = str(value).strip()
        digits = re.sub(r"\D", "", raw)
        if len(digits) < 7 or len(digits) > 15:
            return digits or None, f"invalid phone number: {value!r}"
        return ("+" + digits) if raw.startswith("+") or raw.startswith("00") else digits, None
    return value, None


def infer_type(values: list[Any]) -> str:
    vals = [v for v in values if not is_null(v, DEFAULT_NULL_TOKENS)]
    if not vals:
        return "string"
    n = len(vals)

    def share(pred) -> float:
        return sum(1 for v in vals if pred(v)) / n

    def ok(t: str):
        return lambda v: convert(v, {"type": t}, None)[1] is None

    if all(isinstance(v, bool) for v in vals):
        return "boolean"
    if share(lambda v: isinstance(v, int) and not isinstance(v, bool) or (isinstance(v, str) and re.fullmatch(r"-?\d+", v.strip() or "x"))) >= 0.95:
        # leading zeros mean identifiers, not numbers
        if any(isinstance(v, str) and len(v.strip()) > 1 and v.strip().startswith("0") for v in vals):
            return "identifier"
        return "integer"
    if share(lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) or (isinstance(v, str) and re.fullmatch(r"-?[\d.,]+", v.strip() or "x") is not None)) >= 0.95 and share(ok("float")) >= 0.95:
        return "float"
    if share(lambda v: isinstance(v, str) and v.strip().lower() in _TRUE | _FALSE) >= 0.95 and n >= 2:
        return "boolean"
    if share(lambda v: isinstance(v, str) and EMAIL_RE.match(v.strip())) >= 0.9:
        return "email"
    if share(lambda v: isinstance(v, str) and re.search(r"\d{1,2}:\d{2}", v) and parse_datetime(v)[1] is None) >= 0.9:
        return "datetime"
    if share(lambda v: isinstance(v, (date, datetime)) or (isinstance(v, str) and parse_date(v)[1] is None)) >= 0.9:
        return "date"
    return "string"


_CANONICAL_HINTS = {
    "latitude": ["lat", "latitude", "y_coord"], "longitude": ["lon", "lng", "long", "longitude", "x_coord"],
    "email": ["email", "e_mail", "mail"], "phone": ["phone", "telephone", "mobile", "tel"],
    "event_time": ["timestamp", "event_time", "occurred_at", "datetime", "time"],
}


def snake(name: str) -> str:
    s = re.sub(r"[^0-9a-zA-Z]+", "_", name).strip("_").lower()
    s = re.sub(r"_+", "_", s)
    if not s or not s[0].isalpha():
        s = f"f_{s}" if s else "field"
    return s[:64]


def suggest_mapping(columns: list[str], samples: dict[str, list[Any]]) -> dict[str, dict[str, Any]]:
    """Deterministic schema-mapping suggestion (works without AI)."""
    mapping: dict[str, dict[str, Any]] = {}
    used: set[str] = set()
    for col in columns:
        target = snake(col)
        t = infer_type(samples.get(col, []))
        for canon, hints in _CANONICAL_HINTS.items():
            if target in hints or any(target.endswith("_" + h) for h in hints if len(h) > 3):
                if canon in {"latitude", "longitude"}:
                    t = canon
                elif canon == "event_time" and t not in {"datetime", "date"}:
                    continue
                elif canon in {"email", "phone"}:
                    t = canon
                break
        base, i = target, 2
        while target in used:
            target = f"{base}_{i}"
            i += 1
        used.add(target)
        mapping[col] = {"target": target, "type": t}
    return mapping
