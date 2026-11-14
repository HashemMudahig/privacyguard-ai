"""Integration tests for evidence index lookups and temporal filtering."""

from __future__ import annotations

from collections import defaultdict

from privacyguard.evidence.index import EvidenceIndex
from privacyguard.models import IdentifierKind, ResolutionMethod


def build_index(evidence_build) -> EvidenceIndex:
    return EvidenceIndex(evidence_build.observations)


def test_index_statistics(evidence_build) -> None:
    stats = build_index(evidence_build).stats()
    assert stats.observations == 3499
    assert stats.files == 93
    assert stats.resources == 2059
    assert stats.user_ids == 442
    assert stats.emails == 792
    assert stats.phones == 79
    assert stats.email_hashes == 37
    assert stats.systems == 18
    assert stats.categories == 31
    assert stats.correlation_ids == 994
    assert stats.earliest_captured_at is not None
    assert stats.latest_captured_at is not None
    assert stats.earliest_captured_at <= stats.latest_captured_at


def test_resource_lookup_returns_provenance(evidence_build) -> None:
    index = build_index(evidence_build)
    sample = next(
        observation for observation in evidence_build.observations if observation.resource_id
    )
    matches = index.observations_for_resource(sample.resource_id)
    assert sample.observation_id in {observation.observation_id for observation in matches}
    assert all(observation.resource_id == sample.resource_id for observation in matches)


def test_identifier_lookup(evidence_build) -> None:
    index = build_index(evidence_build)
    sample = next(
        observation for observation in evidence_build.observations if observation.emails
    )
    matches = index.observations_for_identifier(sample.emails[0], IdentifierKind.EMAIL)
    assert sample.observation_id in {observation.observation_id for observation in matches}


def test_user_lookup(evidence_build) -> None:
    index = build_index(evidence_build)
    sample = next(
        observation for observation in evidence_build.observations if observation.user_ids
    )
    matches = index.observations_for_user(sample.user_ids[0])
    assert sample.observation_id in {observation.observation_id for observation in matches}


def test_related_resource_lookup(evidence_build) -> None:
    index = build_index(evidence_build)
    sample = next(
        observation
        for observation in evidence_build.observations
        if observation.related_resource_ids
    )
    related = sample.related_resource_ids[0]
    matches = index.observations_for_resource(related, include_related=True)
    assert matches
    assert any(
        observation.resource_id == related
        or related in observation.related_resource_ids
        for observation in matches
    )


def test_multiple_snapshots_are_preserved(evidence_build) -> None:
    by_resource: dict[str, list] = defaultdict(list)
    for observation in evidence_build.observations:
        if observation.resource_id:
            by_resource[observation.resource_id].append(observation)

    multi = next(
        (resource_id, observations)
        for resource_id, observations in by_resource.items()
        if len({observation.file_id for observation in observations}) > 1
    )
    resource_id, observations = multi
    index = build_index(evidence_build)
    timeline = index.timeline(resource_id)
    assert len(timeline) >= 2
    assert len({observation.file_id for observation in timeline}) > 1
    assert timeline == tuple(
        sorted(
            timeline,
            key=lambda observation: (
                observation.captured_at,
                observation.observed_at or observation.captured_at,
                observation.observation_id,
            ),
        )
    )


def test_latest_for_resource(evidence_build) -> None:
    index = build_index(evidence_build)
    by_resource: dict[str, list] = defaultdict(list)
    for observation in evidence_build.observations:
        if observation.resource_id:
            by_resource[observation.resource_id].append(observation)
    resource_id, observations = next(
        (resource_id, observations)
        for resource_id, observations in by_resource.items()
        if len(observations) > 1
    )
    expected = max(
        observations,
        key=lambda observation: (
            observation.captured_at,
            observation.observed_at or observation.captured_at,
            observation.observation_id,
        ),
    )
    assert index.latest_for_resource(resource_id).observation_id == expected.observation_id


def test_audit_at_filtering_for_sample_requests(
    evidence_build, bundle, resolver
) -> None:
    index = build_index(evidence_build)
    requests_with_evidence = 0
    for row in bundle.sample_requests.rows:
        request = row.record
        observations = index.observations_for_request(request, resolver)
        assert all(observation.captured_at <= request.audit_at for observation in observations)
        if observations:
            requests_with_evidence += 1
    assert requests_with_evidence >= 1


def test_historical_identities_are_queryable(evidence_build, bundle, resolver) -> None:
    index = build_index(evidence_build)
    historical_requests = [
        row.record
        for row in bundle.sample_requests.rows
        if resolver.resolve_email(row.record.email).method == ResolutionMethod.HISTORICAL_EMAIL
    ]
    assert historical_requests
    total = 0
    for request in historical_requests:
        resolution = resolver.resolve_email(request.email)
        assert resolution.identity is not None
        observations = index.observations_for_identity(
            resolution.identity, audit_at=request.audit_at
        )
        assert all(observation.captured_at <= request.audit_at for observation in observations)
        total += len(observations)
    assert total >= 1


def test_file_lookup(evidence_build) -> None:
    index = build_index(evidence_build)
    observations = index.observations_for_file("evidence_03")
    assert len(observations) == 41
    assert all(observation.file_id == "evidence_03" for observation in observations)


def test_post_audit_evidence_is_excluded(evidence_build) -> None:
    index = build_index(evidence_build)
    sample = next(
        observation
        for observation in evidence_build.observations
        if observation.resource_id and observation.captured_at.year == 2026
    )
    before = index.observations_for_resource(
        sample.resource_id,
        audit_at=sample.captured_at.isoformat(),
    )
    assert sample.observation_id in {observation.observation_id for observation in before}
    assert all(
        observation.captured_at <= sample.captured_at for observation in before
    )
