"""Unit tests for policy rules, category resolution and decisions."""

from __future__ import annotations

from datetime import timezone

import pytest

from privacyguard.activity.models import SystemActivity
from privacyguard.context.models import AuditContext
from privacyguard.evidence.models import (
    EvidenceFormat,
    EvidenceLocation,
    EvidenceObservation,
    EvidenceProvenance,
    ObservedState,
)
from privacyguard.identity.index import IdentityIndex
from privacyguard.io.types import DatasetFile
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
from privacyguard.policy.categories import resolve_category
from privacyguard.policy.engine import PolicyEngine
from privacyguard.policy.models import (
    PolicyAction,
    PolicyCategory,
    PolicyDecisionStatus,
    PolicyEvaluation,
)
from privacyguard.policy.rules import load_policy_rules
from privacyguard.state.models import ResourceKind, ResourceState, StateBasis


def make_state(
    resource_id: str,
    category: str,
    state: ObservedState,
    system_id: str,
    *,
    evidence_id: str = "evidence_999",
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
                source_id=f"{evidence_id}:test:00001",
                timestamp=moment,
                state=state,
                detail="synthetic evidence",
                location="test",
                confidence=0.95,
            ),
        ),
        evidence_ids=(f"{evidence_id}:test:00001",),
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
    states: list[ResourceState],
    links: list[LinkedResource],
    *,
    request_text: str = "Please delete my account and personal data.",
    observations: list[EvidenceObservation] | None = None,
) -> AuditContext:
    moment = parse_timestamp("2026-01-02T00:00:00Z")
    request = DeletionRequest(
        case_id="case_9999",
        email="person@example.com",
        requested_at="2026-01-01T00:00:00Z",
        reported_status="COMPLETE",
        reported_at="2026-01-01T12:00:00Z",
        audit_at="2026-01-02T00:00:00Z",
        request_text=request_text,
    )
    identity = UserIdentity(
        user_id="user_synthetic",
        name="Synthetic Person",
        email="person@example.com",
        phone="+1 555 000 0000",
        email_hash="a" * 64,
        updated_at="2026-01-01T00:00:00Z",
    )
    resolved = IdentityResolution(
        status=ResolutionStatus.RESOLVED,
        identifier="person@example.com",
        normalized_identifier="person@example.com",
        kind="email",
        method=ResolutionMethod.CURRENT_EMAIL,
        matched_value="person@example.com",
        user_id="user_synthetic",
        identity=ResolvedIdentity(
            user_id="user_synthetic",
            current=identity,
            historical=HistoricalValues(),
            all_emails=("person@example.com",),
            all_phones=("+1 555 000 0000",),
            all_email_hashes=("a" * 64,),
            provenance=(),
            warnings=(),
        ),
    )
    return AuditContext(
        case_id="case_9999",
        audit_at=moment,
        request=request,
        resolution=resolved,
        identity=resolved.identity,
        linked_resources=tuple(links),
        states=tuple(states),
        relevant_observations=tuple(observations or ()),
    )


def make_legal_observation(
    resource_id: str,
    *,
    retain_until: str | None = None,
    state: ObservedState = ObservedState.PRESENT,
) -> EvidenceObservation:
    moment = parse_timestamp("2026-01-01T00:00:00Z")
    attributes = {"retain_until": retain_until} if retain_until else {}
    return EvidenceObservation(
        observation_id=f"evidence_legal:{resource_id}:00001",
        file_id="evidence_legal",
        file_path="evidence/legal_holds.json",
        captured_at=moment,
        observed_at=moment,
        format=EvidenceFormat.JSON,
        system_id="legal_service",
        resource_id=resource_id,
        data_category="LEGAL_HOLD_RECORD",
        observed_state=state,
        attributes=attributes,
        record={"resource_id": resource_id, "record_type": "LEGAL_HOLD_RECORD", **attributes},
        provenance=EvidenceProvenance(
            file_id="evidence_legal",
            file_path="evidence/legal_holds.json",
            captured_at=moment,
            source_format=EvidenceFormat.JSON,
            location=EvidenceLocation(json_path="records[0]"),
        ),
    )


def make_activity(
    activity_id: str,
    resource_id: str,
    event_type: str,
    *,
    target_system: str = "support_platform",
) -> SystemActivity:
    return SystemActivity.model_validate(
        {
            "activity_id": activity_id,
            "event_time": "2026-01-01T01:00:00Z",
            "event_type": event_type,
            "source_system": "deletion_worker",
            "target_system": target_system,
            "resource_id": resource_id,
            "reported_result": "SUCCESS",
            "details": "",
        }
    )


@pytest.fixture(scope="session")
def rules(settings):
    return load_policy_rules(settings.dataset_dir / "deletion_rules.csv")


def test_policy_rules_load(settings, rules) -> None:
    assert len(rules) == 15
    assert rules.for_category("USER_PROFILE").required_action == PolicyAction.DELETE
    assert rules.for_category("SECURITY_AUDIT_LOG").required_action == PolicyAction.RETAIN
    assert rules.for_category("ACCOUNT_TOMBSTONE").required_action == PolicyAction.REDACT


def test_category_resolution_explicit_and_unknown(rules) -> None:
    explicit = resolve_category(
        make_state("account_1", "USER_PROFILE", ObservedState.PRESENT, "account_service"),
        make_link("account_1", "USER_PROFILE", "account_service"),
        [],
        {"account_service"},
    )
    assert explicit.category == PolicyCategory.USER_PROFILE
    assert explicit.confidence >= 0.9

    unknown = resolve_category(
        make_state("object_1", "UNKNOWN", ObservedState.UNKNOWN, "object_storage"),
        make_link("object_1", "UNKNOWN", "object_storage"),
        [],
        {"object_storage"},
    )
    assert unknown.category == PolicyCategory.UNKNOWN


def test_category_resolution_uses_corroborated_prefix(rules) -> None:
    state = ResourceState(
        resource_id="account_9",
        kind=ResourceKind.RECORD,
        system_ids=(),
        data_categories=(),
        state=ObservedState.ABSENT,
        confidence=0.4,
        verified=False,
        basis=(),
    )
    link = make_link("account_9", "", "search_service")
    resolution = resolve_category(state, link, [], {"account_service"})
    assert resolution.category == PolicyCategory.USER_PROFILE
    assert "system_prefix" in resolution.source


def test_category_resolution_analytics_contact_lookup_is_secondary() -> None:
    moment = parse_timestamp("2026-01-01T00:00:00Z")
    observation = EvidenceObservation(
        observation_id="evidence_1:log:00001",
        file_id="evidence_1",
        file_path="evidence/test.log",
        captured_at=moment,
        observed_at=moment,
        format=EvidenceFormat.LOG,
        system_id="analytics_platform",
        resource_id="analytics_1",
        data_category=None,
        observed_state=ObservedState.PRESENT,
        attributes={"event": "contact_lookup_completed"},
        record={"event": "contact_lookup_completed"},
        provenance=EvidenceProvenance(
            file_id="evidence_1",
            file_path="evidence/test.log",
            captured_at=moment,
            source_format=EvidenceFormat.LOG,
            location=EvidenceLocation(line_number=1),
        ),
    )
    state = make_state("analytics_1", "UNKNOWN", ObservedState.PRESENT, "analytics_platform")
    resolution = resolve_category(state, None, [observation], {"analytics_platform"})
    assert resolution.category == PolicyCategory.SECONDARY_IDENTIFIER


def test_delete_present_is_violation(rules) -> None:
    state = make_state("account_1", "USER_PROFILE", ObservedState.PRESENT, "account_service")
    context = make_context([state], [make_link("account_1", "USER_PROFILE", "account_service")])
    evaluation = PolicyEngine(rules).evaluate(context)
    decision = evaluation.decisions[0]
    assert decision.status == PolicyDecisionStatus.VIOLATION
    assert decision.finding_operation == "REPORT_REMAINING_RECORD"
    assert decision.remediation_operation == "DELETE_RECORD"
    assert decision.verification_operation == "VERIFY_RECORD_ABSENT"


def test_delete_absent_is_compliant(rules) -> None:
    state = make_state("account_1", "USER_PROFILE", ObservedState.ABSENT, "account_service")
    context = make_context([state], [make_link("account_1", "USER_PROFILE", "account_service")])
    decision = PolicyEngine(rules).evaluate(context).decisions[0]
    assert decision.status == PolicyDecisionStatus.COMPLIANT
    assert decision.verification_operation == "VERIFY_RECORD_ABSENT"


def test_redact_present_is_violation(rules) -> None:
    state = make_state("support_1", "SUPPORT_MESSAGE", ObservedState.PRESENT, "support_platform")
    context = make_context([state], [make_link("support_1", "SUPPORT_MESSAGE", "support_platform")])
    decision = PolicyEngine(rules).evaluate(context).decisions[0]
    assert decision.status == PolicyDecisionStatus.VIOLATION
    assert decision.finding_operation == "REPORT_EXPOSED_PII"
    assert decision.remediation_operation == "REDACT_RECORD"


def test_anonymize_present_is_violation(rules) -> None:
    state = make_state("analytics_1", "ANALYTICS_PROFILE", ObservedState.PRESENT, "analytics_platform")
    context = make_context([state], [make_link("analytics_1", "ANALYTICS_PROFILE", "analytics_platform")])
    decision = PolicyEngine(rules).evaluate(context).decisions[0]
    assert decision.status == PolicyDecisionStatus.VIOLATION
    assert decision.finding_operation == "REPORT_EXPOSED_PII"
    assert decision.remediation_operation == "ANONYMIZE_RECORD"


def test_unverified_redact_state_is_unknown_not_compliant(rules) -> None:
    state = make_state(
        "support_1", "SUPPORT_MESSAGE", ObservedState.REDACTED, "support_platform",
        verified=False,
    )
    context = make_context([state], [make_link("support_1", "SUPPORT_MESSAGE", "support_platform")])
    decision = PolicyEngine(rules).evaluate(context).decisions[0]
    assert decision.status == PolicyDecisionStatus.UNKNOWN
    assert decision.finding_operation is None
    assert decision.remediation_operation is None
    assert decision.verification_operation == "VERIFY_RECORD_REDACTED"


def test_verified_redact_state_is_compliant(rules) -> None:
    state = make_state("support_1", "SUPPORT_MESSAGE", ObservedState.REDACTED, "support_platform")
    context = make_context([state], [make_link("support_1", "SUPPORT_MESSAGE", "support_platform")])
    decision = PolicyEngine(rules).evaluate(context).decisions[0]
    assert decision.status == PolicyDecisionStatus.COMPLIANT
    assert decision.verification_operation == "VERIFY_RECORD_REDACTED"


def test_retained_record_is_compliant(rules) -> None:
    state = make_state("audit_record_1", "SECURITY_AUDIT_LOG", ObservedState.PRESENT, "security_service")
    context = make_context(
        [state], [make_link("audit_record_1", "SECURITY_AUDIT_LOG", "security_service")]
    )
    decision = PolicyEngine(rules).evaluate(context).decisions[0]
    assert decision.status == PolicyDecisionStatus.COMPLIANT
    assert decision.verification_operation == "VERIFY_RECORD_PRESENT"


def test_backup_restore_risk(rules) -> None:
    state = make_state(
        "backup_1",
        "BACKUP_ARCHIVE",
        ObservedState.ACTIVE,
        "backup_service",
        restore_risk=True,
    )
    context = make_context([state], [make_link("backup_1", "BACKUP_ARCHIVE", "backup_service")])
    decision = PolicyEngine(rules).evaluate(context).decisions[0]
    assert decision.status == PolicyDecisionStatus.VIOLATION
    assert decision.finding_operation == "REPORT_RESTORE_RISK"
    assert decision.remediation_operation == "BLOCK_RESTORE"
    assert decision.verification_operation == "VERIFY_RESTORE_BLOCKED"


def test_active_data_flow_is_violation(rules) -> None:
    state = make_state("data_flow_1", "DATA_FLOW", ObservedState.ACTIVE, "integration_service")
    context = make_context([state], [make_link("data_flow_1", "DATA_FLOW", "integration_service")])
    decision = PolicyEngine(rules).evaluate(context).decisions[0]
    assert decision.status == PolicyDecisionStatus.VIOLATION
    assert decision.finding_operation == "REPORT_ACTIVE_DATA_FLOW"
    assert decision.remediation_operation == "DISABLE_DATA_FLOW"


def test_unknown_category_is_unknown(rules) -> None:
    state = make_state("object_1", "UNKNOWN", ObservedState.PRESENT, "object_storage")
    context = make_context([state], [make_link("object_1", "UNKNOWN", "object_storage")])
    decision = PolicyEngine(rules).evaluate(context).decisions[0]
    assert decision.status == PolicyDecisionStatus.UNKNOWN
    assert decision.finding_operation is None
    assert decision.remediation_operation is None


def test_active_legal_hold_requires_presence_verification(rules) -> None:
    observation = make_legal_observation(
        "legal_hold_1", retain_until="2026-02-01T00:00:00Z"
    )
    state = make_state(
        "legal_hold_1", "LEGAL_HOLD_RECORD", ObservedState.PRESENT, "legal_service"
    )
    context = make_context(
        [state],
        [make_link("legal_hold_1", "LEGAL_HOLD_RECORD", "legal_service")],
        observations=[observation],
    )
    decision = PolicyEngine(rules).evaluate(context).decisions[0]
    assert decision.condition_met is True
    assert decision.status == PolicyDecisionStatus.COMPLIANT
    assert decision.verification_operation == "VERIFY_RECORD_PRESENT"


def test_expired_legal_hold_needs_no_verification(rules) -> None:
    observation = make_legal_observation(
        "legal_hold_1", retain_until="2025-12-01T00:00:00Z"
    )
    state = make_state(
        "legal_hold_1", "LEGAL_HOLD_RECORD", ObservedState.PRESENT, "legal_service"
    )
    context = make_context(
        [state],
        [make_link("legal_hold_1", "LEGAL_HOLD_RECORD", "legal_service")],
        observations=[observation],
    )
    decision = PolicyEngine(rules).evaluate(context).decisions[0]
    assert decision.condition_met is False
    assert decision.status == PolicyDecisionStatus.COMPLIANT
    assert decision.verification_operation is None


def test_legal_hold_without_retention_date_is_active_by_presence(rules) -> None:
    observation = make_legal_observation("legal_hold_1")
    state = make_state(
        "legal_hold_1", "LEGAL_HOLD_RECORD", ObservedState.PRESENT, "legal_service"
    )
    context = make_context(
        [state],
        [make_link("legal_hold_1", "LEGAL_HOLD_RECORD", "legal_service")],
        observations=[observation],
    )
    decision = PolicyEngine(rules).evaluate(context).decisions[0]
    assert decision.condition_met is True
    assert decision.verification_operation == "VERIFY_RECORD_PRESENT"


def test_absent_legal_hold_is_a_violation_without_restore(rules) -> None:
    observation = make_legal_observation(
        "legal_hold_1", retain_until="2026-02-01T00:00:00Z", state=ObservedState.ABSENT
    )
    state = make_state(
        "legal_hold_1", "LEGAL_HOLD_RECORD", ObservedState.ABSENT, "legal_service"
    )
    context = make_context(
        [state],
        [make_link("legal_hold_1", "LEGAL_HOLD_RECORD", "legal_service")],
        observations=[observation],
    )
    decision = PolicyEngine(rules).evaluate(context).decisions[0]
    assert decision.status == PolicyDecisionStatus.VIOLATION
    assert decision.remediation_operation is None
    assert decision.verification_operation == "VERIFY_RECORD_PRESENT"


def test_support_redact_activity_does_not_classify_message() -> None:
    state = make_state("support_9", "UNKNOWN", ObservedState.PRESENT, "support_platform")
    link = make_link("support_9", "", "support_platform")
    resolution = resolve_category(
        state,
        link,
        [],
        {"support_platform"},
        [make_activity("activity_1", "support_9", "REDACT_RECORD")],
    )
    assert resolution.category == PolicyCategory.UNKNOWN


def test_support_delete_activity_does_not_classify_attachment() -> None:
    state = make_state("support_9", "UNKNOWN", ObservedState.PRESENT, "support_platform")
    link = make_link("support_9", "", "support_platform")
    resolution = resolve_category(
        state,
        link,
        [],
        {"support_platform"},
        [make_activity("activity_1", "support_9", "DELETE_RECORD")],
    )
    assert resolution.category == PolicyCategory.UNKNOWN


def test_conflicting_support_activities_remain_uncertain() -> None:
    state = make_state("support_9", "UNKNOWN", ObservedState.PRESENT, "support_platform")
    link = make_link("support_9", "", "support_platform")
    resolution = resolve_category(
        state,
        link,
        [],
        {"support_platform"},
        [
            make_activity("activity_2", "support_9", "DELETE_RECORD"),
            make_activity("activity_1", "support_9", "REDACT_RECORD"),
        ],
    )
    assert resolution.category == PolicyCategory.UNKNOWN


def test_support_prefix_alone_is_not_enough() -> None:
    state = make_state("support_9", "UNKNOWN", ObservedState.PRESENT, "support_platform")
    link = make_link("support_9", "", "support_platform")
    resolution = resolve_category(state, link, [], {"support_platform"}, [])
    assert resolution.category == PolicyCategory.UNKNOWN


def test_support_message_event_is_content_evidence() -> None:
    observation = make_legal_observation("support_9").model_copy(
        update={
            "system_id": "support_platform",
            "data_category": None,
            "attributes": {"event": "message_pii_scan"},
            "record": {"event": "message_pii_scan", "detector": "direct_identifier"},
        }
    )
    state = make_state("support_9", "UNKNOWN", ObservedState.PRESENT, "support_platform")
    resolution = resolve_category(
        state, make_link("support_9", "", "support_platform"), [observation]
    )
    assert resolution.category == PolicyCategory.SUPPORT_MESSAGE
    assert resolution.source == "content:support_message"


def test_category_evidence_excludes_losing_conflicting_category() -> None:
    state = make_state("object_9", "UNKNOWN", ObservedState.PRESENT, "mixed_service")
    account = make_legal_observation("object_9")
    account = account.model_copy(
        update={
            "file_id": "evidence_account",
            "observation_id": "evidence_account:json:1",
            "data_category": "USER_PROFILE",
        }
    )
    legal = make_legal_observation("object_9")
    resolution = resolve_category(state, None, [legal, account])
    assert resolution.category == PolicyCategory.USER_PROFILE
    assert resolution.evidence_ids == ("evidence_account",)


def test_state_evidence_precedes_activity_claim_for_citation(rules) -> None:
    moment = parse_timestamp("2026-01-01T00:00:00Z")
    state = make_state(
        "account_1", "USER_PROFILE", ObservedState.ABSENT, "account_service"
    ).model_copy(
        update={
            "basis": (
                StateBasis(
                    source_type="ACTIVITY",
                    source_id="activity_claim",
                    timestamp=moment,
                    state=ObservedState.ABSENT,
                    detail="delete success claim",
                    confidence=0.6,
                ),
                StateBasis(
                    source_type="EVIDENCE",
                    source_id="evidence_direct:sql:1",
                    timestamp=moment,
                    state=ObservedState.ABSENT,
                    detail="authoritative snapshot",
                    confidence=1.0,
                ),
            )
        }
    )
    context = make_context(
        [state], [make_link("account_1", "USER_PROFILE", "account_service")]
    )
    decision = PolicyEngine(rules).evaluate(context).decisions[0]
    assert decision.evidence_ids[:2] == ("evidence_direct", "activity_claim")
