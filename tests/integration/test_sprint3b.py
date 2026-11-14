"""Regression coverage for Sprint 3B identity, coverage and OCR behaviours."""

from __future__ import annotations

from privacyguard.linking.models import LinkLevel


def test_account_candidates_are_not_confirmed_links(pipeline) -> None:
    for case_id in ("case_17", "case_26"):
        context = pipeline.context_service.build_context(case_id)
        linked = {resource.resource_id for resource in context.linked_resources}
        assert context.account_candidates
        for candidate in context.account_candidates:
            assert candidate.level == LinkLevel.CANDIDATE
            assert candidate.resource_id not in linked
            assert candidate.warnings


def test_account_candidate_is_not_promoted_to_policy_decision(pipeline) -> None:
    result = pipeline.audit_case("case_01")
    assert result.policy.decisions == ()
    assert result.deletion_status.value == "INCOMPLETE"
    assert result.steps == ()
    assert any("No account resource" in gap for gap in result.coverage_gaps)


def test_overlapping_activity_does_not_link_unrelated_accounts(pipeline) -> None:
    context = pipeline.context_service.build_context("case_26")
    linked = {resource.resource_id for resource in context.linked_resources}
    candidate_ids = {candidate.resource_id for candidate in context.account_candidates}
    assert candidate_ids
    assert candidate_ids.isdisjoint(linked)
    assert not any(resource_id.startswith("account_") for resource_id in linked)


def test_same_identity_reused_across_cases_does_not_leak_related_resources(pipeline) -> None:
    first = pipeline.context_service.build_context("case_33")
    second = pipeline.context_service.build_context("case_52")
    assert first.identity is not None and second.identity is not None
    assert first.identity.user_id == second.identity.user_id
    second_linked = {resource.resource_id for resource in second.linked_resources}
    assert "export_1260" in second_linked
    assert "export_1842" not in second_linked


def test_no_complete_snapshot_exists_in_dataset(pipeline) -> None:
    coverages = pipeline.context_service.snapshot_index.coverages
    assert coverages
    assert all(not coverage.is_complete for coverage in coverages)


def test_absence_proofs_require_a_complete_snapshot(pipeline) -> None:
    for case_id in ("case_01", "case_10", "case_17"):
        context = pipeline.context_service.build_context(case_id)
        assert context.absence_proofs == ()


def test_ocr_link_is_corroborated_but_still_inferred(pipeline) -> None:
    context = pipeline.context_service.build_context("case_35")
    search = next(
        resource
        for resource in context.linked_resources
        if resource.resource_id == "search_428"
    )
    assert search.link_level == LinkLevel.INFERRED
    assert search.verified is False
    assert any("independently identifies the same subject" in warning for warning in search.warnings)


def test_ocr_resource_without_corroboration_stays_unresolved(pipeline) -> None:
    context = pipeline.context_service.build_context("case_35")
    linked = {resource.resource_id for resource in context.linked_resources}
    unresolved = {
        item.resource_id: item.reason for item in context.unresolved_resources
    }
    assert "search_42B" not in linked
    assert "search_42B" in unresolved
    assert "No independent text evidence or activity" in unresolved["search_42B"]
