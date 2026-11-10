# Recon accuracy report

Normalizer: `normalizer_v1`

| Metric | Value |
|---|---|
| Auto-suggest precision | 100.00% |
| Overall recall | 97.00% |
| Top-1 recall | 95.67% |
| Auto-suggest rate | 39.67% |
| Review rate | 57.33% |
| Unmatched rate | 3.00% |
| Gate violations | 0 |
| Labelled pairs | 300 |

## Counts

```json
{
  "auto_suggest": 119,
  "candidates": 353,
  "ledger_lines": 449,
  "review": 172,
  "statement_lines": 300,
  "tier4_abandoned": 9,
  "tier4_nodes": 154531,
  "unmatched": 9
}
```

## What it does not catch

- Screenshot or scan-only PDFs. v1 refuses them rather than guessing.
- Matches outside the configured amount and date windows.
- Parties whose narration and reference both change completely.
- Anything requiring an accounting judgement rather than a data match.
