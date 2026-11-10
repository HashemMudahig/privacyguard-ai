"""Unit tests for identifier normalization."""

from __future__ import annotations

import pytest

from privacyguard.normalization import (
    IdentifierKindError,
    infer_kind,
    normalize_email,
    normalize_email_hash,
    normalize_phone,
)


def test_normalize_email_trims_and_lowercases() -> None:
    assert normalize_email("  Amina.ElMasri@GMAIL.COM ") == "amina.elmasri@gmail.com"


def test_normalize_email_hash_lowercases() -> None:
    value = "A" * 64
    assert normalize_email_hash(value) == "a" * 64


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("+34 612 847 593", "+34612847593"),
        ("+1 (555) 010-9999", "+15550109999"),
        ("00966 50 123 4567", "00966501234567"),
        ("  ", ""),
    ],
)
def test_normalize_phone(raw: str, expected: str) -> None:
    assert normalize_phone(raw) == expected


def test_infer_kind_email() -> None:
    assert infer_kind("Person@Example.com") == "email"


def test_infer_kind_email_hash() -> None:
    assert infer_kind("a" * 64) == "email_hash"


def test_infer_kind_phone() -> None:
    assert infer_kind("+34 612 847 593") == "phone"


def test_infer_kind_rejects_garbage() -> None:
    with pytest.raises(IdentifierKindError):
        infer_kind("not an identifier")
