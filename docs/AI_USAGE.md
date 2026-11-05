# How Claude was used on this project

The spec invites LLM use and asks us to call out where we caught the model's
mistakes. This doc is honest about both.

## Where Claude helped

- **Scaffolding.** First-pass `pyproject.toml`, `.gitignore`, directory layout,
  and the `Rule` protocol came from Claude. All of it got read and edited
  before commit.
- **Pandas idioms.** The groupby-rolling and time-window patterns went through
  a few iterations; Claude knew the shortcuts (e.g., `transform("count")` for
  per-user counts).
- **Reason strings.** First drafts of the analyst-facing reason strings came
  from Claude. I rewrote them to use `|` as a separator and to lead with the
  most material fact (the amount, the device, the user median).
- **Test scaffolding.** The synthetic-frame fixture and the AAA-style test
  structure.

## Where I overrode Claude

1. **Tuning to the labels.** The model initially suggested maximizing recall
   against `confirmed_fraud.csv`. I rejected this — the label set is biased
   per the spec, and tuning to it overfits. See `docs/LABELS_NOTE.md`.
2. **"Flag everything in the burst".** Early velocity-rule drafts flagged
   every txn in a burst window. That spends the whole 1,000-flag budget on a
   handful of incidents. I changed it to flag only the Nth-and-later txns.
3. **No rule engine.** The model suggested a DSL or Drools-style rule
   framework. I explicitly cut that: 5 rules × simple vectorizable logic does
   not justify framework friction inside a 2–3 hour timebox.
4. **Rolling-window alignment bug.** The first version of `VelocityRule` used
   `on="timestamp"` with `groupby(...).rolling(...)`, which produced a result
   indexed by `(user_id, timestamp)` rather than `(user_id, row_idx)`. My
   `reindex(df.index)` call silently returned all NaN. The test caught it; I
   rewrote the rule to rely on the post-sort row order instead.
5. **Amount-anomaly test was wrong.** The first pass used 25 baseline txns +
   1 anomaly, which skewed p99 enough that the anomaly didn't exceed its own
   skewed baseline. I bumped the baseline to 100 txns so p99 stays close to
   the true baseline and the test exercises the real-world case.
6. **Merchant normalization scope.** The model's first `normalize_merchant`
   stripped many token classes. I narrowed it to just case + whitespace +
   trailing `#<digits>`, because aggressive normalization risks collapsing
   genuinely distinct merchants (e.g. `AMAZON FRESH` vs `AMAZON`).

## What I did NOT delegate

- **Rule selection and threshold calibration.** Picking what 5 patterns
  matter, and tuning their thresholds against the 1,000-flag budget, is the
  judgment the problem is testing. That stayed in my head.
- **Budget-trade reasoning.** "What fraud do we knowingly let through, and
  why" is in `docs/RULES.md` and reflects my own thinking, not the model's.
- **The decision to keep this flat.** No framework, no DSL, no premature
  abstractions — the problem fits in one afternoon's worth of code, and that
  is what I shipped.

## Workflow

Claude Code (Opus 4.7) drove the implementation turn-by-turn, with me reading
every diff before accepting it. The TaskList tool tracked progress. I ran
`pytest` after each rule implementation and re-ran on real data once. Total
author time was well under the 3-hour budget; the saved time went into the
docs you're reading now.
