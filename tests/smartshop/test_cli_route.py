from __future__ import annotations

from privacyguard.decision.models import DeletionStatus
from privacyguard.planning.models import AuditStep, Operation, Phase
from privacyguard.policy.models import PolicyEvaluation
from privacyguard.decision.models import AuditResult
from privacyguard.intent.models import IntentStatus, RequestIntent


def _fake_result(request_id):
    return AuditResult(
        case_id=request_id,
        deletion_status=DeletionStatus.COMPLETE,
        steps=(),
        intent=RequestIntent(
            case_id=request_id,
            status=IntentStatus.DELETION_AUTHORIZED,
            authorizes_deletion=True,
            confidence=1.0,
            method="test",
        ),
        policy=PolicyEvaluation(case_id=request_id),
        status_reasons=("ok",),
    )


def test_audit_smartshop_cli_route_uses_smartshop_handler(monkeypatch) -> None:
    import privacyguard.cli as cli
    import privacyguard.smartshop.audit as audit_mod

    monkeypatch.setattr(audit_mod, "audit_smartshop_request", lambda request_id, rules_path: _fake_result(request_id))

    code = cli.main(["audit-smartshop", "--request-id", "REQ-0001"])
    assert code == 0
