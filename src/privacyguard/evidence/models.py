"""Typed models for evidence manifests, observations and inventory reports."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..models import parse_timestamp


class EvidenceFormat(StrEnum):
    SQL = "sql"
    JSON = "json"
    LOG = "log"
    TXT = "txt"
    PDF = "pdf"
    PNG = "png"
    UNKNOWN = "unknown"


SUPPORTED_FORMATS: frozenset[EvidenceFormat] = frozenset(
    {
        EvidenceFormat.SQL,
        EvidenceFormat.JSON,
        EvidenceFormat.LOG,
        EvidenceFormat.TXT,
        EvidenceFormat.PDF,
        EvidenceFormat.PNG,
    }
)


class ObservedState(StrEnum):
    UNKNOWN = "UNKNOWN"
    PRESENT = "PRESENT"
    ABSENT = "ABSENT"
    REDACTED = "REDACTED"
    ANONYMIZED = "ANONYMIZED"
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"
    BLOCKED = "BLOCKED"


class EvidenceManifestEntry(BaseModel):
    """One validated row from ``evidence_files.csv``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    file_id: str
    file_path: str
    origin: str
    captured_at: datetime
    format: EvidenceFormat
    is_supported: bool
    unsupported_reason: str | None = None
    resolved_path: Path = Field(exclude=True, repr=False)


class ManifestIssue(BaseModel):
    """A non-fatal manifest validation issue."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    file_id: str | None = None
    file_path: str | None = None
    message: str


class ManifestLoadResult(BaseModel):
    """Manifest entries plus any issues discovered in non-strict mode."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    manifest_path: Path = Field(exclude=True)
    entries: tuple[EvidenceManifestEntry, ...]
    issues: tuple[ManifestIssue, ...] = ()


class EvidenceLocation(BaseModel):
    """Precise location of an observation inside its source file."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    table: str | None = None
    row_number: int | None = None
    line_number: int | None = None
    page_number: int | None = None
    record_index: int | None = None
    json_path: str | None = None
    region: dict[str, Any] | None = None
    raw_excerpt: str | None = None


class EvidenceProvenance(BaseModel):
    """File-level provenance plus the precise source location."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    file_id: str
    file_path: str
    captured_at: datetime
    source_format: EvidenceFormat
    extraction_method: str | None = None
    image_width: int | None = None
    image_height: int | None = None
    location: EvidenceLocation


class EvidenceObservation(BaseModel):
    """A normalized, provenance-backed observation from one evidence file.

    Observations preserve source facts. They do not contain inferred deletion
    verdicts; a separate state engine will interpret them in Sprint 2B.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    observation_id: str
    file_id: str
    file_path: str
    captured_at: datetime
    observed_at: datetime | None = None
    format: EvidenceFormat
    system_id: str | None = None
    resource_id: str | None = None
    data_category: str | None = None
    observed_state: ObservedState = ObservedState.UNKNOWN
    state_field: str | None = None
    user_ids: tuple[str, ...] = ()
    emails: tuple[str, ...] = ()
    phones: tuple[str, ...] = ()
    email_hashes: tuple[str, ...] = ()
    related_resource_ids: tuple[str, ...] = ()
    attributes: dict[str, Any] = Field(default_factory=dict)
    record: dict[str, Any] | None = None
    provenance: EvidenceProvenance
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    warnings: tuple[str, ...] = ()


class EvidenceParseFailure(BaseModel):
    """A supported file that could not be parsed."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    file_id: str
    file_path: str
    format: EvidenceFormat
    error_type: str
    reason: str


class UnsupportedEvidence(BaseModel):
    """An evidence file whose format is not implemented yet."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    file_id: str
    file_path: str
    format: EvidenceFormat
    reason: str


class EvidenceInventory(BaseModel):
    """Aggregate inventory of manifest entries and parsed observations."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset: str
    manifest_path: str
    total_entries: int
    supported_entries: int
    unsupported_entries: int
    parsed_files: int
    failed_files: int
    observation_count: int
    files_by_format: dict[str, int]
    observations_by_format: dict[str, int]
    observations_by_system: dict[str, int]
    observations_by_category: dict[str, int]
    observations_by_state: dict[str, int]
    parse_warnings: int
    failures: tuple[EvidenceParseFailure, ...] = ()
    unsupported: tuple[UnsupportedEvidence, ...] = ()
    manifest_issues: tuple[ManifestIssue, ...] = ()


class EvidenceIndexStats(BaseModel):
    """High-level statistics for the evidence index."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    observations: int
    files: int
    resources: int
    user_ids: int
    emails: int
    phones: int
    email_hashes: int
    systems: int
    categories: int
    correlation_ids: int = 0
    earliest_captured_at: datetime | None = None
    latest_captured_at: datetime | None = None


def coerce_timestamp(value: str | datetime | None) -> datetime | None:
    """Parse an optional timestamp and guarantee UTC awareness."""
    if value is None:
        return None
    return parse_timestamp(value)
