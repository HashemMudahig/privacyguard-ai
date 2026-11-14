"""Unit tests for PDF and PNG parsing with synthetic fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from privacyguard.evidence.errors import EvidenceParseError
from privacyguard.evidence.models import EvidenceFormat, EvidenceManifestEntry, ObservedState
from privacyguard.evidence.ocr import OcrLine, OcrResult, OcrUnavailableError, OcrWord
from privacyguard.evidence.parsers.image import ImageEvidenceParser
from privacyguard.evidence.multimodal import extract_observation_timestamp
from privacyguard.evidence.parsers.pdf import PdfEvidenceParser
from privacyguard.models import parse_timestamp


def make_entry(path: Path, fmt: EvidenceFormat, origin: str) -> EvidenceManifestEntry:
    return EvidenceManifestEntry(
        file_id="ev_multimodal",
        file_path=path.name,
        origin=origin,
        captured_at=parse_timestamp("2026-01-01T00:00:00Z"),
        format=fmt,
        is_supported=True,
        unsupported_reason=None,
        resolved_path=path,
    )


def line(text: str, x: int = 10, y: int = 10, width: int = 300, height: int = 16) -> OcrLine:
    words = tuple(
        OcrWord(word, x + index * 40, y, 38, height)
        for index, word in enumerate(text.split(" "))
    )
    return OcrLine(text=text, words=words)


class FakeOcr:
    def __init__(self, result: OcrResult | None = None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error

    def extract(self, image_path):
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result


def make_png(path: Path) -> None:
    from PIL import Image

    Image.new("RGB", (400, 300), "white").save(path)


def test_png_parser_extracts_resource_identifier_and_state(project_tmp_path: Path) -> None:
    image_path = project_tmp_path / "connector.png"
    make_png(image_path)
    ocr = OcrResult(
        width=400,
        height=300,
        lines=(
            line("data_flow_1121 jain.aditi@gmail.com Continuous sync"),
        ),
    )
    outcome = ImageEvidenceParser(FakeOcr(ocr)).parse(
        make_entry(image_path, EvidenceFormat.PNG, "integration_admin"),
        project_tmp_path,
    )
    assert outcome.recognized is True
    observation = next(item for item in outcome.observations if item.resource_id == "data_flow_1121")
    assert observation.data_category == "DATA_FLOW"
    assert observation.observed_state == ObservedState.ACTIVE
    assert observation.emails == ("jain.aditi@gmail.com",)
    assert observation.provenance.extraction_method == "windows_ocr"
    assert observation.provenance.image_width == 400
    assert observation.provenance.location.region is not None
    assert observation.confidence == 0.6
    assert observation.warnings


def test_png_parser_identity_only_when_no_resource_id(project_tmp_path: Path) -> None:
    image_path = project_tmp_path / "reference.png"
    make_png(image_path)
    ocr = OcrResult(
        width=400,
        height=300,
        lines=(line("user_17 Retained reference"),),
    )
    outcome = ImageEvidenceParser(FakeOcr(ocr)).parse(
        make_entry(image_path, EvidenceFormat.PNG, "identity_service"),
        project_tmp_path,
    )
    assert outcome.recognized is True
    observation = outcome.observations[0]
    assert observation.resource_id is None
    assert observation.data_category == "ACCOUNT_TOMBSTONE"
    assert observation.observed_state == ObservedState.REDACTED
    assert observation.user_ids == ("user_17",)
    assert any("No primary resource ID" in warning for warning in outcome.warnings)


def test_png_parser_reports_ocr_unavailable(project_tmp_path: Path) -> None:
    image_path = project_tmp_path / "unavailable.png"
    make_png(image_path)
    outcome = ImageEvidenceParser(
        FakeOcr(error=OcrUnavailableError("no OCR engine"))
    ).parse(
        make_entry(image_path, EvidenceFormat.PNG, "support_platform"),
        project_tmp_path,
    )
    assert outcome.recognized is False
    assert any("Local OCR unavailable" in warning for warning in outcome.warnings)


def test_png_parser_rejects_corrupted_image(project_tmp_path: Path) -> None:
    image_path = project_tmp_path / "broken.png"
    image_path.write_bytes(b"not a png")
    with pytest.raises(EvidenceParseError, match="Cannot open image"):
        ImageEvidenceParser(FakeOcr(OcrResult(400, 300, ()))).parse(
            make_entry(image_path, EvidenceFormat.PNG, "support_platform"),
            project_tmp_path,
        )


def test_pdf_parser_rejects_corrupted_pdf(project_tmp_path: Path) -> None:
    pdf_path = project_tmp_path / "broken.pdf"
    pdf_path.write_bytes(b"not a pdf")
    with pytest.raises(EvidenceParseError, match="Cannot open PDF"):
        PdfEvidenceParser().parse(
            make_entry(pdf_path, EvidenceFormat.PDF, "support_platform"),
            project_tmp_path,
        )


def test_pdf_parser_reports_blank_pdf(project_tmp_path: Path) -> None:
    from pypdf import PdfWriter

    pdf_path = project_tmp_path / "blank.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    with pdf_path.open("wb") as handle:
        writer.write(handle)
    outcome = PdfEvidenceParser().parse(
        make_entry(pdf_path, EvidenceFormat.PDF, "account_history_service"),
        project_tmp_path,
    )
    assert outcome.recognized is False
    assert any("no extractable text" in warning.lower() for warning in outcome.warnings)


def test_extract_observation_timestamp_from_human_and_iso() -> None:
    human = extract_observation_timestamp("Captured 12 Sep 2026 07 30 UTC")
    assert human is not None
    assert human.isoformat() == "2026-09-12T07:30:00+00:00"
    iso = extract_observation_timestamp("recorded_at 2026-08-25T04:03:00Z")
    assert iso is not None
    assert iso.isoformat() == "2026-08-25T04:03:00+00:00"


def test_png_duplicate_resource_rows_are_merged(project_tmp_path: Path) -> None:
    image_path = project_tmp_path / "duplicate.png"
    make_png(image_path)
    ocr = OcrResult(
        width=400,
        height=300,
        lines=(
            line("search_428", y=10),
            line("search_428 g.silva76@gmail.com user_13", y=70),
        ),
    )
    outcome = ImageEvidenceParser(FakeOcr(ocr)).parse(
        make_entry(image_path, EvidenceFormat.PNG, "search_index_admin"),
        project_tmp_path,
    )
    search = [item for item in outcome.observations if item.resource_id == "search_428"]
    assert len(search) == 1
    assert search[0].emails == ("g.silva76@gmail.com",)
