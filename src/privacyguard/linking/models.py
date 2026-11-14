"""Models for resource-to-identity linking."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ResourceLinkType(StrEnum):
    EXPLICIT_USER_ID = "EXPLICIT_USER_ID"
    EMAIL = "EMAIL"
    PHONE = "PHONE"
    EMAIL_HASH = "EMAIL_HASH"
    RELATED_RESOURCE = "RELATED_RESOURCE"
    EVIDENCE_CHAIN = "EVIDENCE_CHAIN"
    ACTIVITY_IDENTITY_LINK = "ACTIVITY_IDENTITY_LINK"
    MULTIMODAL_INFERRED = "MULTIMODAL_INFERRED"
    ACTIVITY_RELATIONSHIP = "ACTIVITY_RELATIONSHIP"


class LinkLevel(StrEnum):
    CONFIRMED = "CONFIRMED"
    INFERRED = "INFERRED"
    CANDIDATE = "CANDIDATE"
    UNRESOLVED = "UNRESOLVED"


class LinkProvenance(BaseModel):
    """One source record supporting a resource link."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_type: Literal["EVIDENCE", "ACTIVITY"]
    source_id: str
    timestamp: datetime
    detail: str
    location: str | None = None
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)


class LinkedResource(BaseModel):
    """A resource linked to a resolved identity with explicit confidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    resource_id: str
    system_ids: tuple[str, ...] = ()
    data_categories: tuple[str, ...] = ()
    link_types: tuple[ResourceLinkType, ...] = ()
    confidence: float = Field(ge=0.0, le=1.0)
    verified: bool
    link_level: LinkLevel = LinkLevel.INFERRED
    observation_ids: tuple[str, ...] = ()
    activity_ids: tuple[str, ...] = ()
    event_types: tuple[str, ...] = ()
    provenance: tuple[LinkProvenance, ...] = ()
    warnings: tuple[str, ...] = ()


class UnresolvedResource(BaseModel):
    """A relationship that could not be linked confidently."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    resource_id: str | None = None
    system_id: str | None = None
    reason: str
    observation_ids: tuple[str, ...] = ()
    activity_ids: tuple[str, ...] = ()
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)


class AccountCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    resource_id: str
    system_id: str | None = None
    level: LinkLevel = LinkLevel.CANDIDATE
    confidence: float = Field(ge=0.0, le=1.0)
    reasons: tuple[str, ...] = ()
    observation_ids: tuple[str, ...] = ()
    activity_ids: tuple[str, ...] = ()
    event_types: tuple[str, ...] = ()
    provenance: tuple[LinkProvenance, ...] = ()
    warnings: tuple[str, ...] = ()


class ResourceLinkResult(BaseModel):
    """Linked and unresolved resources for one identity at a cutoff."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    linked: tuple[LinkedResource, ...] = ()
    unresolved: tuple[UnresolvedResource, ...] = ()
    candidates: tuple[AccountCandidate, ...] = ()
    warnings: tuple[str, ...] = ()
