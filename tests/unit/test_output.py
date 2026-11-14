"""Unit tests for output writing and structural validation."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from privacyguard.decision.models import AuditResult, DeletionStatus
from privacyguard.evidence.models import ObservedState
from privacyguard.intent.models import IntentStatus, RequestIntent
from privacyguard.output.validator import validate_output_file
from privacyguard.output.writer import write_output
from privacyguard.planning.models import AuditStep, Operation, Phase
from privacyguard.policy.models import PolicyEvaluation


def make_result(case_id: str = "case_1", status: DeletionStatus = DeletionStatus.COMPLETE) -> AuditResult:
    steps = (
        AuditStep(
            step_no=1,
            phase=Phase.VERIFICATION,
            system_id="account_service",
            resource_id="account_1",
            operation=Operation.VERIFY_RECORD_ABSENT,
            state=ObservedState.ABSENT,
            evidence_id="evidence_1",
        ),
    ) if status == DeletionStatus.COMPLETE else ()
    return AuditResult(
        case_id=case_id,
        deletion_status=status,
        steps=steps,
        intent=RequestIntent(
            case_id=case_id,
            status=IntentStatus.DELETION_AUTHORIZED,
            authorizes_deletion=True,
            confidence=1.0,
            method="test",
        ),
        policy=PolicyEvaluation(case_id=case_id),
    )


def write_rows(target: Path, rows: list[list[str]]) -> None:
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["case_id", "deletion_status", "steps_json"])
        writer.writerows(rows)


def test_write_and_validate_output(project_tmp_path: Path) -> None:
    target = project_tmp_path / "output.csv"
    write_output([make_result("case_2"), make_result("case_1")], target)
    with target.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert [row["case_id"] for row in rows] == ["case_1", "case_2"]
    report = validate_output_file(
        target,
        expected_case_ids={"case_1", "case_2"},
        known_evidence_ids={"evidence_1"},
    )
    assert report.valid, report.errors
    assert report.rows == 2


def test_validation_detects_wrong_count_and_header(project_tmp_path: Path) -> None:
    target = project_tmp_path / "bad.csv"
    target.write_text("wrong,header\n", encoding="utf-8")
    report = validate_output_file(target, expected_case_ids={"case_1"})
    assert not report.valid
    assert any("Header" in error for error in report.errors)
    assert any("Missing" in error for error in report.errors)


def test_validation_detects_bad_not_applicable(project_tmp_path: Path) -> None:
    target = project_tmp_path / "na.csv"
    step = {
        "step_no": 1,
        "phase": "VERIFICATION",
        "system_id": "account_service",
        "resource_id": "account_1",
        "operation": "VERIFY_RECORD_ABSENT",
        "state": "ABSENT",
        "evidence_id": "evidence_1",
    }
    write_rows(target, [["case_1", "NOT_APPLICABLE", json.dumps([step])]])
    report = validate_output_file(target, expected_case_ids={"case_1"})
    assert not report.valid
    assert any("NOT_APPLICABLE" in error for error in report.errors)


def test_validation_detects_invalid_operation_state(project_tmp_path: Path) -> None:
    target = project_tmp_path / "invalid.csv"
    step = {
        "step_no": 1,
        "phase": "FINDING",
        "system_id": "account_service",
        "resource_id": "account_1",
        "operation": "DELETE_RECORD",
        "state": "PRESENT",
        "evidence_id": "evidence_1",
    }
    write_rows(target, [["case_1", "INCOMPLETE", json.dumps([step])]])
    report = validate_output_file(target, expected_case_ids={"case_1"})
    assert not report.valid
    assert any("not allowed in phase" in error for error in report.errors)


def test_validation_detects_unknown_evidence(project_tmp_path: Path) -> None:
    target = project_tmp_path / "unknown_evidence.csv"
    step = {
        "step_no": 1,
        "phase": "VERIFICATION",
        "system_id": "account_service",
        "resource_id": "account_1",
        "operation": "VERIFY_RECORD_ABSENT",
        "state": "ABSENT",
        "evidence_id": "evidence_invented",
    }
    write_rows(target, [["case_1", "COMPLETE", json.dumps([step])]])
    report = validate_output_file(
        target,
        expected_case_ids={"case_1"},
        known_evidence_ids={"evidence_1"},
    )
    assert not report.valid
    assert any("not a known" in error for error in report.errors)


def test_validation_rejects_contradictory_operations(project_tmp_path: Path) -> None:
    target = project_tmp_path / "contradictory.csv"
    steps = [
        {
            "step_no": 1,
            "phase": "REMEDIATION",
            "system_id": "account_service",
            "resource_id": "account_1",
            "operation": "DELETE_RECORD",
            "state": "ABSENT",
            "evidence_id": "",
        },
        {
            "step_no": 2,
            "phase": "REMEDIATION",
            "system_id": "account_service",
            "resource_id": "account_1",
            "operation": "REDACT_RECORD",
            "state": "REDACTED",
            "evidence_id": "",
        },
    ]
    write_rows(target, [["case_1", "INCOMPLETE", json.dumps(steps)]])
    report = validate_output_file(target, expected_case_ids={"case_1"})
    assert not report.valid
    assert any("contradictory" in error for error in report.errors)
