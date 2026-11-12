"""Evidence build orchestration: manifest -> parsers -> observations -> inventory."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .errors import EvidenceParseError
from .manifest import load_evidence_manifest
from .models import (
    EvidenceInventory,
    EvidenceObservation,
    EvidenceParseFailure,
    ManifestLoadResult,
    UnsupportedEvidence,
)
from .parsers.registry import parser_for


@dataclass(frozen=True, slots=True)
class EvidenceBuildResult:
    """Manifest, observations, inventory and non-fatal parse warnings."""

    dataset_dir: Path
    manifest: ManifestLoadResult
    observations: tuple[EvidenceObservation, ...]
    inventory: EvidenceInventory
    warnings: tuple[str, ...]

    def build_index(self):
        """Build an :class:`EvidenceIndex` over the parsed observations."""
        from .index import EvidenceIndex

        return EvidenceIndex(self.observations)


def build_evidence(
    dataset_dir: str | Path,
    *,
    strict_manifest: bool = True,
) -> EvidenceBuildResult:
    """Parse every supported evidence file and report unsupported/failed ones."""
    root = Path(dataset_dir).expanduser().resolve()
    manifest = load_evidence_manifest(root, strict=strict_manifest)

    observations: list[EvidenceObservation] = []
    failures: list[EvidenceParseFailure] = []
    unsupported: list[UnsupportedEvidence] = []
    warnings: list[str] = []
    parsed_files = 0

    for entry in manifest.entries:
        if not entry.is_supported:
            unsupported.append(
                UnsupportedEvidence(
                    file_id=entry.file_id,
                    file_path=entry.file_path,
                    format=entry.format,
                    reason=entry.unsupported_reason or "Unsupported format",
                )
            )
            continue

        if not entry.resolved_path.is_file():
            failures.append(
                EvidenceParseFailure(
                    file_id=entry.file_id,
                    file_path=entry.file_path,
                    format=entry.format,
                    error_type="MissingFile",
                    reason="Evidence file is missing",
                )
            )
            continue

        parser = parser_for(entry.format)
        if parser is None:
            unsupported.append(
                UnsupportedEvidence(
                    file_id=entry.file_id,
                    file_path=entry.file_path,
                    format=entry.format,
                    reason="No parser registered for this format",
                )
            )
            continue

        try:
            outcome = parser.parse(entry, root)
        except EvidenceParseError as exc:
            failures.append(
                EvidenceParseFailure(
                    file_id=entry.file_id,
                    file_path=entry.file_path,
                    format=entry.format,
                    error_type=type(exc).__name__,
                    reason=str(exc),
                )
            )
            continue
        except Exception as exc:  # noqa: BLE001 - report, never crash the build
            failures.append(
                EvidenceParseFailure(
                    file_id=entry.file_id,
                    file_path=entry.file_path,
                    format=entry.format,
                    error_type=type(exc).__name__,
                    reason=str(exc),
                )
            )
            continue

        if not outcome.recognized:
            failures.append(
                EvidenceParseFailure(
                    file_id=entry.file_id,
                    file_path=entry.file_path,
                    format=entry.format,
                    error_type="UnrecognizedStructure",
                    reason="; ".join(outcome.warnings) or "Unrecognized file structure",
                )
            )
            continue

        parsed_files += 1
        observations.extend(outcome.observations)
        if not outcome.observations:
            warnings.append(
                f"{entry.file_id}: parsed successfully but produced no observations"
            )
        for warning in outcome.warnings:
            warnings.append(f"{entry.file_id}: {warning}")

    ordered = tuple(
        sorted(
            observations,
            key=lambda observation: (
                observation.captured_at,
                observation.file_id,
                observation.observation_id,
            ),
        )
    )

    files_by_format = Counter(entry.format.value for entry in manifest.entries)
    observations_by_format = Counter(observation.format.value for observation in ordered)
    by_system = Counter(observation.system_id or "UNKNOWN" for observation in ordered)
    by_category = Counter(observation.data_category or "UNKNOWN" for observation in ordered)
    by_state = Counter(observation.observed_state.value for observation in ordered)

    inventory = EvidenceInventory(
        dataset=str(root),
        manifest_path=str(manifest.manifest_path),
        total_entries=len(manifest.entries),
        supported_entries=sum(1 for entry in manifest.entries if entry.is_supported),
        unsupported_entries=len(unsupported),
        parsed_files=parsed_files,
        failed_files=len(failures),
        observation_count=len(ordered),
        files_by_format=dict(sorted(files_by_format.items())),
        observations_by_format=dict(sorted(observations_by_format.items())),
        observations_by_system=dict(sorted(by_system.items())),
        observations_by_category=dict(sorted(by_category.items())),
        observations_by_state=dict(sorted(by_state.items())),
        parse_warnings=len(warnings),
        failures=tuple(failures),
        unsupported=tuple(unsupported),
        manifest_issues=manifest.issues,
    )

    return EvidenceBuildResult(
        dataset_dir=root,
        manifest=manifest,
        observations=ordered,
        inventory=inventory,
        warnings=tuple(warnings),
    )
