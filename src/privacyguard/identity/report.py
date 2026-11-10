"""Batch resolution summaries and JSON report writing."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from ..config import PROJECT_ROOT
from ..models import (
    RequestIdentityResolution,
    ResolutionException,
    ResolutionStatus,
    ResolutionSummary,
)
from ..safety import ensure_writable_report


def summarize_resolutions(
    dataset_dir: Path,
    request_file_name: str,
    resolutions: tuple[RequestIdentityResolution, ...],
) -> ResolutionSummary:
    """Aggregate a batch of request resolutions into a deterministic summary."""
    methods: Counter[str] = Counter()
    exceptions: list[ResolutionException] = []
    resolved = ambiguous = not_found = 0

    for item in resolutions:
        resolution = item.resolution
        if resolution.status == ResolutionStatus.RESOLVED:
            resolved += 1
            methods[resolution.method.value] += 1
        else:
            if resolution.status == ResolutionStatus.AMBIGUOUS:
                ambiguous += 1
            else:
                not_found += 1
            exceptions.append(
                ResolutionException(
                    case_id=item.case_id,
                    email=item.request_email,
                    status=resolution.status,
                    candidates=resolution.candidates,
                    warnings=resolution.warnings,
                )
            )

    return ResolutionSummary(
        dataset=str(dataset_dir),
        request_file=request_file_name,
        total_requests=len(resolutions),
        resolved=resolved,
        ambiguous=ambiguous,
        not_found=not_found,
        methods=dict(sorted(methods.items())),
        exceptions=tuple(exceptions),
    )


def write_json_report(
    target: Path,
    summary: ResolutionSummary,
    resolutions: tuple[RequestIdentityResolution, ...],
    *,
    project_root: Path = PROJECT_ROOT,
) -> Path:
    """Write a JSON report inside the project root using an atomic replace."""
    destination = ensure_writable_report(project_root, target)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "summary": summary.model_dump(mode="json"),
        "resolutions": [
            item.model_dump(mode="json") for item in resolutions
        ],
    }
    temporary = destination.with_name(destination.name + ".tmp")
    ensure_writable_report(project_root, temporary)
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(destination)
    return destination
