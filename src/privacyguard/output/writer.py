"""CSV output writing."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from ..config import PROJECT_ROOT
from ..decision.models import AuditResult
from ..safety import ensure_writable_report


def case_sort_key(case_id: str) -> tuple[int, str]:
    try:
        return (int(case_id.split("_")[-1]), case_id)
    except ValueError:
        return (10**9, case_id)


def steps_json(result: AuditResult) -> str:
    payload = [step.model_dump(mode="json") for step in result.steps]
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def write_output(
    results: tuple[AuditResult, ...] | list[AuditResult],
    target: str | Path,
    *,
    project_root: Path = PROJECT_ROOT,
) -> Path:
    destination = ensure_writable_report(project_root, Path(target))
    destination.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(results, key=lambda result: case_sort_key(result.case_id))
    temporary = destination.with_name(destination.name + ".tmp")
    ensure_writable_report(project_root, temporary)
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["case_id", "deletion_status", "steps_json"])
        for result in ordered:
            writer.writerow(
                [result.case_id, result.deletion_status.value, steps_json(result)]
            )
    temporary.replace(destination)
    return destination
