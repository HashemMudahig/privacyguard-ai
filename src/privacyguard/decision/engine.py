"""Audit decision engine: intent + policy -> status + steps."""

from __future__ import annotations

from ..context.models import AuditContext
from ..intent.classifier import classify_intent
from ..intent.models import IntentStatus, RequestIntent
from ..planning.planner import StepPlanner
from ..policy.engine import PolicyEngine
from ..policy.models import PolicyDecisionStatus, PolicyEvaluation
from .models import AuditResult, DeletionStatus


class AuditDecisionEngine:
    def __init__(self, policy_engine: PolicyEngine, planner: StepPlanner) -> None:
        self.policy_engine = policy_engine
        self.planner = planner

    def audit(
        self,
        context: AuditContext,
        *,
        intent: RequestIntent | None = None,
    ) -> AuditResult:
        request_intent = intent or classify_intent(
            context.case_id, context.request.request_text
        )
        if not request_intent.authorizes_deletion:
            return AuditResult(
                case_id=context.case_id,
                deletion_status=DeletionStatus.NOT_APPLICABLE,
                steps=(),
                intent=request_intent,
                policy=PolicyEvaluation(case_id=context.case_id),
                coverage_gaps=(),
                uncertainties=request_intent.warnings,
                status_reasons=("Request does not authorize deletion",),
                provisional=False,
            )

        evaluation = self.policy_engine.evaluate(context)
        violations = [
            decision
            for decision in evaluation.decisions
            if decision.status == PolicyDecisionStatus.VIOLATION
        ]
        unknowns = [
            decision
            for decision in evaluation.decisions
            if decision.status == PolicyDecisionStatus.UNKNOWN
        ]
        missing_evidence = self.planner.missing_evidence_for_complete(evaluation)

        reasons: list[str] = []
        if not evaluation.decisions:
            reasons.append("No relevant evidence-backed or coverage resources were found")
        if violations:
            reasons.append(f"{len(violations)} policy violation(s) remain")
        if unknowns:
            reasons.append(f"{len(unknowns)} resource decision(s) remain unresolved")
        if missing_evidence:
            reasons.append(
                f"{len(missing_evidence)} compliant resource(s) lack an evidence citation"
            )

        complete = (
            bool(evaluation.decisions)
            and not violations
            and not unknowns
            and not missing_evidence
        )
        status = DeletionStatus.COMPLETE if complete else DeletionStatus.INCOMPLETE
        steps = self.planner.plan(evaluation, complete=complete)

        if complete:
            reasons.append("All linked/covered resources satisfy policy and required state")
        else:
            reasons.append("Deletion is not proven complete")

        coverage_gaps = list(evaluation.coverage_gaps)
        if not context.linked_resources:
            coverage_gaps.append("No evidence-backed resources were linked to the identity")
        if context.unresolved_resources:
            coverage_gaps.append(
                f"{len(context.unresolved_resources)} linked resource relationship(s) are unresolved"
            )
        if context.candidate_activity_resources:
            coverage_gaps.append(
                f"{len(context.candidate_activity_resources)} activity resource candidate(s) remain unlinked"
            )

        uncertainties: list[str] = []
        uncertainties.extend(request_intent.warnings)
        uncertainties.extend(evaluation.warnings)
        uncertainties.extend(context.uncertainties)
        uncertainties.extend(coverage_gaps)
        for decision in evaluation.decisions:
            uncertainties.extend(decision.uncertainties)

        provisional = (
            request_intent.status == IntentStatus.UNCERTAIN
            or any(decision.provisional for decision in evaluation.decisions)
            or bool(coverage_gaps)
        )

        return AuditResult(
            case_id=context.case_id,
            deletion_status=status,
            steps=steps,
            intent=request_intent,
            policy=evaluation,
            coverage_gaps=tuple(dict.fromkeys(coverage_gaps)),
            uncertainties=tuple(dict.fromkeys(uncertainties)),
            status_reasons=tuple(dict.fromkeys(reasons)),
            provisional=provisional,
        )
