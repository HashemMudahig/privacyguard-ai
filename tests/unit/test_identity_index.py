"""Unit tests for the identity index and resolver using synthetic data.

No challenge rows or answers are hardcoded here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from privacyguard.identity.index import IdentityIndex
from privacyguard.identity.resolver import IdentityResolver
from privacyguard.io.types import DatasetFile, LoadedRow
from privacyguard.models import (
    AuditEvent,
    DeletionRequest,
    IdentifierKind,
    ResolutionMethod,
    ResolutionStatus,
    UserIdentity,
)

IDENTITY_SOURCE = "user_identities.csv"
AUDIT_SOURCE = "user_audit_log.csv"
OLD_HASH = "c" * 64
CURRENT_HASH = "d" * 64


def make_identity(
    row: int,
    user_id: str,
    email: str,
    phone: str,
    email_hash: str,
) -> LoadedRow[UserIdentity]:
    record = UserIdentity(
        user_id=user_id,
        name=f"Name {user_id}",
        email=email,
        phone=phone,
        email_hash=email_hash,
        updated_at="2026-05-28T04:03:00Z",
    )
    raw = {
        "user_id": user_id,
        "name": record.name,
        "email": email,
        "phone": phone,
        "email_hash": email_hash,
        "updated_at": "2026-05-28T04:03:00Z",
    }
    return LoadedRow(row_number=row, record=record, raw=raw)


def make_audit(
    row: int,
    audit_id: str,
    user_id: str,
    field_name: str,
    old_value: str,
    new_value: str,
    event_time: str = "2025-01-01T00:00:00Z",
) -> LoadedRow[AuditEvent]:
    record = AuditEvent(
        audit_id=audit_id,
        user_id=user_id,
        event_time=event_time,
        field_name=field_name,
        old_value=old_value,
        new_value=new_value,
    )
    raw = {
        "audit_id": audit_id,
        "user_id": user_id,
        "event_time": event_time,
        "field_name": field_name,
        "old_value": old_value,
        "new_value": new_value,
    }
    return LoadedRow(row_number=row, record=record, raw=raw)


def build_index(
    identities: tuple[LoadedRow[UserIdentity], ...],
    audits: tuple[LoadedRow[AuditEvent], ...] = (),
) -> IdentityIndex:
    return IdentityIndex(
        DatasetFile(
            path=Path(IDENTITY_SOURCE),
            display_name=IDENTITY_SOURCE,
            rows=identities,
        ),
        DatasetFile(
            path=Path(AUDIT_SOURCE),
            display_name=AUDIT_SOURCE,
            rows=audits,
        ),
    )


@pytest.fixture()
def index() -> IdentityIndex:
    identities = (
        make_identity(1, "user_1", "current@example.com", "+1 555 000 1111", CURRENT_HASH),
        make_identity(2, "user_2", "other@example.com", "+1 555 000 2222", "e" * 64),
    )
    audits = (
        make_audit(1, "audit_1", "user_1", "email", "old@example.com", "current@example.com"),
        make_audit(2, "audit_2", "user_1", "phone", "+1 555 000 0000", "+1 555 000 1111"),
        make_audit(3, "audit_3", "user_1", "email_hash", OLD_HASH, CURRENT_HASH),
    )
    return build_index(identities, audits)


@pytest.fixture()
def resolver(index: IdentityIndex) -> IdentityResolver:
    return IdentityResolver(index)


def test_current_email_resolution(resolver: IdentityResolver) -> None:
    resolution = resolver.resolve_email("CURRENT@example.com")
    assert resolution.status == ResolutionStatus.RESOLVED
    assert resolution.method == ResolutionMethod.CURRENT_EMAIL
    assert resolution.user_id == "user_1"
    assert resolution.identity is not None
    assert resolution.identity.current is not None
    assert resolution.identity.current.email == "current@example.com"
    assert resolution.resolution_provenance
    assert resolution.resolution_provenance[0].source_file == IDENTITY_SOURCE
    assert resolution.resolution_provenance[0].row_number == 1


def test_historical_email_resolution(resolver: IdentityResolver) -> None:
    resolution = resolver.resolve_email("old@example.com")
    assert resolution.status == ResolutionStatus.RESOLVED
    assert resolution.method == ResolutionMethod.HISTORICAL_EMAIL
    assert resolution.user_id == "user_1"
    assert resolution.resolution_provenance[0].record_id == "audit_1"
    assert resolution.resolution_provenance[0].note == "old_value"
    assert resolution.identity is not None
    assert "old@example.com" in resolution.identity.historical.emails
    assert "current@example.com" in resolution.identity.all_emails


def test_historical_phone_resolution(resolver: IdentityResolver) -> None:
    resolution = resolver.resolve_identifier("+1 (555) 000-0000", IdentifierKind.PHONE)
    assert resolution.status == ResolutionStatus.RESOLVED
    assert resolution.method == ResolutionMethod.HISTORICAL_PHONE
    assert resolution.user_id == "user_1"
    assert resolution.resolution_provenance[0].record_id == "audit_2"


def test_current_email_hash_resolution(resolver: IdentityResolver) -> None:
    resolution = resolver.resolve_identifier(CURRENT_HASH)
    assert resolution.status == ResolutionStatus.RESOLVED
    assert resolution.method == ResolutionMethod.CURRENT_EMAIL_HASH
    assert resolution.user_id == "user_1"


def test_historical_email_hash_resolution(resolver: IdentityResolver) -> None:
    resolution = resolver.resolve_identifier(OLD_HASH)
    assert resolution.status == ResolutionStatus.RESOLVED
    assert resolution.method == ResolutionMethod.HISTORICAL_EMAIL_HASH
    assert resolution.user_id == "user_1"


def test_not_found(resolver: IdentityResolver) -> None:
    resolution = resolver.resolve_email("missing@example.com")
    assert resolution.status == ResolutionStatus.NOT_FOUND
    assert resolution.user_id is None
    assert resolution.identity is None
    assert resolution.candidates == ()


def test_ambiguous_historical_value_is_not_guessed() -> None:
    identities = (
        make_identity(1, "user_1", "a@example.com", "+1 555 000 0001", "a" * 64),
        make_identity(2, "user_2", "b@example.com", "+1 555 000 0002", "b" * 64),
    )
    audits = (
        make_audit(1, "audit_1", "user_1", "phone", "+1 555 999 0000", "+1 555 000 0001"),
        make_audit(2, "audit_2", "user_2", "phone", "+1 555 999 0000", "+1 555 000 0002"),
    )
    resolution = IdentityResolver(build_index(identities, audits)).resolve_identifier(
        "+1 555 999 0000", IdentifierKind.PHONE
    )
    assert resolution.status == ResolutionStatus.AMBIGUOUS
    assert resolution.user_id is None
    assert resolution.identity is None
    assert resolution.candidates == ("user_1", "user_2")


def test_current_vs_historical_collision_is_ambiguous() -> None:
    identities = (
        make_identity(1, "user_1", "shared@example.com", "+1 555 000 0001", "a" * 64),
        make_identity(2, "user_2", "b@example.com", "+1 555 000 0002", "b" * 64),
    )
    audits = (
        make_audit(1, "audit_1", "user_2", "email", "shared@example.com", "b@example.com"),
    )
    resolution = IdentityResolver(build_index(identities, audits)).resolve_email(
        "shared@example.com"
    )
    assert resolution.status == ResolutionStatus.AMBIGUOUS
    assert set(resolution.candidates) == {"user_1", "user_2"}


def test_provenance_covers_both_sources(resolver: IdentityResolver) -> None:
    resolution = resolver.resolve_email("old@example.com")
    assert resolution.identity is not None
    sources = {ref.source_file for ref in resolution.identity.provenance}
    assert sources == {IDENTITY_SOURCE, AUDIT_SOURCE}
    assert all(ref.row_number >= 1 for ref in resolution.identity.provenance)


def test_resolve_requests_preserves_case_id(resolver: IdentityResolver) -> None:
    request = DeletionRequest(
        case_id="case_001",
        email="old@example.com",
        requested_at="2026-01-01T00:00:00Z",
        reported_status="NOT_STARTED",
        reported_at="2026-01-02T00:00:00Z",
        audit_at="2026-01-03T00:00:00Z",
        request_text="Delete my data.",
    )
    dataset = DatasetFile(
        path=Path("sample_deletion_requests.csv"),
        display_name="sample_deletion_requests.csv",
        rows=(LoadedRow(row_number=1, record=request, raw={}),),
    )
    resolutions = resolver.resolve_requests(dataset)
    assert len(resolutions) == 1
    assert resolutions[0].case_id == "case_001"
    assert resolutions[0].resolution.user_id == "user_1"


def test_duplicate_current_email_builds_warning_and_is_ambiguous() -> None:
    identities = (
        make_identity(1, "user_1", "duplicate@example.com", "+1 555 000 0001", "a" * 64),
        make_identity(2, "user_2", "duplicate@example.com", "+1 555 000 0002", "b" * 64),
    )
    index = build_index(identities)
    assert index.build_warnings
    resolution = IdentityResolver(index).resolve_email("duplicate@example.com")
    assert resolution.status == ResolutionStatus.AMBIGUOUS
    assert resolution.candidates == ("user_1", "user_2")
