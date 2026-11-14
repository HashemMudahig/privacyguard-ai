"""Integration tests for resource identity linking."""

from __future__ import annotations

from privacyguard.linking.models import ResourceLinkType


def request_by_case(bundle, case_id: str):
    for request_file in (bundle.sample_requests, bundle.eval_requests):
        for row in request_file.rows:
            if row.record.case_id == case_id:
                return row.record
    raise AssertionError(f"request case not found: {case_id}")


def identity_for(resolver, email: str):
    resolution = resolver.resolve_email(email)
    assert resolution.identity is not None
    return resolution.identity


def linked_ids(result) -> set[str]:
    return {resource.resource_id for resource in result.linked}


def test_explicit_user_id_link(resolver, resource_linker, bundle) -> None:
    request = request_by_case(bundle, "case_05")
    identity = identity_for(resolver, request.email)
    result = resource_linker.link(identity, audit_at=request.audit_at)
    account = next(
        resource for resource in result.linked if resource.resource_id == "account_005"
    )
    assert ResourceLinkType.EXPLICIT_USER_ID in account.link_types
    assert account.verified is True
    assert account.confidence == 1.0


def test_historical_email_link(resolver, resource_linker, bundle) -> None:
    request = request_by_case(bundle, "case_10")
    identity = identity_for(resolver, request.email)
    result = resource_linker.link(identity, audit_at=request.audit_at)
    assert result.linked
    assert all(resource.provenance for resource in result.linked)


def test_related_resource_link(resolver, resource_linker, bundle) -> None:
    request = request_by_case(bundle, "case_06")
    identity = identity_for(resolver, request.email)
    result = resource_linker.link(identity, audit_at=request.audit_at)
    account = next(
        resource for resource in result.linked if resource.resource_id == "account_006"
    )
    assert ResourceLinkType.RELATED_RESOURCE in account.link_types
    assert account.verified is False


def test_activity_identity_link(resolver, resource_linker) -> None:
    identity = identity_for(resolver, "haruka.s1838@zoho.com")
    result = resource_linker.link(identity)
    account = next(
        resource for resource in result.linked if resource.resource_id == "account_5762"
    )
    assert ResourceLinkType.ACTIVITY_IDENTITY_LINK in account.link_types
    assert account.verified is False


def test_correlation_chain_links_log_resources(resolver, resource_linker, bundle) -> None:
    request = request_by_case(bundle, "case_15")
    identity = identity_for(resolver, request.email)
    result = resource_linker.link(identity, audit_at=request.audit_at)
    ids = linked_ids(result)
    assert "data_flow_9846" in ids
    assert "audit_record_1596" in ids
    flow = next(resource for resource in result.linked if resource.resource_id == "data_flow_9846")
    assert ResourceLinkType.EVIDENCE_CHAIN in flow.link_types
    assert flow.verified is False


def test_no_implicit_account_number_mapping(resolver, resource_linker) -> None:
    identity = identity_for(resolver, "nadia.ionescu@yahoo.com")
    result = resource_linker.link(identity)
    assert "account_010" not in linked_ids(result)


def test_clean_case_does_not_fabricate_account(resolver, resource_linker, bundle) -> None:
    request = request_by_case(bundle, "case_01")
    identity = identity_for(resolver, request.email)
    result = resource_linker.link(identity, audit_at=request.audit_at)
    assert "account_001" not in linked_ids(result)


def test_every_linked_resource_has_provenance(resolver, resource_linker, bundle) -> None:
    for row in bundle.sample_requests.rows:
        request = row.record
        identity = identity_for(resolver, request.email)
        result = resource_linker.link(identity, audit_at=request.audit_at)
        for resource in result.linked:
            assert resource.resource_id
            assert resource.confidence > 0
            assert resource.provenance
            assert all(item.source_id for item in resource.provenance)


def test_all_sample_cases_link_without_error(resolver, resource_linker, bundle) -> None:
    total_linked = 0
    for row in bundle.sample_requests.rows:
        request = row.record
        identity = identity_for(resolver, request.email)
        result = resource_linker.link(identity, audit_at=request.audit_at)
        total_linked += len(result.linked)
    assert total_linked >= 50


def test_multimodal_link_is_unverified(resolver, resource_linker, bundle) -> None:
    request = request_by_case(bundle, "case_35")
    identity = identity_for(resolver, request.email)
    result = resource_linker.link(identity, audit_at=request.audit_at)
    search = next(resource for resource in result.linked if resource.resource_id == "search_428")
    assert ResourceLinkType.MULTIMODAL_INFERRED in search.link_types
    assert search.verified is False


def test_uncorroborated_ocr_resource_is_not_linked(resolver, resource_linker, bundle) -> None:
    request = request_by_case(bundle, "case_35")
    identity = identity_for(resolver, request.email)
    result = resource_linker.link(identity, audit_at=request.audit_at)
    assert "search_42B" not in linked_ids(result)
    assert any(
        item.resource_id == "search_42B" for item in result.unresolved
    )


def test_multimodal_does_not_mix_identity_emails(resolver, resource_linker, bundle) -> None:
    request = request_by_case(bundle, "case_15")
    identity = identity_for(resolver, request.email)
    result = resource_linker.link(identity, audit_at=request.audit_at)
    assert "data_flow_1121" not in linked_ids(result)
    assert "data_flow_9846" in linked_ids(result)


def test_pdf_text_link_is_verified(resolver, resource_linker, bundle) -> None:
    request = request_by_case(bundle, "case_07")
    identity = identity_for(resolver, request.email)
    result = resource_linker.link(identity, audit_at=request.audit_at)
    support = next(resource for resource in result.linked if resource.resource_id == "support_001")
    assert support.verified is True
    assert ResourceLinkType.EMAIL in support.link_types
