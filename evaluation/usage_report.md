# PrivacyGuard AI — Sprint 2C Usage Report

## Summary

The production audit path is fully deterministic. No LLM, hosted model, paid
API, or external inference service is called.

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

## Final run

The final `output.csv` was generated from:

```text
dataset directory : D:\HackerRank Project\hackerrank-orchestrate-october26\dataset
evaluation requests: 518
sample requests    : 32
output file        : privacyguard-ai/output.csv
```

Generated status distribution:

```text
COMPLETE       143
INCOMPLETE     365
NOT_APPLICABLE  10
Total          518
```

Sample run:

```text
COMPLETE         9
INCOMPLETE      23
NOT_APPLICABLE   0
Total           32
```

## Measured runtime

On the current Windows environment:

```text
Pipeline initialization (dataset + evidence + indexes) : ~0.65s
Audit 32 sample cases                                  : ~0.05s
Audit 518 evaluation cases                            : ~0.74s
Write evaluation CSV                                  : ~0.02s
Validate evaluation CSV                               : ~0.02s
Evaluate sample metrics                               : ~0.002s
Full pytest suite                                      : 17.01s
```

## Token/cost policy

Because the pipeline is deterministic:

- token accounting is not applicable;
- no model-call count is fabricated;
- no estimated cost is fabricated;
- no API keys or provider credentials are required.

If an optional LLM fallback is added later for `UNCERTAIN` intent requests, its
provider, model, call count, input/output tokens and cost must be recorded in a
new version of this report.
