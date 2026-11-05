# Transaction Monitoring Subsystem

Rule-based batch fraud monitor for consumer fintech. Ingests a ~1M-row
transaction CSV and emits a budgeted set of flagged transactions for a
fraud-ops analyst team to review.

- Full pipeline on 1M rows: **~5.4 seconds** on a laptop (M-series, cold cache).
- Budget-respecting: flags trimmed to 1,000 per 1M (0.1%) by default.
- Point-in-time features — rules that look at per-user history use prior-only
  aggregates so a txn never contributes to the baseline it's being tested against.
- 17 targeted tests covering ingest, each rule, merge, and budget trimming.

## Run it (under 10 minutes from a fresh clone)

```bash
# 1. Python 3.9+ venv
python3 -m venv .venv && source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'

# 2. Download the two supplied CSVs and put them in data/
#    data/transactions.csv
#    data/confirmed_fraud.csv

# 3. Run
python -m tms.cli
```

Download the assignment inputs: [transactions.csv](https://drive.google.com/file/d/1aRY6Yf0vQFqoSEg77npv92iJsl16snYP/view) and [confirmed_fraud.csv](https://drive.google.com/file/d/1MS6ZKhhx6v8BYQYWGysBsULiI-nsJLzo/view). The raw CSVs are excluded from Git. If you already have them elsewhere, use `--txns` and `--fraud` with their paths instead of copying them into `data/`.

The pip upgrade is needed for older Python 3.9 environments whose bundled pip cannot install this `pyproject.toml` project in editable mode. The `[dev]` extra installs pytest for the test command below.

Outputs land in `out/`:

- `flagged.csv` — `txn_id, rules_fired, reason, severity`
- `metrics.json` — per-rule counts, overlap, timings, recall vs confirmed fraud

The repo also ships pre-generated `out/flagged.csv` and `out/metrics.json` from
the latest run, so you can inspect the output without running the pipeline.
Running the pipeline overwrites them.

### Options

```bash
python -m tms.cli --txns PATH --fraud PATH --out DIR --budget 1000
```

## Tests

```bash
python -m pytest
```

17 tests, <1s runtime. Cover ingest cleaning, each rule's positive and negative
cases (including point-in-time regressions for R3 and the R5 output selection),
and the end-to-end pipeline on a synthetic CSV.

## What this ships

- **5 rules proposed**, **all 5 implemented**. See [docs/RULES.md](docs/RULES.md).
- **1,000-flag budget** enforced globally (prefers multi-rule hits + severity
  when trimming).
- **Vectorized pandas** throughout — no per-row Python loops.
- **Post-hoc recall** against `confirmed_fraud.csv` — not used for tuning. See
  [docs/LABELS_NOTE.md](docs/LABELS_NOTE.md).

## What was cut, and why

With the 2–3 hour timebox, I prioritized:

1. **Rules that generalize.** Every rule works from the 6 provided columns
   alone, with no external enrichment (no MCC tables, no geo, no account
   tenure).
2. **One pipeline, one entry point.** No framework. A thin `Rule` protocol and
   a vectorized `apply(df) -> flags` function per rule. Easier to defend in a
   follow-up than a DSL.
3. **Targeted tests, not full coverage.** Edge cases where the math is
   non-obvious (rolling windows, p99 floors, merchant normalization). Not every
   branch.

Deliberately skipped:

- **Real-time / streaming.** Spec said out of scope.
- **ML model.** Spec said out of scope; and labels are too few (190) and biased
  to train on.
- **Rule engine (Drools, durable_rules, etc.).** 5 rules with simple
  vectorizable logic — framework overhead > benefit.
- **UI, Docker, CI, auth, deployment.** Spec said not evaluated.
- **Polars / DuckDB.** Pandas finishes in ~5s on 1M rows; swapping was not worth
  the risk.

## Numbers from the latest run

| Metric | Value |
|---|---|
| Input rows | 1,001,000 |
| Rows after cleaning | 999,940 |
| Dropped: dup `txn_id` | 1,000 |
| Dropped: bad timestamps | 20 |
| Dropped: non-positive/null amounts | 25 |
| Dropped: null merchants | 15 |
| Pre-budget flags | 3,335 |
| Final flags (budget = 1,000) | 1,000 |
| Flag rate | 0.10% |
| Recall vs 190 confirmed fraud (pre-budget) | 70.0% (133 / 190) |
| Recall vs 190 confirmed fraud (post-budget) | **45.3% (86 / 190)** |
| Total wall-clock | 5.48 s |

Per-rule counts: R1 1,348 · R2 395 · R3 1,715 · R4 93 · R5 95.

Per-rule budget survival (how many of each rule's hits made the 1,000-flag cut):

| Rule | Pre-budget | Survived | Survival rate |
|---|---:|---:|---:|
| R1 | 1,348 | 599 | 44.4% |
| R2 | 395 | 395 | 100% |
| R3 | 1,715 | 202 | 11.8% |
| R4 | 93 | 93 | 100% |
| R5 | 95 | 22 | 23.2% |

Threshold calibration against the budget is documented in
[docs/RULES.md](docs/RULES.md#threshold-calibration-against-the-review-budget)
and reproducible with `python scripts/sensitivity.py`.

See `out/metrics.json` after a run for full numbers (timings, pairwise overlap,
per-rule survival detail).

## Repository layout

```
src/tms/
  ingest.py          # CSV load, dedup, parse, normalize
  rules/
    base.py          # Rule protocol + flag schema
    velocity.py      # R1 — rolling burst
    new_device.py    # R2 — first-seen device + high amount
    amount_anomaly.py# R3 — amount > user p99 with dollar floor
    card_testing.py  # R4 — micro-charges across many merchants
    device_sharing.py# R5 — one device, many users
  pipeline.py        # merge, budget trim, recall, timings
  cli.py             # typer entrypoint
tests/               # ingest, rule, pipeline tests
scripts/
  sensitivity.py     # threshold-vs-budget sweep (reproduces the RULES.md table)
docs/
  RULES.md           # 5 rules + rationales + deferral reasoning + calibration
  LABELS_NOTE.md     # how confirmed_fraud.csv was (not) used
  AI_USAGE.md        # LLM leverage + mistakes I caught
```

## Further reading

- [docs/RULES.md](docs/RULES.md) — the 5 rules, rationale, thresholds, budget trade
- [docs/LABELS_NOTE.md](docs/LABELS_NOTE.md) — what the 45.3% recall does and doesn't tell you
- [docs/AI_USAGE.md](docs/AI_USAGE.md) — where Claude helped and where I overrode it
