# PrivacyGuard AI — Sprint 2C Evaluation Report

## Scope

This report evaluates the deterministic audit pipeline that consumes
`AuditContext` data and produces:

- `COMPLETE`, `INCOMPLETE`, or `NOT_APPLICABLE`
- ordered `steps_json`
- a structurally validated `output.csv`

The public golden set is `dataset/sample_output.csv`. It is used for evaluation
only and is never used as a production lookup table. Hidden-answer accuracy is
not claimed.

## Test suite

Full local test run:

```text
205 passed in 17.01s
```

Breakdown:

```text
Prior sprints (Sprint 1 + 2A + 2B) : 162 passed
Sprint 2C tests                   : 43 passed
Total                             : 205 passed
```

Sprint 2C tests cover:

- multilingual request intent classification
- non-deletion / NOT_APPLICABLE handling
- typed policy rule loading
- category resolution with explicit evidence and corroborated hints
- DELETE / REDACT / ANONYMIZE / RETAIN / BLOCK_RESTORE / DISABLE_DATA_FLOW
- active data-flow and restore-risk findings
- tombstone redaction
- unknown categories and unknown states
- step ordering, consecutive numbering, deduplication and evidence rules
- output CSV structural validation
- sample and evaluation pipeline runs
- four independent synthetic end-to-end cases

## Sample metrics

Evaluated against `dataset/sample_output.csv`:

| Metric | Actual |
|---|---:|
| Cases | 32 |
| Status accuracy | 31/32 = 0.96875 |
| Exact case matches | 10/32 = 0.3125 |
| Step precision | 0.9571 |
| Step recall | 0.8083 |
| Step F1 | 0.8764 |
| Field accuracy | 0.8135 |
| Evidence citation accuracy | 0.9661 |
| Sequence accuracy | 0.3125 |

### Status confusion matrix

| Expected \ Actual | COMPLETE | INCOMPLETE | NOT_APPLICABLE |
|---|---:|---:|---:|
| COMPLETE | 9 | 1 | 0 |
| INCOMPLETE | 0 | 22 | 0 |
| NOT_APPLICABLE | 0 | 0 | 0 |

The public samples contain no `NOT_APPLICABLE` case. The evaluation dataset
produces 10 `NOT_APPLICABLE` rows, all with `steps_json=[]`.

## Per-case diagnostics

### Status mismatch

| Case | Expected | Actual | Cause |
|---|---|---|---|
| `case_04` | `COMPLETE` | `INCOMPLETE` | No account or analytics resource could be linked without inventing an identifier. The case has zero evidence-backed resources and no unique account activity candidate. |

### Step mismatch patterns

| Pattern | Cases | Explanation |
|---|---|---|
| Missing account/analytics verification | `case_03`, `case_21`, `case_25`, `case_26`, `case_27`, `case_28`, `case_31`, and others | The resources have no explicit identifier link or are absent from evidence, so the pipeline does not invent them. |
| Evidence ID differs | `case_01`, `case_02` | Pipeline cites the `activity_id` from the unique account deletion event; public answers cite `evidence_54`. Both are valid evidence references under the challenge contract. |
| Support message treated as REDACT | `case_10` | The support replica log does not expose the record type/condition. The pipeline applies the conservative support-message redaction rule instead of DELETE. |
| Unresolved state verification | `case_17` | An unresolved tombstone produces a future verification check in addition to the public answer's steps. |
| Missing PDF-backed finding | `case_07` | `evidence_58` is a PDF and is explicitly unsupported; `support_001` cannot be parsed. |
| Missing account/audit steps | `case_09`, `case_18`, `case_20`, `case_22`, `case_23`, `case_24`, `case_29`, `case_30` | Account/audit resources were not linked or were activity-only; no verification step is invented. |

## Output validation

```text
Sample output: PASS  rows=32  errors=0  warnings=0
Eval output:   PASS  rows=518 errors=0  warnings=0
```

The validator checks:

- exact header `case_id,deletion_status,steps_json`
- exactly 32/518 expected rows
- unique and sorted case IDs
- valid JSON arrays
- exactly seven step fields
- legal phases, operations and operation-state pairs
- consecutive `step_no`
- phase/operation/system/resource ordering
- findings and COMPLETE verification with evidence
- empty evidence for remediation and future verification
- no duplicate steps
- known evidence/activity/audit IDs

## Independent synthetic cases

Implemented in `tests/evaluation/test_synthetic.py`:

1. `case_9001` — complete tombstone: account absent, audit retained present,
   tombstone redacted. Expected and actual `COMPLETE` with three verification
   steps.
2. `case_9002` — replica/flow violation: account present, search present, active
   data flow, audit present. Expected and actual `INCOMPLETE` with findings,
   remediation and verification.
3. `case_9003` — access request: expected and actual `NOT_APPLICABLE` with an
   empty step array.
4. `case_9004` — restore-enabled backup: expected and actual `INCOMPLETE` with
   `REPORT_RESTORE_RISK`, `BLOCK_RESTORE` and `VERIFY_RESTORE_BLOCKED`.

All four pass.

## Failures found and improvements made

- Added deterministic multilingual intent classification with explicit
  NOT_APPLICABLE handling.
- Added corroborated category resolution rather than relying on resource-ID
  prefixes alone.
- Added a conservative account coverage decision for the unique account
  deletion event in the workflow window.
- Added future verification steps for known-category resources whose state is
  still `UNKNOWN`, avoiding silent empty step arrays.
- Added strict evidence-reference validation against known evidence, activity
  and audit IDs.
- Added output CSV writing and structural/semantic validation.

## Limitations

- No PDF/image extraction.
- Account linkage remains the main source of missing verification steps.
- Some support/replica records have ambiguous categories.
- `case_04` cannot be proven complete without inventing an identifier.
- No hidden-test accuracy is claimed.
