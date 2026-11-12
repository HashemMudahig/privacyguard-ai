"""Evaluation metrics against the public sample answers."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..decision.models import AuditResult


@dataclass
class CaseDiagnostic:
    case_id: str
    expected_status: str
    actual_status: str
    status_correct: bool
    exact_steps: bool
    missing_steps: list[dict[str, Any]] = field(default_factory=list)
    extra_steps: list[dict[str, Any]] = field(default_factory=list)
    changed_fields: list[str] = field(default_factory=list)


@dataclass
class EvaluationReport:
    total_cases: int
    status_correct: int
    status_accuracy: float
    exact_case_matches: int
    exact_case_accuracy: float
    expected_steps: int
    actual_steps: int
    matched_steps: int
    step_precision: float
    step_recall: float
    step_f1: float
    field_accuracy: float
    sequence_accuracy: float
    evidence_accuracy: float
    diagnostics: list[CaseDiagnostic] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_cases": self.total_cases,
            "status_correct": self.status_correct,
            "status_accuracy": round(self.status_accuracy, 6),
            "exact_case_matches": self.exact_case_matches,
            "exact_case_accuracy": round(self.exact_case_accuracy, 6),
            "expected_steps": self.expected_steps,
            "actual_steps": self.actual_steps,
            "matched_steps": self.matched_steps,
            "step_precision": round(self.step_precision, 6),
            "step_recall": round(self.step_recall, 6),
            "step_f1": round(self.step_f1, 6),
            "field_accuracy": round(self.field_accuracy, 6),
            "sequence_accuracy": round(self.sequence_accuracy, 6),
            "evidence_accuracy": round(self.evidence_accuracy, 6),
            "diagnostics": [
                {
                    "case_id": item.case_id,
                    "expected_status": item.expected_status,
                    "actual_status": item.actual_status,
                    "status_correct": item.status_correct,
                    "exact_steps": item.exact_steps,
                    "missing_steps": item.missing_steps,
                    "extra_steps": item.extra_steps,
                    "changed_fields": item.changed_fields,
                }
                for item in self.diagnostics
            ],
        }


def load_golden(path: str | Path) -> dict[str, dict[str, Any]]:
    golden: dict[str, dict[str, Any]] = {}
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            golden[row["case_id"]] = {
                "status": row["deletion_status"],
                "steps": json.loads(row["steps_json"]),
            }
    return golden


def evaluate_results(
    results: tuple[AuditResult, ...] | list[AuditResult],
    golden_path: str | Path,
) -> EvaluationReport:
    golden = load_golden(golden_path)
    diagnostics: list[CaseDiagnostic] = []
    status_correct = 0
    exact_cases = 0
    expected_steps = 0
    actual_steps = 0
    matched_steps = 0
    field_correct = 0
    field_total = 0
    sequence_correct = 0
    evidence_correct = 0
    evidence_total = 0

    for result in results:
        expected = golden.get(result.case_id)
        if expected is None:
            diagnostics.append(
                CaseDiagnostic(
                    case_id=result.case_id,
                    expected_status="MISSING",
                    actual_status=result.deletion_status.value,
                    status_correct=False,
                    exact_steps=False,
                )
            )
            continue
        expected_status = expected["status"]
        expected_step_list = expected["steps"]
        actual_step_list = [
            step.model_dump(mode="json") for step in result.steps
        ]
        status_ok = expected_status == result.deletion_status.value
        status_correct += int(status_ok)
        expected_set = {_step_key(step) for step in expected_step_list}
        actual_set = {_step_key(step) for step in actual_step_list}
        matched = expected_set & actual_set
        missing = [step for step in expected_step_list if _step_key(step) not in actual_set]
        extra = [step for step in actual_step_list if _step_key(step) not in expected_set]
        exact_steps = expected_step_list == actual_step_list
        exact_cases += int(status_ok and exact_steps)
        sequence_correct += int(status_ok and exact_steps)
        expected_steps += len(expected_step_list)
        actual_steps += len(actual_step_list)
        matched_steps += len(matched)

        changed_fields: list[str] = []
        expected_by_key = {_alignment_key(step): step for step in expected_step_list}
        actual_by_key = {_alignment_key(step): step for step in actual_step_list}
        for key, expected_step in expected_by_key.items():
            actual_step = actual_by_key.get(key)
            field_total += 2
            if actual_step is None:
                continue
            if expected_step.get("state") == actual_step.get("state"):
                field_correct += 1
            else:
                changed_fields.append(f"{key}:state")
            if expected_step.get("evidence_id") == actual_step.get("evidence_id"):
                field_correct += 1
            else:
                changed_fields.append(f"{key}:evidence_id")
            if expected_step.get("evidence_id"):
                evidence_total += 1
                if expected_step.get("evidence_id") == actual_step.get("evidence_id"):
                    evidence_correct += 1

        diagnostics.append(
            CaseDiagnostic(
                case_id=result.case_id,
                expected_status=expected_status,
                actual_status=result.deletion_status.value,
                status_correct=status_ok,
                exact_steps=exact_steps,
                missing_steps=missing,
                extra_steps=extra,
                changed_fields=changed_fields,
            )
        )

    total = len(results)
    precision = matched_steps / actual_steps if actual_steps else 0.0
    recall = matched_steps / expected_steps if expected_steps else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return EvaluationReport(
        total_cases=total,
        status_correct=status_correct,
        status_accuracy=status_correct / total if total else 0.0,
        exact_case_matches=exact_cases,
        exact_case_accuracy=exact_cases / total if total else 0.0,
        expected_steps=expected_steps,
        actual_steps=actual_steps,
        matched_steps=matched_steps,
        step_precision=precision,
        step_recall=recall,
        step_f1=f1,
        field_accuracy=field_correct / field_total if field_total else 0.0,
        sequence_accuracy=sequence_correct / total if total else 0.0,
        evidence_accuracy=evidence_correct / evidence_total if evidence_total else 0.0,
        diagnostics=diagnostics,
    )


def _step_key(step: dict[str, Any]) -> tuple:
    return (
        step.get("phase"),
        step.get("system_id"),
        step.get("resource_id"),
        step.get("operation"),
        step.get("state"),
        step.get("evidence_id"),
    )


def _alignment_key(step: dict[str, Any]) -> str:
    return "|".join(
        [
            str(step.get("phase")),
            str(step.get("system_id")),
            str(step.get("resource_id")),
            str(step.get("operation")),
        ]
    )
