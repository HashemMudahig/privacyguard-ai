"""Command-line interface for Sprint 1 identity resolution."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Sequence

from .config import Settings
from .decision.models import DeletionStatus
from .evaluation.comparison import compare_output_files, write_comparison_json
from .evaluation.report import write_evaluation_json
from .pipeline import AuditPipeline
from .context.report import write_context_json
from .context.service import AuditContextService
from .errors import PrivacyGuardError
from .evidence.index import EvidenceIndex
from .evidence.manifest import load_evidence_manifest
from .evidence.parsers.registry import parser_for
from .evidence.report import write_inventory_json
from .evidence.service import build_evidence
from .identity.index import IdentityIndex
from .identity.report import summarize_resolutions, write_json_report
from .identity.resolver import IdentityResolver
from .io.bundle import DatasetBundle, load_dataset
from .io.types import DatasetFile
from .models import ResolutionStatus, parse_timestamp


def _add_common_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--dataset",
        default=None,
        help=(
            "Path to the read-only challenge dataset directory. "
            "Defaults to PG_DATASET_DIR or the sibling original repository."
        ),
    )
    parser.add_argument(
        "--reports-dir",
        default=None,
        help="Directory inside this project for optional reports.",
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="privacyguard",
        description="PrivacyGuard AI - Sprint 1 identity resolution foundation.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    info = subparsers.add_parser(
        "info", help="Show dataset paths, row counts and index build warnings."
    )
    _add_common_options(info)

    resolve = subparsers.add_parser(
        "resolve", help="Resolve one email, phone or email hash."
    )
    _add_common_options(resolve)
    resolve.add_argument("identifier", help="Value to resolve.")
    resolve.add_argument(
        "--kind",
        choices=("auto", "email", "phone", "email_hash"),
        default="auto",
        help="Identifier kind. 'auto' infers it deterministically.",
    )
    resolve.add_argument(
        "--json",
        action="store_true",
        help="Print the full resolution as JSON.",
    )

    audit = subparsers.add_parser(
        "audit-requests",
        help="Resolve request identities and print a summary of exceptions.",
    )
    _add_common_options(audit)
    audit.add_argument(
        "--requests",
        choices=("sample", "eval", "all"),
        default="all",
        help="Which request file to audit.",
    )
    audit.add_argument(
        "--json-out",
        default=None,
        help=(
            "Optional JSON report path. Must be inside this project directory, "
            "for example reports/identity_report_sample.json"
        ),
    )

    evidence = subparsers.add_parser(
        "evidence", help="Inspect and index evidence files."
    )
    evidence_sub = evidence.add_subparsers(dest="evidence_command", required=True)

    inventory = evidence_sub.add_parser(
        "inventory", help="Parse all evidence and report coverage."
    )
    _add_common_options(inventory)
    inventory.add_argument(
        "--json-out",
        default=None,
        help="Optional inventory JSON path inside this project.",
    )

    inspect = evidence_sub.add_parser(
        "inspect", help="Parse and inspect one evidence file."
    )
    _add_common_options(inspect)
    inspect.add_argument("--file-id", required=True, help="Manifest file_id.")
    inspect.add_argument("--limit", type=int, default=20, help="Maximum observations to show.")
    inspect.add_argument(
        "--show-identifiers",
        action="store_true",
        help="Show raw identifier values. Off by default to avoid unnecessary PII output.",
    )
    inspect.add_argument(
        "--show-excerpt",
        action="store_true",
        help="Show the raw extracted excerpt (may contain personal data).",
    )
    inspect.add_argument(
        "--json",
        action="store_true",
        help="Print the full observations as JSON (may contain personal data).",
    )

    for_user = evidence_sub.add_parser(
        "for-user", help="Query evidence associated with a resolved user."
    )
    _add_common_options(for_user)
    identity_group = for_user.add_mutually_exclusive_group(required=True)
    identity_group.add_argument("--user-id", help="Stable internal user_id.")
    identity_group.add_argument("--email", help="Current or historical email.")
    identity_group.add_argument("--phone", help="Current or historical phone.")
    identity_group.add_argument("--email-hash", help="Current or historical email hash.")
    for_user.add_argument(
        "--audit-at",
        default=None,
        help="Only use evidence captured at or before this ISO-8601 timestamp.",
    )
    for_user.add_argument("--limit", type=int, default=20, help="Maximum observations to show.")

    inspect_case = subparsers.add_parser(
        "inspect-case",
        help="Build and explain the audit context for one request case.",
    )
    _add_common_options(inspect_case)
    inspect_case.add_argument("--case-id", required=True, help="Case identifier.")
    inspect_case.add_argument(
        "--requests",
        choices=("sample", "eval", "all"),
        default="all",
        help="Which request file the case belongs to.",
    )
    inspect_case.add_argument(
        "--json-out",
        default=None,
        help=(
            "Optional full-context JSON path inside this project. "
            "The JSON contains personal data from the source dataset."
        ),
    )
    inspect_case.add_argument("--limit", type=int, default=50, help="Maximum resources to show.")

    audit_sample = subparsers.add_parser(
        "audit-sample", help="Run the full audit pipeline on the 32 sample requests."
    )
    _add_common_options(audit_sample)
    audit_sample.add_argument(
        "--output",
        default="reports/sample_output_generated.csv",
        help="Generated sample CSV path inside this project.",
    )

    audit_eval = subparsers.add_parser(
        "audit-eval", help="Run the full audit pipeline on the 518 evaluation requests."
    )
    _add_common_options(audit_eval)
    audit_eval.add_argument(
        "--output",
        default="output.csv",
        help="Generated evaluation CSV path inside this project.",
    )

    validate_output = subparsers.add_parser(
        "validate-output", help="Validate a generated output CSV."
    )
    _add_common_options(validate_output)
    validate_output.add_argument("--path", required=True, help="Output CSV path.")
    validate_output.add_argument(
        "--requests",
        choices=("sample", "eval"),
        required=True,
        help="Expected request set.",
    )

    evaluate_sample = subparsers.add_parser(
        "evaluate-sample", help="Evaluate generated sample answers against sample_output.csv."
    )
    _add_common_options(evaluate_sample)
    evaluate_sample.add_argument(
        "--json-out",
        default=None,
        help="Optional evaluation JSON path inside this project.",
    )
    compare_output = subparsers.add_parser(
        "compare-output", help="Report every per-case change between two output CSV files."
    )
    _add_common_options(compare_output)
    compare_output.add_argument("--before", required=True, help="Baseline output CSV.")
    compare_output.add_argument("--after", required=True, help="New output CSV.")
    compare_output.add_argument(
        "--json-out", required=True, help="Comparison JSON path inside this project."
    )
    return parser


def _build_resolver(bundle: DatasetBundle) -> IdentityResolver:
    return IdentityResolver(IdentityIndex(bundle.identities, bundle.audit_events))


def _cmd_info(settings: Settings) -> int:
    bundle = load_dataset(settings)
    index = IdentityIndex(bundle.identities, bundle.audit_events)

    print(f"Dataset directory : {bundle.dataset_dir}")
    print("Loaded files:")
    for label, dataset_file in (
        ("current identities", bundle.identities),
        ("audit events", bundle.audit_events),
        ("sample requests", bundle.sample_requests),
        ("evaluation requests", bundle.eval_requests),
    ):
        print(f"  {label:<20} {len(dataset_file):>5} rows  ({dataset_file.display_name})")
    print(f"Index build warnings: {len(index.build_warnings)}")
    for warning in index.build_warnings[:20]:
        print(f"  - {warning}")
    if len(index.build_warnings) > 20:
        print(f"  ... {len(index.build_warnings) - 20} more")
    return 0


def _cmd_resolve(settings: Settings, args: argparse.Namespace) -> int:
    bundle = load_dataset(settings)
    resolver = _build_resolver(bundle)
    kind = None if args.kind == "auto" else args.kind
    resolution = resolver.resolve_identifier(args.identifier, kind)

    if args.json:
        print(json.dumps(resolution.model_dump(mode="json"), ensure_ascii=False, indent=2))
    else:
        print(f"identifier    : {resolution.identifier}")
        print(f"kind          : {resolution.kind.value}")
        print(f"status        : {resolution.status.value}")
        if resolution.status == ResolutionStatus.RESOLVED:
            print(f"user_id       : {resolution.user_id}")
            print(f"method        : {resolution.method.value}")
            print(f"matched value : {resolution.matched_value}")
            identity = resolution.identity
            if identity is not None:
                print(f"current email : {identity.current.email if identity.current else 'n/a'}")
                print(f"all emails    : {', '.join(identity.all_emails)}")
                print(f"all phones    : {', '.join(identity.all_phones)}")
                print(f"all hashes    : {', '.join(identity.all_email_hashes)}")
                print(f"provenance    : {len(identity.provenance)} refs")
            for warning in resolution.warnings:
                print(f"warning       : {warning}")
        else:
            print(f"candidates    : {', '.join(resolution.candidates) or 'none'}")
            for warning in resolution.warnings:
                print(f"warning       : {warning}")

    return 0 if resolution.status == ResolutionStatus.RESOLVED else 1


def _select_requests(bundle: DatasetBundle, choice: str) -> DatasetFile:
    if choice == "sample":
        return bundle.sample_requests
    if choice == "eval":
        return bundle.eval_requests
    combined = bundle.sample_requests.rows + bundle.eval_requests.rows
    return DatasetFile(
        path=bundle.dataset_dir,
        display_name=(
            f"{bundle.sample_requests.display_name} + "
            f"{bundle.eval_requests.display_name}"
        ),
        rows=combined,
    )


def _cmd_audit_requests(settings: Settings, args: argparse.Namespace) -> int:
    bundle = load_dataset(settings)
    resolver = _build_resolver(bundle)
    request_file = _select_requests(bundle, args.requests)
    resolutions = resolver.resolve_requests(request_file)
    summary = summarize_resolutions(
        bundle.dataset_dir, request_file.display_name, resolutions
    )

    print("Identity resolution summary")
    print(f"  dataset        : {summary.dataset}")
    print(f"  request file   : {summary.request_file}")
    print(f"  total requests : {summary.total_requests}")
    print(f"  resolved       : {summary.resolved}")
    print(f"  ambiguous      : {summary.ambiguous}")
    print(f"  not found      : {summary.not_found}")
    print("  methods        :")
    for method, count in summary.methods.items():
        print(f"    {method:<22} {count}")
    if summary.exceptions:
        print("  exceptions     :")
        for exception in summary.exceptions:
            print(
                f"    {exception.case_id} | {exception.email} | "
                f"{exception.status.value} | candidates={list(exception.candidates)}"
            )
    else:
        print("  exceptions     : none")

    if args.json_out:
        destination = write_json_report(Path(args.json_out), summary, resolutions)
        print(f"JSON report written to: {destination}")

    return 0 if summary.not_found == 0 and summary.ambiguous == 0 else 1


def _cmd_evidence_inventory(settings: Settings, args: argparse.Namespace) -> int:
    build = build_evidence(settings.require_dataset())
    inventory = build.inventory

    print("Evidence inventory")
    print(f"  dataset              : {inventory.dataset}")
    print(f"  manifest             : {inventory.manifest_path}")
    print(f"  entries              : {inventory.total_entries}")
    print(f"  supported entries    : {inventory.supported_entries}")
    print(f"  unsupported entries  : {inventory.unsupported_entries}")
    print(f"  parsed files         : {inventory.parsed_files}")
    print(f"  failed files         : {inventory.failed_files}")
    print(f"  observations         : {inventory.observation_count}")
    print(f"  parse warnings       : {inventory.parse_warnings}")
    print("  files by format      : " + ", ".join(
        f"{key}={value}" for key, value in inventory.files_by_format.items()
    ))
    print("  observations/format  : " + ", ".join(
        f"{key}={value}" for key, value in inventory.observations_by_format.items()
    ))
    print("  observations/state   : " + ", ".join(
        f"{key}={value}" for key, value in inventory.observations_by_state.items()
    ))

    if inventory.unsupported:
        print("  unsupported files    :")
        for unsupported in inventory.unsupported:
            print(
                f"    {unsupported.file_id} | {unsupported.format.value} | "
                f"{unsupported.reason}"
            )
    if inventory.failures:
        print("  parse failures       :")
        for failure in inventory.failures:
            print(
                f"    {failure.file_id} | {failure.format.value} | "
                f"{failure.error_type} | {failure.reason}"
            )
    if inventory.manifest_issues:
        print("  manifest issues      :")
        for issue in inventory.manifest_issues:
            print(f"    {issue.code} | {issue.message}")

    if args.json_out:
        destination = write_inventory_json(Path(args.json_out), inventory)
        print(f"Inventory JSON written to: {destination}")

    return 0 if not inventory.failures else 1


def _cmd_evidence_inspect(settings: Settings, args: argparse.Namespace) -> int:
    root = settings.require_dataset()
    manifest = load_evidence_manifest(root)
    entry = next(
        (candidate for candidate in manifest.entries if candidate.file_id == args.file_id),
        None,
    )
    if entry is None:
        print(f"ERROR: Unknown evidence file_id: {args.file_id}", file=sys.stderr)
        return 2
    if not entry.is_supported:
        print(f"{entry.file_id} is unsupported: {entry.unsupported_reason}")
        return 1

    parser = parser_for(entry.format)
    if parser is None:
        print(f"ERROR: No parser for format {entry.format.value}", file=sys.stderr)
        return 2
    outcome = parser.parse(entry, root)
    if not outcome.recognized:
        print(f"{entry.file_id} was not recognized: {'; '.join(outcome.warnings)}")
        return 1

    observations = outcome.observations[: max(0, args.limit)]
    if args.json:
        payload = [observation.model_dump(mode="json") for observation in observations]
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    print(f"Evidence file: {entry.file_id} ({entry.file_path})")
    print(f"  format      : {entry.format.value}")
    print(f"  captured_at : {entry.captured_at.isoformat()}")
    print(f"  observations: {len(outcome.observations)}")
    print(f"  warnings    : {len(outcome.warnings)}")
    for warning in outcome.warnings[:10]:
        print(f"    - {warning}")
    for observation in observations:
        print(
            f"  {observation.observation_id} | {observation.system_id or 'UNKNOWN'} | "
            f"{observation.data_category or 'UNKNOWN'} | "
            f"{observation.resource_id or 'NO_RESOURCE'} | "
            f"{observation.observed_state.value} | {observation.captured_at.isoformat()}"
        )
        if args.show_identifiers:
            print(
                "    identifiers: "
                f"users={list(observation.user_ids)} "
                f"emails={list(observation.emails)} "
                f"phones={list(observation.phones)} "
                f"hashes={list(observation.email_hashes)}"
            )
        else:
            print(
                "    identifiers: "
                f"users={len(observation.user_ids)} "
                f"emails={len(observation.emails)} "
                f"phones={len(observation.phones)} "
                f"hashes={len(observation.email_hashes)} "
                f"related={len(observation.related_resource_ids)}"
            )
        location = observation.provenance.location
        region = location.region
        print(
            "    extraction: "
            f"{observation.provenance.extraction_method or observation.format.value} "
            f"| page={location.page_number} | region={region} | "
            f"confidence={observation.confidence:.2f}"
        )
        if args.show_excerpt and location.raw_excerpt:
            print(f"    excerpt: {location.raw_excerpt}")
        if observation.warnings:
            print(f"    warnings: {'; '.join(observation.warnings)}")
    return 0


def _cmd_evidence_for_user(settings: Settings, args: argparse.Namespace) -> int:
    bundle = load_dataset(settings)
    identity_index = IdentityIndex(bundle.identities, bundle.audit_events)
    resolver = IdentityResolver(identity_index)

    if args.user_id:
        identity = identity_index.build_identity(args.user_id)
    else:
        if args.email:
            value, kind = args.email, "email"
        elif args.phone:
            value, kind = args.phone, "phone"
        else:
            value, kind = args.email_hash, "email_hash"
        resolution = resolver.resolve_identifier(value, kind)
        if resolution.status != ResolutionStatus.RESOLVED or resolution.identity is None:
            print(
                f"No resolved identity for {value!r}: {resolution.status.value}",
                file=sys.stderr,
            )
            return 1
        identity = resolution.identity

    try:
        cutoff = parse_timestamp(args.audit_at) if args.audit_at else None
    except ValueError as exc:
        print(f"ERROR: Invalid --audit-at value: {exc}", file=sys.stderr)
        return 2

    build = build_evidence(settings.require_dataset())
    evidence_index = EvidenceIndex(build.observations)
    observations = evidence_index.observations_for_identity(identity, audit_at=cutoff)

    print("Evidence for resolved identity")
    print(f"  user_id      : {identity.user_id}")
    print(f"  audit_at     : {cutoff.isoformat() if cutoff else 'none'}")
    print(f"  observations : {len(observations)}")
    systems: dict[str, int] = {}
    categories: dict[str, int] = {}
    states: dict[str, int] = {}
    for observation in observations:
        systems[observation.system_id or "UNKNOWN"] = (
            systems.get(observation.system_id or "UNKNOWN", 0) + 1
        )
        categories[observation.data_category or "UNKNOWN"] = (
            categories.get(observation.data_category or "UNKNOWN", 0) + 1
        )
        states[observation.observed_state.value] = (
            states.get(observation.observed_state.value, 0) + 1
        )
    print("  systems      : " + ", ".join(
        f"{key}={value}" for key, value in sorted(systems.items())
    ))
    print("  categories   : " + ", ".join(
        f"{key}={value}" for key, value in sorted(categories.items())
    ))
    print("  states       : " + ", ".join(
        f"{key}={value}" for key, value in sorted(states.items())
    ))
    print("  sample       :")
    for observation in observations[: max(0, args.limit)]:
        print(
            f"    {observation.resource_id or 'NO_RESOURCE'} | "
            f"{observation.system_id or 'UNKNOWN'} | "
            f"{observation.data_category or 'UNKNOWN'} | "
            f"{observation.observed_state.value} | "
            f"{observation.captured_at.isoformat()} | {observation.file_id}"
        )
    return 0


def _mask_email(value: str) -> str:
    if "@" not in value:
        return "***"
    local, domain = value.split("@", 1)
    return f"{(local[:1] or '*')}***@{domain}"


def _cmd_inspect_case(settings: Settings, args: argparse.Namespace) -> int:
    service = AuditContextService(settings.require_dataset())
    if args.case_id not in service.case_ids:
        print(f"ERROR: Unknown case_id: {args.case_id}", file=sys.stderr)
        return 2
    source = service.request_source(args.case_id)
    if args.requests != "all" and source != args.requests:
        print(
            f"ERROR: {args.case_id} belongs to the {source!r} request file, "
            f"not {args.requests!r}",
            file=sys.stderr,
        )
        return 2

    context = service.build_context(args.case_id)
    if args.json_out:
        destination = write_context_json(Path(args.json_out), context)
        print(f"Context JSON written to: {destination}")

    print("Audit context")
    print(f"  case_id        : {context.case_id}")
    print(f"  audit_at       : {context.audit_at.isoformat()}")
    print(f"  requested_at   : {context.request.requested_at.isoformat()}")
    print(f"  reported_at    : {context.request.reported_at.isoformat()}")
    print(f"  reported_status: {context.request.reported_status.value}")
    print(f"  request_email  : {_mask_email(context.request.email)}")
    print(f"  identity       : {context.resolution.status.value}")
    if context.identity is not None:
        print(f"    user_id      : {context.identity.user_id}")
        print(f"    method       : {context.resolution.method.value}")
        print(
            "    identifiers  : "
            f"emails={len(context.identity.all_emails)} "
            f"phones={len(context.identity.all_phones)} "
            f"hashes={len(context.identity.all_email_hashes)}"
        )
    print(f"  linked_resources: {len(context.linked_resources)}")
    for link in context.linked_resources[: max(0, args.limit)]:
        print(
            f"    {link.resource_id} | systems={list(link.system_ids)} | "
            f"categories={list(link.data_categories)} | "
            f"links={[item.value for item in link.link_types]} | "
            f"confidence={link.confidence:.2f} | verified={link.verified}"
        )
    print(f"  states         : {len(context.states)}")
    for state in context.states[: max(0, args.limit)]:
        print(
            f"    {state.resource_id} | {state.kind.value} | {state.state.value} | "
            f"confidence={state.confidence:.2f} | verified={state.verified} | "
            f"recreated={state.recreated} | flow={state.active_data_flow} | "
            f"restore={state.restore_risk}"
        )
        for conflict in state.conflicts:
            print(f"      conflict: {conflict.description} -> {conflict.resolution.value}")
    print(
        "  active_data_flows: "
        + (", ".join(context.active_data_flows) if context.active_data_flows else "none")
    )
    print(
        "  restore_risks    : "
        + (", ".join(context.restore_risks) if context.restore_risks else "none")
    )
    print(f"  conflicts        : {len(context.conflicts)}")
    for conflict in context.conflicts[: max(0, args.limit)]:
        print(
            f"    {conflict.resource_id} | {conflict.description} | "
            f"states={[item.value for item in conflict.competing_states]} | "
            f"rule={conflict.rule}"
        )
    print(f"  unresolved       : {len(context.unresolved_resources)}")
    for unresolved in context.unresolved_resources[: max(0, args.limit)]:
        print(
            f"    {unresolved.resource_id or 'NO_RESOURCE'} | "
            f"system={unresolved.system_id or 'UNKNOWN'} | {unresolved.reason}"
        )
    print(
        f"  candidate_activity: {len(context.candidate_activity_resources)}"
    )
    for candidate in context.candidate_activity_resources[: max(0, args.limit)]:
        print(
            f"    {candidate.resource_id or 'NO_RESOURCE'} | "
            f"system={candidate.system_id or 'UNKNOWN'} | {candidate.reason}"
        )
    print(f"  uncertainties    : {len(context.uncertainties)}")
    for uncertainty in context.uncertainties[: max(0, args.limit)]:
        print(f"    - {uncertainty}")
    print(
        f"  evidence_considered: {len(context.relevant_observations)} observations, "
        f"{len(context.relevant_activity)} activity events"
    )
    return 0


def _status_counts(results) -> Counter[str]:
    return Counter(result.deletion_status.value for result in results)


def _run_audit(settings: Settings, args: argparse.Namespace, choice: str) -> int:
    pipeline = AuditPipeline(settings.require_dataset())
    results = pipeline.audit_requests(choice)
    destination = pipeline.write_results(results, Path(args.output))
    validation = pipeline.validate_output(destination, choice=choice)
    counts = _status_counts(results)
    print(f"Audit {choice} cases: {len(results)}")
    print(f"  output      : {destination}")
    for status in DeletionStatus:
        print(f"  {status.value:<15} {counts.get(status.value, 0)}")
    print(f"  validation  : {'PASS' if validation.valid else 'FAIL'}")
    print(f"  rows        : {validation.rows}")
    for error in validation.errors[:20]:
        print(f"  ERROR: {error}")
    return 0 if validation.valid else 1


def _cmd_validate_output(settings: Settings, args: argparse.Namespace) -> int:
    pipeline = AuditPipeline(settings.require_dataset())
    validation = pipeline.validate_output(Path(args.path), choice=args.requests)
    print(f"Validation: {'PASS' if validation.valid else 'FAIL'}")
    print(f"  path   : {Path(args.path).resolve()}")
    print(f"  rows   : {validation.rows}")
    print(f"  errors : {len(validation.errors)}")
    for error in validation.errors[:50]:
        print(f"  ERROR: {error}")
    for warning in validation.warnings[:20]:
        print(f"  WARN: {warning}")
    return 0 if validation.valid else 1


def _cmd_evaluate_sample(settings: Settings, args: argparse.Namespace) -> int:
    pipeline = AuditPipeline(settings.require_dataset())
    results = pipeline.audit_requests("sample")
    report = pipeline.evaluate_sample(results)
    print("Sample evaluation")
    print(
        f"  cases                 : {report.total_cases}\n"
        f"  status accuracy       : {report.status_correct}/{report.total_cases} "
        f"({report.status_accuracy:.4f})\n"
        f"  exact case matches    : {report.exact_case_matches}/{report.total_cases} "
        f"({report.exact_case_accuracy:.4f})\n"
        f"  exact step-set        : {report.exact_step_set_matches}/{report.total_cases} "
        f"({report.exact_step_set_accuracy:.4f})\n"
        f"  exact sequence        : {report.exact_sequence_matches}/{report.total_cases} "
        f"({report.exact_sequence_accuracy:.4f})\n"
        f"  step precision        : {report.step_precision:.4f}\n"
        f"  step recall           : {report.step_recall:.4f}\n"
        f"  step F1               : {report.step_f1:.4f}\n"
        f"  field accuracy        : {report.field_accuracy:.4f}\n"
        f"  evidence accuracy     : {report.evidence_accuracy:.4f}\n"
        f"  contract validity     : {report.contract_valid_cases}/{report.total_cases} "
        f"({report.contract_validity_accuracy:.4f})"
    )
    print("  status mismatches:")
    mismatches = [item for item in report.diagnostics if not item.status_correct]
    if mismatches:
        for item in mismatches:
            print(
                f"    {item.case_id}: expected {item.expected_status}, got {item.actual_status}"
            )
    else:
        print("    none")
    print("  step mismatches (top 10):")
    step_mismatches = [item for item in report.diagnostics if not item.exact_steps]
    for item in step_mismatches[:10]:
        print(
            f"    {item.case_id}: missing={len(item.missing_steps)} "
            f"extra={len(item.extra_steps)} changed_fields={len(item.changed_fields)}"
        )
    if args.json_out:
        destination = write_evaluation_json(Path(args.json_out), report)
        print(f"Evaluation JSON written to: {destination}")
    return 0


def _cmd_compare_output(settings: Settings, args: argparse.Namespace) -> int:
    comparison = compare_output_files(args.before, args.after)
    destination = write_comparison_json(args.json_out, comparison)
    print("Output comparison")
    print(f"  before cases : {comparison.before_cases}")
    print(f"  after cases  : {comparison.after_cases}")
    print(f"  changed      : {len(comparison.changed_cases)}")
    print(f"  unchanged    : {comparison.unchanged_cases}")
    print(f"  added        : {len(comparison.added_case_ids)}")
    print(f"  removed      : {len(comparison.removed_case_ids)}")
    print(f"  report       : {destination}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        settings = Settings.from_environment(
            dataset_dir=args.dataset,
            reports_dir=args.reports_dir,
        )
        if args.command == "info":
            return _cmd_info(settings)
        if args.command == "resolve":
            return _cmd_resolve(settings, args)
        if args.command == "audit-requests":
            return _cmd_audit_requests(settings, args)
        if args.command == "evidence":
            if args.evidence_command == "inventory":
                return _cmd_evidence_inventory(settings, args)
            if args.evidence_command == "inspect":
                return _cmd_evidence_inspect(settings, args)
            if args.evidence_command == "for-user":
                return _cmd_evidence_for_user(settings, args)
            parser.error(f"Unknown evidence command: {args.evidence_command}")
            return 2
        if args.command == "inspect-case":
            return _cmd_inspect_case(settings, args)
        if args.command == "audit-sample":
            return _run_audit(settings, args, "sample")
        if args.command == "audit-eval":
            return _run_audit(settings, args, "eval")
        if args.command == "validate-output":
            return _cmd_validate_output(settings, args)
        if args.command == "evaluate-sample":
            return _cmd_evaluate_sample(settings, args)
        if args.command == "compare-output":
            return _cmd_compare_output(settings, args)
        parser.error(f"Unknown command: {args.command}")
        return 2
    except PrivacyGuardError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
