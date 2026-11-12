"""End-to-end audit pipeline."""

from __future__ import annotations

from pathlib import Path

from ..activity.index import ActivityIndex
from ..context.service import AuditContextService
from ..decision.engine import AuditDecisionEngine
from ..decision.models import AuditResult
from ..evaluation.metrics import EvaluationReport, evaluate_results
from ..evidence.manifest import load_evidence_manifest
from ..output.validator import ValidationReport, validate_output_file
from ..output.writer import write_output
from ..planning.planner import StepPlanner
from ..policy.engine import PolicyEngine
from ..policy.rules import PolicyRuleSet, load_policy_rules


class AuditPipeline:
    def __init__(self, dataset_dir: str | Path) -> None:
        self.dataset_dir = Path(dataset_dir).expanduser().resolve()
        self.context_service = AuditContextService(self.dataset_dir)
        self.rules: PolicyRuleSet = load_policy_rules(
            self.dataset_dir / "deletion_rules.csv"
        )
        self.policy_engine = PolicyEngine(self.rules)
        self.planner = StepPlanner()
        self.decision_engine = AuditDecisionEngine(self.policy_engine, self.planner)
        self.activity_index = ActivityIndex(self.context_service.bundle.system_activity)
        manifest = load_evidence_manifest(self.dataset_dir)
        self.known_evidence_ids = {
            entry.file_id for entry in manifest.entries
        } | {
            event.activity_id for event in self.activity_index.activities
        } | {
            event.audit_id for event in self.context_service.bundle.audit_events.records
        }

    def audit_case(self, case_id: str) -> AuditResult:
        context = self.context_service.build_context(case_id)
        return self.decision_engine.audit(context)

    def audit_requests(self, choice: str) -> tuple[AuditResult, ...]:
        case_ids = self.case_ids(choice)
        return tuple(self.audit_case(case_id) for case_id in case_ids)

    def case_ids(self, choice: str) -> tuple[str, ...]:
        if choice == "sample":
            source = self.context_service.bundle.sample_requests
        elif choice == "eval":
            source = self.context_service.bundle.eval_requests
        else:
            raise ValueError(f"Unknown request choice: {choice}")
        return tuple(row.record.case_id for row in source.rows)

    def write_results(
        self,
        results: tuple[AuditResult, ...] | list[AuditResult],
        target: str | Path,
    ) -> Path:
        return write_output(results, target)

    def validate_output(
        self,
        target: str | Path,
        *,
        choice: str,
    ) -> ValidationReport:
        return validate_output_file(
            target,
            expected_case_ids=set(self.case_ids(choice)),
            known_evidence_ids=self.known_evidence_ids,
        )

    def evaluate_sample(
        self,
        results: tuple[AuditResult, ...] | list[AuditResult] | None = None,
    ) -> EvaluationReport:
        if results is None:
            results = self.audit_requests("sample")
        return evaluate_results(results, self.dataset_dir / "sample_output.csv")
