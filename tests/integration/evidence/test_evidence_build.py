"""Integration tests for evidence parsing, inventory and provenance."""

from __future__ import annotations

from collections import Counter

from privacyguard.evidence.models import EvidenceFormat, ObservedState


def test_inventory_counts(evidence_build) -> None:
    inventory = evidence_build.inventory
    assert inventory.total_entries == 94
    assert inventory.supported_entries == 94
    assert inventory.unsupported_entries == 0
    assert inventory.parsed_files == 94
    assert inventory.failed_files == 0
    assert inventory.observation_count == 3499
    assert inventory.files_by_format == {
        "json": 28,
        "log": 26,
        "pdf": 4,
        "png": 11,
        "sql": 24,
        "txt": 1,
    }
    assert inventory.observations_by_format == {
        "json": 890,
        "log": 1647,
        "pdf": 9,
        "png": 21,
        "sql": 891,
        "txt": 41,
    }
    assert inventory.parse_warnings == 17


def test_multimodal_formats_are_supported(evidence_build) -> None:
    assert evidence_build.inventory.unsupported == ()
    formats = {
        observation.format for observation in evidence_build.observations
    }
    assert EvidenceFormat.PDF in formats
    assert EvidenceFormat.PNG in formats


def test_no_parse_failures(evidence_build) -> None:
    assert evidence_build.inventory.failures == ()


def test_every_observation_has_provenance(evidence_build) -> None:
    for observation in evidence_build.observations:
        assert observation.observation_id
        assert observation.file_id
        assert observation.file_path
        assert observation.captured_at.tzinfo is not None
        assert observation.provenance.file_id == observation.file_id
        assert observation.provenance.file_path == observation.file_path
        assert observation.provenance.captured_at == observation.captured_at
        assert observation.provenance.source_format == observation.format
        assert observation.provenance.location is not None
        assert 0.0 <= observation.confidence <= 1.0


def test_observation_ids_are_unique(evidence_build) -> None:
    ids = [observation.observation_id for observation in evidence_build.observations]
    assert len(ids) == len(set(ids))


def test_provenance_locations_cover_all_formats(evidence_build) -> None:
    formats = {observation.format for observation in evidence_build.observations}
    assert formats == {
        EvidenceFormat.SQL,
        EvidenceFormat.JSON,
        EvidenceFormat.LOG,
        EvidenceFormat.TXT,
        EvidenceFormat.PDF,
        EvidenceFormat.PNG,
    }
    for observation in evidence_build.observations:
        location = observation.provenance.location
        if observation.format == EvidenceFormat.SQL:
            assert location.table is not None
            assert location.row_number is not None
        elif observation.format == EvidenceFormat.JSON:
            assert location.json_path is not None
        elif observation.format == EvidenceFormat.LOG:
            assert location.line_number is not None
        elif observation.format == EvidenceFormat.TXT:
            assert location.line_number is not None
        elif observation.format == EvidenceFormat.PDF:
            assert location.page_number is not None
        elif observation.format == EvidenceFormat.PNG:
            assert observation.provenance.extraction_method == "windows_ocr"
            assert location.region is not None


def test_known_format_samples(evidence_build) -> None:
    by_file = {}
    for observation in evidence_build.observations:
        by_file.setdefault(observation.file_id, []).append(observation)

    sql_inventory = by_file["evidence_63"]
    assert any(
        observation.data_category == "USER_PROFILE" for observation in sql_inventory
    )
    sql_json = by_file["evidence_05"]
    assert any(observation.record is not None for observation in sql_json)
    sql_flat = by_file["evidence_54"]
    assert any(observation.resource_id == "account_005" for observation in sql_flat)

    json_bundle = by_file["evidence_02"]
    assert any(
        observation.system_id == "account_service" for observation in json_bundle
    )
    json_export = by_file["evidence_92"]
    assert any(
        observation.observed_state == ObservedState.ABSENT
        for observation in json_export
    )
    json_records = by_file["evidence_59"]
    assert any(
        observation.data_category == "customer_export_jobs"
        for observation in json_records
    )

    log_logfmt = by_file["evidence_01"]
    assert any(observation.emails for observation in log_logfmt)
    log_jsonl = by_file["evidence_06"]
    assert any(observation.attributes.get("_style") == "jsonl" for observation in log_jsonl)
    log_pipe = by_file["evidence_21"]
    assert any(observation.attributes.get("_style") == "pipe" for observation in log_pipe)
    log_message = by_file["evidence_53"]
    assert any(observation.resource_id for observation in log_message)

    txt = by_file["evidence_03"]
    assert len(txt) == 41
    assert any(observation.observed_state == ObservedState.ABSENT for observation in txt)

    pdf_attachment = by_file["evidence_58"]
    assert any(
        observation.resource_id == "support_001"
        and observation.data_category == "SUPPORT_ATTACHMENT"
        for observation in pdf_attachment
    )
    assert {observation.provenance.location.page_number for observation in pdf_attachment} == {1}
    legal_pages = {
        observation.provenance.location.page_number for observation in by_file["evidence_27"]
    }
    assert legal_pages == {2}
    png_account = by_file["evidence_04"]
    assert any(
        observation.resource_id == "account_5762"
        and observation.provenance.extraction_method == "windows_ocr"
        for observation in png_account
    )


def test_zero_observation_file_is_reported(evidence_build) -> None:
    counts = Counter(observation.file_id for observation in evidence_build.observations)
    assert "evidence_90" not in counts
    assert any(
        "evidence_90" in warning and "no observations" in warning
        for warning in evidence_build.warnings
    )


def test_manifest_paths_stay_inside_dataset(evidence_build) -> None:
    root = evidence_build.dataset_dir.resolve()
    for entry in evidence_build.manifest.entries:
        assert entry.resolved_path.resolve().is_relative_to(root)


def test_observed_states_are_known(evidence_build) -> None:
    allowed = set(ObservedState)
    assert all(observation.observed_state in allowed for observation in evidence_build.observations)
