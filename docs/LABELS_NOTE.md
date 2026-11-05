# On `confirmed_fraud.csv`

## How we used it

**As a post-hoc check, not for tuning.** The pipeline computes recall against
the 190 labeled txns after the thresholds are frozen. We never adjusted a
threshold to improve this number.

## Why not use it for tuning?

The spec is explicit: the label set is incomplete and biased — customers only
report fraud they notice, and some categories (small, slow, mule-driven) are
systematically underreported. Specifically:

- **190 labels on 999,940 cleaned rows ≈ 0.019%.** That is one-fifth of our
  analyst budget. Tuning to maximize recall against this sample means
  overfitting to the fraud the customer already caught, and ignoring the
  fraud they didn't.
- **Dispute data is skewed to high-visibility fraud.** A card-testing sweep of
  $1.50 charges rarely gets disputed (or is caught by the issuer before
  reaching the user). A stolen-card cashout at $800 almost always does. If we
  tune to this signal we systematically underweight R4 and overweight R3.
- **Threshold tuning via the label set is a feedback loop.** The rules begin
  to encode "look like the fraud we already know" rather than "look like fraud
  in general". That is a failure mode of label-driven tuning in fraud.

## What the two recall numbers tell you

The pipeline reports recall against the 190 labeled fraud txns at two points:

- **Pre-budget recall: 70.0%** (133 / 190). Of the labeled fraud, this is how
  much our rules catch *before* the 1,000-flag trim. That is the ceiling of
  what our rule set can see given its thresholds.
- **Post-budget recall: 45.3%** (86 / 190). After trimming to the 1,000-flag
  analyst budget, this is how much actually reaches a reviewer.

The gap between the two (24.7 percentage points, or 47 labeled fraud txns) is
the direct cost of the budget cut — mostly R3 single-rule hits that get
outranked by multi-rule corroborated flags. The per-rule survival table in
`metrics.json` shows exactly which rule paid for the budget.

Both numbers are post-hoc — never used to adjust thresholds. They are reported
so a reviewer can see the recall-vs-precision tradeoff explicitly instead of
the pipeline hiding the cost of its own budget decision.

## What the recall numbers do NOT tell you

- **They do not measure total fraud recall.** We only see labels for fraud the
  customer reported. The 57 labeled fraud txns our rules missed entirely
  (190 − 133 pre-budget) are known misses; the dataset almost certainly
  contains additional unlabeled fraud that neither the labels nor our rules
  surface. Neither number estimates that denominator.
- **They do not validate the rules against underreported patterns.** Mule
  activity (R5) and card testing (R4) are structurally underreported in
  dispute data. Low recall against the labels for those rules is expected
  and not a bug.
- **They are not a precision estimate.** We have no "confirmed legit" set, so
  false-positive rate is unknown. The best we can say is that an analyst
  reviewing 1,000 flags, of which 86 are known-bad, will see corroborated
  evidence (multi-rule hits) for a substantial fraction of the rest — see the
  pairwise overlap matrix in `metrics.json`.

## What we'd want next

- A **confirmed-legit sample** (even a few thousand txns) would let us
  estimate per-rule false-positive rate.
- A **wider label window** (not just dispute-based) — e.g., issuer
  authorization declines, device reputation signals — would let us validate
  R4 and R5 honestly.
- **Time-split evaluation** (train rules on month 1, evaluate on months 2–3)
  to check for threshold drift. Our fixed thresholds are a first pass.
