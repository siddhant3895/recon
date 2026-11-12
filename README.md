# Recon — CA Reconciliation Prep Layer

> **"You review. It does the typing."**
> Deterministic reconciliation prep for Indian Chartered Accountancy firms.

Recon is a **working prototype** (not a hosted service) that matches bank statement lines
against client ledger lines, proposes scored candidates, and lets a human reviewer accept,
reject, or unmatch each one from a keyboard-first worklist. Output is an XLSX/CSV
reconciliation schedule you feed into your existing filing software.

---

## Project Status — Read This First

What exists and works today:

- A deterministic **4-tier matching cascade** with hard gates, explainable 0–100 scores,
  and bounded subset-sum search for split payments.
- A **CLI** to run matching, generate the demo/golden datasets, evaluate accuracy, run a
  synthetic benchmark, and purge raw files past a retention timestamp.
- A **FastAPI web app**: marketing pages, a live demo worklist running the real engine on
  synthetic data, XLSX/CSV export from your review decisions, and an append-only in-memory
  decision audit log.
- **72 automated tests** covering normalization, similarity, cascade behavior, allocation
  invariants, export safety, the API, and the purge job.

What does **not** exist yet (be honest with yourself before deploying):

- No authentication, user accounts, or multi-tenancy.
- No database — the demo workspace and audit log live in process memory.
- No file-upload endpoint; ingestion is via the CLI on files you provide.
- No encryption at rest/in transit (the dev server speaks plain HTTP).
- No hosted scheduling for the purge job — it is a command you run.

See `web/security.html` for the full honest list.

---

## Verified Benchmarks

Measured on a **synthetic, seeded golden dataset** (300 labelled pairs, 449 ledger lines,
40 adversarial cases in four categories) by `python -m recon accuracy`:

| Metric | Measured Value | Specification Bar | Result |
|---|---|---|---|
| Auto-Suggest Precision (Score ≥ 95) | **100.00%** | ≥ 97.00% | PASSED |
| Overall Recall | **97.00%** | ≥ 85.00% | PASSED |
| Top-1 Candidate Recall | **95.67%** | ≥ 90.00% | PASSED |
| Gate Violations | **0** | 0 | PASSED |
| Determinism | **Byte-identical across repeated runs** | Identical | VERIFIED |
| Tier-4 search bound | **5,000 nodes / group** | Bounded | VERIFIED |

These numbers describe the synthetic golden set only — they are not a claim about
accuracy on any firm's real data. The report is reproducible:

```bash
python -m recon accuracy     # rewrites data/accuracy_report.json + .md
```

---

## Quickstart

Requires Python 3.11+.

```bash
pip install -e .            # or: pip install fastapi uvicorn pyyaml openpyxl pytest httpx
python -m pytest -q         # run the test suite (72 tests)
python -m recon serve --port 8000
```

Then open:

- `http://localhost:8000/` — marketing site + ROI calculator
- `http://localhost:8000/demo` — live keyboard-first review app (synthetic data)

### CLI

```bash
python -m recon accuracy                                   # evaluate golden set
python -m recon build-golden --out data/golden.json --seed 42
python -m recon demo --format csv --out out                # demo run exports
python -m recon match --statement stmt.json --ledger ledger.json --out out --format both
python -m recon benchmark --rows 5000                      # synthetic performance check
python -m recon purge --registry data/uploads.json --storage data/storage
```

`match` accepts normalized JSON records (`id`, `date`, `amount_paise`, `direction`,
`text`); see `recon/models.py` and `data/golden.json` for the schema.

---

## Architecture

```
part2/
├── data/
│   ├── golden.json             # seeded 300-pair golden dataset
│   ├── accuracy_report.json    # machine-readable metrics
│   └── accuracy_report.md      # human-readable summary
├── recon/
│   ├── __main__.py             # CLI entrypoint
│   ├── cli.py                  # accuracy / demo / match / benchmark / purge / serve
│   ├── normalizer.py           # normalizer_v1: paise, ref tokens, dates, direction
│   ├── similarity.py           # Jaro-Winkler, token-set ratio, ref similarity
│   ├── scoring.py              # gates + 45/25/20/10 component scoring
│   ├── cascade.py              # 4-tier cascade + bounded subset-sum DFS
│   ├── engine.py               # matching coordinator (duplicate-ID guard)
│   ├── golden.py               # deterministic dataset generator (seed=42)
│   ├── metrics.py              # precision/recall/gate evaluation
│   ├── export.py               # XLSX/CSV export, decision honoring, formula-injection guard
│   ├── purge.py                # retention job with purged/skipped/failed audit events
│   └── service.py              # FastAPI app + static page handler
├── web/                        # HTML pages, CSS, JS (no build step)
│   ├── index.html  how-it-works.html  accuracy.html  security.html
│   ├── pricing.html  demo.html  shadow-month.html  about.html
│   ├── legal/terms.html  legal/privacy.html  legal/dpa.html
│   └── static/css/style.css
│       static/js/review-app.js  calculator.js  shadow-form.js
└── tests/
    ├── test_normalizer.py  test_similarity.py  test_cascade.py
    ├── test_export.py  test_service.py  test_purge.py  test_acceptance.py
```

### Matching pipeline

1. **Normalize** both sides identically: NFKC, case folding, Indian banking boilerplate
   stripping, UTR/reference extraction (8+ digit runs, account-number contexts masked),
   punctuation cleanup preserving Devanagari combining marks, integer paise, strict
   date parsing, direction inference (`dr`/`cr` suffixes, conflict rejection).
2. **Apply hard gates** per tier: direction, amount tolerance, date window.
3. **Cascade tiers** (first tier producing candidates wins):
   - Tier 1: exact amount, same day, overlapping reference token.
   - Tier 2: exact amount, ±3 days, reference Jaro-Winkler ≥ 0.85.
   - Tier 3: ±2% amount, ±30 days, narration token-set ratio ≥ 0.60.
   - Tier 4: 1 statement line vs 2–4 ledger lines, sum within ±₹1 or ±0.5%, ±10 days,
     5,000-node bounded DFS (abandons deterministically at the cap).
4. **Score** every candidate: amount 45 + date 25 + reference 20 + narration 10, with a
   plain-English reason string.
5. **Human review** in the worklist: Enter accept, R reject, U unmatch, Ctrl+Z undo.
   Every decision is appended to an audit log; undo is itself an audited row.

---

## Review App Keyboard Map

| Key | Action |
|---|---|
| <kbd>J</kbd> or <kbd>↓</kbd> | Move to next statement line |
| <kbd>K</kbd> or <kbd>↑</kbd> | Move to previous statement line |
| <kbd>Enter</kbd> | Accept focused candidate match |
| <kbd>Tab</kbd> | Cycle through candidate proposals for the current row |
| <kbd>R</kbd> | Reject candidate (audited reason: wrong amount / party / period / duplicate / other) |
| <kbd>U</kbd> | Mark statement line as unmatched |
| <kbd>Ctrl+Z</kbd> / <kbd>Cmd+Z</kbd> | Undo the latest still-active decision |
| <kbd>?</kbd> | Toggle the shortcuts dialog |
| <kbd>Esc</kbd> | Close the active dialog |

Notes on invariants the app and API enforce (covered by tests): a statement line may have
only one active decision at a time; the same ledger line cannot be allocated to two
different accepted statements; an undo row cannot itself be undone; a decision can only be
undone once.

---

## Deployment Notes

The included web app is a development server. Before exposing Recon beyond localhost:

- Do not process real client data through the demo endpoints — they are in-memory and
  unauthenticated by design.
- Add authentication, HTTPS termination, and tenant isolation.
- Wire the purge job to a scheduler and your own storage layer.
- Treat the legal pages as unexecuted drafts for lawyer review.

## License

See `LICENSE`.
