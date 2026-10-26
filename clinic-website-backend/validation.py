"""Input cleaning shared by the API and the services layer (pure Python)."""
from __future__ import annotations

import re
import unicodedata


class ValidationFailed(ValueError):
    """Bad user input. ``str(e)`` is safe to show to the user."""


_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_PHONE_STRIP = re.compile(r"[\s\-().]")
_PHONE_OK = re.compile(r"^\+?\d{10,13}$")
_EMAIL_OK = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def clean_text(value: str | None, *, max_len: int, allow_newlines: bool = False) -> str:
    text = unicodedata.normalize("NFC", value or "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if not allow_newlines:
        text = text.replace("\n", " ").replace("\t", " ")
    text = _CONTROL.sub("", text).strip()
    return text[:max_len]


def normalize_name(value: str | None) -> str:
    name = " ".join(clean_text(value, max_len=200).split())
    if len(name) < 2 or len(name) > 100:
        raise ValidationFailed("Please enter your full name (2-100 characters).")
    if "<" in name or ">" in name or not any(ch.isalpha() for ch in name):
        raise ValidationFailed("Please enter a valid name using letters only.")
    return name


def normalize_phone(value: str | None) -> str:
    phone = _PHONE_STRIP.sub("", clean_text(value, max_len=40))
    if not _PHONE_OK.match(phone):
        raise ValidationFailed("Please enter a valid mobile number with 10 to 13 digits.")
    return phone


def normalize_email(value: str | None) -> str:
    email = clean_text(value, max_len=255).lower()
    if not _EMAIL_OK.match(email):
        raise ValidationFailed("Please enter a valid email address.")
    return email


def normalize_reason(value: str | None) -> str | None:
    reason = clean_text(value, max_len=500, allow_newlines=True)
    return reason or None
