"""Typed domain models.

All models are Pydantic v2 models. Timestamps are normalized to timezone-aware
UTC ``datetime`` objects. Identifier values keep their original casing; use
``privacyguard.normalization`` for case-insensitive matching.

Sprint 1 scope: requests, current identities, audit events, provenance and
resolved identities. Policy, evidence and output models are intentionally
out of scope.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

_CASE_ID_RE = re.compile(r"^case_\d+$")


def parse_timestamp(value: str | datetime) -> datetime:
    """Parse an ISO-8601 timestamp and normalize it to UTC."""
    if isinstance(value, datetime):
        moment = value
    else:
        text = value.strip()
        if text.endswith(("Z", "z")):
            text = text[:-1] + "+00:00"
        moment = datetime.fromisoformat(text)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


class ReportedStatus(StrEnum):
    COMPLETE = "COMPLETE"
    PARTIALLY_COMPLETE = "PARTIALLY_COMPLETE"
    NOT_STARTED = "NOT_STARTED"


class AuditField(StrEnum):
    EMAIL = "email"
    EMAIL_HASH = "email_hash"
    PHONE = "phone"


class IdentifierKind(StrEnum):
    EMAIL = "email"
    EMAIL_HASH = "email_hash"
    PHONE = "phone"


class ResolutionStatus(StrEnum):
    RESOLVED = "RESOLVED"
    AMBIGUOUS = "AMBIGUOUS"
    NOT_FOUND = "NOT_FOUND"


class ResolutionMethod(StrEnum):
    CURRENT_EMAIL = "CURRENT_EMAIL"
    HISTORICAL_EMAIL = "HISTORICAL_EMAIL"
    CURRENT_PHONE = "CURRENT_PHONE"
    HISTORICAL_PHONE = "HISTORICAL_PHONE"
    CURRENT_EMAIL_HASH = "CURRENT_EMAIL_HASH"
    HISTORICAL_EMAIL_HASH = "HISTORICAL_EMAIL_HASH"
    NONE = "NONE"


class DeletionRequest(BaseModel):
    """One row from ``deletion_requests.csv`` or the sample file."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)

    case_id: str
    email: str
    requested_at: datetime
    reported_status: ReportedStatus
    reported_at: datetime
    audit_at: datetime
    request_text: str

    @field_validator("case_id")
    @classmethod
    def _validate_case_id(cls, value: str) -> str:
        if not _CASE_ID_RE.fullmatch(value):
            raise ValueError(f"Invalid case_id: {value!r}")
        return value

    @field_validator("email")
    @classmethod
    def _validate_email(cls, value: str) -> str:
        if "@" not in value:
            raise ValueError(f"Invalid request email: {value!r}")
        return value

    @field_validator("requested_at", "reported_at", "audit_at", mode="before")
    @classmethod
    def _parse_timestamps(cls, value: str | datetime) -> datetime:
        return parse_timestamp(value)


class UserIdentity(BaseModel):
    """One current identity row from ``user_identities.csv``."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)

    user_id: str
    name: str
    email: str
    phone: str
    email_hash: str
    updated_at: datetime

    @field_validator("updated_at", mode="before")
    @classmethod
    def _parse_updated_at(cls, value: str | datetime) -> datetime:
        return parse_timestamp(value)


class AuditEvent(BaseModel):
    """One historical identity change from ``user_audit_log.csv``."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)

    audit_id: str
    user_id: str
    event_time: datetime
    field_name: AuditField
    old_value: str
    new_value: str

    @field_validator("event_time", mode="before")
    @classmethod
    def _parse_event_time(cls, value: str | datetime) -> datetime:
        return parse_timestamp(value)


class ProvenanceRef(BaseModel):
    """A precise pointer back to an input row and field."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_file: str
    row_number: int = Field(ge=1)
    record_id: str
    field: str
    value: str
    note: str | None = None


class HistoricalValues(BaseModel):
    """Historical identifiers excluding the values that are still current."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    emails: tuple[str, ...] = ()
    phones: tuple[str, ...] = ()
    email_hashes: tuple[str, ...] = ()


class ResolvedIdentity(BaseModel):
    """A fully resolved subject identity with provenance."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    user_id: str
    current: UserIdentity | None
    historical: HistoricalValues
    all_emails: tuple[str, ...]
    all_phones: tuple[str, ...]
    all_email_hashes: tuple[str, ...]
    provenance: tuple[ProvenanceRef, ...]
    warnings: tuple[str, ...] = ()


class IdentityResolution(BaseModel):
    """Result of resolving a single identifier."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: ResolutionStatus
    identifier: str
    normalized_identifier: str
    kind: IdentifierKind
    method: ResolutionMethod = ResolutionMethod.NONE
    matched_value: str | None = None
    user_id: str | None = None
    identity: ResolvedIdentity | None = None
    candidates: tuple[str, ...] = ()
    resolution_provenance: tuple[ProvenanceRef, ...] = ()
    warnings: tuple[str, ...] = ()


class RequestIdentityResolution(BaseModel):
    """Identity resolution attached to one deletion request."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str
    request_email: str
    resolution: IdentityResolution


class ResolutionException(BaseModel):
    """A request that could not be resolved unambiguously."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str
    email: str
    status: ResolutionStatus
    candidates: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


class ResolutionSummary(BaseModel):
    """Aggregate report for a batch of request resolutions."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset: str
    request_file: str
    total_requests: int
    resolved: int
    ambiguous: int
    not_found: int
    methods: dict[str, int]
    exceptions: tuple[ResolutionException, ...] = ()
