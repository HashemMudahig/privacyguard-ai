"""Deterministic deletion policy evaluation on top of audit contexts."""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from ..activity.models import SystemActivity
from ..context.models import AuditContext
from ..evidence.models import EvidenceObservation, ObservedState
from ..linking.models import LinkLevel, LinkedResource
from ..models import parse_timestamp
from ..state.models import ResourceState
from .categories import observations_by_resource, resolve_category
from .models import (
    CategoryResolution,
    PolicyAction,
    PolicyCategory,
    PolicyDecision,
    PolicyDecisionStatus,
    PolicyEvaluation,
)
from .rules import PolicyRuleSet

_ACTION_FINAL_STATE: dict[PolicyAction, ObservedState] = {
    PolicyAction.DELETE: ObservedState.ABSENT,
    PolicyAction.REDACT: ObservedState.REDACTED,
    PolicyAction.ANONYMIZE: ObservedState.ANONYMIZED,
    PolicyAction.RETAIN: ObservedState.PRESENT,
    PolicyAction.BLOCK_RESTORE: ObservedState.BLOCKED,
    PolicyAction.DISABLE_DATA_FLOW: ObservedState.DISABLED,
}

_ACTION_VERIFICATION: dict[PolicyAction, tuple[str, ObservedState]] = {
    PolicyAction.DELETE: ("VERIFY_RECORD_ABSENT", ObservedState.ABSENT),
    PolicyAction.REDACT: ("VERIFY_RECORD_REDACTED", ObservedState.REDACTED),
    PolicyAction.ANONYMIZE: ("VERIFY_RECORD_ANONYMIZED", ObservedState.ANONYMIZED),
    PolicyAction.RETAIN: ("VERIFY_RECORD_PRESENT", ObservedState.PRESENT),
    PolicyAction.BLOCK_RESTORE: ("VERIFY_RESTORE_BLOCKED", ObservedState.BLOCKED),
    PolicyAction.DISABLE_DATA_FLOW: ("VERIFY_DATA_FLOW_DISABLED", ObservedState.DISABLED),
}

_ACTION_FINDING: dict[PolicyAction, tuple[str, ObservedState]] = {
    PolicyAction.DELETE: ("REPORT_REMAINING_RECORD", ObservedState.PRESENT),
    PolicyAction.REDACT: ("REPORT_EXPOSED_PII", ObservedState.PRESENT),
    PolicyAction.ANONYMIZE: ("REPORT_EXPOSED_PII", ObservedState.PRESENT),
    PolicyAction.BLOCK_RESTORE: ("REPORT_RESTORE_RISK", ObservedState.ACTIVE),
    PolicyAction.DISABLE_DATA_FLOW: ("REPORT_ACTIVE_DATA_FLOW", ObservedState.ACTIVE),
}

_ACTION_REMEDIATION: dict[PolicyAction, tuple[str, ObservedState]] = {
    PolicyAction.DELETE: ("DELETE_RECORD", ObservedState.ABSENT),
    PolicyAction.REDACT: ("REDACT_RECORD", ObservedState.REDACTED),
    PolicyAction.ANONYMIZE: ("ANONYMIZE_RECORD", ObservedState.ANONYMIZED),
    PolicyAction.BLOCK_RESTORE: ("BLOCK_RESTORE", ObservedState.BLOCKED),
    PolicyAction.DISABLE_DATA_FLOW: ("DISABLE_DATA_FLOW", ObservedState.DISABLED),
}

_ABSENT_VERIFICATION = ("VERIFY_RECORD_ABSENT", ObservedState.ABSENT)


class PolicyEngine:
    def __init__(self, rules: PolicyRuleSet) -> None:
        self.rules = rules

    def evaluate(self, context: AuditContext) -> PolicyEvaluation:
        observations = observations_by_resource(context.relevant_observations)
        links = {link.resource_id: link for link in context.linked_resources}
        activity_systems = _activity_systems_by_resource(context)
        activity_events = _activity_events_by_resource(context)
        decisions = [
            self._evaluate_resource(
                state,
                links.get(state.resource_id),
                observations.get(state.resource_id, []),
                activity_systems.get(state.resource_id, set()),
                activity_events.get(state.resource_id, []),
                context.audit_at,
            )
            for state in context.states
        ]

        coverage_gaps: list[str] = []
        if not any(
            decision.category == PolicyCategory.USER_PROFILE for decision in decisions
        ):
            coverage_gaps.append("No account resource could be linked to the identity")

        if not decisions:
            coverage_gaps.append("No relevant resources could be linked or covered")

        return PolicyEvaluation(
            case_id=context.case_id,
            decisions=tuple(decisions),
            coverage_gaps=tuple(dict.fromkeys(coverage_gaps)),
            warnings=tuple(
                warning for decision in decisions for warning in decision.uncertainties
            ),
        )

    def _evaluate_resource(
        self,
        state: ResourceState,
        link: LinkedResource | None,
        observations: list[EvidenceObservation],
        activity_systems: set[str],
        activity_events: list[SystemActivity],
        audit_at,
    ) -> PolicyDecision:
        resolution = resolve_category(
            state, link, observations, activity_systems, activity_events
        )
        rule = (
            self.rules.for_category(resolution.category.value)
            if resolution.category != PolicyCategory.UNKNOWN
            else None
        )
        evidence_ids = _evidence_ids(state, resolution)
        provisional = not state.verified or resolution.confidence < 0.8
        system_id = _choose_system(resolution.category, state.system_ids, activity_systems)

        if resolution.category == PolicyCategory.DATA_FLOW:
            return _build_decision(
                state,
                resolution,
                system_id,
                "risk_data_flow",
                PolicyAction.DISABLE_DATA_FLOW,
                "Active data flow can recreate or copy the subject's data",
                True,
                evidence_ids,
                provisional,
                link.link_level if link else None,
            )
        if resolution.category == PolicyCategory.BACKUP_ARCHIVE:
            return _build_decision(
                state,
                resolution,
                system_id,
                rule.rule_id if rule else "rule_14",
                PolicyAction.BLOCK_RESTORE,
                rule.condition if rule else "Restore access can be blocked",
                True,
                evidence_ids,
                provisional,
                link.link_level if link else None,
            )

        if rule is None:
            return PolicyDecision(
                resource_id=state.resource_id,
                system_id=_choose_system(resolution.category, state.system_ids, activity_systems),
                category=resolution.category,
                category_confidence=resolution.confidence,
                category_source=resolution.source,
                status=PolicyDecisionStatus.UNKNOWN,
                link_level=link.link_level if link else None,
                observed_state=state.state,
                reason="No deletion rule could be established for this resource category",
                evidence_ids=evidence_ids,
                provisional=True,
                uncertainties=(
                    *resolution.warnings,
                    "Policy category is unknown; no destructive action was invented",
                ),
            )

        action = rule.required_action
        condition_met = _condition_met(
            rule.rule_id, action, state, observations, resolution, audit_at
        )
        return _build_decision(
            state,
            resolution,
            system_id,
            rule.rule_id,
            action,
            rule.condition,
            condition_met,
            evidence_ids,
            provisional,
            link.link_level if link else None,
        )

_EXPECTED_SYSTEM: dict[PolicyCategory, str] = {
    PolicyCategory.USER_PROFILE: "account_service",
    PolicyCategory.SEARCH_INDEX_ENTRY: "search_service",
    PolicyCategory.ANALYTICS_PROFILE: "analytics_platform",
    PolicyCategory.PRODUCT_TELEMETRY: "analytics_platform",
    PolicyCategory.SUPPORT_MESSAGE: "support_platform",
    PolicyCategory.SUPPORT_ATTACHMENT: "support_platform",
    PolicyCategory.USER_EXPORT: "export_service",
    PolicyCategory.MARKETING_PROFILE: "marketing_platform",
    PolicyCategory.EMAIL_DELIVERY_LOG: "email_delivery_service",
    PolicyCategory.SECURITY_AUDIT_LOG: "security_service",
    PolicyCategory.LEGAL_HOLD_RECORD: "legal_service",
    PolicyCategory.BACKUP_ARCHIVE: "backup_service",
    PolicyCategory.ACCOUNT_TOMBSTONE: "identity_service",
    PolicyCategory.DATA_FLOW: "integration_service",
    PolicyCategory.CACHE_ENTRY: "cache_service",
    PolicyCategory.SECONDARY_IDENTIFIER: "analytics_platform",
}


def _choose_system(
    category: PolicyCategory,
    state_systems: tuple[str, ...],
    activity_systems: Iterable[str],
) -> str | None:
    available = list(dict.fromkeys([*state_systems, *activity_systems]))
    expected = _EXPECTED_SYSTEM.get(category)
    if expected and expected in available:
        return expected
    if available:
        return available[0]
    return None


def _build_decision(
    state: ResourceState,
    resolution: CategoryResolution,
    system_id: str | None,
    rule_id: str,
    action: PolicyAction,
    condition: str,
    condition_met: bool | None,
    evidence_ids: tuple[str, ...],
    provisional: bool,
    link_level: LinkLevel | None = None,
) -> PolicyDecision:
    observed = state.state
    base = dict(
        resource_id=state.resource_id,
        system_id=system_id,
        category=resolution.category,
        category_confidence=resolution.confidence,
        category_source=resolution.source,
        rule_id=rule_id,
        required_action=action,
        condition=condition,
        condition_met=condition_met,
        observed_state=observed,
        required_final_state=_ACTION_FINAL_STATE[action],
        evidence_ids=evidence_ids,
        link_level=link_level,
        provisional=provisional,
        uncertainties=tuple(resolution.warnings),
    )

    if action == PolicyAction.RETAIN:
        if condition_met is False:
            return PolicyDecision(
                **base,
                status=PolicyDecisionStatus.COMPLIANT,
                reason=(
                    "The retention period or legal hold is inactive at audit_at; "
                    "no retention verification is required"
                ),
            )
        if condition_met is None:
            return PolicyDecision(
                **base,
                status=PolicyDecisionStatus.UNKNOWN,
                reason=(
                    "The retention period or legal hold applicability could not be "
                    "established; no verification was invented"
                ),
            )
        if observed == ObservedState.ABSENT:
            return PolicyDecision(
                **base,
                status=PolicyDecisionStatus.VIOLATION,
                verification_operation="VERIFY_RECORD_PRESENT",
                verification_state=ObservedState.PRESENT,
                reason=(
                    "A policy-required retained record is absent; no restore operation is defined"
                ),
            )
        if observed == ObservedState.PRESENT and state.verified:
            return PolicyDecision(
                **base,
                status=PolicyDecisionStatus.COMPLIANT,
                verification_operation="VERIFY_RECORD_PRESENT",
                verification_state=ObservedState.PRESENT,
                reason="Policy-required retained record remains available",
            )
        return PolicyDecision(
            **base,
            status=PolicyDecisionStatus.UNKNOWN,
            verification_operation="VERIFY_RECORD_PRESENT",
            verification_state=ObservedState.PRESENT,
            reason=(
                "Retained record state is unknown"
                if observed != ObservedState.PRESENT
                else "Retained record presence is supported only by an unverified activity/inference"
            ),
        )

    if action == PolicyAction.BLOCK_RESTORE:
        if observed == ObservedState.ACTIVE or state.restore_risk:
            return PolicyDecision(
                **base,
                status=PolicyDecisionStatus.VIOLATION,
                finding_operation="REPORT_RESTORE_RISK",
                finding_state=ObservedState.ACTIVE,
                remediation_operation="BLOCK_RESTORE",
                remediation_state=ObservedState.BLOCKED,
                verification_operation="VERIFY_RESTORE_BLOCKED",
                verification_state=ObservedState.BLOCKED,
                reason="Backup still permits restore of deleted data",
            )
        if observed == ObservedState.BLOCKED and state.verified:
            return PolicyDecision(
                **base,
                status=PolicyDecisionStatus.COMPLIANT,
                verification_operation="VERIFY_RESTORE_BLOCKED",
                verification_state=ObservedState.BLOCKED,
                reason="Backup restore access is blocked",
            )
        if observed == ObservedState.ABSENT:
            return PolicyDecision(
                **base,
                status=PolicyDecisionStatus.VIOLATION,
                verification_operation="VERIFY_RECORD_PRESENT",
                verification_state=ObservedState.PRESENT,
                reason="A policy-required backup archive is absent",
            )
        return PolicyDecision(
            **base,
            status=PolicyDecisionStatus.UNKNOWN,
            verification_operation="VERIFY_RESTORE_BLOCKED",
            verification_state=ObservedState.BLOCKED,
            reason="Backup restore state is unknown",
        )

    if action == PolicyAction.DISABLE_DATA_FLOW:
        if observed == ObservedState.ACTIVE:
            return PolicyDecision(
                **base,
                status=PolicyDecisionStatus.VIOLATION,
                finding_operation="REPORT_ACTIVE_DATA_FLOW",
                finding_state=ObservedState.ACTIVE,
                remediation_operation="DISABLE_DATA_FLOW",
                remediation_state=ObservedState.DISABLED,
                verification_operation="VERIFY_DATA_FLOW_DISABLED",
                verification_state=ObservedState.DISABLED,
                reason="An active data flow can recreate or copy the subject's data",
            )
        if observed == ObservedState.DISABLED and state.verified:
            return PolicyDecision(
                **base,
                status=PolicyDecisionStatus.COMPLIANT,
                verification_operation="VERIFY_DATA_FLOW_DISABLED",
                verification_state=ObservedState.DISABLED,
                reason="The data flow is disabled",
            )
        if observed == ObservedState.ABSENT and state.verified:
            return PolicyDecision(
                **base,
                status=PolicyDecisionStatus.COMPLIANT,
                verification_operation="VERIFY_DATA_FLOW_DISABLED",
                verification_state=ObservedState.DISABLED,
                reason="No active data flow remains",
            )
        return PolicyDecision(
            **base,
            status=PolicyDecisionStatus.UNKNOWN,
            verification_operation="VERIFY_DATA_FLOW_DISABLED",
            verification_state=ObservedState.DISABLED,
            reason="Data-flow state is unknown",
        )

    # DELETE / REDACT / ANONYMIZE
    if observed == ObservedState.ABSENT and state.verified:
        return PolicyDecision(
            **base,
            status=PolicyDecisionStatus.COMPLIANT,
            verification_operation="VERIFY_RECORD_ABSENT",
            verification_state=ObservedState.ABSENT,
            reason="The record is absent",
        )
    if observed == ObservedState.UNKNOWN or (
        observed == ObservedState.ABSENT and not state.verified
    ):
        verification, verification_state = _ACTION_VERIFICATION[action]
        return PolicyDecision(
            **base,
            status=PolicyDecisionStatus.UNKNOWN,
            verification_operation=verification,
            verification_state=verification_state,
            reason=(
                "The record state is unknown; no outcome was invented"
                if observed == ObservedState.UNKNOWN
                else "Record absence is supported only by an unverified activity/inference"
            ),
        )
    if not state.verified:
        verification, verification_state = _ACTION_VERIFICATION[action]
        return PolicyDecision(
            **base,
            status=PolicyDecisionStatus.UNKNOWN,
            verification_operation=verification,
            verification_state=verification_state,
            reason=(
                "The apparent final record state is supported only by an "
                "unverified activity or inference"
            ),
        )

    if action == PolicyAction.DELETE:
        violation = observed == ObservedState.PRESENT or observed == ObservedState.REDACTED
        if violation:
            return PolicyDecision(
                **base,
                status=PolicyDecisionStatus.VIOLATION,
                finding_operation="REPORT_REMAINING_RECORD",
                finding_state=ObservedState.PRESENT,
                remediation_operation="DELETE_RECORD",
                remediation_state=ObservedState.ABSENT,
                verification_operation="VERIFY_RECORD_ABSENT",
                verification_state=ObservedState.ABSENT,
                reason="A record that policy requires deleting is still present",
            )
        return PolicyDecision(
            **base,
            status=PolicyDecisionStatus.UNKNOWN,
            reason="Record state does not support a delete decision",
        )

    if action == PolicyAction.REDACT:
        if observed == ObservedState.REDACTED and state.verified:
            return PolicyDecision(
                **base,
                status=PolicyDecisionStatus.COMPLIANT,
                verification_operation="VERIFY_RECORD_REDACTED",
                verification_state=ObservedState.REDACTED,
                reason="Required direct identifiers are redacted",
            )
        if observed == ObservedState.ANONYMIZED and state.verified:
            return PolicyDecision(
                **base,
                status=PolicyDecisionStatus.COMPLIANT,
                verification_operation="VERIFY_RECORD_ANONYMIZED",
                verification_state=ObservedState.ANONYMIZED,
                reason="Record is anonymized rather than redacted; stricter treatment is present",
            )
        return PolicyDecision(
            **base,
            status=PolicyDecisionStatus.VIOLATION,
            finding_operation="REPORT_EXPOSED_PII",
            finding_state=ObservedState.PRESENT,
            remediation_operation="REDACT_RECORD",
            remediation_state=ObservedState.REDACTED,
            verification_operation="VERIFY_RECORD_REDACTED",
            verification_state=ObservedState.REDACTED,
            reason="A retained record still exposes identifiers that policy requires redacting",
        )

    if action == PolicyAction.ANONYMIZE:
        if observed == ObservedState.ANONYMIZED and state.verified:
            return PolicyDecision(
                **base,
                status=PolicyDecisionStatus.COMPLIANT,
                verification_operation="VERIFY_RECORD_ANONYMIZED",
                verification_state=ObservedState.ANONYMIZED,
                reason="Record is anonymized",
            )
        return PolicyDecision(
            **base,
            status=PolicyDecisionStatus.VIOLATION,
            finding_operation="REPORT_EXPOSED_PII",
            finding_state=ObservedState.PRESENT,
            remediation_operation="ANONYMIZE_RECORD",
            remediation_state=ObservedState.ANONYMIZED,
            verification_operation="VERIFY_RECORD_ANONYMIZED",
            verification_state=ObservedState.ANONYMIZED,
            reason="An attributable analytics/telemetry record requires anonymization",
        )

    return PolicyDecision(
        **base,
        status=PolicyDecisionStatus.UNKNOWN,
        reason="Unsupported policy action",
    )


def _condition_met(
    rule_id: str,
    action: PolicyAction,
    state: ResourceState,
    observations: list[EvidenceObservation],
    resolution: CategoryResolution,
    audit_at,
) -> bool | None:
    if rule_id == "rule_13":
        retain_until = _latest_retention_date(observations)
        if retain_until is None:
            return True
        return audit_at <= retain_until
    if rule_id == "rule_12":
        retain_until = _latest_retention_date(observations)
        if retain_until is None:
            return True
        return audit_at <= retain_until
    if rule_id in {"rule_05", "rule_06", "rule_14", "rule_15"}:
        return True
    if rule_id in {"rule_07", "rule_08"}:
        if state.state == ObservedState.PRESENT:
            return True
        if state.state in {ObservedState.ANONYMIZED, ObservedState.ABSENT}:
            return False
        return None
    if rule_id == "rule_11":
        return any(observation.emails for observation in observations)
    if rule_id in {"rule_01", "rule_02", "rule_03", "rule_04", "rule_09", "rule_10"}:
        return True
    return None


def _latest_retention_date(observations: list[EvidenceObservation]):
    values = []
    for observation in observations:
        for source in (observation.attributes, observation.record or {}):
            for key in ("retain_until", "retention_until", "retain_until_date"):
                value = source.get(key) if isinstance(source, dict) else None
                if not value:
                    continue
                try:
                    values.append(parse_timestamp(str(value)))
                except ValueError:
                    continue
    return max(values) if values else None


def _evidence_ids(state: ResourceState, resolution: CategoryResolution) -> tuple[str, ...]:
    # State evidence supports the asserted observation and therefore outranks
    # category-only evidence and activity claims. Preserve multiple independent
    # sources deterministically; the planner uses the first as the citation.
    matching = [basis for basis in state.basis if basis.state == state.state]
    other = [basis for basis in state.basis if basis.state != state.state]
    ordered = sorted(
        matching,
        key=lambda basis: (
            0 if basis.source_type == "EVIDENCE" else 1,
            -basis.timestamp.timestamp(),
            basis.source_id,
        ),
    )
    values: list[str] = []
    for basis in ordered:
        values.append(
            basis.source_id.split(":", 1)[0]
            if basis.source_type == "EVIDENCE"
            else basis.source_id
        )
    values.extend(resolution.evidence_ids)
    for basis in other:
        values.append(
            basis.source_id.split(":", 1)[0]
            if basis.source_type == "EVIDENCE"
            else basis.source_id
        )
    return tuple(dict.fromkeys(value for value in values if value))


def _activity_events_by_resource(
    context: AuditContext,
) -> dict[str, list[SystemActivity]]:
    events: dict[str, list[SystemActivity]] = defaultdict(list)
    for event in context.relevant_activity:
        events[event.resource_id].append(event)
    return events


def _activity_systems_by_resource(context: AuditContext) -> dict[str, set[str]]:
    systems: dict[str, set[str]] = defaultdict(set)
    for event in context.relevant_activity:
        systems[event.resource_id].add(event.target_system)
        systems[event.resource_id].add(event.source_system)
    return systems
