"""Deterministic step planning and ordering."""

from __future__ import annotations

from ..evidence.models import ObservedState
from ..policy.models import PolicyDecision, PolicyDecisionStatus, PolicyEvaluation
from .models import AuditStep, Operation, Phase

_PHASE_RANK = {Phase.FINDING: 0, Phase.REMEDIATION: 1, Phase.VERIFICATION: 2}
_OPERATION_RANK = {
    Operation.REPORT_REMAINING_RECORD: 0,
    Operation.REPORT_EXPOSED_PII: 1,
    Operation.REPORT_ACTIVE_DATA_FLOW: 2,
    Operation.REPORT_RESTORE_RISK: 3,
    Operation.DISABLE_DATA_FLOW: 0,
    Operation.BLOCK_RESTORE: 1,
    Operation.DELETE_RECORD: 2,
    Operation.REDACT_RECORD: 3,
    Operation.ANONYMIZE_RECORD: 4,
    Operation.VERIFY_RECORD_ABSENT: 0,
    Operation.VERIFY_RECORD_PRESENT: 1,
    Operation.VERIFY_RECORD_REDACTED: 2,
    Operation.VERIFY_RECORD_ANONYMIZED: 3,
    Operation.VERIFY_DATA_FLOW_DISABLED: 4,
    Operation.VERIFY_RESTORE_BLOCKED: 5,
}


class StepPlanner:
    """Turn policy decisions into ordered, deduplicated audit steps."""

    def plan(
        self,
        evaluation: PolicyEvaluation,
        *,
        complete: bool,
    ) -> tuple[AuditStep, ...]:
        raw: list[tuple[Phase, str, str, Operation, ObservedState, str]] = []
        for decision in evaluation.decisions:
            raw.extend(self._steps_for_decision(decision, complete=complete))

        seen: set[tuple[Phase, str, str, Operation, ObservedState, str]] = set()
        unique: list[tuple[Phase, str, str, Operation, ObservedState, str]] = []
        for item in raw:
            if item in seen:
                continue
            seen.add(item)
            unique.append(item)

        unique.sort(
            key=lambda item: (
                _PHASE_RANK[item[0]],
                _OPERATION_RANK[item[3]],
                item[1],
                item[2],
                item[4].value,
                item[5],
            )
        )

        return tuple(
            AuditStep(
                step_no=index,
                phase=phase,
                system_id=system_id,
                resource_id=resource_id,
                operation=operation,
                state=state,
                evidence_id=evidence_id,
            )
            for index, (
                phase,
                system_id,
                resource_id,
                operation,
                state,
                evidence_id,
            ) in enumerate(unique, start=1)
        )

    def _steps_for_decision(
        self, decision: PolicyDecision, *, complete: bool
    ) -> list[tuple[Phase, str, str, Operation, ObservedState, str]]:
        system_id = decision.system_id or "UNKNOWN"
        resource_id = decision.resource_id or "UNKNOWN"
        primary_evidence = decision.evidence_ids[0] if decision.evidence_ids else ""
        steps: list[tuple[Phase, str, str, Operation, ObservedState, str]] = []

        if not complete and decision.status == PolicyDecisionStatus.VIOLATION:
            if decision.finding_operation and decision.finding_state:
                steps.append(
                    (
                        Phase.FINDING,
                        system_id,
                        resource_id,
                        Operation(decision.finding_operation),
                        decision.finding_state,
                        primary_evidence,
                    )
                )
            if decision.remediation_operation and decision.remediation_state:
                steps.append(
                    (
                        Phase.REMEDIATION,
                        system_id,
                        resource_id,
                        Operation(decision.remediation_operation),
                        decision.remediation_state,
                        "",
                    )
                )

        if decision.verification_operation and decision.verification_state:
            steps.append(
                (
                    Phase.VERIFICATION,
                    system_id,
                    resource_id,
                    Operation(decision.verification_operation),
                    decision.verification_state,
                    primary_evidence if complete else "",
                )
            )
        return steps

    def missing_evidence_for_complete(
        self, evaluation: PolicyEvaluation
    ) -> tuple[str, ...]:
        missing: list[str] = []
        for decision in evaluation.decisions:
            if (
                decision.status == PolicyDecisionStatus.COMPLIANT
                and decision.verification_operation
                and not decision.evidence_ids
            ):
                missing.append(decision.resource_id or "UNKNOWN")
        return tuple(missing)
