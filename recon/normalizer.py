from __future__ import annotations

import re
import unicodedata
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from .models import Direction, Line, Side

NORMALIZER_VERSION = "normalizer_v1"

_PREFIX_RE = re.compile(
    r"^(?:neft|rtgs|imps|upi|chq|clg|atm|pos|ach|to|from|by|ref|trf)\b[\s/\-:.]*",
    re.IGNORECASE,
)
_LONG_DIGITS_RE = re.compile(r"\d{8,}")
_OCR_DIGITS_RE = re.compile(r"(?=[0-9OolISsBZzGg]*[0-9])[0-9OolISsBZzGg]{8,}")
_WS_RE = re.compile(r"\s+")
_ACCOUNT_CONTEXT_RE = re.compile(r"(?i)\b(?:a/c|a\.c\.?|acct|account|ifsc|ac)[\s./#:*-]*(?:no\.?\s*)?\d{6,}")

_OCR_TRANSLATION = str.maketrans(
    {
        "O": "0",
        "o": "0",
        "l": "1",
        "I": "1",
        "i": "1",
        "S": "5",
        "s": "5",
        "B": "8",
        "b": "8",
        "Z": "2",
        "z": "2",
        "G": "6",
        "g": "6",
    }
)
_OCR_CHARS = set("0123456789o0l1i5s8b2z6g")

_DIRECTION_MAP = {
    "debit": "debit",
    "dr": "debit",
    "d": "debit",
    "withdrawal": "debit",
    "credit": "credit",
    "cr": "credit",
    "c": "credit",
    "deposit": "credit",
}


class NormalizationError(ValueError):
    pass


def normalize_record(record: dict[str, Any], side: Side) -> Line:
    record_id = str(record.get("id") or "").strip()
    if not record_id:
        raise NormalizationError("record is missing an id")

    source = str(record.get("source") or "csv").strip().lower()
    if source not in {"csv", "pdf_digital", "ocr"}:
        raise NormalizationError(f"unsupported source: {source}")

    raw_text = _first_text(record)
    text = _normalise_text(raw_text, source)
    ref_token = _extract_ref_token(raw_text, source)

    amount_paise, negative, direction_hint = _parse_amount_paise(record)
    if amount_paise == 0:
        raise NormalizationError("amount is zero")
    direction = _parse_direction(record.get("direction"), negative, direction_hint)

    date_value, ambiguous = _parse_date(record.get("date") or record.get("date_iso") or record.get("value_date"))

    return Line(
        id=record_id,
        side=side,
        amount_paise=amount_paise,
        direction=direction,
        date=date_value,
        date_ambiguous=ambiguous,
        ref_token=ref_token,
        text_norm=text,
        source=source,
        raw=dict(record),
    )


def _first_text(record: dict[str, Any]) -> str:
    for key in ("text", "narration", "description", "particulars", "details"):
        value = record.get(key)
        if value is not None and str(value).strip():
            return str(value)
    return ""


def _normalise_text(raw_text: str, source: str) -> str:
    text = unicodedata.normalize("NFKC", raw_text)
    text = _WS_RE.sub(" ", text).strip().lower()

    while True:
        stripped = _PREFIX_RE.sub("", text, count=1).strip()
        if stripped == text:
            break
        text = stripped

    if source == "ocr":
        text = _OCR_DIGITS_RE.sub(" ", text)
    else:
        text = _LONG_DIGITS_RE.sub(" ", text)
    text = _strip_punctuation(text)
    if source == "ocr":
        text = _repair_ocr_numeric(text)
    text = _WS_RE.sub(" ", text).strip()
    return text


def _keep_char(char: str) -> bool:
    return char.isalnum() or char == "." or unicodedata.category(char).startswith("M")


def _strip_punctuation(text: str) -> str:
    return "".join(char if _keep_char(char) else " " for char in text)


def _extract_ref_token(raw_text: str, source: str) -> str:
    text = unicodedata.normalize("NFKC", raw_text).lower()
    while True:
        stripped = _PREFIX_RE.sub("", text, count=1).strip()
        if stripped == text:
            break
        text = stripped
    text = _mask_account_numbers(text)
    if source == "ocr":
        runs = _OCR_DIGITS_RE.findall(text)
        runs = [_repair_ocr_numeric(run) for run in runs]
    else:
        runs = _LONG_DIGITS_RE.findall(text)
    return " ".join(sorted(set(runs)))


def _mask_account_numbers(text: str) -> str:
    return _ACCOUNT_CONTEXT_RE.sub(lambda match: re.sub(r"\d+", "", match.group(0)), text)


def _repair_ocr_numeric(text: str) -> str:
    repaired: list[str] = []
    for token in text.split():
        core = token.replace(",", "").replace(".", "")
        if core and any(char.isdigit() for char in core) and all(char in _OCR_CHARS for char in core):
            token = token.translate(_OCR_TRANSLATION)
        repaired.append(token)
    return " ".join(repaired)


def _parse_amount_paise(record: dict[str, Any]) -> tuple[int, bool, str | None]:
    direct = record.get("amount_paise")
    if direct is not None:
        try:
            paise = int(direct)
        except (TypeError, ValueError) as exc:
            raise NormalizationError(f"invalid amount_paise: {direct!r}") from exc
        return abs(paise), paise < 0, None

    value = record.get("amount")
    if value is None:
        raise NormalizationError("record is missing amount")
    hint: str | None = None
    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        decimal_value = Decimal(str(value))
    else:
        cleaned = str(value).strip()
        negative = False
        if cleaned.startswith("(") and cleaned.endswith(")"):
            negative = True
            cleaned = cleaned[1:-1].strip()
        cleaned = cleaned.replace("₹", "").replace(",", "").replace(" ", "")
        cleaned = re.sub(r"(?i)(?:rs\.?|inr)", "", cleaned)
        if cleaned[:1] in {"+", "-"}:
            negative = negative or cleaned[0] == "-"
            cleaned = cleaned[1:]
        lowered = cleaned.lower()
        if lowered.endswith(("dr", "cr")):
            hint = "debit" if lowered.endswith("dr") else "credit"
            negative = negative or hint == "debit"
            cleaned = cleaned[:-2]
        if cleaned.endswith("-"):
            negative = True
            cleaned = cleaned[:-1]
        if not cleaned:
            raise NormalizationError(f"invalid amount: {value!r}")
        try:
            decimal_value = Decimal(cleaned)
        except InvalidOperation as exc:
            raise NormalizationError(f"invalid amount: {value!r}") from exc
        if negative:
            decimal_value = -abs(decimal_value)

    scaled = decimal_value * 100
    if not scaled.is_finite():
        raise NormalizationError(f"invalid amount: {value!r}")
    if scaled != scaled.to_integral_value():
        raise NormalizationError(f"amount has sub-paise precision: {value!r}")
    paise = int(scaled)
    return abs(paise), paise < 0, hint


def _parse_direction(value: Any, negative: bool, hint: str | None) -> Direction:
    if value is not None and str(value).strip():
        normalised = _DIRECTION_MAP.get(str(value).strip().lower())
        if normalised is None:
            raise NormalizationError(f"invalid direction: {value!r}")
        if hint is not None and hint != normalised:
            raise NormalizationError(f"direction {value!r} contradicts the amount suffix")
        if negative and normalised == "credit":
            raise NormalizationError("direction 'credit' contradicts a negative amount")
        return normalised  # type: ignore[return-value]
    if hint is not None:
        if negative and hint == "credit":
            raise NormalizationError("amount suffix 'cr' contradicts a negative amount")
        return hint  # type: ignore[return-value]
    if negative:
        return "debit"
    raise NormalizationError("record is missing a direction for a positive amount")


def _parse_date(value: Any) -> tuple[date, bool]:
    if value is None:
        raise NormalizationError("record is missing date")
    if isinstance(value, date):
        return value, False

    text = str(value).strip()
    iso = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", text)
    if iso:
        try:
            return date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3))), False
        except ValueError as exc:
            raise NormalizationError(f"invalid date: {value!r}") from exc

    dmy = re.fullmatch(r"(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})", text)
    if not dmy:
        raise NormalizationError(f"invalid date: {value!r}")

    day = int(dmy.group(1))
    month = int(dmy.group(2))
    year_text = dmy.group(3)
    year = int(year_text) if len(year_text) == 4 else (2000 + int(year_text) if int(year_text) < 70 else 1900 + int(year_text))
    ambiguous = day <= 12 and month <= 12
    try:
        return date(year, month, day), ambiguous
    except ValueError as exc:
        raise NormalizationError(f"invalid date: {value!r}") from exc
