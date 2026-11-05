"""R3 — Amount anomaly vs user baseline.

Pattern: stolen-card single-shot cashout. Attacker who got access to an account
often makes one or two large charges — rental deposits, electronics, airline
tickets — well above the victim's normal spend.

Flag: ``amount`` exceeds BOTH the user's p99 historical amount AND a fixed
dollar floor. The floor matters because a user whose p99 is $10 would otherwise
get flagged on a $30 Uber.

Design notes:
- "Historical" means all txns in the dataset — we only have 90 days. In a real
  system this would be a trailing window keyed off account tenure.
- Users with fewer than ``min_history`` txns are skipped. Not enough signal to
  trust the baseline; flagging them would just surface new accounts.
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
    multiplier: float = 1.5  # must exceed p99 by this factor

    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        grp = df.groupby("user_id", sort=False)["amount"]
        counts = grp.transform("count")
        p99 = grp.transform(lambda s: s.quantile(self.quantile))
        threshold = (p99 * self.multiplier).clip(lower=self.floor)
        mask = (counts >= self.min_history) & (df["amount"] > threshold)
        if not mask.any():
            return pd.DataFrame(columns=FLAG_COLUMNS)
        hits = df.loc[mask, ["txn_id", "amount"]].copy()
        hits["p99"] = p99[mask].round(2)
        hits["threshold"] = threshold[mask].round(2)
        hits["rule_id"] = self.id
        hits["reason"] = [
            f"${a:.2f} vs user p99 ${p:.2f} (threshold ${t:.2f}) — possible stolen-card cashout"
            for a, p, t in zip(hits["amount"], hits["p99"], hits["threshold"])
        ]
        hits["severity"] = 3
        return hits[FLAG_COLUMNS]
