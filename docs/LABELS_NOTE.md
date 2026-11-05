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

## What the 43.2% recall tells you

82 of 190 labeled fraud txns landed in our 1,000-flag budget. That is strong
precision-vs-budget evidence:

- Our thresholds, tuned only on fraud-pattern reasoning, surface 43% of known
  fraud while using 0.1% of total volume.
- Multi-rule hits (R1+R2, R1+R4, R2+R3+R5, etc.) show up repeatedly in the
  labeled subset — corroboration across independent signals is real.

## What the 43.2% recall does NOT tell you

- **It does not measure total fraud recall.** We only see labels for fraud the
  customer reported. The unlabeled 108 misses include an unknown mix of
  genuine misses and genuinely benign txns.
- **It does not validate the rules against underreported patterns.** Mule
  activity (R5) and card testing (R4) are structurally underreported. Low
  recall against the labels for those rules is expected and not a bug.
- **It is not a precision estimate.** We have no "confirmed legit" set, so
  false-positive rate is unknown. The best we can say is that an analyst
  reviewing 1,000 flags, of which 82 are known-bad, will see corroborated
  evidence for most of the rest (per the multi-rule overlap matrix in
  `metrics.json`).

## What we'd want next

- A **confirmed-legit sample** (even a few thousand txns) would let us
  estimate per-rule false-positive rate.
- A **wider label window** (not just dispute-based) — e.g., issuer
  authorization declines, device reputation signals — would let us validate
  R4 and R5 honestly.
- **Time-split evaluation** (train rules on month 1, evaluate on months 2–3)
  to check for threshold drift. Our fixed thresholds are a first pass.
