"""PDF evidence parser using local, text-layer extraction."""

from __future__ import annotations

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
    category_from_pdf_title,
    extract_observation_timestamp,
    extract_text_identifiers,
    extract_retain_until,
    normalize_inline,
    system_from_origin,
)
from .base import ObservationBuilder, ParseOutcome


class PdfEvidenceParser:
    format = EvidenceFormat.PDF

    def parse(self, entry: EvidenceManifestEntry, dataset_dir: Path) -> ParseOutcome:
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise EvidenceParseError(
                "pypdf is not installed; PDF evidence cannot be extracted"
            ) from exc

        try:
            reader = PdfReader(str(entry.resolved_path))
        except Exception as exc:  # noqa: BLE001 - report as a parse failure
            raise EvidenceParseError(f"Cannot open PDF {entry.file_path}: {exc}") from exc

        if getattr(reader, "is_encrypted", False):
            try:
                reader.decrypt("")
            except Exception as exc:  # noqa: BLE001
                raise EvidenceParseError(
                    f"Encrypted PDF cannot be read: {entry.file_path}"
                ) from exc

        pages: list[tuple[int, str, int]] = []
        warnings: list[str] = []
        for page_number, page in enumerate(reader.pages, start=1):
            try:
                text = page.extract_text() or ""
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"Page {page_number}: text extraction failed ({exc})")
                text = ""
            try:
                image_count = len(page.images)
            except Exception:  # noqa: BLE001
                image_count = 0
            if image_count:
                warnings.append(
                    f"Page {page_number} contains {image_count} embedded image(s); "
                    "they were not OCRed in this pass"
                )
            if not text.strip():
                warnings.append(f"Page {page_number}: no extractable text layer")
            pages.append((page_number, text, image_count))

        full_text = "\n".join(text for _, text, _ in pages)
        if not full_text.strip():
            return ParseOutcome(
                observations=(),
                warnings=tuple(
                    [*warnings, "PDF has no extractable text; OCR would be required"]
                ),
                recognized=False,
            )

        metadata = reader.metadata or {}
        title = str(metadata.get("/Title") or "").strip()
        if not title:
            title = next(
                (line.strip() for line in full_text.splitlines() if line.strip()),
                entry.resolved_path.stem,
            )
        category, category_warnings = category_from_pdf_title(title, entry.origin)
        warnings.extend(category_warnings)
        system_id = system_from_origin(entry.origin) or entry.origin
        buckets, resources, orders, files = extract_text_identifiers(full_text)
        observed_at = extract_observation_timestamp(full_text)

        builder = ObservationBuilder(entry, self.format)
        observations: list[EvidenceObservation] = []

        row_observations = self._legal_hold_rows(
            builder, pages, title, category, system_id, observed_at, warnings
        )
        observations.extend(row_observations)

        if not observations:
            observations.extend(
                self._document_observations(
                    builder,
                    pages,
                    title,
                    category,
                    system_id,
                    observed_at,
                    buckets,
                    resources,
                    orders,
                    files,
                    warnings,
                )
            )

        if not observations:
            warnings.append("No resource or document reference could be extracted")
        elif not any(observation.resource_id for observation in observations):
            warnings.append("No standard resource ID was visible in the PDF")

        confidence = 0.95 if not any("no extractable text" in item for item in warnings) else 0.9
        # Rebuild observations with the final confidence/warnings context is unnecessary;
        # each observation already carries its own source-level confidence.
        return ParseOutcome(
            observations=tuple(observations),
            warnings=tuple(dict.fromkeys(warnings)),
            recognized=True,
            metadata={
                "pages": str(len(pages)),
                "title": title,
                "extraction": "pypdf_text",
            },
        )

    def _legal_hold_rows(
        self,
        builder: ObservationBuilder,
        pages: list[tuple[int, str, int]],
        title: str,
        category: str | None,
        system_id: str,
        observed_at,
        warnings: list[str],
    ) -> list[EvidenceObservation]:
        if category != "LEGAL_HOLD_RECORD":
            return []
        observations: list[EvidenceObservation] = []
        for page_number, text, _ in pages:
            for line in text.splitlines():
                if "ORD-" not in line or "user_" not in line:
                    continue
                fields = [field.strip() for field in line.split("|")]
                if len(fields) < 4:
                    continue
                order_id = fields[0]
                user_id = fields[1]
                buckets, _, _, _ = extract_text_identifiers(line)
                buckets.add_user_id(user_id)
                retain_raw = fields[5] if len(fields) > 5 else None
                retain_until = extract_retain_until(retain_raw or "")
                attributes = {
                    "document_title": title,
                    "order_id": order_id,
                    "user_reference": user_id,
                    "category_label": fields[2] if len(fields) > 2 else None,
                    "date": fields[3] if len(fields) > 3 else None,
                    "amount": fields[4] if len(fields) > 4 else None,
                    "retain_until": retain_until.isoformat() if retain_until else None,
                    "retain_until_raw": retain_raw,
                    "hold_active_at_capture": (
                        observed_at <= retain_until
                        if observed_at is not None and retain_until is not None
                        else None
                    ),
                    "case_code": fields[6] if len(fields) > 6 else None,
                }
                observations.append(
                    builder.build(
                        system_id=system_id,
                        resource_id=order_id,
                        data_category="LEGAL_HOLD_RECORD",
                        observed_state=ObservedState.PRESENT,
                        state_field="retention_register_row",
                        identifiers=buckets,
                        related_resource_ids=(),
                        record=attributes,
                        attributes=attributes,
                        location=EvidenceLocation(
                            page_number=page_number,
                            raw_excerpt=excerpt(line),
                        ),
                        observed_at=observed_at,
                        confidence=0.95,
                        extraction_method="pypdf_text",
                        warnings=(),
                    )
                )
        if observations:
            warnings.append(
                f"Extracted {len(observations)} legal-hold row(s) from the retention register"
            )
        return observations

    def _document_observations(
        self,
        builder: ObservationBuilder,
        pages: list[tuple[int, str, int]],
        title: str,
        category: str | None,
        system_id: str,
        observed_at,
        buckets,
        resources: tuple[str, ...],
        orders: tuple[str, ...],
        files: tuple[str, ...],
        warnings: list[str],
    ) -> list[EvidenceObservation]:
        page_by_resource: dict[str, int] = {}
        for page_number, text, _ in pages:
            for reference in (*resources, *orders, *files):
                if reference in text and reference not in page_by_resource:
                    page_by_resource[reference] = page_number

        primary_resources = resources
        if not primary_resources:
            primary_resources = orders[:1] or files[:1] or ((),)
        if isinstance(primary_resources, tuple) and len(primary_resources) == 1 and primary_resources[0] == ():
            primary_resources = ()

        observations: list[EvidenceObservation] = []
        if primary_resources:
            for resource in primary_resources:
                page_number = page_by_resource.get(resource)
                page_text = next(
                    (text for number, text, _ in pages if number == page_number),
                    "\n".join(text for _, text, _ in pages),
                )
                observations.append(
                    builder.build(
                        system_id=system_id,
                        resource_id=resource,
                        data_category=category,
                        observed_state=ObservedState.PRESENT,
                        state_field="document_record_visible",
                        identifiers=buckets,
                        related_resource_ids=tuple(
                            [*orders, *files]
                        ),
                        record={"document_title": title, "page_text": page_text},
                        attributes={
                            "document_title": title,
                            "page_number": page_number,
                            "resource_references": list(resources),
                            "order_references": list(orders),
                            "file_references": list(files),
                        },
                        location=EvidenceLocation(
                            page_number=page_number,
                            raw_excerpt=excerpt(page_text),
                        ),
                        observed_at=observed_at,
                        confidence=0.95,
                        extraction_method="pypdf_text",
                        warnings=(),
                    )
                )
        else:
            warnings.append("No resource, order, or file reference was found in the PDF")
            page_number, page_text, _ = pages[0]
            observations.append(
                builder.build(
                    system_id=system_id,
                    resource_id=None,
                    data_category=category,
                    observed_state=ObservedState.UNKNOWN,
                    state_field=None,
                    identifiers=buckets,
                    related_resource_ids=tuple([*orders, *files]),
                    record={"document_title": title, "page_text": page_text},
                    attributes={"document_title": title, "page_number": page_number},
                    location=EvidenceLocation(
                        page_number=page_number,
                        raw_excerpt=excerpt(page_text),
                    ),
                    observed_at=observed_at,
                    confidence=0.8,
                    extraction_method="pypdf_text",
                    warnings=("No resource ID was visible",),
                )
            )
        if category is None:
            warnings.append("PDF category is unknown; policy action will remain unresolved")
        return observations
