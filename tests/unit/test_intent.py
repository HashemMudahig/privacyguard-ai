"""Unit tests for deterministic request-intent classification."""

from __future__ import annotations

import pandas as pd

from privacyguard.intent.classifier import classify_intent
from privacyguard.intent.models import IntentStatus


def test_english_deletion_request() -> None:
    intent = classify_intent("case_x", "Please permanently delete my account and all personal data.")
    assert intent.status == IntentStatus.DELETION_AUTHORIZED
    assert intent.authorizes_deletion is True


def test_multilingual_deletion_requests() -> None:
    samples = [
        "Solicito la eliminación permanente de la cuenta asociada a este correo.",
        "Solicito a exclusão permanente da conta associada a este e-mail.",
        "Je demande la suppression définitive du compte associé à cette adresse.",
        "このメールアドレスに関連するアカウントの完全な削除を依頼します。",
        "이 이메일 주소에 연결된 계정의 영구 삭제를 요청합니다.",
    ]
    for text in samples:
        assert classify_intent("case_x", text).status == IntentStatus.DELETION_AUTHORIZED


def test_non_deletion_access_request() -> None:
    intent = classify_intent(
        "case_x",
        "Could you send me a copy of the information held on my account? "
        "I still use it, so please don't delete or change anything.",
    )
    assert intent.status == IntentStatus.NOT_APPLICABLE
    assert intent.authorizes_deletion is False


def test_marketing_opt_out_is_not_deletion() -> None:
    intent = classify_intent(
        "case_x",
        "Please remove me from marketing lists only. I still want receipts and service messages.",
    )
    assert intent.status == IntentStatus.NOT_APPLICABLE


def test_correction_and_login_requests_are_not_deletion() -> None:
    for text in (
        "My surname is misspelled on the account. Can you correct it?",
        "I can't access my profile and need help resetting the login.",
        "Please change the email address used for this account.",
    ):
        assert classify_intent("case_x", text).status == IntentStatus.NOT_APPLICABLE


def test_ambiguous_request_is_isolated() -> None:
    intent = classify_intent("case_x", "Please review my account records.")
    assert intent.status == IntentStatus.UNCERTAIN
    assert intent.authorizes_deletion is True


def test_sample_requests_are_all_deletion(settings) -> None:
    sample = pd.read_csv(settings.dataset_dir / "sample_deletion_requests.csv")
    statuses = {
        classify_intent(row.case_id, row.request_text).status
        for row in sample.itertuples()
    }
    assert statuses == {IntentStatus.DELETION_AUTHORIZED}


def test_evaluation_non_deletion_count(settings) -> None:
    requests = pd.read_csv(settings.dataset_dir / "deletion_requests.csv")
    statuses = [
        classify_intent(row.case_id, row.request_text).status for row in requests.itertuples()
    ]
    assert statuses.count(IntentStatus.NOT_APPLICABLE) == 10
    assert statuses.count(IntentStatus.UNCERTAIN) == 0
