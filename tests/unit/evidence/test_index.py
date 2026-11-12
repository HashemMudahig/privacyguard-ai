"""Unit tests for the evidence index using synthetic observations."""

from __future__ import annotations

from datetime import datetime

from privacyguard.evidence.index import EvidenceIndex
from privacyguard.evidence.models import (
    EvidenceFormat,
    EvidenceLocation,
    EvidenceObservation,
    EvidenceProvenance,
    ObservedState,
)
from privacyguard.models import (
    HistoricalValues,
    ResolvedIdentity,
    UserIdentity,
    parse_timestamp,
)


def make_observation(
    observation_id: str,
    captured_at: str,
    *,
    resource_id: str | None = None,
    user_ids: tuple[str, ...] = (),
    emails: tuple[str, ...] = (),
    phones: tuple[str, ...] = (),
    email_hashes: tuple[str, ...] = (),
    related: tuple[str, ...] = (),
    state: ObservedState = ObservedState.PRESENT,
) -> EvidenceObservation:
    moment = parse_timestamp(captured_at)
    return EvidenceObservation(
        observation_id=observation_id,
        file_id="ev_test",
        file_path="evidence/test.log",
        captured_at=moment,
        observed_at=moment,
        format=EvidenceFormat.LOG,
        system_id="test_system",
        resource_id=resource_id,
        data_category="TEST_CATEGORY",
        observed_state=state,
        user_ids=user_ids,
        emails=emails,
        phones=phones,
        email_hashes=email_hashes,
        related_resource_ids=related,
        attributes={},
        record=None,
        provenance=EvidenceProvenance(
            file_id="ev_test",
            file_path="evidence/test.log",
            captured_at=moment,
            source_format=EvidenceFormat.LOG,
            location=EvidenceLocation(line_number=1),
        ),
        confidence=1.0,
        warnings=(),
    )


def make_identity() -> ResolvedIdentity:
    current = UserIdentity(
        user_id="user_1",
        name="Alice",
        email="current@example.com",
        phone="+1 555 000 1111",
        email_hash="a" * 64,
        updated_at="2026-01-01T00:00:00Z",
    )
    return ResolvedIdentity(
        user_id="user_1",
        current=current,
        historical=HistoricalValues(emails=("old@example.com",)),
        all_emails=("current@example.com", "old@example.com"),
        all_phones=("+1 555 000 1111",),
        all_email_hashes=("a" * 64,),
        provenance=(),
        warnings=(),
    )


def test_resource_lookup_and_temporal_filter() -> None:
    index = EvidenceIndex(
        [
            make_observation("obs_1", "2026-01-01T00:00:00Z", resource_id="account_1"),
            make_observation("obs_2", "2026-02-01T00:00:00Z", resource_id="account_1"),
        ]
    )
    assert len(index.observations_for_resource("account_1")) == 2
    early = index.observations_for_resource(
        "account_1", audit_at="2026-01-15T00:00:00Z"
    )
    assert [observation.observation_id for observation in early] == ["obs_1"]
    assert index.latest_for_resource(
        "account_1", audit_at="2026-01-15T00:00:00Z"
    ).observation_id == "obs_1"
    assert index.latest_for_resource("account_1").observation_id == "obs_2"


def test_identifier_lookup_is_normalized() -> None:
    index = EvidenceIndex(
        [
            make_observation(
                "obs_1",
                "2026-01-01T00:00:00Z",
                emails=("Person@Example.com",),
                phones=("+1 555 000 1111",),
                email_hashes=("A" * 64,),
            )
        ]
    )
    assert index.observations_for_identifier("person@example.com", "email")
    assert index.observations_for_identifier("+1 (555) 000-1111", "phone")
    assert index.observations_for_identifier("a" * 64, "email_hash")


def test_identity_lookup_expands_resource_neighbors() -> None:
    index = EvidenceIndex(
        [
            make_observation(
                "obs_search",
                "2026-01-01T00:00:00Z",
                resource_id="search_1",
                emails=("current@example.com",),
                related=("account_1",),
            ),
            make_observation("obs_account", "2026-01-01T00:00:00Z", resource_id="account_1"),
            make_observation("obs_other", "2026-01-01T00:00:00Z", resource_id="account_2"),
        ]
    )
    identity = make_identity()
    direct = index.observations_for_identity(identity, include_resource_neighbors=False)
    assert [observation.observation_id for observation in direct] == ["obs_search"]
    expanded = index.observations_for_identity(identity, include_resource_neighbors=True)
    assert {observation.observation_id for observation in expanded} == {
        "obs_search",
        "obs_account",
    }


def test_identity_lookup_uses_historical_identifiers() -> None:
    index = EvidenceIndex(
        [
            make_observation(
                "obs_old",
                "2026-01-01T00:00:00Z",
                resource_id="account_1",
                emails=("old@example.com",),
            )
        ]
    )
    observations = index.observations_for_identity(make_identity())
    assert [observation.observation_id for observation in observations] == ["obs_old"]


def test_identity_lookup_respects_audit_cutoff() -> None:
    index = EvidenceIndex(
        [
            make_observation(
                "obs_old",
                "2026-01-01T00:00:00Z",
                resource_id="account_1",
                emails=("current@example.com",),
            ),
            make_observation(
                "obs_new",
                "2026-03-01T00:00:00Z",
                resource_id="account_1",
                emails=("current@example.com",),
            ),
        ]
    )
    observations = index.observations_for_identity(
        make_identity(), audit_at="2026-02-01T00:00:00Z"
    )
    assert [observation.observation_id for observation in observations] == ["obs_old"]


def test_related_resource_lookup() -> None:
    index = EvidenceIndex(
        [
            make_observation(
                "obs_1",
                "2026-01-01T00:00:00Z",
                resource_id="search_1",
                related=("account_1",),
            ),
            make_observation("obs_2", "2026-01-01T00:00:00Z", resource_id="account_1"),
        ]
    )
    assert {
        observation.observation_id
        for observation in index.observations_for_resource(
            "account_1", include_related=True
        )
    } == {"obs_1", "obs_2"}
    assert [
        observation.observation_id
        for observation in index.observations_for_resource(
            "search_1", include_related=True
        )
    ] == ["obs_1"]


def test_index_statistics() -> None:
    index = EvidenceIndex(
        [
            make_observation(
                "obs_1",
                "2026-01-01T00:00:00Z",
                resource_id="account_1",
                user_ids=("user_1",),
                emails=("a@example.com",),
                phones=("+1 555 000 1111",),
                email_hashes=("a" * 64,),
            ),
            make_observation(
                "obs_2",
                "2026-02-01T00:00:00Z",
                resource_id="account_2",
                user_ids=("user_2",),
                emails=("b@example.com",),
            ),
        ]
    )
    stats = index.stats()
    assert stats.observations == 2
    assert stats.resources == 2
    assert stats.user_ids == 2
    assert stats.emails == 2
    assert stats.earliest_captured_at == datetime.fromisoformat(
        "2026-01-01T00:00:00+00:00"
    )
