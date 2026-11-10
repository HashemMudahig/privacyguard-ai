# PrivacyGuard AI

AI-powered personal data deletion auditing agent.

**Current status: Sprint 1 — identity resolution foundation.** This repository
does **not** yet implement evidence parsing, policy decisions, remediation
planning, PDF/image extraction, or final `output.csv` generation.

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

Tests:

```text
45 passed
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
│   └── identity/
│       ├── index.py
│       ├── report.py
│       └── resolver.py
└── tests/
    ├── conftest.py
    ├── unit/
    └── integration/
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
6. **The 10 `NOT_APPLICABLE` cases are not classified in this sprint.** Intent
   classification and deletion-status decisions are out of scope.

## Known limitations (Sprint 1)

- No `account_id` inference. The earlier discovery report identified this as
  the largest unresolved risk; Sprint 1 deliberately does not guess it.
- No PDF or image parsing (PDF and OCR/vision belong to a later sprint).
- No policy engine, risk detector, remediation planner, or `output.csv`.
- `.env` is not auto-loaded; use PowerShell environment variables or pass CLI
  flags explicitly.
- The 32 sample requests do not include any `NOT_APPLICABLE` case, so that
  output shape is still untested against real data.
- Exact row counts in integration tests are tied to the current challenge
  dataset; if the dataset is regenerated, update the expected counts.

## Tests

```powershell
$env:PYTHONPATH = "src"
& ".\.venv\Scripts\python.exe" -m pytest -o addopts="" -q
```

Integration tests skip automatically when the dataset directory is absent and
`PG_DATASET_DIR` is not set.

## Next sprint

Sprint 2 should add:

1. An evidence index with SQL/JSON/log/text parsers and `captured_at` filtering.
2. A temporal state engine (`present`, `absent`, `redacted`, `anonymized`,
   `active`, `disabled`, `blocked`) at `audit_at`.
3. Calibration of `account_id` linkage against the 32 sample answers.
4. The deletion policy engine over `deletion_rules.csv`.
