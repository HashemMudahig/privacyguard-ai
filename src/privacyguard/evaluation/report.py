"""Evaluation report writing."""

from __future__ import annotations

import json
from pathlib import Path

from ..config import PROJECT_ROOT
from ..safety import ensure_writable_report
from .metrics import EvaluationReport


def write_evaluation_json(
    target: Path,
    report: EvaluationReport,
    *,
    project_root: Path = PROJECT_ROOT,
) -> Path:
    destination = ensure_writable_report(project_root, target)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    ensure_writable_report(project_root, temporary)
    temporary.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(destination)
    return destination
