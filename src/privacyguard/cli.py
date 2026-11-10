"""Command-line interface for Sprint 1 identity resolution."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from .config import Settings
from .errors import PrivacyGuardError
from .identity.index import IdentityIndex
from .identity.report import summarize_resolutions, write_json_report
from .identity.resolver import IdentityResolver
from .io.bundle import DatasetBundle, load_dataset
from .io.types import DatasetFile
from .models import ResolutionStatus


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
        parser.error(f"Unknown command: {args.command}")
        return 2
    except PrivacyGuardError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
