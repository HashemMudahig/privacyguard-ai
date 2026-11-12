"""Normalized system activity models."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from ..evidence.models import ObservedState
from ..models import parse_timestamp
from .details import parse_activity_details


class ReportedResult(StrEnum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    PARTIAL = "PARTIAL"


class ActivityMetadata(BaseModel):
    """Operational metadata parsed from the free-text ``details`` column."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    user_ids: tuple[str, ...] = ()
    emails: tuple[str, ...] = ()
    phones: tuple[str, ...] = ()
    email_hashes: tuple[str, ...] = ()
    related_resource_ids: tuple[str, ...] = ()
    correlation_ids: dict[str, str] = {}
    state_claim: ObservedState | None = None
    state_claim_source: str | None = None
    notes: tuple[str, ...] = ()


class ActivityIndexStats(BaseModel):
    """High-level statistics for the activity index."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    events: int
    resources: int
    user_ids: int
    emails: int
    phones: int
    email_hashes: int
    event_types: int
    source_systems: int
    target_systems: int
    earliest_event_at: datetime | None = None
    latest_event_at: datetime | None = None


class SystemActivity(BaseModel):
    """One row from ``system_activity.csv``.

    ``reported_result`` is an operational claim. It is never treated as proof of
    resource state without corroborating evidence.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    activity_id: str
    event_time: datetime
    event_type: str
    source_system: str
    target_system: str
    resource_id: str
    reported_result: ReportedResult
    details: str
    metadata: ActivityMetadata = ActivityMetadata()

    @field_validator("event_time", mode="before")
    @classmethod
    def _parse_event_time(cls, value: str | datetime) -> datetime:
        return parse_timestamp(value)

    @model_validator(mode="before")
    @classmethod
    def _inject_metadata(cls, data: Any) -> Any:
        if isinstance(data, dict) and "metadata" not in data:
            payload = dict(data)
            payload["metadata"] = parse_activity_details(
                str(data.get("details") or ""),
                str(data.get("event_type") or ""),
                str(data.get("resource_id") or ""),
            )
            return payload
        return data

    @property
    def is_success(self) -> bool:
        return self.reported_result == ReportedResult.SUCCESS
