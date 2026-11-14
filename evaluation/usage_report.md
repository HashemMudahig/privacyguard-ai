# PrivacyGuard AI — Sprint 3C Correctness Review Usage Report

## Summary

The production audit path is deterministic. No LLM, hosted model, paid API, or
external inference service is called. PDF text extraction uses local `pypdf`;
PNG OCR uses the built-in Windows OCR engine through a bundled local PowerShell
script.

```text
Model providers          : none
Model names              : none
Model calls              : 0
Input tokens             : 0
Output tokens            : 0
Total tokens             : 0
Average tokens/request   : 0
Estimated total cost     : $0.00
Estimated cost/request   : $0.00
```

## Final run (Sprint 3C Correctness Review)

```text
dataset directory : D:\HackerRank Project\hackerrank-orchestrate-october26\dataset
evaluation requests: 518
sample requests    : 32
output files       : privacyguard-ai/output.csv
                     privacyguard-ai/reports/recovery_eval_output.csv
                     privacyguard-ai/reports/recovery_sample_output.csv
```

Generated status distribution:

```text
COMPLETE       129
INCOMPLETE     379
NOT_APPLICABLE  10
Total          518
```

Sample distribution:

```text
COMPLETE         7
INCOMPLETE      25
NOT_APPLICABLE   0
Total           32
```

Sample evaluation metrics (against `dataset/sample_output.csv`):

```text
status accuracy   : 29/32 (0.9062)
exact case matches: 8/32 (0.2500)
step precision    : 0.9329
step recall       : 0.7927
step F1           : 0.8571
field accuracy    : 0.7881
evidence accuracy : 0.9483
contract validity : 32/32 (1.0000)
```

Sprint 3B measured distribution (historical): `143 COMPLETE / 365 INCOMPLETE /
10 NOT_APPLICABLE`. Sprint 3C measured distribution (historical, pre-review):
`49 COMPLETE / 459 INCOMPLETE / 10 NOT_APPLICABLE`.

## Multimodal processing

```text
PDF files parsed        : 4/4
PNG files OCR-processed : 11/11
PDF observations        : 9
PNG observations        : 21
Unsupported files       : 0
Parse failures          : 0
```

Local OCR does not call an external service and does not consume tokens.

## Sprint 3B deterministic logic (historical)

Sprint 3B adds no model or network dependency:

- account candidates are grouped from local `system_activity.csv` rows and kept
  outside confirmed links;
- legal-hold dates come from local PDF/JSON text;
- snapshot coverage is computed from local SQL/JSON evidence;
- OCR corroboration uses only local evidence, activity and historical identity
  values;
- no sample case ID, expected account ID or `sample_output.csv` value is used
  in production logic.

Sample evaluation metrics after Sprint 3B:

```text
status accuracy   : 31/32 (0.96875)
exact case matches: 9/32 (0.28125)
step precision    : 0.9419
step recall       : 0.8394
step F1           : 0.8877
field accuracy    : 0.8446
evidence accuracy : 0.9672
sequence accuracy : 0.28125
```

## Sprint 3C Correctness Review deterministic logic

The correctness review adds no model or network dependency and changes two
local semantics:

- an account candidate in the workflow window is uncertainty only and never
  becomes a confirmed missing resource, a policy decision, or a completion
  blocker;
- a `REDACTED`/`ANONYMIZED` state is verified only from direct evidence (an
  explicit null identifier field or a literal redaction marker), never from a
  `REDACT_RECORD`/`ANONYMIZE_RECORD` activity claim alone;
- absence is proven only by a complete authoritative snapshot, never by a
  partial or unscoped snapshot.

## Measured runtime

On the current Windows environment:

```text
Pipeline initialization (dataset + all evidence + OCR + coverage) : ~6.9s
Audit 32 sample cases                                          : ~0.07s
Audit 518 evaluation cases                                     : ~1.1s
Full pytest suite (with -W error)                              : 28.13s
```

The initialization cost is dominated by local OCR over 11 PNG screenshots and
building the snapshot coverage index. Parsing is cached in-process for repeated
engine use.

## Dependencies

```text
pydantic>=2.7
pypdf>=7.0
pillow>=13.0
```

PNG OCR additionally requires Windows 10/11 PowerShell and an installed Windows
OCR language pack. On systems without Windows OCR, PNG evidence is explicitly
reported as OCR-unavailable.

## Token/cost policy

Because the pipeline is deterministic and local:

- token accounting is not applicable;
- no model-call count is fabricated;
- no estimated cost is fabricated;
- no API keys or provider credentials are required.

If an optional LLM or vision fallback is added later, its provider, model, call
count, input/output tokens and cost must be recorded in a new version of this
report.
