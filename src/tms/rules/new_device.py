"""R2 — New device + high-value spend (point-in-time).

Pattern: account takeover via SIM-swap or credential stuffing. Attacker logs in
from a device the legitimate user has never used, then cashes out quickly.

Flag: the first time a user is seen on a device, if any of the first
``lookahead_hours`` of txns on that device exceed ``multiple`` × the user's
prior median. The flagged transaction is the specific one that crossed
the threshold.

Point-in-time correctness: the user's history count and median are computed
only over txns strictly *before* the current one. A fraud alert must reflect
what could have been known at the time the transaction cleared.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .base import FLAG_COLUMNS


@dataclass
class NewDeviceRule:
    id: str = "R2"
    name: str = "new_device_spike"
    priority: int = 1
    min_history: int = 20
    lookahead_hours: int = 24
    multiple: float = 5.0
    floor: float = 150.0

    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        grp_user = df.groupby("user_id", sort=False)
        # Prior-only features: count of previous txns, median of previous amounts.
        prior_count = grp_user.cumcount()
        prior_median = grp_user["amount"].transform(
            lambda s: s.shift(1).expanding().median()
        )
        # cummin is "as-of" — it only uses current + prior rows, never future.
        first_seen_ud = df.groupby(["user_id", "device_id"], sort=False)["timestamp"].transform("cummin")
        user_first_ts = grp_user["timestamp"].transform("cummin")

        delta_hours = (df["timestamp"] - first_seen_ud).dt.total_seconds() / 3600.0
        in_lookahead = delta_hours <= self.lookahead_hours
        is_not_users_first_ever = first_seen_ud > user_first_ts
        threshold = (prior_median * self.multiple).clip(lower=self.floor)

        mask = (
            (prior_count >= self.min_history)
            & is_not_users_first_ever
            & in_lookahead
            & (df["amount"] > threshold)
        )
        if not mask.any():
            return pd.DataFrame(columns=FLAG_COLUMNS)
        hits = df.loc[mask, ["txn_id", "amount", "device_id"]].copy()
        hits["median"] = prior_median[mask].round(2)
        hits["threshold"] = threshold[mask].round(2)
        hits["rule_id"] = self.id
        hits["reason"] = [
            f"${a:.2f} on new device {d} (user prior median ${m:.2f}, threshold ${t:.2f}) "
            f"within {self.lookahead_hours}h of first use — possible ATO"
            for a, d, m, t in zip(hits["amount"], hits["device_id"], hits["median"], hits["threshold"])
        ]
        hits["severity"] = 5
        return hits[FLAG_COLUMNS]
