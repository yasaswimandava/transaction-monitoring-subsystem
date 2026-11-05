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
produce meaningful multi-rule corroboration (see the pairwise overlap matrix
in `metrics.json`).

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

**On this dataset:** 1,348 flagged pre-budget, 599 survive the budget cut
(44.4%). Correlates strongly with R4 (81 overlapping txns — bursts of
micro-charges are often card-testing).

---

## R2 — New-device + high-value spend

**Pattern:** ATO via SIM-swap or credential stuffing. Attacker logs in from
their own device and cashes out within hours. One of the highest-signal
patterns in consumer fintech.

**Logic:** first-ever appearance of `(user_id, device_id)` after the user has
≥ 20 historical txns, AND the txn is within 24h of that first-seen, AND the
amount exceeds 5 × user's **prior** median (floored at $150 so tiny-median
users don't get spammed). "Prior" means the median of amounts strictly before
this txn — the new device's own charge never contributes to the baseline it's
being tested against.

**Threshold:** `min_history=20`, `multiple=5`, `floor=$150`, `lookahead=24h`.

**Point-in-time correctness:** median is computed over the user's txns strictly
*before* the current one. Full-period median would let the attacker's cashout
drag its own baseline up and mask itself.

**False-positive tradeoff:** travel scenarios (new vacation phone). Analysts
can usually tell within the first txn's merchant context.

**On this dataset:** 395 flagged pre-budget, all 395 survive the budget cut.
Highest severity (5) because the pattern has the lowest false-positive rate of
the five and R2 txns are small enough in volume that none are dropped.

---

## R3 — Amount anomaly vs user's own baseline

**Pattern:** Stolen-card cashout. Attacker puts the card to work on a single
large charge — travel, electronics, prepaid-card purchases.

**Logic:** amount > `max(1.5 × user's prior p99, $300)`. Users need ≥ 20
historical txns to have a trustworthy baseline.

**Threshold:** `quantile=0.99`, `multiplier=1.5`, `floor=$300`.

**Point-in-time correctness (reviewer counterexample):** p99 is computed over
the user's txns strictly *before* the current one. A naïve full-period p99 lets
the spike drag its own threshold up: 20 × $10 + 1 × $500 gives p99 ≈ $402,
threshold = $603, and the $500 does **not** fire. Prior-only p99 on the same
baseline is $10, threshold is $300 (from the floor), and the $500 fires — which
is exactly what the rule is supposed to detect.

**False-positive tradeoff:** Legitimate once-a-year big spend (rent, deposit,
tax payment). The $300 floor is deliberately conservative to let these through
when the user's own baseline is already $200+.

**On this dataset:** 1,715 flagged pre-budget. The point-in-time rewrite raised
the raw count from the previous (biased) 1,182 — unsurprising, since prior-only
p99 is always ≤ full-period p99, so more txns clear the ratio test.
R3's survival rate at the budget cut is 12.3% — 1,504 of its flags are dropped
in favor of multi-rule corroborated hits and higher-severity singletons. That
is the rule paying the most for the shared 1,000-flag budget, and it is a
deliberate choice: single-txn amount signal is the weakest of the five.

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

**Logic:** a txn fires when, by the time it happens, the device has already
been used by ≥ 4 distinct `user_id`s (including the current txn's user).
Surface the first 5 qualifying txns per device *by timestamp*.

**Threshold:** `user_threshold=4`, `top_n_per_device=5`.

**Point-in-time correctness:** two steps, both strictly as-of:

1. **Firing**: the distinct-user count is a *running* tally. Txns from the
   first three users on a device do **not** fire just because the device
   later serves many users. Using the eventual (end-of-file) count would
   retroactively flag innocent txns that happened before the device looked
   suspicious.
2. **Per-device cap**: once a device has more than 5 qualifying txns, the cap
   picks the *first 5 by timestamp*, not the 5 highest-amount. Amount-sorting
   would let a later large purchase retroactively displace an earlier
   qualifying txn from the output — a subtler form of the same look-ahead
   bias.

**False-positive tradeoff:** shared family phones exist — hence the per-device
cap, which keeps one legitimate shared device from flooding the queue.

**On this dataset:** 95 flagged pre-budget, 22 survive the budget cut (23.2%).

---

## Severity ordering

Severity is set per rule and drives the budget-trim tiebreak. The ranking is
based on signal-to-noise, not on analyst dollar impact:

| Rule | Severity | Why |
|---|---|---|
| R2 — new-device + high-value | 5 | Two independent corroborating signals (new device AND amount anomaly within 24h) — among the lowest false-positive profiles in consumer fraud. |
| R4 — micro-charge sweep | 5 | ≥5 distinct merchants under $2 in 30 min is near-definitionally card testing. Very low legitimate-traffic analogue. |
| R1 — velocity burst | 4 | Strong signal, but legitimate bursts exist (split bills, retry loops). Flagging only the 6th+ txn in the burst limits false positives but doesn't eliminate them. |
| R3 — amount anomaly | 3 | Single-signal rule. One large txn on a user's own device is explainable (rent, deposit, electronics) and relatively often legitimate. |
| R5 — device sharing | 3 | Shared family devices exist; the per-device cap limits damage but a 4-user threshold still has genuine false-positive risk. |

R2 and R4 share severity 5 because both carry independent corroborating
signal (R2: device + amount; R4: multi-merchant + micro-amount). R1 sits one
tier below because velocity alone is noisier. R3 and R5 share severity 3
because each is a single-signal rule that an analyst would want more context on
before escalating.

## Threshold calibration against the review budget

Each rule has one primary calibration knob. The table below shows how
pre-budget candidate counts move as that knob is varied around its chosen
value on the 1M-row dataset. This is how the thresholds were sized against
the 1,000-flag analyst budget — not label recall, which stays post-hoc.

Reproduce with `python scripts/sensitivity.py`.

| Rule | Knob | Value | Pre-budget count |
|---|---|---:|---:|
| R1 | `burst_count` (10-min window) | 5 | 3,689 |
| R1 | | **6 (chosen)** | **1,348** |
| R1 | | 7 | 515 |
| R1 | | 8 | 204 |
| R2 | amount `floor` ($) | 50 | 437 |
| R2 | | 100 | 426 |
| R2 | | **150 (chosen)** | **395** |
| R2 | | 300 | 306 |
| R3 | amount `floor` ($) | 150 | 2,946 |
| R3 | | 200 | 2,467 |
| R3 | | **300 (chosen)** | **1,715** |
| R3 | | 500 | 834 |
| R4 | `distinct_merchants` (30-min window) | 4 | 165 |
| R4 | | **5 (chosen)** | **93** |
| R4 | | 6 | 44 |
| R5 | `user_threshold` (distinct users/device) | 3 | 180 |
| R5 | | **4 (chosen)** | **95** |
| R5 | | 5 | 65 |
| R5 | | 6 | 45 |

Reading the table:

- **R1 at 5** produces 3,689 candidates — larger than the entire budget on its
  own. Dropping to 6 cuts volume ~63% and leaves R1 contributing a defensible
  share of the final 1,000. Going to 7 or 8 trims volume further but also
  skips a plausible fraud shape — a legitimate 7-txn-in-10-min burst is rarer
  than a 6-txn one, so pushing the threshold higher narrows what the rule
  catches, not what it rejects.
- **R2 is relatively insensitive to the floor** — stepping the floor from $50
  to $150 only trims 42 txns. The choice is driven by false-positive reasoning
  (tiny-median users making a routine $75 gift-card purchase on a newly-seen
  phone shouldn't fire), not by budget pressure.
- **R3's floor is where budget pressure is most visible.** $150 gives 2,946
  candidates — three times the analyst budget by this one rule alone. $300
  keeps R3 under 2k pre-budget; $500 would squeeze it further but cuts the
  "mid-range stolen-card cashout" segment ($300–$500) that the rule is partly
  designed for.
- **R4 at 4 merchants** doubles the flag count but weakens the "card testing
  looks like card testing" story — 4 distinct micro-charges in 30 min is
  plausible for a legitimate rapid-fire shopper. 5 is the smallest value
  where the pattern looks unambiguously like BIN validation.
- **R5 at 3 users** nearly doubles the flag count. 3-user households exist
  (parents + one kid). 4 draws a cleaner line between "shared device" and
  "device farm".

## Budget enforcement

The analyst team can review ~1,000 flags per 1M txns. Our rules collectively
produced 3,335 pre-budget flags (after merging same-txn hits across rules).
The merge-and-trim step:

1. Groups per-rule flags by `txn_id`, concatenating reasons and taking the max
   severity.
2. Sorts by `(rule_count DESC, severity DESC)`.
3. Takes the top 1,000.

This prefers multi-rule corroborated hits (they're almost always worth an
analyst's time) and higher-severity single-rule hits. Per-rule survival at the
budget cut is reported in `metrics.json` under `per_rule_budget_survival` so a
reviewer can see exactly what each rule lost at the trim step rather than
guessing from the aggregate.

**Observed survival on this run (1,000-flag budget):**

| Rule | Pre-budget | Survived | Dropped | Survival rate |
|---|---:|---:|---:|---:|
| R1 | 1,348 | 599 | 749 | 44.4% |
| R2 | 395 | 395 | 0 | 100% |
| R3 | 1,715 | 202 | 1,513 | 11.8% |
| R4 | 93 | 93 | 0 | 100% |
| R5 | 95 | 22 | 73 | 23.2% |

R2 and R4 keep everything because their raw counts fit well within the budget
even after ranking. R3 pays the most because its rank — single signal, severity
3 — puts it near the bottom of the sort key. That tradeoff is explicit by
design: if a single large txn is the only evidence we have, the analyst's time
is better spent on multi-rule hits.

### What we knowingly let through

- **Slow-burn ATO** that stays under the velocity window and the amount
  anomaly floor. R2 catches some of this; the rest is systematically invisible
  to a 90-day, column-limited rule set.
- **Mule activity on new devices** with txns below $150. The $150 floor on R2
  trades recall for a lower false-positive rate — a tiny-median user who buys a
  $100 gift card on a newly-seen phone would otherwise fire R2 every weekend.
  The floor is a design choice, not a label-tuned threshold.
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
