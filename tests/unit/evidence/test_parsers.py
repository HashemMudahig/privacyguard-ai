"""Unit tests for SQL, JSON, LOG and TXT parsers using synthetic files."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from privacyguard.evidence.errors import EvidenceParseError, UnsupportedSqlConstruct
from privacyguard.evidence.models import (
    EvidenceFormat,
    EvidenceManifestEntry,
    ObservedState,
)
from privacyguard.evidence.parsers.json_parser import JsonEvidenceParser
from privacyguard.evidence.parsers.log import LogEvidenceParser
from privacyguard.evidence.parsers.sql import SqlEvidenceParser
from privacyguard.evidence.parsers.txt import TxtEvidenceParser
from privacyguard.models import parse_timestamp


def make_entry(path: Path, evidence_format: EvidenceFormat, file_id: str = "ev_test") -> EvidenceManifestEntry:
    return EvidenceManifestEntry(
        file_id=file_id,
        file_path=path.name,
        origin="test",
        captured_at=parse_timestamp("2026-01-01T00:00:00Z"),
        format=evidence_format,
        is_supported=True,
        unsupported_reason=None,
        resolved_path=path,
    )


# ----------------------------------------------------------------------
# SQL
# ----------------------------------------------------------------------
def test_sql_flat_and_flag_tables(project_tmp_path: Path) -> None:
    path = project_tmp_path / "snapshot.sql"
    path.write_text(
        """
        BEGIN TRANSACTION;
        CREATE TABLE customer_profiles (
            resource_id TEXT, customer_reference TEXT, full_name TEXT,
            email TEXT, phone TEXT, email_hash TEXT,
            account_status TEXT, updated_at TEXT
        );
        INSERT INTO customer_profiles VALUES
            ('account_1','user_1','Alice','a@example.com','+1 555 000 1111',NULL,'ACTIVE','2026-01-01T00:00:00Z');
        CREATE TABLE connector_subscriptions (
            resource_id TEXT, customer_reference TEXT, customer_email TEXT,
            connector_name TEXT, enabled INTEGER, last_delivery_status TEXT, updated_at TEXT
        );
        INSERT INTO connector_subscriptions VALUES
            ('flow_1','user_1','a@example.com','sync',0,'delivered','2026-01-01T00:00:00Z');
        COMMIT;
        """,
        encoding="utf-8",
    )
    outcome = SqlEvidenceParser().parse(make_entry(path, EvidenceFormat.SQL), project_tmp_path)
    assert outcome.recognized is True
    assert len(outcome.observations) == 2
    by_id = {observation.resource_id: observation for observation in outcome.observations}
    assert by_id["account_1"].system_id == "account_service"
    assert by_id["account_1"].data_category == "USER_PROFILE"
    assert by_id["account_1"].user_ids == ("user_1",)
    assert by_id["account_1"].emails == ("a@example.com",)
    assert by_id["account_1"].observed_state == ObservedState.PRESENT
    assert by_id["flow_1"].observed_state == ObservedState.DISABLED
    assert by_id["flow_1"].attributes["_table"] == "connector_subscriptions"


def test_sql_json_record_table(project_tmp_path: Path) -> None:
    path = project_tmp_path / "json_records.sql"
    record = {
        "resource_id": "analytics_1",
        "user_id": "user_2",
        "email": "b@example.com",
        "phone": "+1 555 000 2222",
    }
    path.write_text(
        f"""
        BEGIN TRANSACTION;
        CREATE TABLE customer_data_primary (
            resource_id TEXT, origin_system TEXT, collection_name TEXT,
            record_json TEXT, updated_at TEXT
        );
        INSERT INTO customer_data_primary VALUES
            ('analytics_1','analytics_platform','customer_analytics_reports','{json.dumps(record)}','2026-01-01T00:00:00Z');
        COMMIT;
        """,
        encoding="utf-8",
    )
    outcome = SqlEvidenceParser().parse(make_entry(path, EvidenceFormat.SQL), project_tmp_path)
    assert len(outcome.observations) == 1
    observation = outcome.observations[0]
    assert observation.system_id == "analytics_platform"
    assert observation.data_category == "customer_analytics_reports"
    assert observation.resource_id == "analytics_1"
    assert observation.user_ids == ("user_2",)
    assert observation.emails == ("b@example.com",)
    assert observation.record == record


def test_sql_rejects_attach(project_tmp_path: Path) -> None:
    path = project_tmp_path / "dangerous.sql"
    path.write_text("ATTACH DATABASE 'outside.db' AS outside;", encoding="utf-8")
    with pytest.raises(UnsupportedSqlConstruct):
        SqlEvidenceParser().parse(make_entry(path, EvidenceFormat.SQL), project_tmp_path)


def test_sql_rejects_unknown_pragma(project_tmp_path: Path) -> None:
    path = project_tmp_path / "pragma.sql"
    path.write_text("PRAGMA journal_mode=WAL; SELECT 1;", encoding="utf-8")
    with pytest.raises(UnsupportedSqlConstruct):
        SqlEvidenceParser().parse(make_entry(path, EvidenceFormat.SQL), project_tmp_path)


def test_sql_accepts_foreign_keys_pragma(project_tmp_path: Path) -> None:
    path = project_tmp_path / "pragma_ok.sql"
    path.write_text(
        "PRAGMA foreign_keys=ON;\nCREATE TABLE t (id TEXT);\nINSERT INTO t VALUES ('x');\n",
        encoding="utf-8",
    )
    outcome = SqlEvidenceParser().parse(make_entry(path, EvidenceFormat.SQL), project_tmp_path)
    assert len(outcome.observations) == 1
    assert outcome.observations[0].resource_id is None


# ----------------------------------------------------------------------
# JSON
# ----------------------------------------------------------------------
def test_json_snapshot_shape(project_tmp_path: Path) -> None:
    path = project_tmp_path / "snapshots.json"
    path.write_text(
        json.dumps(
            {
                "exported_at": "2026-01-01T00:00:00Z",
                "source": "records_assurance_service",
                "snapshots": [
                    {
                        "captured_at": "2026-01-01T00:00:00Z",
                        "data_store": "account_service",
                        "collection": "customer_profiles",
                        "records": [
                            {
                                "resource_id": "account_1",
                                "customer_reference": "user_1",
                                "email": "a@example.com",
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    outcome = JsonEvidenceParser().parse(make_entry(path, EvidenceFormat.JSON), project_tmp_path)
    assert len(outcome.observations) == 1
    observation = outcome.observations[0]
    assert observation.system_id == "account_service"
    assert observation.data_category == "customer_profiles"
    assert observation.user_ids == ("user_1",)
    assert observation.emails == ("a@example.com",)


def test_json_service_exports_shape(project_tmp_path: Path) -> None:
    path = project_tmp_path / "service.json"
    path.write_text(
        json.dumps(
            {
                "exported_at": "2026-01-01T00:00:00Z",
                "region": "global",
                "service_exports": {
                    "search_service": {
                        "index_queries": [
                            {
                                "resource_id": "search_1",
                                "correlation_key": "a@example.com",
                                "status_code": 404,
                                "observed_at": "2026-01-01T00:00:00Z",
                            }
                        ]
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    outcome = JsonEvidenceParser().parse(make_entry(path, EvidenceFormat.JSON), project_tmp_path)
    observation = outcome.observations[0]
    assert observation.system_id == "search_service"
    assert observation.data_category == "index_queries"
    assert observation.observed_state == ObservedState.ABSENT


def test_json_records_shape(project_tmp_path: Path) -> None:
    path = project_tmp_path / "records.json"
    path.write_text(
        json.dumps(
            {
                "exported_at": "2026-01-01T00:00:00Z",
                "origin": "export_service",
                "record_count": 1,
                "records": [
                    {
                        "recorded_at": "2026-01-01T00:00:00Z",
                        "system": "account_service",
                        "resource_id": "account_1",
                        "record_type": "USER_PROFILE",
                        "result": "NOT_FOUND",
                        "subject_reference": "a@example.com",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    outcome = JsonEvidenceParser().parse(make_entry(path, EvidenceFormat.JSON), project_tmp_path)
    observation = outcome.observations[0]
    assert observation.data_category == "USER_PROFILE"
    assert observation.observed_state == ObservedState.ABSENT
    assert observation.emails == ("a@example.com",)


def test_json_malformed_raises(project_tmp_path: Path) -> None:
    path = project_tmp_path / "broken.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(EvidenceParseError):
        JsonEvidenceParser().parse(make_entry(path, EvidenceFormat.JSON), project_tmp_path)


def test_json_unknown_shape_not_recognized(project_tmp_path: Path) -> None:
    path = project_tmp_path / "unknown.json"
    path.write_text(json.dumps({"foo": 1}), encoding="utf-8")
    outcome = JsonEvidenceParser().parse(make_entry(path, EvidenceFormat.JSON), project_tmp_path)
    assert outcome.recognized is False
    assert outcome.observations == ()


# ----------------------------------------------------------------------
# LOG
# ----------------------------------------------------------------------
def test_log_all_supported_styles(project_tmp_path: Path) -> None:
    path = project_tmp_path / "mixed.log"
    path.write_text(
        "\n".join(
            [
                '2026-01-01T00:00:00Z level=INFO service=account_service event=profile_lookup_completed resource_id=account_1 rows=1 http_status=200 correlation_key=a@example.com',
                '2026-01-01T00:00:01Z | INFO | support_platform | tr-1 | contact_query_completed | resource_id="support_1" rows=0 lookup_key="b@example.com"',
                '2026-01-01T00:00:02Z [INFO] [account_service] [tr-2] profile_lookup_completed: resource_id="account_2" http_status="200" correlation_key="c@example.com"',
                '2026-01-01T00:00:03Z {"service":"search_service","event":"index_query_completed","resource_id":"search_2","result":"hit","correlation_key":"d@example.com"}',
                '2026-01-01T00:00:04Z requestId=tr-3 level=INFO function=profile_service message="resource_id=\\"account_3\\" event=\\"profile_lookup_completed\\" correlation_key=\\"e@example.com\\" rows=\\"0\\""',
                "2026-01-01T00:00:05Z INFO service=log_router event=export_started",
                "not-a-timestamp INFO service=x resource_id=account_9",
            ]
        ),
        encoding="utf-8",
    )
    outcome = LogEvidenceParser().parse(make_entry(path, EvidenceFormat.LOG), project_tmp_path)
    assert outcome.recognized is True
    assert len(outcome.observations) == 5
    assert len(outcome.warnings) == 1
    by_resource = {observation.resource_id: observation for observation in outcome.observations}
    assert by_resource["account_1"].observed_state == ObservedState.PRESENT
    assert by_resource["support_1"].observed_state == ObservedState.ABSENT
    assert by_resource["account_2"].observed_state == ObservedState.PRESENT
    assert by_resource["search_2"].observed_state == ObservedState.PRESENT
    assert by_resource["account_3"].observed_state == ObservedState.ABSENT
    assert by_resource["account_3"].emails == ("e@example.com",)
    assert by_resource["support_1"].emails == ("b@example.com",)


# ----------------------------------------------------------------------
# TXT
# ----------------------------------------------------------------------
def test_txt_handover(project_tmp_path: Path) -> None:
    path = project_tmp_path / "handover.txt"
    path.write_text(
        "\n".join(
            [
                "CUSTOMER PLATFORM - SHIFT HANDOVER",
                "Snapshot: 2026-01-01T00:00:00Z",
                "",
                "- 2026-01-01T00:00:00Z | account_service | account_1 | USER_PROFILE | NOT_FOUND | a@example.com",
                "- 2026-01-01T00:00:00Z | backup_service | backup_1 | BACKUP_ARCHIVE | ACTIVE | user_1",
            ]
        ),
        encoding="utf-8",
    )
    outcome = TxtEvidenceParser().parse(make_entry(path, EvidenceFormat.TXT), project_tmp_path)
    assert len(outcome.observations) == 2
    first, second = outcome.observations
    assert first.resource_id == "account_1"
    assert first.observed_state == ObservedState.ABSENT
    assert first.emails == ("a@example.com",)
    assert second.observed_state == ObservedState.ACTIVE
    assert second.user_ids == ("user_1",)


def test_txt_unrecognized(project_tmp_path: Path) -> None:
    path = project_tmp_path / "freeform.txt"
    path.write_text("just some text\nwithout structured rows\n", encoding="utf-8")
    outcome = TxtEvidenceParser().parse(make_entry(path, EvidenceFormat.TXT), project_tmp_path)
    assert outcome.recognized is False
    assert outcome.observations == ()
