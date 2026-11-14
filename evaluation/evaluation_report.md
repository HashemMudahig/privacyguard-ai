# PrivacyGuard AI — Evaluation Report (Sprint 3C Correctness Review Final)

## Scope

This report records the evaluation history from Sprint 2C through the Sprint 3C
Correctness Review. Earlier sprint sections are retained as historical
benchmarks; the current implementation is the Sprint 3C Correctness Review.

The public golden set is `dataset/sample_output.csv`. It is used for evaluation
only and is never used as a production lookup table. Hidden-answer accuracy is
not claimed.

## Sprint 3C Correctness Review — Final

The correctness review removed an over-broad account-coverage rule that blocked
completion whenever no account resource was linked, and tightened redaction
verification so a `REDACT_RECORD` activity claim alone is never treated as
proof of redaction.

Test suite after the correctness review:

```text
262 passed in 28.13s   (with -W error, zero warnings)
```

### Final metrics

| Metric | Sprint 3C (measured) | Correctness Review (final) |
|---|---:|---:|
| Tests | 249 passed | **262 passed** |
| Status accuracy | 23/32 (0.7188) | **29/32 (0.9062)** |
| Exact case matches | 8/32 (0.2500) | **8/32 (0.2500)** |
| Step precision | 0.8537 | **0.9329** |
| Step recall | 0.7254 | **0.7927** |
| Step F1 | 0.7843 | **0.8571** |
| Field accuracy (six-field) | 0.7772 | **0.7881** |
| Evidence accuracy | 0.7241 | **0.9483** |
| Output contract validity | 32/32 | **32/32 (1.0000)** |

Evaluation distribution:

```text
Sprint 3C:       49 COMPLETE / 459 INCOMPLETE / 10 NOT_APPLICABLE
Correctness:     129 COMPLETE / 379 INCOMPLETE / 10 NOT_APPLICABLE
```

Output validation:

```text
sample: PASS  rows=32  errors=0
eval:   PASS  rows=518 errors=0
```

### Remaining sample status mismatches (3)

`case_01`, `case_02` and `case_04` are expected `COMPLETE` but classified
`INCOMPLETE`. In each case the public answer cites an account resource that is
not attributable from participant-visible evidence:

- `case_01` / `case_02`: the answer cites `evidence_54` for `account_001` /
  `account_002`, but that failover replica does not contain those identifiers.
- `case_04`: the answer cites `account_004` (absent from all supplied evidence)
  and `analytics_901` (an analytics record with no identity identifier).

These are not addressed with sample-specific logic; the subject–resource
relationship is unsupported and cannot be inferred safely from timing or
numeric convention.

### Redaction verification (12 evaluation cases)

Twelve evaluation cases moved `COMPLETE → INCOMPLETE` versus Sprint 3C because
their support records carry a `REDACTED` state supported only by a
`REDACT_RECORD SUCCESS` activity claim, without direct evidence (explicit null
requester fields or a literal redaction marker). Per the evidence rules, an
activity result is a claim, so these remain `UNKNOWN` rather than being accepted
as compliant.

Eleven of the twelve serialize the nulled requester fields as the literal
string `null` (logfmt), which the current null-field detection does not treat as
a null value; one (`case_264`) carries `message_text="[REDACTED]"` on a log row
whose `data_category` is absent. These are documented as conservative
uncertainties, not as confirmed policy violations. Production behavior was not
changed to recover the benchmark score.

## Sprint 3B update (historical)

Test suite after Sprint 3B:

```text
242 passed in 29.23s
```

The 23 new tests cover account candidates, candidate coverage decisions,
snapshot absence/presence ambiguity, legal holds (active, expired, undated,
absent), activity-backed support classification, OCR corroboration, conflicting
OCR identities, same-user multi-case isolation and overlapping workflow
activity.

### Metrics before and after

| Metric | Sprint 3A | Sprint 3B |
|---|---:|---:|
| Status accuracy | 31/32 (0.96875) | **31/32 (0.96875)** |
| Exact case matches | 9/32 (0.28125) | **9/32 (0.28125)** |
| Step precision | 0.9244 | **0.9419** |
| Step recall | 0.8238 | **0.8394** |
| Step F1 | 0.8712 | **0.8877** |
| Field accuracy | 0.8290 | **0.8446** |
| Evidence citation accuracy | 0.9667 | **0.9672** |
| Sequence accuracy | 0.28125 | **0.28125** |

Generated distributions are unchanged:

```text
Sample (32):   COMPLETE=9  INCOMPLETE=23  NOT_APPLICABLE=0
Eval (518):    COMPLETE=143 INCOMPLETE=365 NOT_APPLICABLE=10
```

Output validation:

```text
sample: PASS  rows=32  errors=0
eval:   PASS  rows=518 errors=0
```

### Improvements

- Activity-backed support classification fixes the category choice for
  `case_10` (`SUPPORT_ATTACHMENT`/`DELETE`) and preserves `case_19`
  (`SUPPORT_MESSAGE`/`REDACT`) while citing snapshot evidence first.
- Evidence ordering and legal-hold applicability improve step precision,
  recall, F1 and field accuracy without changing status.
- Account resources that appear only in the workflow window are now explicit
  `CANDIDATE` records. They are excluded from linked resources, so overlapping
  activity from unrelated users cannot silently become an identity link.
- Snapshot absence proofs are represented explicitly. The current dataset has
  no complete snapshot scope, so no absence is proven; this is reported rather
  than inferred from a partial replica.
- OCR corroboration now checks text evidence, activity and historical identity
  references, blocks conflicting identities, and tolerates only narrowly
  scoped OCR confusions during identity comparison. Resource IDs are never
  rewritten.

### Regressions / remaining mismatches

- `case_04` remains `INCOMPLETE` versus the public `COMPLETE`. The only account
  evidence is a failover replica that does not contain `account_004` and does
  not declare a complete subject universe. Using it as an absence proof would
  violate the snapshot coverage rule. The analytics resource `analytics_901`
  also has no identity identifier, so it cannot be linked without inference.
- Legal-hold PDF rows still add policy-required `VERIFY_RECORD_PRESENT` steps
  that the public sample answers omit, so exact-step precision remains below
  Sprint 2C.
- Unlinked account/analytics/audit resources still reduce step-level recall.
- OCR cannot recover every identifier; suspicious or uncorroborated resource
  IDs remain unresolved rather than auto-corrected.

## Sprint 3A baseline (historical)

## Test suite

Baseline before Sprint 3A:

```text
205 passed
```

Actual final run after Sprint 3A:

```text
219 passed in 29.33s
```

The new tests cover:

- text-based and multi-page PDFs
- blank and malformed PDFs
- PNG evidence through a synthetic OCR engine
- OCR unavailable / corrupted image handling
- resource and identifier extraction from OCR rows
- duplicate OCR rows for the same resource
- timestamp extraction from human-readable and ISO formats
- provenance, page numbers, image regions and extraction methods
- low-confidence OCR evidence and temporal filtering
- corroborated vs uncorroborated multimodal resource linking
- prevention of OCR identity mixing across rows
- PDF text links remaining verified

## Evidence coverage

| Item | Sprint 2C | Sprint 3A |
|---|---:|---:|
| Manifest entries | 94 | 94 |
| Supported entries | 79 | **94** |
| Unsupported entries | 15 | **0** |
| Parsed files | 79 | **94** |
| Parse failures | 0 | **0** |
| Normalized observations | 3,469 | **3,499** |
| PDF observations | 0 | **9** |
| PNG observations | 0 | **21** |
| Parse warnings | 1 | **17** |

All 4 PDF files and all 11 PNG files were processed successfully:

```text
PDF : 4/4 parsed
PNG : 11/11 OCR-processed
```

No evidence file was silently dropped. Warnings explicitly identify OCR
uncertainty, missing primary resource IDs, unknown PDF categories, embedded PDF
images, and `evidence_90`'s zero observations.

## PDF extraction results

| File | Result |
|---|---|
| `evidence_18` account history statement | 1 observation, `NST-2026-0718-1842`, user_18, ingrid email; category unknown and kept unresolved |
| `evidence_27` legal retention register | 6 legal-hold row observations on page 2 (`ORD-20264118`, `ORD-20264207`, `ORD-20264319`, `ORD-20264402`, `ORD-20264511`, `ORD-20264600`) |
| `evidence_55` security retention extract | `audit_record_003`, user_03, `SECURITY_AUDIT_LOG`, page 1 |
| `evidence_58` delivery correction attachment | `support_001`, priya email, `SUPPORT_ATTACHMENT`, page 1 |

The delivery attachment PDF makes `case_07` an exact-step match. The legal
retention register adds policy-required retained-record verification steps for
explicit `user_08`, `user_12`, `user_17`, `user_21`, `user_24` and `user_29` rows.
The public sample answers do not include those legal-hold steps, so exact-step
and precision metrics decrease even though the policy behavior is correct.

## PNG extraction results

Representative extractions:

| File | Extracted relation |
|---|---|
| `evidence_04` account admin console | `account_5762`, haruka email, `USER_PROFILE`, PRESENT |
| `evidence_09` search inspector | `search_428`, user_13, `SEARCH_INDEX_ENTRY`, PRESENT |
| `evidence_14` connector console | `data_flow_1121`, jain email, `DATA_FLOW`, ACTIVE |
| `evidence_19` analytics profile | `analytics_7438`, user_20, `ANALYTICS_PROFILE`, PRESENT |
| `evidence_23` export console | `export_1260`, ingrid email, `USER_EXPORT`, PRESENT |
| `evidence_28` support ticket | `support_1034`, kagyeman email, `SUPPORT_MESSAGE`, PRESENT |
| `evidence_32` backup console | `backup_9287`, `BACKUP_ARCHIVE`, PRESENT; OCR misread other backup IDs |
| `evidence_37` security audit | `audit_record_003`, user_03, `SECURITY_AUDIT_LOG`, PRESENT |
| `evidence_60` marketing console | `marketing_001`, sj.park email, `MARKETING_PROFILE`, PRESENT |
| `evidence_42` deleted account reference | identity-only `user_17`, `ACCOUNT_TOMBSTONE`, REDACTED; no standard tombstone resource ID visible |
| `evidence_46` object storage browser | no standard resource or user identifier; document-level observation only |

OCR is imperfect. Observed examples include `search_42B` (actual `search_428`),
`gmaiI.com` (actual `gmail.com`), and misread backup archive IDs. These values
are never auto-corrected into fabricated identifiers. Uncorroborated OCR
resource IDs are dropped as unresolved; OCR-derived links that survive require
text evidence or activity corroboration and remain `verified=False`.

## Sample metrics before and after

| Metric | Sprint 2C | Sprint 3A |
|---|---:|---:|
| Status accuracy | 31/32 (0.96875) | **31/32 (0.96875)** |
| Exact case matches | 10/32 (0.3125) | **9/32 (0.28125)** |
| Step precision | 0.9571 | **0.9244** |
| Step recall | 0.8083 | **0.8238** |
| Step F1 | 0.8764 | **0.8712** |
| Field accuracy | 0.8135 | **0.8290** |
| Evidence citation accuracy | 0.9661 | **0.9667** |
| Sequence accuracy | 0.3125 | **0.28125** |

### Status distribution

```text
Sample (32):   COMPLETE=9  INCOMPLETE=23  NOT_APPLICABLE=0
Eval (518):    COMPLETE=143 INCOMPLETE=365 NOT_APPLICABLE=10
```

Status accuracy and evaluation status distribution are unchanged. Multimodal
evidence does not change any sample status.

### Improvements

- `case_07` now exactly matches: the PDF yields `support_001` as
  `SUPPORT_ATTACHMENT`, enabling the missing finding and remediation.
- Step recall improved from 0.8083 to 0.8238.
- Field accuracy improved from 0.8135 to 0.8290.
- Evidence accuracy improved slightly from 0.9661 to 0.9667.
- OCR images add findings for evaluation cases including `case_33`, `case_34`,
  `case_35`, `case_39`, `case_50`, `case_52`, `case_53`, `case_55` and `case_63`
  without changing their status.

### Regressions / remaining mismatches

- Legal-hold PDF rows add `VERIFY_RECORD_PRESENT` steps for `case_08`,
  `case_12`, `case_17`, `case_21`, `case_24` and `case_29`; these steps are not
  in the public sample answers, reducing exact-step and precision scores.
- `case_04` remains `INCOMPLETE` because no account/analytics resource can be
  linked without inventing an identifier.
- In Sprint 3A, `case_10` used REDACT instead of DELETE for a support record
  with an ambiguous replica-log category; Sprint 3B fixes this with
  activity-backed classification.
- Account/analytics/audit resources that were never linked still produce
  missing verification steps.
- OCR cannot recover every identifier; unreadable values are reported rather
  than guessed.

## Output validation

```text
sample: PASS  rows=32  errors=0
eval:   PASS  rows=518 errors=0
```

## Independent synthetic tests

Added in `tests/unit/test_multimodal_parsers.py`, `tests/unit/test_state_engine.py`
and `tests/integration/test_linking.py`:

- synthetic PNG + fake OCR resource extraction
- identity-only OCR observation
- OCR unavailable and corrupted image
- blank and malformed PDF
- multi-page PDF provenance
- duplicate OCR resource rows
- timestamp extraction
- low-confidence and post-audit OCR evidence
- corroborated vs uncorroborated OCR links
- OCR identity mixing prevention
- PDF text link verification

## Limitations

- No external vision model or paid API is used.
- PNG OCR depends on Windows OCR and is unavailable elsewhere.
- OCR confidence is a fixed conservative value; Windows OCR does not expose
  reliable per-word confidence through this integration.
- Some screenshots contain no standard resource ID and remain identity-only or
  document-level observations.
- PDFs with only embedded images are reported as requiring OCR; they are not
  silently treated as empty evidence.

## Sprint 3C measured evaluation (pre-review, historical)

Baseline (recalculated before Sprint 3C edits):

| Metric | Baseline |
|---|---:|
| Tests | 242 passed |
| Status accuracy | 31/32 (0.9688) |
| Exact case | 9/32 (0.2812) |
| Step precision | 0.9419 |
| Step recall | 0.8394 |
| Step F1 | 0.8877 |
| Field accuracy (legacy definition) | 0.8446 |
| Evidence equality | 0.9672 |

Final:

| Metric | Sprint 3C |
|---|---:|
| Tests | 249 passed |
| Status accuracy | 23/32 (0.7188) |
| Exact case | 8/32 (0.2500) |
| Exact step set | 8/32 (0.2500) |
| Exact sequence | 8/32 (0.2500) |
| Step precision | 0.8537 |
| Step recall | 0.7254 |
| Step F1 | 0.7843 |
| Six-field accuracy | 0.7772 |
| Benchmark evidence equality | 0.7241 |
| Output contract validity | 32/32 (1.0000) |

The field metric changed definition and is therefore not directly comparable
to the legacy baseline field metric. Final field accuracy aligns steps
deterministically across phase, system, resource, operation, state and evidence,
and penalizes missing and extra steps.

All 518 evaluation rows validated. Distribution changed from
`143 COMPLETE / 365 INCOMPLETE / 10 NOT_APPLICABLE` to
`49 COMPLETE / 459 INCOMPLETE / 10 NOT_APPLICABLE`. The comparator found 116
changed cases: 94 status changes (`COMPLETE` to `INCOMPLETE`) caused exclusively
by missing subject-linked account coverage, and 22 step-only changes. Full case
lists are in `reports/sprint3c_eval_comparison.json`.

The score decrease is intentional evidence calibration. The public reference
links resources that cannot always be attributed from participant-visible data;
for example, `case_04` has no reliable link to `account_004` or
`analytics_901`, and `evidence_54` does not contain `account_001` or
`account_002`. Those identifiers are not promoted from timing coincidence.
