"""Unit tests for step planning and ordering."""

from __future__ import annotations

from privacyguard.evidence.models import ObservedState
from privacyguard.planning.models import Operation, Phase
from privacyguard.planning.planner import StepPlanner
from privacyguard.policy.models import (
    PolicyDecision,
    PolicyDecisionStatus,
    PolicyEvaluation,
)


def decision(
    resource_id: str,
    system_id: str,
    status: PolicyDecisionStatus,
    *,
    finding: str | None = None,
    remediation: str | None = None,
    remediation_state: ObservedState = ObservedState.ABSENT,
    verification: str | None = None,
    verification_state: ObservedState = ObservedState.ABSENT,
    evidence: tuple[str, ...] = ("evidence_1",),
) -> PolicyDecision:
    return PolicyDecision(
        resource_id=resource_id,
        system_id=system_id,
        category="USER_PROFILE",
        category_confidence=1.0,
        category_source="test",
        status=status,
        observed_state=ObservedState.PRESENT,
        required_final_state=verification_state,
        finding_operation=finding,
        finding_state=ObservedState.PRESENT if finding else None,
        remediation_operation=remediation,
        remediation_state=remediation_state if remediation else None,
        verification_operation=verification,
        verification_state=verification_state,
        reason="test",
        evidence_ids=evidence,
    )


def test_incomplete_step_order_and_evidence_rules() -> None:
    evaluation = PolicyEvaluation(
        case_id="case_x",
        decisions=(
            decision(
                "account_2",
                "account_service",
                PolicyDecisionStatus.VIOLATION,
                finding="REPORT_REMAINING_RECORD",
                remediation="DELETE_RECORD",
                verification="VERIFY_RECORD_ABSENT",
                evidence=("evidence_2",),
            ),
            decision(
                "data_flow_1",
                "integration_service",
                PolicyDecisionStatus.VIOLATION,
                finding="REPORT_ACTIVE_DATA_FLOW",
                remediation="DISABLE_DATA_FLOW",
                remediation_state=ObservedState.DISABLED,
                verification="VERIFY_DATA_FLOW_DISABLED",
                verification_state=ObservedState.DISABLED,
                evidence=("evidence_3",),
            ),
            decision(
                "audit_record_1",
                "security_service",
                PolicyDecisionStatus.COMPLIANT,
                verification="VERIFY_RECORD_PRESENT",
                verification_state=ObservedState.PRESENT,
                evidence=("evidence_4",),
            ),
        ),
    )
    steps = StepPlanner().plan(evaluation, complete=False)
    assert [step.step_no for step in steps] == list(range(1, len(steps) + 1))
    assert [step.phase for step in steps[:2]] == [Phase.FINDING, Phase.FINDING]
    assert [step.operation for step in steps[:2]] == [
        Operation.REPORT_REMAINING_RECORD,
        Operation.REPORT_ACTIVE_DATA_FLOW,
    ]
    assert [step.phase for step in steps[2:4]] == [Phase.REMEDIATION, Phase.REMEDIATION]
    assert [step.operation for step in steps if step.phase == Phase.REMEDIATION] == [
        Operation.DISABLE_DATA_FLOW,
        Operation.DELETE_RECORD,
    ]
    for step in steps:
        if step.phase == Phase.FINDING:
            assert step.evidence_id
        elif step.phase in {Phase.REMEDIATION, Phase.VERIFICATION}:
            assert step.evidence_id == ""


def test_complete_has_only_verification_with_evidence() -> None:
    evaluation = PolicyEvaluation(
        case_id="case_x",
        decisions=(
            decision(
                "account_1",
                "account_service",
                PolicyDecisionStatus.COMPLIANT,
                verification="VERIFY_RECORD_ABSENT",
                evidence=("evidence_1",),
            ),
            decision(
                "audit_record_1",
                "security_service",
                PolicyDecisionStatus.COMPLIANT,
                verification="VERIFY_RECORD_PRESENT",
                verification_state=ObservedState.PRESENT,
                evidence=("evidence_2",),
            ),
        ),
    )
    steps = StepPlanner().plan(evaluation, complete=True)
    assert all(step.phase == Phase.VERIFICATION for step in steps)
    assert all(step.evidence_id for step in steps)
    assert steps[0].operation == Operation.VERIFY_RECORD_ABSENT
    assert steps[1].operation == Operation.VERIFY_RECORD_PRESENT


def test_planner_deduplicates_identical_steps() -> None:
    duplicate = decision(
        "account_1",
        "account_service",
        PolicyDecisionStatus.COMPLIANT,
        verification="VERIFY_RECORD_ABSENT",
        evidence=("evidence_1",),
    )
    steps = StepPlanner().plan(
        PolicyEvaluation(case_id="case_x", decisions=(duplicate, duplicate)),
        complete=True,
    )
    assert len(steps) == 1


def test_missing_evidence_detection() -> None:
    evaluation = PolicyEvaluation(
        case_id="case_x",
        decisions=(
            decision(
                "account_1",
                "account_service",
                PolicyDecisionStatus.COMPLIANT,
                verification="VERIFY_RECORD_ABSENT",
                evidence=(),
            ),
        ),
    )
    assert StepPlanner().missing_evidence_for_complete(evaluation) == ("account_1",)
