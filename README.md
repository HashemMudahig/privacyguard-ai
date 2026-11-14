# PrivacyGuard AI

AI-powered personal data deletion auditing agent.

**Current status: Sprint 3C Correctness Review — final.** The deterministic
pipeline separates confirmed, inferred and candidate links, verifies redaction
and absence only from direct evidence (never from an activity claim or a
partial snapshot), and treats an unresolved account candidate as uncertainty
rather than a completion blocker.

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

## What Sprint 3A provides

- A PDF parser using local `pypdf` text-layer extraction:
  - page-level text and page numbers;
  - resource/user/email/phone/hash/order extraction;
  - document-type and explicit state detection;
  - embedded-image warnings;
  - no OCR fallback when a text layer is sufficient.
- A PNG parser using the built-in Windows OCR engine through a bundled local
  PowerShell script:
  - line- and word-level OCR with bounding boxes;
  - resource and identifier extraction;
  - visual-row grouping;
  - per-observation regions, image dimensions and confidence;
  - no external service and no paid API.
- Multimodal evidence integration:
  - PDF/PNG observations use the existing `EvidenceObservation` model;
  - the evidence index, temporal filter, resource linker, state engine and
    policy engine consume them without duplicated logic;
  - low-confidence OCR links require corroboration by text evidence or activity;
  - OCR-derived identifiers are never silently promoted to verified identity
    matches.
- Explicit reporting of OCR unavailability, unreadable text, missing resource
  IDs and embedded PDF images.
- CLI inspection of PDF/PNG evidence via the existing `evidence inspect`
  command, including extraction method, page, region and confidence.

## What Sprint 3B provides

- Explicit link levels on every resource and policy decision:
  `CONFIRMED`, `INFERRED`, `CANDIDATE` and `UNRESOLVED`.
- Workflow-window account candidates (`account_*`) are retained as
  `CANDIDATE` relationships when the reported activity contains a deletion,
  sync, index, restore, redact, anonymize or check event. They are never added
  to `linked_resources` and are never treated as confirmed identity mappings.
- Coverage decisions for a missing account are marked
  `link_level=CANDIDATE`, `category_confidence=0.4`, and `provisional=True`.
- Support message/attachment classification now requires content or activity
  evidence:
  - `REDACT_RECORD` activity → `SUPPORT_MESSAGE`,
  - `DELETE_RECORD` activity → `SUPPORT_ATTACHMENT`,
  - the bare `support_` prefix is not sufficient.
- State promotion to `REDACTED`/`ANONYMIZED` now requires a successful
  redact/anonymize activity claim (or explicit evidence) and no conflicting
  direct identifiers. A missing identifier is not treated as proof of
  redaction.
- Legal holds parse `retain_until` from PDF rows and JSON records. A hold is
  active only at or before its retention date; expired holds require no
  verification, and legal-hold records without a date are active by presence.
- Snapshot coverage model (`evidence/coverage.py`):
  - SQL replicas, inventory captures, JSON bundles and subject-scoped captures
    are explicitly non-complete;
  - absence is `PROVEN` only when a complete snapshot covers the system and
    collection at or before `audit_at`;
  - conflicting complete snapshots at the same timestamp are `AMBIGUOUS`.
- OCR corroboration cross-references OCR resource IDs against:
  - text evidence for the same resource,
  - activity for the same resource,
  - historical identity observations and activity references;
  - OCR-only identifiers use a narrowly scoped confusable-character match
    (for example `gmaiI.com`/`gmail.com`) only for identifying the resolved
    subject; the resource ID itself is never rewritten.
  Conflicting identifiers from another identity block the OCR link, and every
  surviving OCR link remains `INFERRED` and `verified=False`.

### Multimodal dependencies

The local environment requires:

```text
pypdf>=7.0
pillow>=13.0
```

PNG OCR also requires Windows 10/11 PowerShell and a Windows OCR language pack.
On non-Windows systems, PNG files are explicitly reported as OCR-unavailable
rather than silently skipped.

Local installation:

```powershell
& ".\.venv\Scripts\python.exe" -m pip install "pypdf>=7.0" "pillow>=13.0"
```

### Multimodal CLI examples

```powershell
$env PYTHONPATH = "src"

# Inspect the delivery attachment PDF
python -m privacyguard evidence inspect --file-id evidence_58 --limit 3

# Inspect the search console screenshot
python -m privacyguard evidence inspect --file-id evidence_09 --limit 3

# Show extraction warnings and normalized observations
python -m privacyguard evidence inspect --file-id evidence_04 --show-excerpt

# Evidence coverage after multimodal parsing
python -m privacyguard evidence inventory
```

## Temporal state algorithm

1. Filter evidence observations to `captured_at <= audit_at`.
2. Filter activity events to `event_time <= audit_at`.
3. Normalize each observation to an explicit or structurally inferred state.
   Inference is limited to:
   - tombstones with no direct identifiers → `REDACTED`,
   - analytics records with no attributable identifiers → `ANONYMIZED`,
   - successful REDACT/ANONYMIZE activity plus evidence with no direct
     identifiers → `REDACTED`/`ANONYMIZED` (unverified).
   A support message with no parsed identifiers is **not** assumed redacted.
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
- Account resources that appear only in the reported workflow window are stored
  as `CANDIDATE` account candidates. Exactly one candidate with an
  `account_service` deletion event may produce a provisional coverage decision;
  none of these candidates is a confirmed identity link.
- OCR resource IDs require independent corroboration. A conflicting identity in
  text evidence or activity blocks the link; an existence-only corroboration is
  accepted with a warning that the subject match still depends on OCR.
- Every link carries provenance, a confidence score and an explicit link level.

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
| Supported entries | 94 |
| Unsupported entries | 0 |
| Parsed files | 94 |
| Parse failures | 0 |
| Normalized observations | 3,499 |
| Observations by format | JSON 890, LOG 1,647, SQL 891, TXT 41, PDF 9, PNG 21 |
| Observations by state | PRESENT 2,143, ABSENT 245, ACTIVE 227, DISABLED 62, BLOCKED 57, ANONYMIZED 12, REDACTED 6, UNKNOWN 747 |

Evidence index:

```text
observations=3499 files=93 resources=2059 user_ids=442
emails=792 phones=79 email_hashes=37 systems=18 categories=31
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

Sprint 3B sample evaluation (against `dataset/sample_output.csv`):

| Metric | Sprint 2C | Sprint 3A | Sprint 3B |
|---|---:|---:|---:|
| Status accuracy | 31/32 (0.96875) | 31/32 (0.96875) | **31/32 (0.96875)** |
| Exact case matches | 10/32 (0.3125) | 9/32 (0.28125) | **9/32 (0.28125)** |
| Step precision | 0.9571 | 0.9244 | **0.9419** |
| Step recall | 0.8083 | 0.8238 | **0.8394** |
| Step F1 | 0.8764 | 0.8712 | **0.8877** |
| Field accuracy | 0.8135 | 0.8290 | **0.8446** |
| Evidence citation accuracy | 0.9661 | 0.9667 | **0.9672** |
| Sequence accuracy | 0.3125 | 0.28125 | **0.28125** |

Sprint 3B keeps the same status and exact-case counts while improving step
precision, recall, F1 and field accuracy. The gain comes from activity-backed
support classification (`case_10`, `case_19`), correct evidence ordering, and
legal-hold applicability checks. Legal-hold PDF rows still add
policy-required `VERIFY_RECORD_PRESENT` steps that the public sample answers do
not include, so exact-step precision remains below Sprint 2C.

Generated status distribution:

```text
Sample (32):   COMPLETE=9  INCOMPLETE=23  NOT_APPLICABLE=0
Eval (518):    COMPLETE=143 INCOMPLETE=365 NOT_APPLICABLE=10
```

Sample status mismatch: `case_04` is expected `COMPLETE` but is classified
`INCOMPLETE` because the only account evidence is a partial failover replica
that does not contain `account_004` and has no explicit complete snapshot
scope. Treating that replica as proof of absence would violate the snapshot
coverage rule, so the account stays unresolved. The remaining exact-step
mismatches are missing account/analytics/audit verification steps caused by
unresolved links, plus evidence-citation differences that do not change status.

Output validation:

```text
sample: PASS  rows=32  errors=0
eval:   PASS  rows=518 errors=0
```

Tests:

```text
242 passed (219 prior sprints + 23 Sprint 3B)
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
│   │   ├── coverage.py
│   │   ├── errors.py
│   │   ├── identifiers.py
│   │   ├── index.py
│   │   ├── manifest.py
│   │   ├── models.py
│   │   ├── multimodal.py
│   │   ├── report.py
│   │   ├── service.py
│   │   ├── ocr/
│   │   │   ├── engine.py
│   │   │   └── windows_ocr.ps1
│   │   └── parsers/
│   │       ├── base.py
│   │       ├── image.py
│   │       ├── json_parser.py
│   │       ├── log.py
│   │       ├── pdf.py
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
21. **Candidate is a result, not a link.** Workflow-window account candidates
    carry `CANDIDATE` and stay outside `linked_resources`; a coverage decision
    may use one but remains provisional.
22. **Absence needs a complete scope.** A replica, inventory or JSON bundle that
    does not declare a complete subject universe can never prove absence.
23. **Legal holds are date-aware.** An expired `retain_until` makes the hold
    inactive; a hold with no date is active by presence, not unknown.
24. **OCR can corroborate but cannot promote.** OCR links stay `INFERRED` and
    `verified=False`; conflicting identities block them, and OCR resource IDs
    are never rewritten.

## Known limitations (Sprint 3C Correctness Review)

- No `account_id` inference from `user_id` and no confirmed link from a bare
  numeric convention. Accounts absent from evidence remain `CANDIDATE` or
  unresolved, not guessed links. This is why `case_01`, `case_02` and `case_04`
  remain `INCOMPLETE` against the public `COMPLETE`.
- The dataset contains no complete snapshot scope. SQL replicas, the inventory
  capture and JSON bundles are explicitly non-complete, so absence cannot be
  proven from any current evidence file.
- `observed_state=UNKNOWN` remains common in logs that only contain a lookup
  start or a resource identifier without a completion/status field.
- `evidence_90` parses successfully but contains no data observations and is
  reported as a parse warning.
- Log and SQL records do not always carry a `data_category`; the index keeps
  them with `UNKNOWN` category rather than inferring one.
- Workflow-window account candidates are deliberately broad and may include
  unrelated activity. They are `CANDIDATE`, excluded from linked resources, and
  never treated as confirmed identity mappings.
- Activity-only and activity-promoted states remain provisional
  (`verified=False`) and are documented in the audit result.
- Redaction verification recognizes explicit null identifier fields and literal
  `[REDACTED]` markers, but not the logfmt string `null` used to serialize
  nulled requester fields, nor a `[REDACTED]` marker on a log row whose
  `data_category` is absent. Twelve evaluation support cases therefore remain
  conservatively `INCOMPLETE`.
- Account/analytics/audit resources that were never linked cannot produce the
  corresponding verification steps; this reduces step-level recall but not the
  status decision in most cases.
- OCR confidence is a fixed conservative value, and OCR text can misread
  characters. Confusable-character matching is limited to identity comparison;
  resource IDs are never rewritten or auto-corrected.
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

Sprint 4 / production hardening should add:

1. A snapshot-scope contract from the dataset owner that explicitly declares a
   complete subject universe, so absence proofs can be used without weakening
   the current conservative rule.
2. Account-link calibration that uses independently supplied evidence (for
   example a complete account snapshot or explicit request-to-account
   reference), never numeric naming conventions.
3. Redaction-marker normalization: recognize the logfmt string `null` (nulled
   requester fields) and a `[REDACTED]` marker on log rows with absent
   `data_category`, so those support records are verified from direct evidence
   rather than conservatively left `UNKNOWN`.
4. Additional synthetic conflict cases for legal holds, multi-replica drift,
   overlapping workflow windows and same-user multi-case isolation.
5. Packaging instructions for the original challenge submission
   (`code.zip`, `code/evaluation/` copies, and chat transcript) if required.
6. Optional LLM classification only for requests the deterministic classifier
   marks `UNCERTAIN`, with structured output, caching, and a token/cost report.

## Sprint 3C: decision accuracy and policy calibration

Sprint 3C deliberately prioritizes evidence validity over public-sample score.
The baseline was reproduced before edits (`242 passed`, status `31/32`, exact
case `9/32`, step F1 `0.8877`). The final run has `249 passed`; both the 32-row
sample and 518-row evaluation outputs pass structural validation.

Two production rules changed:

- workflow-window account candidates are uncertainty only. A deletion activity
  without an identity link is not proof that the account belongs to the subject
  and is not proof of absence;
- support message/attachment policy is derived from record evidence, not from
  the historical remediation operation. Ambiguous support records remain
  `UNKNOWN`.

Completeness now requires no policy coverage gap. Consequently, final public
sample status accuracy is `23/32` and exact-case accuracy is `8/32`; this is a
measured benchmark regression, not an attempt to optimize the score. Eight
sample `COMPLETE` answers became `INCOMPLETE` because no subject-linked account
resource exists. Across the 518 evaluation requests, 94 cases made the same
transition. No resource identifier was invented to recover those scores.

Evaluation now reports status accuracy, exact step-set accuracy, exact sequence
accuracy, step precision/recall/F1, six-field accuracy, benchmark citation
equality, contract validity, structured case diagnostics, and failure taxonomy.
Use the new comparator to capture status and step-only changes:

```powershell
$env:PYTHONPATH = "src"
& ".\.venv\Scripts\python.exe" -m privacyguard compare-output `
  --before reports/sprint3c_baseline_eval_output.csv `
  --after reports/sprint3c_eval_output.csv `
  --json-out reports/sprint3c_eval_comparison.json
```

Measured Sprint 3C artifacts are under `reports/sprint3c_*`. The detailed Arabic
engineering report is `reports/sprint3c_final_report_ar.md`.

## Sprint 3C Correctness Review (final)

The correctness review corrected two over-corrections and tightened one
verification rule:

- the `No account resource could be linked to the identity` gap no longer blocks
  completion; an unresolved candidate is uncertainty only;
- a confirmed resource without deletion proof (unknown or unverified absence)
  still blocks completion;
- redaction and anonymization are verified only from direct evidence, never from
  a `REDACT_RECORD`/`ANONYMIZE_RECORD` activity claim alone;
- absence is proven only by a complete authoritative snapshot.

Final measured state:

```text
tests                  : 262 passed (with -W error, zero warnings)
sample status accuracy : 29/32 (0.9062)
exact case matches     : 8/32 (0.2500)
step F1                : 0.8571
field accuracy         : 0.7881
evidence accuracy      : 0.9483
contract validity      : 32/32
eval distribution      : 129 COMPLETE / 379 INCOMPLETE / 10 NOT_APPLICABLE
```

Remaining sample status mismatches are `case_01`, `case_02` and `case_04`: the
public answers cite account identifiers (`account_001`, `account_002`,
`account_004`) that are not attributable from participant-visible evidence, so
they are not inferred. The final Arabic engineering report is
`reports/sprint3c_correctness_review_final_ar.md`.
