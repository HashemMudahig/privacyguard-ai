"""Deterministic multilingual request-intent classification.

The classifier is intentionally conservative: strong non-deletion signals win
over weak deletion words, while explicit deletion language authorizes a deletion
audit. Ambiguous requests are marked ``UNCERTAIN`` and can be routed to an
optional AI classifier later.
"""

from __future__ import annotations

import unicodedata

from .models import IntentStatus, RequestIntent

# Strong non-deletion intents. These override deletion words such as "erase"
# in a sentence like "this is not a request to erase it".
_NON_DELETION_STRONG: tuple[tuple[str, float], ...] = (
    ("not asking for deletion", 1.0),
    ("not a request for deletion", 1.0),
    ("not a request to erase", 1.0),
    ("not a deletion request", 1.0),
    ("do not delete", 1.0),
    ("don't delete", 1.0),
    ("do not close", 1.0),
    ("don't close", 1.0),
    ("please don't delete or change anything", 1.0),
    ("without removing", 0.9),
    ("leave the account active", 0.95),
    ("leave my profile", 0.95),
    ("leave my account", 0.95),
    ("keep the account", 0.9),
    ("keep my account", 0.9),
    ("purchase history in place", 0.9),
    ("marketing lists only", 1.0),
    ("stop the promotional emails", 0.95),
    ("stop promotional emails", 0.95),
    ("unsubscribe", 0.9),
    ("opt out", 0.9),
    ("download my account information", 0.95),
    ("download my data", 0.9),
    ("portable format", 0.85),
    ("copy of the information", 0.95),
    ("copy of last year's invoices", 0.95),
    ("information held", 0.9),
    ("what personal information", 0.9),
    ("information request", 0.9),
    ("access my profile", 0.9),
    ("can't access", 0.9),
    ("cannot access", 0.9),
    ("resetting the login", 0.95),
    ("reset the login", 0.95),
    ("reset my password", 0.9),
    ("misspelled", 0.9),
    ("change the email", 0.95),
    ("change my email", 0.95),
    ("update my email", 0.9),
    ("still want", 0.85),
    ("still need", 0.85),
    ("still use", 0.8),
    ("no destructive action", 0.95),
    ("no eliminar", 0.95),
    ("no borrar", 0.95),
    ("mantener la cuenta", 0.9),
    ("não excluir", 0.95),
    ("não apagar", 0.95),
    ("manter a conta", 0.9),
    ("ne pas supprimer", 0.95),
    ("ne supprimez pas", 0.95),
    ("conserver le compte", 0.9),
    ("nicht löschen", 0.95),
    ("behalten", 0.8),
    ("削除しないで", 1.0),
    ("アカウントを残す", 0.9),
    ("삭제하지 마세요", 1.0),
    ("계정을 유지", 0.9),
    ("لا تحذف", 1.0),
)

# Weaker access/correction/marketing signals. They classify as non-deletion
# only when no strong deletion language is present.
_NON_DELETION_WEAK: tuple[tuple[str, float], ...] = (
    ("download", 0.6),
    ("copy of", 0.7),
    ("information", 0.45),
    ("access", 0.55),
    ("correct", 0.6),
    ("correction", 0.6),
    ("change", 0.5),
    ("update", 0.45),
    ("marketing", 0.55),
    ("promotional", 0.5),
    ("reset", 0.55),
    ("login", 0.5),
    ("acceder", 0.55),
    ("acceso", 0.55),
    ("corregir", 0.6),
    ("corrección", 0.6),
    ("cambiar", 0.5),
    ("actualizar", 0.45),
    ("copia de", 0.7),
    ("información", 0.45),
    ("acessar", 0.55),
    ("acesso", 0.55),
    ("corrigir", 0.6),
    ("correção", 0.6),
    ("alterar", 0.5),
    ("atualizar", 0.45),
    ("cópia", 0.7),
    ("informações", 0.45),
    ("accéder", 0.55),
    ("accès", 0.55),
    ("corriger", 0.6),
    ("correction", 0.6),
    ("modifier", 0.5),
    ("mettre à jour", 0.45),
    ("copie", 0.7),
    ("informations", 0.45),
    ("zugriff", 0.5),
    ("auskunft", 0.55),
    ("korrigieren", 0.6),
    ("ändern", 0.5),
    ("kopie", 0.7),
    ("開示", 0.6),
    ("訂正", 0.6),
    ("変更", 0.5),
    ("コピー", 0.7),
    ("열람", 0.6),
    ("정정", 0.6),
    ("변경", 0.5),
    ("복사", 0.7),
)

# Explicit deletion language.
_DELETION_TERMS: tuple[tuple[str, float], ...] = (
    ("delete", 0.9),
    ("deleting", 0.9),
    ("deletion", 0.95),
    ("deleted", 0.75),
    ("removed", 0.75),
    ("remove", 0.7),
    ("close the account", 0.9),
    ("profile is gone", 0.8),
    ("is gone", 0.55),
    ("switch off", 0.65),
    ("erase", 0.9),
    ("erased", 0.8),
    ("erasure", 0.9),
    ("permanently delete", 1.0),
    ("permanently closed", 0.8),
    ("remove my account", 0.95),
    ("remove my data", 0.95),
    ("remove my profile", 0.9),
    ("remove the profile", 0.9),
    ("close my account", 0.95),
    ("close this account", 0.9),
    ("account deletion", 1.0),
    ("right to be forgotten", 0.95),
    ("eliminar", 0.9),
    ("eliminación", 0.95),
    ("eliminacion", 0.95),
    ("borrar", 0.85),
    ("suprimir", 0.85),
    ("cancelar mi cuenta", 0.9),
    ("excluir", 0.9),
    ("exclusão", 0.95),
    ("exclusao", 0.95),
    ("apagar", 0.85),
    ("remover", 0.8),
    ("encerrar a conta", 0.9),
    ("supprimer", 0.9),
    ("suppression", 0.95),
    ("effacer", 0.85),
    ("fermer mon compte", 0.9),
    ("löschen", 0.9),
    ("loeschen", 0.9),
    ("löschung", 0.95),
    ("削除", 0.95),
    ("消去", 0.85),
    ("退会", 0.8),
    ("삭제", 0.95),
    ("탈퇴", 0.8),
    ("حذف", 0.9),
    ("مسح", 0.8),
)


def classify_intent(case_id: str, text: str) -> RequestIntent:
    """Classify a request's intent deterministically."""
    normalized = unicodedata.normalize("NFKC", text).lower()
    normalized = " ".join(normalized.split())

    strong_matches = [
        (term, weight) for term, weight in _NON_DELETION_STRONG if term in normalized
    ]
    if strong_matches:
        return RequestIntent(
            case_id=case_id,
            status=IntentStatus.NOT_APPLICABLE,
            authorizes_deletion=False,
            confidence=min(1.0, max(weight for _, weight in strong_matches)),
            method="strong_non_deletion_phrase",
            matched_terms=tuple(term for term, _ in strong_matches),
        )

    deletion_matches = [
        (term, weight) for term, weight in _DELETION_TERMS if term in normalized
    ]
    if deletion_matches:
        return RequestIntent(
            case_id=case_id,
            status=IntentStatus.DELETION_AUTHORIZED,
            authorizes_deletion=True,
            confidence=min(1.0, max(weight for _, weight in deletion_matches)),
            method="deletion_terms",
            matched_terms=tuple(term for term, _ in deletion_matches),
        )

    weak_matches = [
        (term, weight) for term, weight in _NON_DELETION_WEAK if term in normalized
    ]
    if weak_matches:
        return RequestIntent(
            case_id=case_id,
            status=IntentStatus.NOT_APPLICABLE,
            authorizes_deletion=False,
            confidence=min(0.85, max(weight for _, weight in weak_matches)),
            method="weak_non_deletion_terms",
            matched_terms=tuple(term for term, _ in weak_matches),
            warnings=("No explicit deletion language was found",),
        )

    return RequestIntent(
        case_id=case_id,
        status=IntentStatus.UNCERTAIN,
        authorizes_deletion=True,
        confidence=0.3,
        method="uncertain",
        warnings=("Request intent is ambiguous; auditing conservatively as deletion",),
    )
