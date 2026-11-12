# PrivacyGuard AI

AI-powered personal data deletion auditing agent.

**Current status: Sprint 2C — policy engine, audit decision and output
pipeline.** The deterministic end-to-end pipeline now produces validated
`output.csv` files. PDF/image extraction remains out of scope.

## What Sprint 1 provides

- A strict CSV loader for the read-only challenge dataset.
- Typed Pydantic v2 models for requests, current identities, audit events,
  provenance and resolved identities.
- An in-memory identity index over `user_identities.csv` and
  `user_audit_log.csv`.
- Deterministic resolution by current/historical email, phone and email hash.
- Explicit `AMBIGUOUS` handling. The resolver never guesses a `user_id`.
- Provenance for every matched identifier and every resolved identity.
- A CLI, unit tests and integration tests against the real dataset.

## What Sprint 2A provides

- A validated evidence manifest loader (`evidence_files.csv`) with file
  existence, duplicate-ID, timestamp and path-traversal checks.
- Deterministic parsers for:
  - SQLite-compatible SQL snapshots, executed only in an isolated in-memory
    database with rejected `ATTACH`/`DETACH`/unsafe `PRAGMA` constructs.
  - JSON snapshot bundles, service exports, record ledgers and collection files.
  - LOG files in logfmt, pipe, bracket, JSON-lines and nested `message` styles.
  - TXT handover records.
- Typed `EvidenceObservation` models with file/capture provenance, source
  location, explicit observed state, identifiers, related resources and
  structured record contents.
- An in-memory evidence index by resource, user, email, phone, hash, related
  resource, file, system, category and capture time.
- `audit_at` filtering so evidence captured after a request cutoff is excluded.
- Explicit reporting of unsupported PDF/PNG files and parser failures.

## What Sprint 2B provides

- A strict loader and typed model for all 4,011 `system_activity.csv` events,
  including parsed free-text metadata, identifiers, related resources,
  correlation IDs and explicit state claims.
- An `ActivityIndex` by resource, related resource, identity, event type,
  source/target system and time, with `audit_at` filtering.
- A `ResourceLinker` that connects a resolved identity to resources through:
  - explicit `user_id` references,
  - current and historical email/phone/email hash,
  - related resource references (`source_resource_id`, `ticket_id`,
    `audit_id`),
  - shared `trace_id`/`requestId` evidence chains,
  - explicit activity identity links (`LINK_RESOURCE_IDENTITY`),
  - activity relationships.
- Explicit confidence, verification status and provenance on every link.
- A deterministic `StateEngine` that reconstructs each linked resource's state
  at `audit_at` (`PRESENT`, `ABSENT`, `REDACTED`, `ANONYMIZED`, `ACTIVE`,
  `DISABLED`, `BLOCKED`, `UNKNOWN`).
- Conservative conflict resolution across evidence sources, replicas, activity
  claims and deletion/recreation chains.
- A request-level `build_audit_context(case_id)` service that assembles:
  - request details and resolved identity,
  - linked resources and unresolved/candidate resources,
  - resource states, active data-flow candidates and restore risks,
  - conflicts, uncertainties and full evidence/activity provenance.
- A CLI `inspect-case` command with optional in-project JSON output.

## What Sprint 2C provides

- A deterministic multilingual request-intent classifier. Non-deletion
  requests become `NOT_APPLICABLE` with `steps_json=[]`; ambiguous requests are
  isolated as `UNCERTAIN` and audited conservatively.
- A typed policy engine loaded from the actual `deletion_rules.csv`, with
  condition-aware handling for `DELETE`, `REDACT`, `ANONYMIZE`, `RETAIN`,
  `BLOCK_RESTORE` and `DISABLE_DATA_FLOW`.
- Corroborated category resolution. Explicit evidence/table categories win;
  system+resource-prefix hints are lower confidence and are never used alone.
- Risk findings for active data flows, restore-enabled backups, exposed PII in
  retained records, and deleted records that still exist.
- A conservative audit decision engine:
  - `COMPLETE` only when every linked/covered decision is compliant, required
    retained records are present, and no recreation/restore/flow risk remains.
  - `INCOMPLETE` when any violation, unresolved decision, or missing coverage
    remains.
  - `NOT_APPLICABLE` only for non-deletion requests.
- A step planner with the exact allowed phases, operations, states and ordering;
  remediation/future verification steps use empty evidence IDs.
- A CSV writer and structural/semantic validator for `case_id`,
  `deletion_status`, `steps_json`.
- A sample evaluation harness (status, exact-case, step precision/recall/F1,
  field, evidence, sequence) and four synthetic end-to-end cases.
- No LLM calls are used in the production path. Token usage and cost are zero.

## Temporal state algorithm

1. Filter evidence observations to `captured_at <= audit_at`.
2. Filter activity events to `event_time <= audit_at`.
3. Normalize each observation to an explicit or structurally inferred state.
   Inference is limited to:
   - tombstones with no direct identifiers → `REDACTED`,
   - analytics records with no attributable identifiers → `ANONYMIZED`,
   - support messages with no direct identifiers → `REDACTED`.
4. Group observations by source key `(system, category, table)` and keep the
   latest state-bearing observation per source.
5. Aggregate sources with conservative precedence:
   - records: `PRESENT` > `REDACTED` > `ANONYMIZED` > `ABSENT`,
   - data flows: `ACTIVE` > `DISABLED`,
   - backups: `ACTIVE` > `BLOCKED`.
6. Treat activity rows as claims. They become the state only when no evidence
   state exists, and are marked `verified=False`.
7. Detect recreation after a successful deletion when a later sync, index,
   restore, export, cache, email or `PRESENT` observation contradicts it.
   `CONFIRMED` requires both a later recreation event and later `PRESENT`
   evidence; a single contradiction is `SUSPECTED`.
8. Attach a `StateBasis` for every selected observation and activity claim, plus
   explicit `StateConflict` records for disagreements.

## Resource linking rules

- Never derive `account_id` from `user_id` (for example, `user_10` does not
  imply `account_010`).
- Direct evidence links require an explicit identifier match.
- Related resources require an explicit reference from a linked record.
- Correlation-chain links require a shared `trace_id`/`requestId` rooted in an
  observation that already matches the identity.
- Activity identity links rely on explicit activity metadata and are reported as
  unverified.
- Resources in the reported workflow window that cannot be linked are retained
  as `candidate_activity_resources` with confidence `0.0`; they are not silently
  promoted to links.
- Every link carries provenance and a confidence score.

## Conflict-resolution strategy

- Evidence observations override activity claims.
- Successful deletion followed by `PRESENT` evidence → `PRESENT`, with a
  recreation conflict.
- Failed deletion followed by `ABSENT` evidence → `ABSENT`, with a conflict
  noting the failed claim.
- Primary `ABSENT` + replica `PRESENT` → `PRESENT`, with a replication-drift
  conflict.
- Backup `restore_allowed=true` → restore risk.
- Active connector evidence → active data-flow candidate.
- Tombstone with direct identifiers → `PRESENT`, with a tombstone-exposure
  conflict.
- Missing evidence is `UNKNOWN`, never `ABSENT`, unless a snapshot scope
  explicitly proves absence.
- Every state has either a `StateBasis` or a documented uncertainty.

## Read-only dataset policy

The challenge dataset is owned by the sibling repository:

```text
D:\HackerRank Project\hackerrank-orchestrate-october26\dataset
```

PrivacyGuard AI only **reads** those files. It never copies, edits, renames or
writes inside that repository. Reports may only be written inside this project
(`privacyguard-ai`).

## Requirements

- Python 3.11+ (the existing `.venv` uses Python 3.14.6)
- `pydantic>=2.7`
- `pytest>=8` for tests

The existing virtual environment already contains these packages:

```powershell
D:\HackerRank Project\privacyguard-ai\.venv\Scripts\python.exe
```

No paid APIs, external services or additional dependencies are used.

## Quick start (PowerShell)

From `D:\HackerRank Project\privacyguard-ai`:

```powershell
$py = ".\.venv\Scripts\python.exe"
$env:PYTHONPATH = "src"

# Dataset and row counts
& $py -m privacyguard info

# Resolve one current email
& $py -m privacyguard resolve "amina.elmasri@gmail.com" --kind email

# Resolve a historical email through user_audit_log.csv
& $py -m privacyguard resolve "nadia.ionescu@yahoo.com" --kind email

# Resolve all 32 sample requests and all 518 evaluation requests
& $py -m privacyguard audit-requests --requests all

# Write an optional JSON report (must stay inside this project)
& $py -m privacyguard audit-requests --requests sample --json-out reports/identity_sample.json

# Evidence inventory and coverage
& $py -m privacyguard evidence inventory

# Inspect one parsed evidence file (identifiers are hidden by default)
& $py -m privacyguard evidence inspect --file-id evidence_03 --limit 5

# Query evidence for a resolved user, optionally with an audit cutoff
& $py -m privacyguard evidence for-user --email "nadia.ionescu@yahoo.com" --audit-at "2026-09-18T12:25:00Z"

# Write an inventory JSON report (must stay inside this project)
& $py -m privacyguard evidence inventory --json-out reports/evidence_inventory.json

# Inspect one request case end-to-end
& $py -m privacyguard inspect-case --case-id case_05 --requests sample

# Write the full audit context JSON (must stay inside this project)
& $py -m privacyguard inspect-case --case-id case_11 --requests sample --json-out reports/context_case_11.json

# Run the full audit pipeline on the 32 public samples
& $py -m privacyguard audit-sample

# Run the full audit pipeline on the 518 evaluation requests
& $py -m privacyguard audit-eval

# Validate a generated output file
& $py -m privacyguard validate-output --path output.csv --requests eval

# Evaluate sample accuracy against dataset/sample_output.csv
& $py -m privacyguard evaluate-sample --json-out reports/sample_evaluation.json
```

The package also declares a console entry point:

```toml
[project.scripts]
privacyguard = "privacyguard.cli:main"
```

An editable install is optional and is not required for the commands above:

```powershell
& $py -m pip install -e .
privacyguard info
```

## Configuration

| Setting | CLI flag | Environment variable | Default |
|---|---|---|---|
| Dataset directory | `--dataset` | `PG_DATASET_DIR` | `../hackerrank-orchestrate-october26/dataset` |
| Reports directory | `--reports-dir` | `PG_REPORTS_DIR` | `reports` |

See `.env.example`. Do not commit a real `.env` file or any credentials.

Relative `--json-out` paths are resolved against the current working
directory, but the target must still be inside `privacyguard-ai`; otherwise the
CLI refuses the write with `UnsafePathError`.

## Verified results

The following counts come from the current dataset and the actual test run:

| File | Rows |
|---|---:|
| `user_identities.csv` | 850 |
| `user_audit_log.csv` | 306 |
| `sample_deletion_requests.csv` | 32 |
| `deletion_requests.csv` | 518 |

Identity resolution:

| Batch | Total | Resolved | Ambiguous | Not found | Current email | Historical email |
|---|---:|---:|---:|---:|---:|---:|
| Sample requests | 32 | 32 | 0 | 0 | 29 | 3 |
| Evaluation requests | 518 | 518 | 0 | 0 | 418 | 100 |
| Combined | 550 | 550 | 0 | 0 | 447 | 103 |

Evidence inventory:

| Item | Count |
|---|---:|
| Manifest entries | 94 |
| Supported entries | 79 |
| Unsupported entries (PDF/PNG) | 15 |
| Parsed files | 79 |
| Parse failures | 0 |
| Normalized observations | 3,469 |
| Observations by format | JSON 890, LOG 1,647, SQL 891, TXT 41 |
| Observations by state | PRESENT 2,116, ABSENT 245, ACTIVE 218, DISABLED 62, BLOCKED 57, ANONYMIZED 12, REDACTED 5, UNKNOWN 754 |

Evidence index:

```text
observations=3469 files=78 resources=2040 user_ids=440
emails=781 phones=76 email_hashes=37 systems=15 categories=29
correlation_ids=994
earliest_captured_at=2026-01-29T11:44:59Z
latest_captured_at=2026-10-01T12:00:00Z
```

`files=78` in the index means files that produced at least one observation.
`evidence_90` parsed successfully but contains no data observations; it is
reported as a parse warning, not a failure.

System activity:

```text
events=4011 resources=3948 event_types=17
source_systems=11 target_systems=19
user_identity_links=11 email_identity_links=11
earliest=2026-01-04T14:56:29Z latest=2026-10-01T10:18:34Z
```

Sprint 2B sample-case audit contexts (without using `sample_output.csv`):

| Item | Count |
|---|---:|
| Sample contexts built | 32 / 32 |
| Linked resources | 79 |
| Reconstructed states | 79 |
| Verified states | 72 |
| Unverified states | 7 |
| Contexts with conflicts | 8 |
| Total conflicts | 12 |
| Recreated-state detections | 5 (2 CONFIRMED, 3 SUSPECTED) |
| Active data-flow candidates | 6 |
| Restore-risk candidates | 3 |
| Candidate activity resources | 333 |
| Unresolved linked relationships | 0 |
| Sample cases with zero direct links | 3 (`case_01`, `case_02`, `case_04`) |

State distribution across the 32 sample contexts:

```text
PRESENT=48 ABSENT=10 ACTIVE=9 REDACTED=4 BLOCKED=3 DISABLED=3 UNKNOWN=2
```

A full pass over all 550 requests produced 1,349 linked resources and 1,349
states with no exceptions; this is a build/quality check, not a classification
result.

Sprint 2C sample evaluation (against `dataset/sample_output.csv`):

| Metric | Actual |
|---|---:|
| Status accuracy | 31/32 (0.96875) |
| Exact case matches | 10/32 (0.3125) |
| Step precision | 0.9571 |
| Step recall | 0.8083 |
| Step F1 | 0.8764 |
| Field accuracy | 0.8135 |
| Evidence citation accuracy | 0.9661 |
| Sequence accuracy | 0.3125 |

Generated status distribution:

```text
Sample (32):   COMPLETE=9  INCOMPLETE=23  NOT_APPLICABLE=0
Eval (518):    COMPLETE=143 INCOMPLETE=365 NOT_APPLICABLE=10
```

Sample status mismatch: `case_04` is expected `COMPLETE` but is classified
`INCOMPLETE` because no account/analytics resource could be linked without
inventing an identifier. The remaining exact-step mismatches are missing
account/analytics/audit verification steps caused by unresolved links, plus one
support-category choice (`case_10`) where REDACT is used instead of DELETE.

Output validation:

```text
sample: PASS  rows=32  errors=0
eval:   PASS  rows=518 errors=0
```

Tests:

```text
205 passed (162 prior sprints + 43 Sprint 2C)
```

## Project layout

```text
privacyguard-ai/
├── pyproject.toml
├── README.md
├── .env.example
├── src/privacyguard/
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli.py
│   ├── config.py
│   ├── errors.py
│   ├── models.py
│   ├── normalization.py
│   ├── safety.py
│   ├── io/
│   │   ├── bundle.py
│   │   ├── csv_loader.py
│   │   └── types.py
│   ├── identity/
│   │   ├── index.py
│   │   ├── report.py
│   │   └── resolver.py
│   ├── evidence/
│   │   ├── errors.py
│   │   ├── identifiers.py
│   │   ├── index.py
│   │   ├── manifest.py
│   │   ├── models.py
│   │   ├── report.py
│   │   ├── service.py
│   │   └── parsers/
│   │       ├── base.py
│   │       ├── json_parser.py
│   │       ├── log.py
│   │       ├── registry.py
│   │       ├── sql.py
│   │       └── txt.py
│   ├── activity/
│   │   ├── details.py
│   │   ├── index.py
│   │   └── models.py
│   ├── linking/
│   │   ├── linker.py
│   │   └── models.py
│   ├── state/
│   │   ├── engine.py
│   │   └── models.py
│   ├── context/
│   │   ├── errors.py
│   │   ├── models.py
│   │   ├── report.py
│   │   └── service.py
│   ├── intent/
│   │   ├── classifier.py
│   │   └── models.py
│   ├── policy/
│   │   ├── categories.py
│   │   ├── engine.py
│   │   ├── models.py
│   │   └── rules.py
│   ├── planning/
│   │   ├── models.py
│   │   └── planner.py
│   ├── decision/
│   │   ├── engine.py
│   │   └── models.py
│   ├── output/
│   │   ├── validator.py
│   │   └── writer.py
│   ├── pipeline/
│   │   └── service.py
│   └── evaluation/
│       ├── metrics.py
│       └── report.py
├── evaluation/
│   ├── evaluation_report.md
│   └── usage_report.md
├── output.csv
└── tests/
    ├── conftest.py
    ├── unit/
    ├── integration/
    └── evaluation/
```

## Design decisions

1. **Exact matching only.** Normalization canonicalizes case and phone
   formatting; it does not perform fuzzy matching or infer account IDs.
2. **Ambiguity is a result, not an error to hide.** A value that maps to more
   than one `user_id` returns `AMBIGUOUS` with candidates and provenance.
3. **Current snapshot wins only when unique.** If a value is both a current
   identifier and a historical identifier for different users, the result is
   `AMBIGUOUS`.
4. **Provenance is first-class.** Every resolution points back to the source
   CSV, 1-based data row, record ID, field and original value.
5. **No dataset writes.** The loader validates headers strictly and only reads
   from the configured dataset directory.
6. **Intent classification is deterministic and multilingual.** Strong
   non-deletion phrases override deletion words; ambiguous requests are isolated
   as `UNCERTAIN` and audited conservatively.
7. **Source observations are separate from inferred conclusions.** An explicit
   `result`, `http_status`, `rows`, `enabled` or `restore_allowed` value may set
   `observed_state`; other records remain `UNKNOWN` rather than being guessed.
8. **SQL snapshots are isolated.** They are executed only in a fresh in-memory
   SQLite connection, and external-attachment or extension-loading constructs
   are rejected.
9. **Unsupported formats are explicit.** PDF and PNG entries remain in the
   manifest but are reported as unsupported with a reason instead of being
   silently ignored.
10. **The index never bypasses `audit_at`.** Every query accepts an optional
    cutoff and filters on the manifest `captured_at` timestamp.
11. **Activity results are claims.** `reported_result` never becomes a verified
    state on its own; activity-only states carry `verified=False`.
12. **No implicit account mapping.** `user_10` never implies `account_010`;
    links require an explicit identifier, reference or correlation chain.
13. **Resource links are provenance-backed and confidence-scored.** Correlation
    chains and activity links are reported as unverified.
14. **State aggregation is conservative.** A copy that remains `PRESENT` wins
    over `ABSENT`; a single `ACTIVE` flow or restore path is retained as a risk.
15. **Missing evidence is not absence.** `UNKNOWN` is used unless a snapshot
    scope or explicit observation proves otherwise.
16. **Policy categories are never taken from a bare resource prefix.** Prefix
    hints require a matching system, and explicit evidence/table categories have
    higher confidence.
17. **Unknown policy categories do not invent destructive operations.** They
    produce `UNKNOWN` decisions and prevent a `COMPLETE` classification.
18. **Account coverage can be provisional.** When exactly one account deletion
    event exists in the workflow window and no account evidence was linked, a
    low-confidence coverage decision is used and marked provisional.
19. **Future remediation/verification never cites evidence.** Only current
    findings and `COMPLETE` verification steps carry evidence IDs.
20. **The output validator checks references.** Non-empty evidence IDs must be a
    known `evidence_*`, `activity_*` or `audit_*` identifier.

## Known limitations (Sprint 2C)

- No `account_id` inference from `user_id`. Accounts absent from evidence remain
  candidates, not guessed links. This is the main reason for the single sample
  status mismatch.
- No PDF or image parsing. This affects `evidence_58` and the other 14 PDF/PNG
  files, and therefore some support/attachment and marketing evidence.
- `observed_state=UNKNOWN` remains common in logs that only contain a lookup
  start or a resource identifier without a completion/status field.
- `evidence_90` parses successfully but contains no data observations and is
  reported as a parse warning.
- Log and SQL records do not always carry a `data_category`; the index keeps
  them with `UNKNOWN` category rather than inferring one.
- The reported-workflow-window candidate list is deliberately broad (±2 hours)
  and contains unrelated activity. It is marked confidence `0.0` and is not a
  resource link.
- Activity-only and structurally inferred states remain provisional
  (`verified=False`) and are documented in the audit result.
- Account/analytics/audit resources that were never linked cannot produce the
  corresponding verification steps; this reduces step-level recall but not the
  status decision in most cases.
- `case_04` remains `INCOMPLETE` because no account/analytics resource can be
  linked without inventing an identifier; the public answer expects `COMPLETE`.
- `case_10` uses `REDACT` for a support record where the public answer uses
  `DELETE`; this is a category/condition ambiguity, not a status error.
- `.env` is not auto-loaded; use PowerShell environment variables or pass CLI
  flags explicitly.
- Exact row/observation counts in integration tests are tied to the current
  challenge dataset; if the dataset is regenerated, update the expected counts.

## Tests

```powershell
$env:PYTHONPATH = "src"
& ".\.venv\Scripts\python.exe" -m pytest -o addopts="" -q
```

Integration tests skip automatically when the dataset directory is absent and
`PG_DATASET_DIR` is not set.

## Next sprint

Sprint 3 / production hardening should add:

1. PDF text extraction and image/OCR interfaces for the remaining 15 evidence
   files, with provenance-preserving extraction.
2. Account-linkage calibration using workflow activity clusters and snapshot
   scope, without hardcoding sample case IDs or expected account IDs.
3. Better support-message/attachment condition resolution, especially for
   replica logs where the record type is not explicit.
4. Additional synthetic conflict cases for retention, legal holds, and
   multi-replica drift.
5. Packaging instructions for the original challenge submission
   (`code.zip`, `code/evaluation/` copies, and chat transcript) if required.
6. Optional LLM classification only for requests the deterministic classifier
   marks `UNCERTAIN`, with structured output, caching, and a token/cost report.
