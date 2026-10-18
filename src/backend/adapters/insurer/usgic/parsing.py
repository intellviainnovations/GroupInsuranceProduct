"""USGIC value parsing and outcome classification (docs/contracts/usgic-gpa.md).

* Request dates are ``dd/MM/yyyy`` (day first is an Assumption, confirm in UAT).
* Reply dates come in four shapes; anything else is rejected.
* Premiums are strings or numbers; both become ``Decimal``, never float.
* The literal string ``"null"`` and empty strings are no value.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from backend.adapters.insurer.base import ErrorCategory

_ISO_DATE_TIME = re.compile(
    r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d{1,7})?)?(Z|[+-]\d{2}:?\d{2})?$"
)
_DMY_DASH_TIME = re.compile(r"^\d{2}-\d{2}-\d{4} \d{2}:\d{2}:\d{2}$")
_DMY_SLASH = re.compile(r"^\d{2}/\d{2}/\d{4}$")


class ReplyFormatError(ValueError):
    """A reply value is not in any accepted shape."""


def is_blank(value: object) -> bool:
    return value is None or (isinstance(value, str) and value.strip() in ("", "null", "NULL"))


def clean_text(value: object) -> str | None:
    if is_blank(value):
        return None
    return str(value).strip()


def format_request_date(value: date) -> str:
    return value.strftime("%d/%m/%Y")


def parse_reply_date(value: object) -> date | None:
    """Accept ISO with time, ``dd-MM-yyyy hh:mm:ss``, ``dd/MM/yyyy`` and ``yyyy-MM-ddTHH:mm:ss``."""
    if is_blank(value):
        return None
    if not isinstance(value, str):
        raise ReplyFormatError("date is not a string")
    text = value.strip()
    try:
        if _ISO_DATE_TIME.fullmatch(text):
            # Keep the calendar date as written; the insurer states dates in its local time.
            return date.fromisoformat(text[:10])
        if _DMY_DASH_TIME.fullmatch(text):
            return datetime.strptime(text, "%d-%m-%Y %H:%M:%S").date()
        if _DMY_SLASH.fullmatch(text):
            return datetime.strptime(text, "%d/%m/%Y").date()
    except ValueError as exc:
        raise ReplyFormatError("date out of range") from exc
    raise ReplyFormatError("unrecognised date shape")


def parse_amount(value: object) -> Decimal | None:
    """Decimal from a string or a JSON number already parsed as Decimal/int (never float)."""
    if is_blank(value):
        return None
    if isinstance(value, bool | float):
        raise ReplyFormatError("amount must not be a float")
    if isinstance(value, int | Decimal):
        return Decimal(value)
    if isinstance(value, str):
        try:
            amount = Decimal(value.strip().replace(",", ""))
        except InvalidOperation as exc:
            raise ReplyFormatError("amount is not a number") from exc
        if not amount.is_finite():
            raise ReplyFormatError("amount is not finite")
        return amount
    raise ReplyFormatError("amount has an unexpected type")


_VALIDATION_WORDS = ("invalid", "mandatory", "required", "format", "must be", "cannot be blank")
_NOT_FOUND_WORDS = ("not found", "no record", "does not exist", "not exist", "no data")
_AUTH_WORDS = ("token", "unauthori", "authentication", "expired", "not authorised")


def classify_message(text: str | None) -> ErrorCategory:
    """Map the insurer's free-text error to our category (USGIC sends no error codes)."""
    lowered = (text or "").lower()
    if any(w in lowered for w in _AUTH_WORDS):
        return ErrorCategory.AUTH
    if any(w in lowered for w in _NOT_FOUND_WORDS):
        return ErrorCategory.NOT_FOUND
    if any(w in lowered for w in _VALIDATION_WORDS):
        return ErrorCategory.VALIDATION
    return ErrorCategory.BUSINESS_RULE


def is_success_status(value: object) -> bool:
    return isinstance(value, str) and value.strip().upper() == "SUCCESS"
