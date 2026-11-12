"""Audit context report writing."""

from __future__ import annotations

import json
from pathlib import Path

from ..config import PROJECT_ROOT
from ..safety import ensure_writable_report
from .models import AuditContext


def write_context_json(
    target: Path,
    context: AuditContext,
    *,
    project_root: Path = PROJECT_ROOT,
) -> Path:
    """Write a full audit context JSON inside the project root."""
    destination = ensure_writable_report(project_root, target)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    ensure_writable_report(project_root, temporary)
    temporary.write_text(
        json.dumps(context.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(destination)
    return destination
