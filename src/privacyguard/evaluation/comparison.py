"""Per-case comparison of two generated output CSV files."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import PROJECT_ROOT
from ..safety import ensure_writable_report


@dataclass(frozen=True, slots=True)
class OutputComparison:
    before_cases: int
    after_cases: int
    unchanged_cases: int
    changed_cases: tuple[dict[str, Any], ...]
    added_case_ids: tuple[str, ...]
    removed_case_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "before_cases": self.before_cases,
            "after_cases": self.after_cases,
            "unchanged_cases": self.unchanged_cases,
            "changed_case_count": len(self.changed_cases),
            "added_case_ids": list(self.added_case_ids),
            "removed_case_ids": list(self.removed_case_ids),
            "changed_cases": list(self.changed_cases),
        }


def compare_output_files(before: str | Path, after: str | Path) -> OutputComparison:
    before_rows = _load_output(before)
    after_rows = _load_output(after)
    common = sorted(before_rows.keys() & after_rows.keys())
    changed: list[dict[str, Any]] = []
    for case_id in common:
        old = before_rows[case_id]
        new = after_rows[case_id]
        if old == new:
            continue
        old_steps = old["steps"]
        new_steps = new["steps"]
        changed.append(
            {
                "case_id": case_id,
                "status_before": old["status"],
                "status_after": new["status"],
                "status_changed": old["status"] != new["status"],
                "step_count_before": len(old_steps),
                "step_count_after": len(new_steps),
                "steps_changed": old_steps != new_steps,
            }
        )
    return OutputComparison(
        before_cases=len(before_rows),
        after_cases=len(after_rows),
        unchanged_cases=len(common) - len(changed),
        changed_cases=tuple(changed),
        added_case_ids=tuple(sorted(after_rows.keys() - before_rows.keys())),
        removed_case_ids=tuple(sorted(before_rows.keys() - after_rows.keys())),
    )


def write_comparison_json(
    target: str | Path,
    comparison: OutputComparison,
    *,
    project_root: Path = PROJECT_ROOT,
) -> Path:
    destination = ensure_writable_report(project_root, Path(target))
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    ensure_writable_report(project_root, temporary)
    temporary.write_text(
        json.dumps(comparison.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(destination)
    return destination


def _load_output(path: str | Path) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            rows[row["case_id"]] = {
                "status": row["deletion_status"],
                "steps": json.loads(row["steps_json"]),
            }
    return rows
