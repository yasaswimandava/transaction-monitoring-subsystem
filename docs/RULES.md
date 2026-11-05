# Proposed Rules

All rules are computable from the six provided columns (`txn_id`, `user_id`,
`timestamp`, `merchant_name`, `amount`, `device_id`). No external data.

## The five rules, rated by fraud-pattern value

| ID | Name | Fraud pattern | Priority | Implemented |
|---|---|---|---|---|
| R1 | Velocity burst | Card testing / ATO cash-out burst | 1 | ✅ |
| R2 | New-device spike | ATO via SIM-swap or credential stuffing | 1 | ✅ |
| R3 | Amount anomaly | Stolen-card single-shot cashout | 2 | ✅ |
| R4 | Micro-charge sweep | Post-breach BIN validation | 2 | ✅ |
| R5 | Device sharing | Mule ring / account farming | 3 | ✅ |

All five shipped. Spec requires ≥3; the extra two cost < 50 lines each and
measurably improve precision when combined.

---

## R1 — Velocity burst

**Pattern:** Card testing or ATO burst. Fraudsters who just got hold of a card
or an account cash out fast before the user notices. Six legitimate charges in
10 minutes is already an unusual day; past that threshold the signal flips.

**Logic:** rolling count of transactions per user in a `window`-minute window.
Fire on the Nth and later txn in the burst (not every txn in the window) so one
incident doesn't eat the whole budget.

**Threshold:** `burst_count = 6`, `window = 10 min`.

**False-positive tradeoff:** legitimate rapid-fire patterns exist — splitting a
bill across apps, replaying a cart. These usually show up at low amounts; a
fraud-ops analyst dismisses them in seconds.

**On this dataset:** 1,348 flagged pre-budget. Correlates strongly with R4
(81 overlapping txns — bursts of micro-charges are often card-testing).

---

## R2 — New-device + high-value spend

**Pattern:** ATO via SIM-swap or credential stuffing. Attacker logs in from
their own device and cashes out within hours. One of the highest-signal
patterns in consumer fintech.

**Logic:** first-ever appearance of `(user_id, device_id)` after the user has
≥ 20 historical txns, AND the txn is within 24h of that first-seen, AND the
amount exceeds 5 × user's median (floored at $150 so tiny-median users don't
get spammed).

**Threshold:** `min_history=20`, `multiple=5`, `floor=$150`, `lookahead=24h`.

**False-positive tradeoff:** travel scenarios (new vacation phone). Analysts
can usually tell within the first txn's merchant context.

**On this dataset:** 424 flagged. Highest severity (5) because the pattern has
the lowest false-positive rate of the five. 58 txns co-fire with R3.

---

## R3 — Amount anomaly vs user's own baseline

**Pattern:** Stolen-card cashout. Attacker puts the card to work on a single
large charge — travel, electronics, prepaid-card purchases.

**Logic:** amount > `max(1.5 × user's p99, $300)`. Users need ≥ 20 historical
txns to have a trustworthy baseline.

**Threshold:** `quantile=0.99`, `multiplier=1.5`, `floor=$300`.

**False-positive tradeoff:** Legitimate once-a-year big spend (rent, deposit,
tax payment). The $300 floor is deliberately conservative to let these through
when the user's own baseline is already $200+.

**On this dataset:** 1,182 flagged. Lower severity (3) because the single-txn
signal is weaker than R2's device signal.

---

## R4 — Micro-charge card testing across merchants

**Pattern:** Post-breach BIN validation sweep. An attacker sprays sub-$2
charges across many merchants to find which stolen cards are still live.

**Logic:** within a 30-min window, user has ≥ 5 distinct normalized merchants
with amounts < $2.

**Threshold:** `window=30min`, `micro_threshold=$2`, `distinct_merchants=5`.

**False-positive tradeoff:** very low — legitimate users don't make $1 charges
across 5 merchants in half an hour. But also low recall on this dataset — the
synthetic data has limited card-testing signal.

**On this dataset:** 93 flagged. Low volume, high confidence. Deferral note:
this would be the first rule I'd cut if forced to keep only 4, but it's cheap
to run (29 ms) and 81 of its 93 flags co-fire with R1 — strong corroboration.

---

## R5 — Device shared across many users

**Pattern:** Mule ring / account farming. One device operating many accounts
is overwhelmingly a fraud operation.

**Logic:** device serves ≥ 4 distinct `user_id`s across its lifetime. Surface
the top 5 txns by amount per such device.

**Threshold:** `user_threshold=4`, `top_n_per_device=5`.

**False-positive tradeoff:** shared family phones exist — hence the top-N-per-
device cap, which keeps one legitimate shared device from flooding the queue.

**On this dataset:** 95 flagged. Multiple suspicious devices surfaced (one
device serving 14 distinct users made the top-5 hits across several R2
flags — this is the kind of pattern that really does warrant investigation).

---

## Budget enforcement

The analyst team can review ~1,000 flags per 1M txns. Our rules collectively
produced 2,957 pre-budget flags. The merge-and-trim step:

1. Groups per-rule flags by `txn_id`, concatenating reasons.
2. Sorts by `(rule_count DESC, severity DESC)`.
3. Takes the top 1,000.

This prefers multi-rule corroborated hits (they're almost always worth an
analyst's time) and higher-severity single-rule hits.

### What we knowingly let through

- **Slow-burn ATO** that stays under the velocity window and the amount
  anomaly floor. R2 catches some of this; the rest is systematically invisible
  to a 90-day, column-limited rule set.
- **Mule activity on new devices** with txns below $150. R2's floor was tuned
  to keep the flag rate within budget; lowering it to $50 doubled R2's count
  without a matching recall gain against the labels.
- **Single-merchant fraud** (attacker spends only at one merchant). No rule
  currently targets single-merchant abuse — would be R6, but we have no
  per-merchant risk signal to key off.
- **Refund abuse.** The dataset contains refunds (10 non-positive amounts) but
  the volume is too small to support a rule, and the spec says "positive =
  debit" — refund-chain exploitation is a rule for a different release.

### Deferral reasoning (if we had to cut rules)

If I had to ship only 3 rules, I would keep **R1, R2, R3** — they catch the
highest-severity patterns and together account for the vast majority of
labeled-fraud hits. I would defer R4 (low volume, high confidence but
easily added later) and R5 (needs more design around "legitimate shared
device" to avoid flooding flags from one household).
