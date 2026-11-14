"""Sprint 3C regression tests for transparent evaluation diagnostics."""

from __future__ import annotations

import csv
import json

from privacyguard.evaluation.comparison import compare_output_files
from privacyguard.evaluation.metrics import evaluate_results


def _write_output(path, rows) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=("case_id", "deletion_status", "steps_json")
        )
        writer.writeheader()
        writer.writerows(rows)


def test_evaluator_separates_step_set_from_sequence(tmp_path, pipeline) -> None:
    result = pipeline.audit_case("case_05")
    golden = tmp_path / "golden.csv"
    expected_steps = [step.model_dump(mode="json") for step in reversed(result.steps)]
    _write_output(
        golden,
        [
            {
                "case_id": result.case_id,
                "deletion_status": result.deletion_status.value,
                "steps_json": json.dumps(expected_steps),
            }
        ],
    )
    report = evaluate_results([result], golden)
    assert report.exact_step_set_matches == 1
    assert report.exact_sequence_matches == 0
    assert report.diagnostics[0].failure_causes == ["ordering_only"]
    assert report.diagnostics[0].ordering_differences


def test_evaluator_labels_citation_divergence(tmp_path, pipeline) -> None:
    result = pipeline.audit_case("case_05")
    expected_steps = [step.model_dump(mode="json") for step in result.steps]
    expected_steps[0]["evidence_id"] = "different_valid_reference"
    golden = tmp_path / "golden.csv"
    _write_output(
        golden,
        [
            {
                "case_id": result.case_id,
                "deletion_status": result.deletion_status.value,
                "steps_json": json.dumps(expected_steps),
            }
        ],
    )
    diagnostic = evaluate_results([result], golden).diagnostics[0]
    assert diagnostic.evidence_mismatches[0]["classification"] == (
        "benchmark_citation_divergence"
    )


def test_output_comparison_reports_step_only_changes(tmp_path) -> None:
    before = tmp_path / "before.csv"
    after = tmp_path / "after.csv"
    base = {
        "case_id": "case_1",
        "deletion_status": "INCOMPLETE",
        "steps_json": "[]",
    }
    _write_output(before, [base])
    changed = dict(base)
    changed["steps_json"] = json.dumps(
        [
            {
                "step_no": 1,
                "phase": "VERIFICATION",
                "system_id": "account_service",
                "resource_id": "account_1",
                "operation": "VERIFY_RECORD_ABSENT",
                "state": "ABSENT",
                "evidence_id": "",
            }
        ]
    )
    _write_output(after, [changed])
    comparison = compare_output_files(before, after)
    assert len(comparison.changed_cases) == 1
    assert comparison.changed_cases[0]["status_changed"] is False
    assert comparison.changed_cases[0]["steps_changed"] is True
