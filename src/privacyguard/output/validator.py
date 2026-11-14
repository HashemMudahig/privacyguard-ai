"""Structural and semantic validation of generated output."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path

from ..evidence.models import ObservedState
from ..planning.models import Operation, Phase

HEADER = ("case_id", "deletion_status", "steps_json")
ALLOWED_STATUSES = {"COMPLETE", "INCOMPLETE", "NOT_APPLICABLE"}
ALLOWED_FIELDS = {
    "step_no",
    "phase",
    "system_id",
    "resource_id",
    "operation",
    "state",
    "evidence_id",
}
PHASE_RANK = {Phase.FINDING.value: 0, Phase.REMEDIATION.value: 1, Phase.VERIFICATION.value: 2}
OPERATION_RANK = {
    "REPORT_REMAINING_RECORD": 0,
    "REPORT_EXPOSED_PII": 1,
    "REPORT_ACTIVE_DATA_FLOW": 2,
    "REPORT_RESTORE_RISK": 3,
    "DISABLE_DATA_FLOW": 0,
    "BLOCK_RESTORE": 1,
    "DELETE_RECORD": 2,
    "REDACT_RECORD": 3,
    "ANONYMIZE_RECORD": 4,
    "VERIFY_RECORD_ABSENT": 0,
    "VERIFY_RECORD_PRESENT": 1,
    "VERIFY_RECORD_REDACTED": 2,
    "VERIFY_RECORD_ANONYMIZED": 3,
    "VERIFY_DATA_FLOW_DISABLED": 4,
    "VERIFY_RESTORE_BLOCKED": 5,
}
OP_STATE = {
    "REPORT_REMAINING_RECORD": "PRESENT",
    "REPORT_EXPOSED_PII": "PRESENT",
    "REPORT_ACTIVE_DATA_FLOW": "ACTIVE",
    "REPORT_RESTORE_RISK": "ACTIVE",
    "DISABLE_DATA_FLOW": "DISABLED",
    "BLOCK_RESTORE": "BLOCKED",
    "DELETE_RECORD": "ABSENT",
    "REDACT_RECORD": "REDACTED",
    "ANONYMIZE_RECORD": "ANONYMIZED",
    "VERIFY_RECORD_ABSENT": "ABSENT",
    "VERIFY_RECORD_PRESENT": "PRESENT",
    "VERIFY_RECORD_REDACTED": "REDACTED",
    "VERIFY_RECORD_ANONYMIZED": "ANONYMIZED",
    "VERIFY_DATA_FLOW_DISABLED": "DISABLED",
    "VERIFY_RESTORE_BLOCKED": "BLOCKED",
}
PHASE_OP = {
    "FINDING": {
        "REPORT_REMAINING_RECORD",
        "REPORT_EXPOSED_PII",
        "REPORT_ACTIVE_DATA_FLOW",
        "REPORT_RESTORE_RISK",
    },
    "REMEDIATION": {
        "DISABLE_DATA_FLOW",
        "BLOCK_RESTORE",
        "DELETE_RECORD",
        "REDACT_RECORD",
        "ANONYMIZE_RECORD",
    },
    "VERIFICATION": {
        "VERIFY_RECORD_ABSENT",
        "VERIFY_RECORD_PRESENT",
        "VERIFY_RECORD_REDACTED",
        "VERIFY_RECORD_ANONYMIZED",
        "VERIFY_DATA_FLOW_DISABLED",
        "VERIFY_RESTORE_BLOCKED",
    },
}


@dataclass
class ValidationReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    rows: int = 0

    @property
    def valid(self) -> bool:
        return not self.errors


def read_output(target: str | Path) -> list[dict[str, str]]:
    path = Path(target)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader)


def validate_output_file(
    target: str | Path,
    expected_case_ids: set[str] | None = None,
    *,
    known_evidence_ids: set[str] | None = None,
) -> ValidationReport:
    path = Path(target)
    report = ValidationReport()
    if not path.is_file():
        report.errors.append(f"Output file not found: {path}")
        return report
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        actual_header = tuple(reader.fieldnames or ())
        if actual_header != HEADER:
            report.errors.append(
                f"Header {actual_header!r} does not match {HEADER!r}"
            )
        rows = list(reader)
    report.rows = len(rows)
    _validate_rows(rows, report, expected_case_ids, known_evidence_ids)
    return report


def _validate_rows(
    rows: list[dict[str, str]],
    report: ValidationReport,
    expected_case_ids: set[str] | None,
    known_evidence_ids: set[str] | None,
) -> None:
    seen_cases: set[str] = set()
    previous_key: tuple[int, str] | None = None
    for row_index, row in enumerate(rows, start=1):
        case_id = row.get("case_id", "")
        status = row.get("deletion_status", "")
        if not case_id:
            report.errors.append(f"Row {row_index}: empty case_id")
            continue
        if case_id in seen_cases:
            report.errors.append(f"Row {row_index}: duplicate case_id {case_id}")
        seen_cases.add(case_id)
        sort_key = _case_sort_key(case_id)
        if previous_key is not None and sort_key < previous_key:
            report.errors.append(f"Row {row_index}: case_id is not sorted")
        previous_key = sort_key
        if status not in ALLOWED_STATUSES:
            report.errors.append(f"{case_id}: invalid deletion_status {status!r}")
            continue
        try:
            steps = json.loads(row.get("steps_json", ""))
        except json.JSONDecodeError as exc:
            report.errors.append(f"{case_id}: invalid steps_json: {exc}")
            continue
        if not isinstance(steps, list):
            report.errors.append(f"{case_id}: steps_json is not an array")
            continue
        if status == "NOT_APPLICABLE" and steps:
            report.errors.append(f"{case_id}: NOT_APPLICABLE must use []")
        _validate_steps(case_id, status, steps, report, known_evidence_ids)

    if expected_case_ids is not None:
        missing = expected_case_ids - seen_cases
        extra = seen_cases - expected_case_ids
        if missing:
            report.errors.append(
                f"Missing {len(missing)} expected case(s): {sorted(missing)[:5]}"
            )
        if extra:
            report.errors.append(
                f"Found {len(extra)} unexpected case(s): {sorted(extra)[:5]}"
            )


def _validate_steps(
    case_id: str,
    status: str,
    steps: list,
    report: ValidationReport,
    known_evidence_ids: set[str] | None,
) -> None:
    previous_key = None
    seen_steps = set()
    target_operations: dict[tuple[str, str, str], str] = {}
    for index, step in enumerate(steps, start=1):
        if not isinstance(step, dict):
            report.errors.append(f"{case_id}: step {index} is not an object")
            continue
        if set(step.keys()) != ALLOWED_FIELDS:
            report.errors.append(
                f"{case_id}: step {index} fields {sorted(step.keys())} are invalid"
            )
            continue
        if step["step_no"] != index:
            report.errors.append(
                f"{case_id}: step_no {step['step_no']} is not consecutive at {index}"
            )
        phase = step["phase"]
        operation = step["operation"]
        state = step["state"]
        if phase not in PHASE_OP or operation not in PHASE_OP[phase]:
            report.errors.append(
                f"{case_id}: operation {operation!r} not allowed in phase {phase!r}"
            )
            continue
        expected_state = OP_STATE.get(operation)
        if expected_state is not None and state != expected_state:
            report.errors.append(
                f"{case_id}: operation {operation!r} requires state {expected_state}, got {state!r}"
            )
        ordering_key = (
            PHASE_RANK.get(phase, 99),
            OPERATION_RANK.get(operation, 99),
            step.get("system_id", ""),
            step.get("resource_id", ""),
        )
        if previous_key is not None and ordering_key < previous_key:
            report.errors.append(f"{case_id}: step {index} is out of order")
        previous_key = ordering_key
        step_key = (
            phase,
            step.get("system_id"),
            step.get("resource_id"),
            operation,
            state,
            step.get("evidence_id"),
        )
        if step_key in seen_steps:
            report.errors.append(f"{case_id}: duplicate step at {index}")
        seen_steps.add(step_key)
        target_key = (
            phase,
            str(step.get("system_id", "")),
            str(step.get("resource_id", "")),
        )
        previous_operation = target_operations.get(target_key)
        if (
            phase in {"REMEDIATION", "VERIFICATION"}
            and previous_operation is not None
            and previous_operation != operation
        ):
            report.errors.append(
                f"{case_id}: contradictory {phase.lower()} operations for "
                f"{target_key[1]}/{target_key[2]}: {previous_operation} and {operation}"
            )
        target_operations[target_key] = operation
        evidence_id = str(step.get("evidence_id", ""))
        if phase == "FINDING" and not evidence_id:
            report.errors.append(f"{case_id}: finding {index} has no evidence_id")
        if status == "COMPLETE":
            if phase != "VERIFICATION":
                report.errors.append(f"{case_id}: COMPLETE contains non-verification step")
            if not evidence_id:
                report.errors.append(f"{case_id}: COMPLETE verification has no evidence_id")
        if status == "INCOMPLETE":
            if phase in {"REMEDIATION", "VERIFICATION"} and evidence_id:
                report.errors.append(
                    f"{case_id}: future {phase.lower()} step has evidence_id {evidence_id!r}"
                )
        if evidence_id and known_evidence_ids is not None and evidence_id not in known_evidence_ids:
            report.errors.append(
                f"{case_id}: evidence_id {evidence_id!r} is not a known evidence/activity/audit ID"
            )


def _case_sort_key(case_id: str) -> tuple[int, str]:
    try:
        return (int(case_id.split("_")[-1]), case_id)
    except ValueError:
        return (10**9, case_id)
