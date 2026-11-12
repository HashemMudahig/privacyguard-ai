"""Independent synthetic end-to-end policy/decision cases.

These cases are not derived from the public sample answers. They exercise the
same production decision engine with hand-built audit contexts.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from privacyguard.context.models import AuditContext
from privacyguard.decision.models import DeletionStatus
from privacyguard.evidence.models import ObservedState
from privacyguard.linking.models import LinkedResource, ResourceLinkType
from privacyguard.models import (
    DeletionRequest,
    HistoricalValues,
    IdentityResolution,
    ResolutionMethod,
    ResolutionStatus,
    ResolvedIdentity,
    UserIdentity,
    parse_timestamp,
)
from privacyguard.planning.models import Operation, Phase
from privacyguard.state.models import ResourceKind, ResourceState, StateBasis


def make_state(
    resource_id: str,
    category: str,
    state: ObservedState,
    system_id: str,
    *,
    evidence_id: str,
    verified: bool = True,
    restore_risk: bool = False,
) -> ResourceState:
    moment = parse_timestamp("2026-01-01T00:00:00Z")
    kind = ResourceKind.RECORD
    if category == "DATA_FLOW":
        kind = ResourceKind.FLOW
    elif category == "BACKUP_ARCHIVE":
        kind = ResourceKind.BACKUP
    return ResourceState(
        resource_id=resource_id,
        kind=kind,
        system_ids=(system_id,),
        data_categories=(category,),
        state=state,
        confidence=0.95,
        verified=verified,
        basis=(
            StateBasis(
                source_type="EVIDENCE",
                source_id=f"{evidence_id}:synthetic:00001",
                timestamp=moment,
                state=state,
                detail="synthetic evidence",
                location="synthetic",
                confidence=0.95,
            ),
        ),
        evidence_ids=(f"{evidence_id}:synthetic:00001",),
        restore_risk=restore_risk,
    )


def make_link(resource_id: str, category: str, system_id: str) -> LinkedResource:
    return LinkedResource(
        resource_id=resource_id,
        system_ids=(system_id,),
        data_categories=(category,),
        link_types=(ResourceLinkType.EMAIL,),
        confidence=0.95,
        verified=True,
        observation_ids=(),
        activity_ids=(),
    )


def make_context(
    case_id: str,
    text: str,
    states: list[ResourceState],
    links: list[LinkedResource],
) -> AuditContext:
    moment = parse_timestamp("2026-01-02T00:00:00Z")
    request = DeletionRequest(
        case_id=case_id,
        email="synthetic@example.com",
        requested_at="2026-01-01T00:00:00Z",
        reported_status="COMPLETE",
        reported_at="2026-01-01T12:00:00Z",
        audit_at="2026-01-02T00:00:00Z",
        request_text=text,
    )
    identity = UserIdentity(
        user_id="user_synthetic",
        name="Synthetic Person",
        email="synthetic@example.com",
        phone="+1 555 000 0000",
        email_hash="a" * 64,
        updated_at="2026-01-01T00:00:00Z",
    )
    resolved = ResolvedIdentity(
        user_id="user_synthetic",
        current=identity,
        historical=HistoricalValues(),
        all_emails=("synthetic@example.com",),
        all_phones=("+1 555 000 0000",),
        all_email_hashes=("a" * 64,),
        provenance=(),
        warnings=(),
    )
    resolution = IdentityResolution(
        status=ResolutionStatus.RESOLVED,
        identifier="synthetic@example.com",
        normalized_identifier="synthetic@example.com",
        kind="email",
        method=ResolutionMethod.CURRENT_EMAIL,
        matched_value="synthetic@example.com",
        user_id="user_synthetic",
        identity=resolved,
    )
    return AuditContext(
        case_id=case_id,
        audit_at=moment,
        request=request,
        resolution=resolution,
        identity=resolved,
        linked_resources=tuple(links),
        states=tuple(states),
    )


def test_synthetic_complete_tombstone(pipeline) -> None:
    context = make_context(
        "case_9001",
        "Please delete my account and personal data.",
        [
            make_state("account_1", "USER_PROFILE", ObservedState.ABSENT, "account_service", evidence_id="evidence_1001"),
            make_state("audit_record_1", "SECURITY_AUDIT_LOG", ObservedState.PRESENT, "security_service", evidence_id="evidence_1002"),
            make_state("tombstone_1", "ACCOUNT_TOMBSTONE", ObservedState.REDACTED, "identity_service", evidence_id="evidence_1003"),
        ],
        [
            make_link("account_1", "USER_PROFILE", "account_service"),
            make_link("audit_record_1", "SECURITY_AUDIT_LOG", "security_service"),
            make_link("tombstone_1", "ACCOUNT_TOMBSTONE", "identity_service"),
        ],
    )
    result = pipeline.decision_engine.audit(context)
    assert result.deletion_status == DeletionStatus.COMPLETE
    assert [step.operation for step in result.steps] == [
        Operation.VERIFY_RECORD_ABSENT,
        Operation.VERIFY_RECORD_PRESENT,
        Operation.VERIFY_RECORD_REDACTED,
    ]
    assert all(step.phase == Phase.VERIFICATION for step in result.steps)
    assert all(step.evidence_id for step in result.steps)


def test_synthetic_incomplete_replica_and_flow(pipeline) -> None:
    context = make_context(
        "case_9002",
        "Please delete my account permanently.",
        [
            make_state("account_2", "USER_PROFILE", ObservedState.PRESENT, "account_service", evidence_id="evidence_2001"),
            make_state("search_2", "SEARCH_INDEX_ENTRY", ObservedState.PRESENT, "search_service", evidence_id="evidence_2002"),
            make_state("data_flow_2", "DATA_FLOW", ObservedState.ACTIVE, "integration_service", evidence_id="evidence_2003"),
            make_state("audit_record_2", "SECURITY_AUDIT_LOG", ObservedState.PRESENT, "security_service", evidence_id="evidence_2004"),
        ],
        [
            make_link("account_2", "USER_PROFILE", "account_service"),
            make_link("search_2", "SEARCH_INDEX_ENTRY", "search_service"),
            make_link("data_flow_2", "DATA_FLOW", "integration_service"),
            make_link("audit_record_2", "SECURITY_AUDIT_LOG", "security_service"),
        ],
    )
    result = pipeline.decision_engine.audit(context)
    assert result.deletion_status == DeletionStatus.INCOMPLETE
    findings = [step for step in result.steps if step.phase == Phase.FINDING]
    remediation = [step for step in result.steps if step.phase == Phase.REMEDIATION]
    assert [step.operation for step in findings] == [
        Operation.REPORT_REMAINING_RECORD,
        Operation.REPORT_REMAINING_RECORD,
        Operation.REPORT_ACTIVE_DATA_FLOW,
    ]
    assert [step.operation for step in remediation] == [
        Operation.DISABLE_DATA_FLOW,
        Operation.DELETE_RECORD,
        Operation.DELETE_RECORD,
    ]
    assert all(step.evidence_id == "" for step in remediation)


def test_synthetic_not_applicable_access(pipeline) -> None:
    context = make_context(
        "case_9003",
        "Could you send me a copy of the information held on my account? I still use it.",
        [],
        [],
    )
    result = pipeline.decision_engine.audit(context)
    assert result.deletion_status == DeletionStatus.NOT_APPLICABLE
    assert result.steps == ()


def test_synthetic_restore_backup_risk(pipeline) -> None:
    context = make_context(
        "case_9004",
        "Please delete my account and do not let backups restore my data.",
        [
            make_state("account_3", "USER_PROFILE", ObservedState.ABSENT, "account_service", evidence_id="evidence_3001"),
            make_state(
                "backup_3",
                "BACKUP_ARCHIVE",
                ObservedState.ACTIVE,
                "backup_service",
                evidence_id="evidence_3002",
                restore_risk=True,
            ),
            make_state("audit_record_3", "SECURITY_AUDIT_LOG", ObservedState.PRESENT, "security_service", evidence_id="evidence_3003"),
        ],
        [
            make_link("account_3", "USER_PROFILE", "account_service"),
            make_link("backup_3", "BACKUP_ARCHIVE", "backup_service"),
            make_link("audit_record_3", "SECURITY_AUDIT_LOG", "security_service"),
        ],
    )
    result = pipeline.decision_engine.audit(context)
    assert result.deletion_status == DeletionStatus.INCOMPLETE
    assert any(step.operation == Operation.REPORT_RESTORE_RISK for step in result.steps)
    assert any(step.operation == Operation.BLOCK_RESTORE for step in result.steps)
    assert any(step.operation == Operation.VERIFY_RESTORE_BLOCKED for step in result.steps)
