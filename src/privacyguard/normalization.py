"""Identifier normalization and classification.

Normalization is deterministic and intentionally conservative. It never
fabricates identifiers; it only canonicalizes formatting for matching.
"""

from __future__ import annotations

import re

from .errors import PrivacyGuardError

_EMAIL_HASH_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_PHONE_RE = re.compile(r"^[+\d][\d\s\-().]*$")


class IdentifierKindError(PrivacyGuardError):
    """Raised when an identifier cannot be classified unambiguously."""


def normalize_email(value: str) -> str:
    """Lowercase and trim an email address."""
    return value.strip().lower()


def normalize_email_hash(value: str) -> str:
    """Lowercase and trim a hexadecimal email hash."""
    return value.strip().lower()


def normalize_phone(value: str) -> str:
    """Keep an optional leading ``+`` and digits only.

    Formatting such as spaces, dashes, dots and parentheses is discarded.
    The transformation is lossy by design and is used only for matching;
    original values are preserved in provenance records.
    """
    text = value.strip()
    leading_plus = text.startswith("+")
    digits = re.sub(r"\D", "", text)
    return f"+{digits}" if leading_plus else digits


def looks_like_email(value: str) -> bool:
    text = value.strip()
    return "@" in text and not text.startswith("@") and not text.endswith("@")


def looks_like_email_hash(value: str) -> bool:
    return bool(_EMAIL_HASH_RE.fullmatch(value.strip()))


def looks_like_phone(value: str) -> bool:
    return bool(_PHONE_RE.fullmatch(value.strip()))


def infer_kind(value: str) -> str:
    """Infer ``email``, ``email_hash`` or ``phone`` from a raw value."""
    if looks_like_email(value):
        return "email"
    if looks_like_email_hash(value):
        return "email_hash"
    if looks_like_phone(value):
        return "phone"
    raise IdentifierKindError(f"Cannot infer identifier kind for value: {value!r}")


def normalize(value: str, kind: str) -> str:
    """Normalize a value for the given identifier kind."""
    if kind == "email":
        return normalize_email(value)
    if kind == "email_hash":
        return normalize_email_hash(value)
    if kind == "phone":
        return normalize_phone(value)
    raise IdentifierKindError(f"Unsupported identifier kind: {kind!r}")
