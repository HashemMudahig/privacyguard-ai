"""Integration tests against the real read-only challenge dataset."""

from __future__ import annotations

from privacyguard.identity.report import summarize_resolutions
from privacyguard.normalization import normalize_email, normalize_email_hash, normalize_phone


def test_dataset_row_counts(bundle) -> None:
    assert len(bundle.identities) == 850
    assert len(bundle.audit_events) == 306
    assert len(bundle.sample_requests) == 32
    assert len(bundle.eval_requests) == 518


def test_current_identities_are_unique(bundle) -> None:
    identities = bundle.identities.records
    assert len({identity.user_id for identity in identities}) == len(identities)
    assert len({normalize_email(identity.email) for identity in identities}) == len(identities)
    assert len({normalize_phone(identity.phone) for identity in identities}) == len(identities)
    assert (
        len({normalize_email_hash(identity.email_hash) for identity in identities})
        == len(identities)
    )


def test_audit_users_exist_in_current_snapshot(bundle) -> None:
    known = {identity.user_id for identity in bundle.identities.records}
    unknown = sorted(
        {event.user_id for event in bundle.audit_events.records} - known
    )
    assert unknown == []


def test_sample_requests_all_resolve(bundle, resolver) -> None:
    resolutions = resolver.resolve_requests(bundle.sample_requests)
    summary = summarize_resolutions(
        bundle.dataset_dir, bundle.sample_requests.display_name, resolutions
    )
    assert summary.total_requests == 32
    assert summary.resolved == 32
    assert summary.ambiguous == 0
    assert summary.not_found == 0
    assert summary.exceptions == ()
    assert summary.methods.get("CURRENT_EMAIL", 0) > 0
    assert summary.methods.get("HISTORICAL_EMAIL", 0) > 0


def test_eval_requests_all_resolve(bundle, resolver) -> None:
    resolutions = resolver.resolve_requests(bundle.eval_requests)
    summary = summarize_resolutions(
        bundle.dataset_dir, bundle.eval_requests.display_name, resolutions
    )
    assert summary.total_requests == 518
    assert summary.resolved == 518
    assert summary.ambiguous == 0
    assert summary.not_found == 0
    assert summary.exceptions == ()
    assert summary.methods.get("HISTORICAL_EMAIL", 0) > 0


def test_all_request_resolutions_have_provenance(bundle, resolver) -> None:
    for request_file in (bundle.sample_requests, bundle.eval_requests):
        for item in resolver.resolve_requests(request_file):
            identity = item.resolution.identity
            assert identity is not None
            assert identity.user_id == item.resolution.user_id
            assert identity.provenance
            assert item.resolution.resolution_provenance
            assert all(ref.row_number >= 1 for ref in identity.provenance)
            assert all(ref.row_number >= 1 for ref in item.resolution.resolution_provenance)


def test_historical_email_method_is_consistent(bundle, resolver) -> None:
    historical = [
        item
        for item in resolver.resolve_requests(bundle.eval_requests)
        if item.resolution.method.value == "HISTORICAL_EMAIL"
    ]
    assert historical
    for item in historical:
        identity = item.resolution.identity
        assert identity is not None and identity.current is not None
        assert item.resolution.normalized_identifier != normalize_email(
            identity.current.email
        )


def test_current_phone_and_hash_roundtrip(bundle, resolver) -> None:
    failures: list[str] = []
    for identity in bundle.identities.records:
        for kind, value in (
            ("phone", identity.phone),
            ("email_hash", identity.email_hash),
        ):
            resolution = resolver.resolve_identifier(value, kind)
            if resolution.status.value != "RESOLVED" or resolution.user_id != identity.user_id:
                failures.append(
                    f"{identity.user_id} {kind}: status={resolution.status.value} "
                    f"resolved={resolution.user_id} candidates={resolution.candidates}"
                )
    assert failures == [], failures[:20]
