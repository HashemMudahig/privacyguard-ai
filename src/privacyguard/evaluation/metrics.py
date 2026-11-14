"""Transparent, case-level evaluation against the public sample answers."""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from ..decision.models import AuditResult

_FIELDS = ("phase", "system_id", "resource_id", "operation", "state", "evidence_id")


@dataclass
class CaseDiagnostic:
    case_id: str
    expected_status: str
    actual_status: str
    status_correct: bool
    expected_step_count: int
    actual_step_count: int
    exact_step_set: bool
    exact_sequence: bool
    exact_case: bool
    contract_valid: bool
    contract_errors: list[str] = field(default_factory=list)
    missing_steps: list[dict[str, Any]] = field(default_factory=list)
    extra_steps: list[dict[str, Any]] = field(default_factory=list)
    incorrect_operations: list[dict[str, Any]] = field(default_factory=list)
    incorrect_states: list[dict[str, Any]] = field(default_factory=list)
    incorrect_references: list[dict[str, Any]] = field(default_factory=list)
    evidence_mismatches: list[dict[str, Any]] = field(default_factory=list)
    ordering_differences: list[dict[str, Any]] = field(default_factory=list)
    changed_fields: list[str] = field(default_factory=list)
    failure_causes: list[str] = field(default_factory=list)

    @property
    def exact_steps(self) -> bool:
        """Compatibility alias retained for older report consumers."""
        return self.exact_sequence


@dataclass
class EvaluationReport:
    total_cases: int
    status_correct: int
    status_accuracy: float
    exact_case_matches: int
    exact_case_accuracy: float
    exact_step_set_matches: int
    exact_step_set_accuracy: float
    exact_sequence_matches: int
    exact_sequence_accuracy: float
    expected_steps: int
    actual_steps: int
    matched_steps: int
    step_precision: float
    step_recall: float
    step_f1: float
    field_correct: int
    field_total: int
    field_accuracy: float
    evidence_correct: int
    evidence_total: int
    evidence_accuracy: float
    contract_valid_cases: int
    contract_validity_accuracy: float
    failure_taxonomy: dict[str, list[str]] = field(default_factory=dict)
    diagnostics: list[CaseDiagnostic] = field(default_factory=list)

    @property
    def sequence_accuracy(self) -> float:
        """Compatibility alias for the explicitly named sequence metric."""
        return self.exact_sequence_accuracy

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric_definitions": {
                "step_match": "exact phase/system/resource/operation/state/evidence tuple; step_no ignored",
                "exact_step_set": "multiset equality; order and step_no ignored",
                "exact_sequence": "ordered step tuple equality; step_no ignored",
                "exact_case": "status and exact sequence match",
                "field_accuracy": "equal fields across best deterministic alignment, penalizing missing/extra steps",
                "evidence_accuracy": "benchmark citation equality on aligned expected steps with non-empty citations",
                "contract_validity": "allowed phases/operations/states, phase order, and consecutive numbering",
            },
            "total_cases": self.total_cases,
            "status_correct": self.status_correct,
            "status_accuracy": round(self.status_accuracy, 6),
            "exact_case_matches": self.exact_case_matches,
            "exact_case_accuracy": round(self.exact_case_accuracy, 6),
            "exact_step_set_matches": self.exact_step_set_matches,
            "exact_step_set_accuracy": round(self.exact_step_set_accuracy, 6),
            "exact_sequence_matches": self.exact_sequence_matches,
            "exact_sequence_accuracy": round(self.exact_sequence_accuracy, 6),
            "sequence_accuracy": round(self.sequence_accuracy, 6),
            "expected_steps": self.expected_steps,
            "actual_steps": self.actual_steps,
            "matched_steps": self.matched_steps,
            "step_precision": round(self.step_precision, 6),
            "step_recall": round(self.step_recall, 6),
            "step_f1": round(self.step_f1, 6),
            "field_correct": self.field_correct,
            "field_total": self.field_total,
            "field_accuracy": round(self.field_accuracy, 6),
            "evidence_correct": self.evidence_correct,
            "evidence_total": self.evidence_total,
            "evidence_accuracy": round(self.evidence_accuracy, 6),
            "contract_valid_cases": self.contract_valid_cases,
            "contract_validity_accuracy": round(self.contract_validity_accuracy, 6),
            "failure_taxonomy": self.failure_taxonomy,
            "diagnostics": [
                {
                    "case_id": item.case_id,
                    "expected_status": item.expected_status,
                    "actual_status": item.actual_status,
                    "status_correct": item.status_correct,
                    "expected_step_count": item.expected_step_count,
                    "actual_step_count": item.actual_step_count,
                    "exact_step_set": item.exact_step_set,
                    "exact_sequence": item.exact_sequence,
                    "exact_steps": item.exact_steps,
                    "exact_case": item.exact_case,
                    "contract_valid": item.contract_valid,
                    "contract_errors": item.contract_errors,
                    "missing_steps": item.missing_steps,
                    "extra_steps": item.extra_steps,
                    "incorrect_operations": item.incorrect_operations,
                    "incorrect_states": item.incorrect_states,
                    "incorrect_references": item.incorrect_references,
                    "evidence_mismatches": item.evidence_mismatches,
                    "ordering_differences": item.ordering_differences,
                    "changed_fields": item.changed_fields,
                    "failure_causes": item.failure_causes,
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
    status_correct = exact_cases = exact_sets = exact_sequences = 0
    expected_steps = actual_steps = matched_steps = 0
    field_correct = field_total = 0
    evidence_correct = evidence_total = 0
    contract_valid_cases = 0

    for result in results:
        expected = golden.get(result.case_id)
        actual_step_list = [step.model_dump(mode="json") for step in result.steps]
        contract_errors = _contract_errors(actual_step_list)
        contract_valid = not contract_errors
        contract_valid_cases += int(contract_valid)
        if expected is None:
            diagnostics.append(
                CaseDiagnostic(
                    case_id=result.case_id,
                    expected_status="MISSING",
                    actual_status=result.deletion_status.value,
                    status_correct=False,
                    expected_step_count=0,
                    actual_step_count=len(actual_step_list),
                    exact_step_set=False,
                    exact_sequence=False,
                    exact_case=False,
                    contract_valid=contract_valid,
                    contract_errors=contract_errors,
                    extra_steps=actual_step_list,
                    failure_causes=["missing_reference_case"],
                )
            )
            continue

        expected_status = expected["status"]
        expected_step_list = expected["steps"]
        status_ok = expected_status == result.deletion_status.value
        status_correct += int(status_ok)
        expected_counter = Counter(_step_key(step) for step in expected_step_list)
        actual_counter = Counter(_step_key(step) for step in actual_step_list)
        intersection = expected_counter & actual_counter
        matched = sum(intersection.values())
        missing = _counter_difference_steps(expected_step_list, actual_counter)
        extra = _counter_difference_steps(actual_step_list, expected_counter)
        exact_set = expected_counter == actual_counter
        expected_sequence = [_step_key(step) for step in expected_step_list]
        actual_sequence = [_step_key(step) for step in actual_step_list]
        exact_sequence = expected_sequence == actual_sequence
        exact_case = status_ok and exact_sequence
        exact_sets += int(exact_set)
        exact_sequences += int(exact_sequence)
        exact_cases += int(exact_case)
        expected_steps += len(expected_step_list)
        actual_steps += len(actual_step_list)
        matched_steps += matched

        aligned, unmatched_expected, unmatched_actual = _align_steps(
            expected_step_list, actual_step_list
        )
        case_field_correct, case_field_total = _field_score(
            aligned, unmatched_expected, unmatched_actual
        )
        field_correct += case_field_correct
        field_total += case_field_total

        incorrect_operations: list[dict[str, Any]] = []
        incorrect_states: list[dict[str, Any]] = []
        incorrect_references: list[dict[str, Any]] = []
        evidence_mismatches: list[dict[str, Any]] = []
        changed_fields: list[str] = []
        for expected_index, actual_index, expected_step, actual_step in aligned:
            context = {"expected_index": expected_index + 1, "actual_index": actual_index + 1}
            if expected_step.get("operation") != actual_step.get("operation"):
                incorrect_operations.append(
                    {**context, "expected": expected_step.get("operation"), "actual": actual_step.get("operation")}
                )
            if expected_step.get("state") != actual_step.get("state"):
                incorrect_states.append(
                    {**context, "expected": expected_step.get("state"), "actual": actual_step.get("state")}
                )
            reference_fields = {
                name: {"expected": expected_step.get(name), "actual": actual_step.get(name)}
                for name in ("system_id", "resource_id")
                if expected_step.get(name) != actual_step.get(name)
            }
            if reference_fields:
                incorrect_references.append({**context, "fields": reference_fields})
            if expected_step.get("evidence_id") != actual_step.get("evidence_id"):
                evidence_mismatches.append(
                    {
                        **context,
                        "expected": expected_step.get("evidence_id"),
                        "actual": actual_step.get("evidence_id"),
                        "classification": "benchmark_citation_divergence",
                    }
                )
            if expected_step.get("evidence_id"):
                evidence_total += 1
                evidence_correct += int(
                    expected_step.get("evidence_id") == actual_step.get("evidence_id")
                )
            for name in _FIELDS:
                if expected_step.get(name) != actual_step.get(name):
                    changed_fields.append(
                        f"expected[{expected_index + 1}]~actual[{actual_index + 1}]:{name}"
                    )

        ordering = _ordering_differences(expected_sequence, actual_sequence, exact_set)
        causes = _failure_causes(
            status_ok=status_ok,
            exact_set=exact_set,
            exact_sequence=exact_sequence,
            missing=missing,
            extra=extra,
            evidence=evidence_mismatches,
            operations=incorrect_operations,
            states=incorrect_states,
            references=incorrect_references,
            contract_valid=contract_valid,
        )
        diagnostics.append(
            CaseDiagnostic(
                case_id=result.case_id,
                expected_status=expected_status,
                actual_status=result.deletion_status.value,
                status_correct=status_ok,
                expected_step_count=len(expected_step_list),
                actual_step_count=len(actual_step_list),
                exact_step_set=exact_set,
                exact_sequence=exact_sequence,
                exact_case=exact_case,
                contract_valid=contract_valid,
                contract_errors=contract_errors,
                missing_steps=missing,
                extra_steps=extra,
                incorrect_operations=incorrect_operations,
                incorrect_states=incorrect_states,
                incorrect_references=incorrect_references,
                evidence_mismatches=evidence_mismatches,
                ordering_differences=ordering,
                changed_fields=changed_fields,
                failure_causes=causes,
            )
        )

    total = len(results)
    precision = matched_steps / actual_steps if actual_steps else 0.0
    recall = matched_steps / expected_steps if expected_steps else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    taxonomy: dict[str, list[str]] = defaultdict(list)
    for item in diagnostics:
        for cause in item.failure_causes:
            taxonomy[cause].append(item.case_id)
    return EvaluationReport(
        total_cases=total,
        status_correct=status_correct,
        status_accuracy=status_correct / total if total else 0.0,
        exact_case_matches=exact_cases,
        exact_case_accuracy=exact_cases / total if total else 0.0,
        exact_step_set_matches=exact_sets,
        exact_step_set_accuracy=exact_sets / total if total else 0.0,
        exact_sequence_matches=exact_sequences,
        exact_sequence_accuracy=exact_sequences / total if total else 0.0,
        expected_steps=expected_steps,
        actual_steps=actual_steps,
        matched_steps=matched_steps,
        step_precision=precision,
        step_recall=recall,
        step_f1=f1,
        field_correct=field_correct,
        field_total=field_total,
        field_accuracy=field_correct / field_total if field_total else 0.0,
        evidence_correct=evidence_correct,
        evidence_total=evidence_total,
        evidence_accuracy=evidence_correct / evidence_total if evidence_total else 0.0,
        contract_valid_cases=contract_valid_cases,
        contract_validity_accuracy=contract_valid_cases / total if total else 0.0,
        failure_taxonomy=dict(sorted(taxonomy.items())),
        diagnostics=diagnostics,
    )


def _counter_difference_steps(
    source: list[dict[str, Any]], other: Counter[tuple[Any, ...]]
) -> list[dict[str, Any]]:
    remaining = other.copy()
    difference: list[dict[str, Any]] = []
    for step in source:
        key = _step_key(step)
        if remaining[key]:
            remaining[key] -= 1
        else:
            difference.append(step)
    return difference


def _align_steps(
    expected: list[dict[str, Any]], actual: list[dict[str, Any]]
) -> tuple[
    list[tuple[int, int, dict[str, Any], dict[str, Any]]], list[int], list[int]
]:
    """Greedily align steps by maximum equal fields with stable tie-breaking."""
    candidates: list[tuple[int, int, int]] = []
    for expected_index, expected_step in enumerate(expected):
        for actual_index, actual_step in enumerate(actual):
            score = sum(
                expected_step.get(name) == actual_step.get(name) for name in _FIELDS
            )
            candidates.append((-score, expected_index, actual_index))
    used_expected: set[int] = set()
    used_actual: set[int] = set()
    aligned: list[tuple[int, int, dict[str, Any], dict[str, Any]]] = []
    for negative_score, expected_index, actual_index in sorted(candidates):
        if expected_index in used_expected or actual_index in used_actual:
            continue
        # Fewer than three shared fields is not a defensible alignment; report
        # the records independently as missing/extra instead of inventing field
        # substitutions between unrelated steps.
        if -negative_score < 3:
            continue
        used_expected.add(expected_index)
        used_actual.add(actual_index)
        aligned.append(
            (expected_index, actual_index, expected[expected_index], actual[actual_index])
        )
    aligned.sort(key=lambda item: item[0])
    return (
        aligned,
        [index for index in range(len(expected)) if index not in used_expected],
        [index for index in range(len(actual)) if index not in used_actual],
    )


def _field_score(
    aligned: Iterable[tuple[int, int, dict[str, Any], dict[str, Any]]],
    unmatched_expected: list[int],
    unmatched_actual: list[int],
) -> tuple[int, int]:
    correct = total = 0
    for _, _, expected, actual in aligned:
        total += len(_FIELDS)
        correct += sum(expected.get(name) == actual.get(name) for name in _FIELDS)
    total += len(_FIELDS) * (len(unmatched_expected) + len(unmatched_actual))
    return correct, total


def _ordering_differences(
    expected: list[tuple[Any, ...]], actual: list[tuple[Any, ...]], exact_set: bool
) -> list[dict[str, Any]]:
    if not exact_set or expected == actual:
        return []
    return [
        {"position": index + 1, "expected": expected[index], "actual": actual[index]}
        for index in range(min(len(expected), len(actual)))
        if expected[index] != actual[index]
    ]


def _failure_causes(**values: Any) -> list[str]:
    causes: list[str] = []
    if not values["status_ok"]:
        causes.append("status_classification")
    if values["missing"]:
        causes.append("missing_steps")
    if values["extra"]:
        causes.append("extra_steps")
    if values["evidence"]:
        causes.append("benchmark_citation_divergence")
    if values["operations"]:
        causes.append("operation_mismatch")
    if values["states"]:
        causes.append("state_mismatch")
    if values["references"]:
        causes.append("resource_or_system_mismatch")
    if values["exact_set"] and not values["exact_sequence"]:
        causes.append("ordering_only")
    if not values["contract_valid"]:
        causes.append("output_contract")
    return causes or ["exact_match"]


def _contract_errors(steps: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    phases = {"FINDING": 0, "REMEDIATION": 1, "VERIFICATION": 2}
    allowed = {
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
    previous_phase = -1
    target_operations: dict[tuple[Any, Any, Any], Any] = {}
    for index, step in enumerate(steps, start=1):
        if step.get("step_no") != index:
            errors.append(f"step {index}: non-consecutive step_no {step.get('step_no')!r}")
        phase = step.get("phase")
        if phase not in phases:
            errors.append(f"step {index}: invalid phase {phase!r}")
        elif phases[phase] < previous_phase:
            errors.append(f"step {index}: phase order regressed to {phase}")
        else:
            previous_phase = phases[phase]
        operation = step.get("operation")
        if operation not in allowed:
            errors.append(f"step {index}: invalid operation {operation!r}")
        elif step.get("state") != allowed[operation]:
            errors.append(
                f"step {index}: {operation} requires state {allowed[operation]}, got {step.get('state')!r}"
            )
        target = (phase, step.get("system_id"), step.get("resource_id"))
        previous_operation = target_operations.get(target)
        if (
            phase in {"REMEDIATION", "VERIFICATION"}
            and previous_operation is not None
            and previous_operation != operation
        ):
            errors.append(
                f"step {index}: contradictory operations for {target[1]}/{target[2]}"
            )
        target_operations[target] = operation
    return errors


def _step_key(step: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(step.get(name) for name in _FIELDS)


def _alignment_key(step: dict[str, Any]) -> str:
    """Legacy helper retained for callers that imported it privately."""
    return "|".join(str(step.get(name)) for name in _FIELDS[:4])
