"""Integration tests for the end-to-end audit pipeline."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from privacyguard.decision.models import DeletionStatus
from privacyguard.errors import UnsafePathError


def test_sample_pipeline_output(settings, pipeline, sample_results, project_tmp_path: Path) -> None:
    assert len(sample_results) == 32
    counts = Counter(result.deletion_status for result in sample_results)
    assert counts[DeletionStatus.COMPLETE] == 9
    assert counts[DeletionStatus.INCOMPLETE] == 23
    assert counts[DeletionStatus.NOT_APPLICABLE] == 0
    target = project_tmp_path / "sample.csv"
    pipeline.write_results(sample_results, target)
    report = pipeline.validate_output(target, choice="sample")
    assert report.valid, report.errors
    assert report.rows == 32


def test_eval_pipeline_output(settings, pipeline, project_tmp_path: Path) -> None:
    results = pipeline.audit_requests("eval")
    assert len(results) == 518
    counts = Counter(result.deletion_status for result in results)
    assert counts[DeletionStatus.COMPLETE] == 143
    assert counts[DeletionStatus.INCOMPLETE] == 365
    assert counts[DeletionStatus.NOT_APPLICABLE] == 10
    target = project_tmp_path / "eval.csv"
    pipeline.write_results(results, target)
    report = pipeline.validate_output(target, choice="eval")
    assert report.valid, report.errors
    assert report.rows == 518


def test_not_applicable_cases_have_empty_steps(pipeline) -> None:
    results = pipeline.audit_requests("eval")
    not_applicable = [
        result for result in results if result.deletion_status == DeletionStatus.NOT_APPLICABLE
    ]
    assert len(not_applicable) == 10
    assert all(result.steps == () for result in not_applicable)


def test_sample_evaluation_metrics(pipeline, sample_results) -> None:
    report = pipeline.evaluate_sample(sample_results)
    assert report.total_cases == 32
    assert report.status_correct == 31
    assert report.status_accuracy == pytest.approx(31 / 32)
    assert report.step_f1 >= 0.85
    assert report.evidence_accuracy >= 0.90
    assert report.exact_case_matches >= 10
    assert len(report.diagnostics) == 32
    assert sum(1 for item in report.diagnostics if not item.status_correct) == 1


def test_output_write_refuses_outside_project(pipeline, sample_results) -> None:
    outside = Path(pipeline.dataset_dir).parent / "privacyguard-forbidden-output.csv"
    with pytest.raises(UnsafePathError):
        pipeline.write_results(sample_results, outside)
    assert not outside.exists()


def test_all_sample_cases_produce_steps_or_documented_gap(pipeline) -> None:
    for case_id in pipeline.case_ids("sample"):
        result = pipeline.audit_case(case_id)
        if result.deletion_status == DeletionStatus.NOT_APPLICABLE:
            assert result.steps == ()
        elif result.deletion_status == DeletionStatus.COMPLETE:
            assert result.steps
            assert all(step.evidence_id for step in result.steps)
        else:
            # An unresolved case may have no resource to act on; it must document why.
            assert result.status_reasons or result.uncertainties
