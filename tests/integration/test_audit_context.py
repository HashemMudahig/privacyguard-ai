"""Integration tests for request-level audit contexts."""

from __future__ import annotations

from collections import Counter, defaultdict

from privacyguard.context.service import _workflow_window
from privacyguard.models import DeletionRequest, ResolutionStatus
from privacyguard.state.models import RecreationStatus


def test_system_activity_loader_and_index(bundle, activity_index) -> None:
    assert len(bundle.system_activity) == 4011
    stats = activity_index.stats()
    assert stats.events == 4011
    assert stats.resources == 3948
    assert stats.event_types == 17
    assert stats.source_systems == 11
    assert stats.target_systems == 19


def sample_case_ids(service) -> list[str]:
    return sorted(
        case_id
        for case_id in service.case_ids
        if service.request_source(case_id) == "sample"
    )


def test_all_sample_cases_produce_contexts(audit_service) -> None:
    case_ids = sample_case_ids(audit_service)
    assert len(case_ids) == 32
    for case_id in case_ids:
        context = audit_service.build_context(case_id)
        assert context.case_id == case_id
        assert context.audit_at == context.request.audit_at
        assert context.resolution.status == ResolutionStatus.RESOLVED
        assert all(
            observation.captured_at <= context.audit_at
            for observation in context.relevant_observations
        )
        assert all(
            event.event_time <= context.audit_at
            for event in context.relevant_activity
        )


def test_linked_resources_have_states(audit_service) -> None:
    for case_id in sample_case_ids(audit_service):
        context = audit_service.build_context(case_id)
        linked = {resource.resource_id for resource in context.linked_resources}
        stated = {state.resource_id for state in context.states}
        assert linked == stated


def test_every_state_has_basis_or_uncertainty(audit_service) -> None:
    for case_id in sample_case_ids(audit_service):
        context = audit_service.build_context(case_id)
        for state in context.states:
            assert state.basis or state.uncertainties


def test_aggregate_sample_context_statistics(audit_service) -> None:
    linked = states = conflicts = flows = backups = candidates = unresolved = 0
    for case_id in sample_case_ids(audit_service):
        context = audit_service.build_context(case_id)
        linked += len(context.linked_resources)
        states += len(context.states)
        conflicts += len(context.conflicts)
        flows += len(context.active_data_flows)
        backups += len(context.restore_risks)
        candidates += len(context.candidate_activity_resources)
        unresolved += len(context.unresolved_resources)
    assert linked >= 50
    assert states == linked
    assert conflicts >= 1
    assert flows >= 1
    assert backups >= 1
    assert candidates >= 1
    assert unresolved >= 0


def test_same_user_with_different_audit_timestamps(audit_service) -> None:
    requests = [
        row.record
        for request_file in (
            audit_service.bundle.sample_requests,
            audit_service.bundle.eval_requests,
        )
        for row in request_file.rows
    ]
    by_user: dict[str, list] = defaultdict(list)
    for request in requests:
        resolution = audit_service.resolver.resolve_email(request.email)
        if resolution.identity is not None:
            by_user[resolution.identity.user_id].append(request)

    pair = next(
        (items for items in by_user.values() if len({item.audit_at for item in items}) > 1),
        None,
    )
    assert pair is not None
    contexts = [audit_service.build_context(item.case_id) for item in pair[:2]]
    assert contexts[0].audit_at != contexts[1].audit_at
    for context in contexts:
        assert all(
            observation.captured_at <= context.audit_at
            for observation in context.relevant_observations
        )
        assert all(
            event.event_time <= context.audit_at
            for event in context.relevant_activity
        )


def test_candidate_activity_resources_are_reported(audit_service) -> None:
    contexts = [
        audit_service.build_context(case_id) for case_id in sample_case_ids(audit_service)
    ]
    with_candidates = [
        context for context in contexts if context.candidate_activity_resources
    ]
    assert with_candidates
    for context in with_candidates[:3]:
        for candidate in context.candidate_activity_resources:
            assert candidate.reason
            assert candidate.confidence == 0.0


def test_conflicts_are_explicit(audit_service) -> None:
    contexts = [
        audit_service.build_context(case_id) for case_id in sample_case_ids(audit_service)
    ]
    conflict_contexts = [context for context in contexts if context.conflicts]
    assert conflict_contexts
    for context in conflict_contexts:
        for conflict in context.conflicts:
            assert conflict.description
            assert conflict.competing_states
            assert conflict.rule


def test_active_flow_and_restore_risk_candidates(audit_service) -> None:
    contexts = [
        audit_service.build_context(case_id) for case_id in sample_case_ids(audit_service)
    ]
    assert any(context.active_data_flows for context in contexts)
    assert any(context.restore_risks for context in contexts)


def test_context_is_json_serializable(audit_service) -> None:
    context = audit_service.build_context("case_11")
    payload = context.model_dump(mode="json")
    assert payload["case_id"] == "case_11"
    assert "linked_resources" in payload
    assert "states" in payload
    assert "relevant_observations" in payload


def test_public_build_audit_context_function(settings) -> None:
    from privacyguard.context.service import build_audit_context

    context = build_audit_context("case_03", dataset_dir=settings.dataset_dir)
    assert context.case_id == "case_03"
    assert context.request.audit_at == context.audit_at


def test_workflow_window_never_starts_before_request() -> None:
    request = DeletionRequest(
        case_id="case_999",
        email="person@example.com",
        requested_at="2026-01-01T10:00:00Z",
        reported_status="COMPLETE",
        reported_at="2026-01-01T11:00:00Z",
        audit_at="2026-01-01T12:00:00Z",
        request_text="Delete my data.",
    )
    start, end = _workflow_window(request)
    assert start == request.requested_at
    assert end == request.audit_at


def test_candidate_activity_resources_are_never_linked(audit_service) -> None:
    for case_id in sample_case_ids(audit_service):
        context = audit_service.build_context(case_id)
        linked = {resource.resource_id for resource in context.linked_resources}
        candidates = {
            candidate.resource_id
            for candidate in context.candidate_activity_resources
            if candidate.resource_id
        }
        assert linked.isdisjoint(candidates)


def test_recreation_status_distinguishes_confirmed_and_suspected(audit_service) -> None:
    statuses: Counter[str] = Counter()
    for case_id in sample_case_ids(audit_service):
        context = audit_service.build_context(case_id)
        statuses.update(
            state.recreation_status.value for state in context.states
        )
    assert statuses[RecreationStatus.CONFIRMED.value] >= 1
    assert statuses[RecreationStatus.SUSPECTED.value] >= 1
