"""Unit tests for Pydantic models and timestamp parsing."""

from __future__ import annotations

from datetime import timezone

import pytest
from pydantic import ValidationError

from privacyguard.models import (
    AuditEvent,
    DeletionRequest,
    ReportedStatus,
    UserIdentity,
    parse_timestamp,
)


def test_parse_timestamp_z_suffix() -> None:
    moment = parse_timestamp("2026-08-18T09:14:00Z")
    assert moment.tzinfo is timezone.utc
    assert moment.year == 2026 and moment.month == 8 and moment.day == 18


def test_parse_timestamp_naive_is_utc() -> None:
    moment = parse_timestamp("2026-08-18T09:14:00")
    assert moment.tzinfo is timezone.utc


def test_deletion_request_parses_and_freezes() -> None:
    request = DeletionRequest(
        case_id="case_999",
        email="person@example.com",
        requested_at="2026-08-18T09:14:00Z",
        reported_status="COMPLETE",
        reported_at="2026-08-20T16:42:00Z",
        audit_at="2026-09-03T11:30:00Z",
        request_text="Please delete my account.",
    )
    assert request.reported_status is ReportedStatus.COMPLETE
    with pytest.raises(ValidationError):
        request.email = "other@example.com"  # type: ignore[misc]


def test_deletion_request_rejects_invalid_status() -> None:
    with pytest.raises(ValidationError):
        DeletionRequest(
            case_id="case_999",
            email="person@example.com",
            requested_at="2026-08-18T09:14:00Z",
            reported_status="DONE",
            reported_at="2026-08-20T16:42:00Z",
            audit_at="2026-09-03T11:30:00Z",
            request_text="Please delete my account.",
        )


def test_deletion_request_rejects_invalid_case_id() -> None:
    with pytest.raises(ValidationError):
        DeletionRequest(
            case_id="999",
            email="person@example.com",
            requested_at="2026-08-18T09:14:00Z",
            reported_status="COMPLETE",
            reported_at="2026-08-20T16:42:00Z",
            audit_at="2026-09-03T11:30:00Z",
            request_text="Please delete my account.",
        )


def test_user_identity_parses() -> None:
    identity = UserIdentity(
        user_id="user_1",
        name="Amina",
        email="amina@example.com",
        phone="+34 600 000 000",
        email_hash="b" * 64,
        updated_at="2026-05-28T04:03:00Z",
    )
    assert identity.user_id == "user_1"
    assert identity.updated_at.tzinfo is timezone.utc


def test_audit_event_parses_and_rejects_unknown_field() -> None:
    event = AuditEvent(
        audit_id="audit_1",
        user_id="user_1",
        event_time="2026-01-01T00:00:00Z",
        field_name="email",
        old_value="old@example.com",
        new_value="new@example.com",
    )
    assert event.field_name == "email"
    with pytest.raises(ValidationError):
        AuditEvent(
            audit_id="audit_2",
            user_id="user_1",
            event_time="2026-01-01T00:00:00Z",
            field_name="address",
            old_value="x",
            new_value="y",
        )
