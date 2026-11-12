"""Unit tests for identifier extraction and state mapping."""

from __future__ import annotations

from privacyguard.evidence.identifiers import (
    IdentifierBuckets,
    derive_state,
    extract_identifiers,
)
from privacyguard.evidence.models import ObservedState


def test_extract_nested_identifiers_and_related_resources() -> None:
    record = {
        "resource_id": "account_1",
        "profile": {
            "email": "Person@Example.com",
            "phone": "+1 555 000 1111",
            "customer_reference": "user_1",
        },
        "document": {"source_resource_id": "account_1", "ticket_id": "support_2"},
        "email_hash": "a" * 64,
    }
    buckets = extract_identifiers(record)
    assert buckets.user_ids == ["user_1"]
    assert buckets.emails == ["Person@Example.com"]
    assert buckets.phones == ["+1 555 000 1111"]
    assert buckets.email_hashes == ["a" * 64]
    assert set(buckets.related_resource_ids) == {"account_1", "support_2"}


def test_subject_reference_can_be_email_or_user_id() -> None:
    buckets = IdentifierBuckets()
    buckets.add_keyed_value("subject_reference", "person@example.com")
    buckets.add_keyed_value("subject_reference", "user_99")
    assert buckets.emails == ["person@example.com"]
    assert buckets.user_ids == ["user_99"]


def test_correlation_key_is_classified_by_value() -> None:
    buckets = IdentifierBuckets()
    buckets.add_keyed_value("correlation_key", "b" * 64)
    buckets.classify_and_add("user_42")
    buckets.classify_and_add("+44 7700 900123")
    assert buckets.email_hashes == ["b" * 64]
    assert buckets.user_ids == ["user_42"]
    assert buckets.phones == ["+44 7700 900123"]


def test_derive_state_from_result_tokens() -> None:
    assert derive_state({"result": "FOUND"})[0] == ObservedState.PRESENT
    assert derive_state({"result": "NOT_FOUND"})[0] == ObservedState.ABSENT
    assert derive_state({"result": "ANONYMIZED"})[0] == ObservedState.ANONYMIZED
    assert derive_state({"result": "BLOCKED"})[0] == ObservedState.BLOCKED
    assert derive_state({"result": "SUCCESS"})[0] == ObservedState.UNKNOWN


def test_derive_state_from_http_status() -> None:
    assert derive_state({"http_status": "200"})[0] == ObservedState.PRESENT
    assert derive_state({"http_status": "404"})[0] == ObservedState.ABSENT
    assert derive_state({"status_code": 404})[0] == ObservedState.ABSENT
    assert derive_state({"status_code": 500})[0] == ObservedState.UNKNOWN


def test_derive_state_from_flags() -> None:
    assert derive_state({"enabled": 1})[0] == ObservedState.ACTIVE
    assert derive_state({"enabled": "false"})[0] == ObservedState.DISABLED
    assert derive_state({"restore_allowed": 1})[0] == ObservedState.ACTIVE
    assert derive_state({"restore_allowed": 0})[0] == ObservedState.BLOCKED


def test_derive_state_from_row_counts_requires_completed_event() -> None:
    assert (
        derive_state({"rows": 0}, event="profile_lookup_completed")[0]
        == ObservedState.ABSENT
    )
    assert (
        derive_state({"rows": 1}, event="contact_query_completed")[0]
        == ObservedState.PRESENT
    )
    assert derive_state({"rows": 0}, event="batch_started")[0] == ObservedState.UNKNOWN


def test_derive_state_from_restore_candidate_fields() -> None:
    assert (
        derive_state(
            {"eligible": "true", "deletion_block": "false"},
            event="restore_candidate_evaluated",
        )[0]
        == ObservedState.ACTIVE
    )
    assert (
        derive_state(
            {"eligible": "true", "deletion_block": "true"},
            event="restore_candidate_evaluated",
        )[0]
        == ObservedState.BLOCKED
    )
    assert (
        derive_state(
            {"eligible": "false", "deletion_block": "false"},
            event="restore_candidate_evaluated",
        )[0]
        == ObservedState.BLOCKED
    )


def test_matched_value_is_classified_as_identifier() -> None:
    buckets = IdentifierBuckets()
    buckets.add_keyed_value("matched_value", "Person@Example.com")
    assert buckets.emails == ["Person@Example.com"]
