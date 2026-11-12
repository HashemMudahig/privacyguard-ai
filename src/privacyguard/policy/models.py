"""Policy-engine models."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from ..evidence.models import ObservedState


class PolicyCategory(StrEnum):
    USER_PROFILE = "USER_PROFILE"
    SECONDARY_IDENTIFIER = "SECONDARY_IDENTIFIER"
    SEARCH_INDEX_ENTRY = "SEARCH_INDEX_ENTRY"
    CACHE_ENTRY = "CACHE_ENTRY"
    SUPPORT_MESSAGE = "SUPPORT_MESSAGE"
    SUPPORT_ATTACHMENT = "SUPPORT_ATTACHMENT"
    ANALYTICS_PROFILE = "ANALYTICS_PROFILE"
    PRODUCT_TELEMETRY = "PRODUCT_TELEMETRY"
    USER_EXPORT = "USER_EXPORT"
    MARKETING_PROFILE = "MARKETING_PROFILE"
    EMAIL_DELIVERY_LOG = "EMAIL_DELIVERY_LOG"
    SECURITY_AUDIT_LOG = "SECURITY_AUDIT_LOG"
    LEGAL_HOLD_RECORD = "LEGAL_HOLD_RECORD"
    BACKUP_ARCHIVE = "BACKUP_ARCHIVE"
    ACCOUNT_TOMBSTONE = "ACCOUNT_TOMBSTONE"
    DATA_FLOW = "DATA_FLOW"
    UNKNOWN = "UNKNOWN"


class PolicyAction(StrEnum):
    DELETE = "DELETE"
    REDACT = "REDACT"
    ANONYMIZE = "ANONYMIZE"
    RETAIN = "RETAIN"
    BLOCK_RESTORE = "BLOCK_RESTORE"
    DISABLE_DATA_FLOW = "DISABLE_DATA_FLOW"


class PolicyDecisionStatus(StrEnum):
    COMPLIANT = "COMPLIANT"
    VIOLATION = "VIOLATION"
    UNKNOWN = "UNKNOWN"


class PolicyRule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    rule_id: str
    data_category: str
    condition: str
    required_action: PolicyAction


class CategoryResolution(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    category: PolicyCategory
    confidence: float = Field(ge=0.0, le=1.0)
    source: str
    evidence_ids: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


class PolicyDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    resource_id: str | None
    system_id: str | None
    category: PolicyCategory
    category_confidence: float = Field(ge=0.0, le=1.0)
    category_source: str
    rule_id: str | None = None
    required_action: PolicyAction | None = None
    condition: str | None = None
    condition_met: bool | None = None
    status: PolicyDecisionStatus
    observed_state: ObservedState
    required_final_state: ObservedState | None = None
    finding_operation: str | None = None
    finding_state: ObservedState | None = None
    remediation_operation: str | None = None
    remediation_state: ObservedState | None = None
    verification_operation: str | None = None
    verification_state: ObservedState | None = None
    reason: str
    evidence_ids: tuple[str, ...] = ()
    provisional: bool = False
    uncertainties: tuple[str, ...] = ()


class PolicyEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str
    decisions: tuple[PolicyDecision, ...] = ()
    coverage_gaps: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
