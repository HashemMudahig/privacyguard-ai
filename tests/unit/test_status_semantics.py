"""Independent Sprint 3C correctness tests for audit status semantics."""

from __future__ import annotations

from privacyguard.context.models import AuditContext
from privacyguard.context.service import apply_authoritative_absence
from privacyguard.decision.models import DeletionStatus
from privacyguard.evidence.coverage import (
    SnapshotCoverage,
    SnapshotCoverageIndex,
    SnapshotScopeType,
)
from privacyguard.evidence.models import ObservedState
from privacyguard.linking.models import (
    AccountCandidate,
    LinkLevel,
    LinkedResource,
    ResourceLinkType,
)
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
from privacyguard.state.models import ResourceKind, ResourceState, StateBasis


MOMENT = parse_timestamp("2026-01-02T00:00:00Z")


def _identity() -> tuple[ResolvedIdentity, IdentityResolution]:
    current = UserIdentity(
        user_id="user_semantic",
        name="Semantic Test",
        email="semantic@example.com",
        phone="+1 555 0100",
        email_hash="a" * 64,
        updated_at="2026-01-01T00:00:00Z",
    )
    identity = ResolvedIdentity(
        user_id=current.user_id,
        current=current,
        historical=HistoricalValues(),
        all_emails=(current.email,),
        all_phones=(current.phone,),
        all_email_hashes=(current.email_hash,),
        provenance=(),
        warnings=(),
    )
    resolution = IdentityResolution(
        status=ResolutionStatus.RESOLVED,
        identifier=current.email,
        normalized_identifier=current.email,
        kind="email",
        method=ResolutionMethod.CURRENT_EMAIL,
        matched_value=current.email,
        user_id=current.user_id,
        identity=identity,
    )
    return identity, resolution


def _state(
    resource_id: str,
    category: str,
    system_id: str,
    observed: ObservedState,
    *,
    verified: bool,
) -> ResourceState:
    basis = ()
    evidence_ids = ()
    if verified:
        basis = (
            StateBasis(
                source_type="EVIDENCE",
                source_id=f"evidence_{resource_id}",
                timestamp=MOMENT,
                state=observed,
                detail="authoritative synthetic observation",
                confidence=1.0,
            ),
        )
        evidence_ids = (f"evidence_{resource_id}",)
    return ResourceState(
        resource_id=resource_id,
        kind=ResourceKind.RECORD,
        system_ids=(system_id,),
        data_categories=(category,),
        state=observed,
        confidence=1.0 if verified else 0.5,
        verified=verified,
        basis=basis,
        evidence_ids=evidence_ids,
    )


def _link(resource_id: str, category: str, system_id: str) -> LinkedResource:
    return LinkedResource(
        resource_id=resource_id,
        system_ids=(system_id,),
        data_categories=(category,),
        link_types=(ResourceLinkType.EXPLICIT_USER_ID,),
        confidence=1.0,
        verified=True,
        link_level=LinkLevel.CONFIRMED,
    )


def _candidate(resource_id: str) -> AccountCandidate:
    return AccountCandidate(
        resource_id=resource_id,
        system_id="account_service",
        confidence=0.3,
        reasons=("same workflow window only",),
        event_types=("DELETE_RECORD",),
        warnings=("ownership unresolved",),
    )


def _context(
    states: tuple[ResourceState, ...],
    links: tuple[LinkedResource, ...],
    *,
    candidates: tuple[AccountCandidate, ...] = (),
) -> AuditContext:
    identity, resolution = _identity()
    request = DeletionRequest(
        case_id="case_9999",
        email=identity.current.email,
        requested_at="2026-01-01T00:00:00Z",
        reported_status="COMPLETE",
        reported_at="2026-01-01T12:00:00Z",
        audit_at=MOMENT,
        request_text="Delete my account and all personal data.",
    )
    return AuditContext(
        case_id=request.case_id,
        audit_at=MOMENT,
        request=request,
        resolution=resolution,
        identity=identity,
        linked_resources=links,
        account_candidates=candidates,
        states=states,
    )


def _audit_state() -> tuple[ResourceState, LinkedResource]:
    state = _state(
        "audit_record_1",
        "SECURITY_AUDIT_LOG",
        "security_service",
        ObservedState.PRESENT,
        verified=True,
    )
    return state, _link(
        "audit_record_1", "SECURITY_AUDIT_LOG", "security_service"
    )


def test_confirmed_account_without_deletion_proof_is_incomplete(pipeline) -> None:
    account = _state(
        "account_1", "USER_PROFILE", "account_service", ObservedState.UNKNOWN,
        verified=False,
    )
    result = pipeline.decision_engine.audit(
        _context(
            (account,),
            (_link("account_1", "USER_PROFILE", "account_service"),),
        )
    )
    assert result.deletion_status == DeletionStatus.INCOMPLETE
    assert result.policy.decisions[0].status.value == "UNKNOWN"


def test_confirmed_account_activity_only_absence_is_incomplete(pipeline) -> None:
    account = _state(
        "account_1", "USER_PROFILE", "account_service", ObservedState.ABSENT,
        verified=False,
    )
    result = pipeline.decision_engine.audit(
        _context(
            (account,),
            (_link("account_1", "USER_PROFILE", "account_service"),),
        )
    )
    assert result.deletion_status == DeletionStatus.INCOMPLETE
    assert "unverified" in result.policy.decisions[0].reason


def test_unresolved_candidate_is_uncertainty_not_a_finding_or_blocker(pipeline) -> None:
    retained, retained_link = _audit_state()
    result = pipeline.decision_engine.audit(
        _context((retained,), (retained_link,), candidates=(_candidate("account_x"),))
    )
    assert result.deletion_status == DeletionStatus.COMPLETE
    assert all(step.resource_id != "account_x" for step in result.steps)
    assert result.provisional is True


def test_no_observed_account_does_not_create_a_synthetic_account_decision(pipeline) -> None:
    retained, retained_link = _audit_state()
    result = pipeline.decision_engine.audit(_context((retained,), (retained_link,)))
    assert result.deletion_status == DeletionStatus.COMPLETE
    assert not any(d.category.value == "USER_PROFILE" for d in result.policy.decisions)
    assert any("No account resource" in gap for gap in result.coverage_gaps)


def test_complete_snapshot_proves_confirmed_account_absence(pipeline) -> None:
    account = _state(
        "account_1", "USER_PROFILE", "account_service", ObservedState.UNKNOWN,
        verified=False,
    )
    coverage = SnapshotCoverage(
        file_id="evidence_complete",
        file_path="evidence/complete.sql",
        captured_at=MOMENT,
        system_id="account_service",
        collection="customer_profiles",
        record_count=0,
        resource_ids=(),
        scope_type=SnapshotScopeType.COMPLETE_COLLECTION,
        is_complete=True,
        completeness_reason="synthetic complete collection",
        provenance="evidence_complete:customer_profiles",
    )
    states, proofs = apply_authoritative_absence(
        (account,), SnapshotCoverageIndex((coverage,)), MOMENT
    )
    assert proofs and states[0].verified and states[0].state == ObservedState.ABSENT
    result = pipeline.decision_engine.audit(
        _context(
            states,
            (_link("account_1", "USER_PROFILE", "account_service"),),
        )
    )
    assert result.deletion_status == DeletionStatus.COMPLETE
    assert result.steps[0].evidence_id == "evidence_complete"


def test_partial_snapshot_does_not_prove_absence(pipeline) -> None:
    account = _state(
        "account_1", "USER_PROFILE", "account_service", ObservedState.UNKNOWN,
        verified=False,
    )
    coverage = SnapshotCoverage(
        file_id="evidence_partial",
        file_path="evidence/partial.sql",
        captured_at=MOMENT,
        system_id="account_service",
        collection="customer_profiles",
        record_count=0,
        resource_ids=(),
        scope_type=SnapshotScopeType.REPLICA_CAPTURE,
        is_complete=False,
        completeness_reason="partial replica",
        provenance="evidence_partial:customer_profiles",
    )
    states, proofs = apply_authoritative_absence(
        (account,), SnapshotCoverageIndex((coverage,)), MOMENT
    )
    assert proofs == () and states[0].state == ObservedState.UNKNOWN
    result = pipeline.decision_engine.audit(
        _context(
            states,
            (_link("account_1", "USER_PROFILE", "account_service"),),
        )
    )
    assert result.deletion_status == DeletionStatus.INCOMPLETE


def test_unrelated_account_activity_in_window_does_not_change_status(pipeline) -> None:
    retained, retained_link = _audit_state()
    candidate = _candidate("account_unrelated")
    result = pipeline.decision_engine.audit(
        _context((retained,), (retained_link,), candidates=(candidate,))
    )
    assert result.deletion_status == DeletionStatus.COMPLETE
    assert "account_unrelated" not in {step.resource_id for step in result.steps}


def test_multiple_account_candidates_do_not_choose_or_block_one(pipeline) -> None:
    retained, retained_link = _audit_state()
    candidates = (_candidate("account_a"), _candidate("account_b"))
    result = pipeline.decision_engine.audit(
        _context((retained,), (retained_link,), candidates=candidates)
    )
    assert result.deletion_status == DeletionStatus.COMPLETE
    assert {step.resource_id for step in result.steps} == {"audit_record_1"}
