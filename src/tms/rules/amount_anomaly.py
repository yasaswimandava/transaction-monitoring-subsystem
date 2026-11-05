"""R3 — Amount anomaly vs user baseline (point-in-time).

Pattern: stolen-card single-shot cashout. Attacker who got access to an account
often makes one or two large charges — rental deposits, electronics, airline
tickets — well above the victim's normal spend.

Flag: ``amount`` exceeds BOTH the user's prior p99 historical amount AND a
fixed dollar floor. The floor matters because a user whose p99 is $10 would
otherwise get flagged on a $30 Uber.

Point-in-time correctness: p99 is computed over txns strictly *before* the
current one. Including the current txn in its own baseline can hide exactly
the spike the rule is meant to detect (20 x $10 + one $500 drags p99 up to
~$400 and masks the $500).
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .base import FLAG_COLUMNS


@dataclass
class AmountAnomalyRule:
    id: str = "R3"
    name: str = "amount_anomaly"
    priority: int = 2
    min_history: int = 20
    quantile: float = 0.99
    floor: float = 300.0
    multiplier: float = 1.5

    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        grp_user = df.groupby("user_id", sort=False)
        prior_count = grp_user.cumcount()
        prior_p99 = grp_user["amount"].transform(
            lambda s: s.shift(1).expanding().quantile(self.quantile)
        )
        threshold = (prior_p99 * self.multiplier).clip(lower=self.floor)
        mask = (prior_count >= self.min_history) & (df["amount"] > threshold)
        if not mask.any():
            return pd.DataFrame(columns=FLAG_COLUMNS)
        hits = df.loc[mask, ["txn_id", "amount"]].copy()
        hits["p99"] = prior_p99[mask].round(2)
        hits["threshold"] = threshold[mask].round(2)
        hits["rule_id"] = self.id
        hits["reason"] = [
            f"${a:.2f} vs user prior p99 ${p:.2f} (threshold ${t:.2f}) — possible stolen-card cashout"
            for a, p, t in zip(hits["amount"], hits["p99"], hits["threshold"])
        ]
        hits["severity"] = 3
        return hits[FLAG_COLUMNS]
