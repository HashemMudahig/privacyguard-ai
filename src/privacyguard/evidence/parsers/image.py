"""PNG evidence parser using local Windows OCR.

The parser is deliberately conservative: OCR text is low-confidence data, not a
confirmed identity match. The ResourceLinker requires corroboration from text
evidence or activity before it will use an OCR-derived resource relationship.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..errors import EvidenceParseError
from ..identifiers import excerpt
from ..models import (
    EvidenceFormat,
    EvidenceLocation,
    EvidenceManifestEntry,
    EvidenceObservation,
    ObservedState,
)
from ..multimodal import (
    category_from_image,
    extract_observation_timestamp,
    extract_text_identifiers,
    image_state,
    normalize_ocr_spacing,
    system_from_origin,
)
from ..ocr import OcrError, OcrLine, OcrResult, OcrUnavailableError, WindowsOcrEngine
from .base import ObservationBuilder, ParseOutcome

_EXPECTED_PREFIX = {
    "account_admin_portal": "account_",
    "search_index_admin": "search_",
    "integration_admin": "data_flow_",
    "analytics_platform": "analytics_",
    "export_service": "export_",
    "support_platform": "support_",
    "backup_service": "backup_",
    "security_service": "audit_record_",
    "identity_service": "tombstone_",
    "object_storage": "object_",
    "marketing_platform": "marketing_",
}


@dataclass(frozen=True, slots=True)
class _Row:
    text: str
    bounds: tuple[int, int, int, int] | None
    lines: tuple[OcrLine, ...]


class ImageEvidenceParser:
    format = EvidenceFormat.PNG

    def __init__(self, ocr_engine=None) -> None:
        self.ocr_engine = ocr_engine or WindowsOcrEngine()

    def parse(self, entry: EvidenceManifestEntry, dataset_dir: Path) -> ParseOutcome:
        try:
            from PIL import Image
        except ImportError as exc:
            raise EvidenceParseError(
                "Pillow is not installed; image evidence cannot be read"
            ) from exc

        try:
            with Image.open(entry.resolved_path) as image:
                width, height = image.size
                image_format = image.format or "PNG"
        except Exception as exc:  # noqa: BLE001
            raise EvidenceParseError(
                f"Cannot open image {entry.file_path}: {exc}"
            ) from exc

        try:
            ocr_result = self.ocr_engine.extract(entry.resolved_path)
        except OcrUnavailableError as exc:
            return ParseOutcome(
                observations=(),
                warnings=(f"Local OCR unavailable: {exc}",),
                recognized=False,
                metadata={"image_width": str(width), "image_height": str(height), "format": image_format},
            )
        except OcrError as exc:
            return ParseOutcome(
                observations=(),
                warnings=(f"OCR extraction failed: {exc}",),
                recognized=False,
                metadata={"image_width": str(width), "image_height": str(height), "format": image_format},
            )

        if not ocr_result.lines:
            return ParseOutcome(
                observations=(),
                warnings=("OCR returned no readable text",),
                recognized=False,
                metadata={"image_width": str(width), "image_height": str(height), "format": image_format},
            )

        text = normalize_ocr_spacing(ocr_result.text)
        category, category_warnings = category_from_image(entry.origin, text)
        system_id = system_from_origin(entry.origin) or entry.origin
        expected_prefix = _EXPECTED_PREFIX.get(entry.origin.strip().lower())
        global_buckets, global_resources, orders, files = extract_text_identifiers(text)
        global_observed_at = extract_observation_timestamp(text)
        rows = _group_rows(ocr_result)

        row_data: list[tuple[_Row, list[str], object, tuple[str, ...], tuple[str, ...]]] = []
        all_primary: list[str] = []
        for row in rows:
            row_text = normalize_ocr_spacing(row.text)
            row_buckets, row_resources, row_orders, row_files = extract_text_identifiers(row_text)
            if expected_prefix:
                primary = [resource for resource in row_resources if resource.startswith(expected_prefix)]
            else:
                primary = list(row_resources)
            if primary:
                row_data.append((row, primary, row_buckets, row_orders, row_files))
                all_primary.extend(primary)
        unique_primary = tuple(dict.fromkeys(all_primary))

        selected: dict[str, tuple[_Row, object, tuple[str, ...], tuple[str, ...], int]] = {}
        for row, primary_resources, row_buckets, row_orders, row_files in row_data:
            buckets = row_buckets
            distinct_emails = {email.lower() for email in global_buckets.emails}
            distinct_users = set(global_buckets.user_ids)
            if (
                not (
                    buckets.user_ids
                    or buckets.emails
                    or buckets.phones
                    or buckets.email_hashes
                )
                and len(unique_primary) == 1
                and len(distinct_emails) <= 1
                and len(distinct_users) <= 1
            ):
                buckets = global_buckets
            score = len(buckets.user_ids) + len(buckets.emails) + len(buckets.phones) + len(buckets.email_hashes)
            for resource_id in primary_resources:
                previous = selected.get(resource_id)
                if previous is None or score > previous[4]:
                    selected[resource_id] = (row, buckets, row_orders, row_files, score)

        builder = ObservationBuilder(entry, self.format)
        observations: list[EvidenceObservation] = []
        warnings: list[str] = list(category_warnings)
        warnings.append(
            "OCR extraction is low-confidence; identifiers and resource links require corroboration"
        )

        for resource_id, (row, buckets, row_orders, row_files, _score) in selected.items():
            row_text = normalize_ocr_spacing(row.text)
            has_direct = bool(buckets.emails or buckets.phones or buckets.email_hashes)
            has_user = bool(buckets.user_ids)
            observed_state, state_field, state_warnings = image_state(
                row_text,
                category,
                has_direct_identifiers=has_direct,
                has_user_id=has_user,
            )
            if observed_state == ObservedState.UNKNOWN:
                global_state, global_field, global_warnings = image_state(
                    text,
                    category,
                    has_direct_identifiers=has_direct,
                    has_user_id=has_user,
                )
                if global_state != ObservedState.UNKNOWN:
                    observed_state = global_state
                    state_field = global_field
                    state_warnings = (*state_warnings, *global_warnings)
            row_observed_at = extract_observation_timestamp(row_text) or global_observed_at
            observations.append(
                builder.build(
                    system_id=system_id,
                    resource_id=resource_id,
                    data_category=category,
                    observed_state=observed_state,
                    state_field=state_field,
                    identifiers=buckets,
                    related_resource_ids=tuple([*row_orders, *row_files]),
                    record={
                        "ocr_text": row_text,
                        "image_dimensions": [width, height],
                        "visible_files": list(row_files),
                        "origin": entry.origin,
                    },
                    attributes={
                        "origin": entry.origin,
                        "image_width": width,
                        "image_height": height,
                        "ocr_line_count": len(row.lines),
                        "visible_files": list(row_files),
                    },
                    location=EvidenceLocation(
                        region=(
                            {
                                "x": row.bounds[0],
                                "y": row.bounds[1],
                                "width": row.bounds[2],
                                "height": row.bounds[3],
                            }
                            if row.bounds
                            else None
                        ),
                        raw_excerpt=excerpt(row_text),
                    ),
                    observed_at=row_observed_at,
                    confidence=0.6,
                    warnings=tuple(
                        [
                            *state_warnings,
                            "Low-confidence OCR observation",
                            *(["Multiple primary resource IDs were merged or appeared in one OCR row"] if len(selected) > 1 else []),
                        ]
                    ),
                    extraction_method="windows_ocr",
                    image_width=width,
                    image_height=height,
                )
            )

        if not observations:
            observed_state, state_field, state_warnings = image_state(
                text,
                category,
                has_direct_identifiers=bool(
                    global_buckets.emails
                    or global_buckets.phones
                    or global_buckets.email_hashes
                ),
                has_user_id=bool(global_buckets.user_ids),
            )
            warnings.extend(state_warnings)
            warnings.append("No primary resource ID was visible in the screenshot")
            observations.append(
                builder.build(
                    system_id=system_id,
                    resource_id=None,
                    data_category=category,
                    observed_state=observed_state,
                    state_field=state_field,
                    identifiers=global_buckets,
                    related_resource_ids=tuple([*orders, *files]),
                    record={
                        "ocr_text": text,
                        "image_dimensions": [width, height],
                        "visible_files": list(files),
                        "origin": entry.origin,
                    },
                    attributes={
                        "origin": entry.origin,
                        "image_width": width,
                        "image_height": height,
                        "ocr_line_count": len(ocr_result.lines),
                        "visible_files": list(files),
                    },
                    location=EvidenceLocation(
                        region={"x": 0, "y": 0, "width": width, "height": height},
                        raw_excerpt=excerpt(text),
                    ),
                    observed_at=global_observed_at,
                    confidence=0.45,
                    warnings=(
                        "No primary resource ID visible; identity-only OCR observation",
                        "Low-confidence OCR observation",
                    ),
                    extraction_method="windows_ocr",
                    image_width=width,
                    image_height=height,
                )
            )

        if category is None:
            warnings.append("Image category is unknown; policy action will remain unresolved")
        return ParseOutcome(
            observations=tuple(observations),
            warnings=tuple(dict.fromkeys(warnings)),
            recognized=True,
            metadata={
                "image_width": str(width),
                "image_height": str(height),
                "format": image_format,
                "extraction": "windows_ocr",
            },
        )


def _group_rows(result: OcrResult) -> tuple[_Row, ...]:
    if not result.lines:
        return ()
    line_bounds = [
        (line, line.bounds or (0, 0, result.width, result.height))
        for line in result.lines
    ]
    tolerance = max(8, int(result.height * 0.012))
    groups: list[list[tuple[OcrLine, tuple[int, int, int, int]]]] = []
    current: list[tuple[OcrLine, tuple[int, int, int, int]]] = []
    last_center: float | None = None
    for line, bounds in sorted(line_bounds, key=lambda item: item[1][1] + item[1][3] / 2):
        center = bounds[1] + bounds[3] / 2
        if current and last_center is not None and center - last_center > tolerance:
            groups.append(current)
            current = []
        current.append((line, bounds))
        last_center = center
    if current:
        groups.append(current)

    rows: list[_Row] = []
    for group in groups:
        group.sort(key=lambda item: item[1][0])
        text = " ".join(line.text for line, _ in group)
        x = min(bounds[0] for _, bounds in group)
        y = min(bounds[1] for _, bounds in group)
        right = max(bounds[0] + bounds[2] for _, bounds in group)
        bottom = max(bounds[1] + bounds[3] for _, bounds in group)
        rows.append(
            _Row(
                text=text,
                bounds=(x, y, right - x, bottom - y),
                lines=tuple(line for line, _ in group),
            )
        )
    return tuple(rows)
