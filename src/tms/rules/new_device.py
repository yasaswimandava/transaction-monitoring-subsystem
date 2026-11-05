"""R2 — New device + high-value spend.

Pattern: account takeover via SIM-swap or credential stuffing. Attacker logs in
from a device the legitimate user has never used, then cashes out quickly.

Flag: the first time a user is seen on a device, if any of the first
``lookahead_hours`` of txns on that device exceed ``multiple`` × the user's
historical median. The flagged transaction is the specific one that crossed
the threshold.

We require the user to have enough history (``min_history``) so that a brand-new
account doesn't look suspicious for just transacting.
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
    floor: float = 150.0  # don't flag tiny amounts even if they beat the median

    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        # Per-user history count (for the min_history gate) and median amount.
        grp_user = df.groupby("user_id", sort=False)["amount"]
        user_count = grp_user.transform("count")
        user_median = grp_user.transform("median")

        # First-seen timestamp per (user_id, device_id).
        first_seen = df.groupby(["user_id", "device_id"], sort=False)["timestamp"].transform("min")
        # First-seen per user (to determine if this device is "new" — i.e. not
        # the user's very first device, since every user has to start somewhere).
        user_first_ts = grp_user.transform("count")  # placeholder, replaced below
        user_first_ts = df.groupby("user_id", sort=False)["timestamp"].transform("min")

        delta_hours = (df["timestamp"] - first_seen).dt.total_seconds() / 3600.0
        in_lookahead = delta_hours <= self.lookahead_hours
        is_not_users_first_ever = first_seen > user_first_ts
        threshold = (user_median * self.multiple).clip(lower=self.floor)

        mask = (
            (user_count >= self.min_history)
            & is_not_users_first_ever
            & in_lookahead
            & (df["amount"] > threshold)
        )
        if not mask.any():
            return pd.DataFrame(columns=FLAG_COLUMNS)
        hits = df.loc[mask, ["txn_id", "amount", "device_id"]].copy()
        hits["median"] = user_median[mask].round(2)
        hits["threshold"] = threshold[mask].round(2)
        hits["rule_id"] = self.id
        hits["reason"] = [
            f"${a:.2f} on new device {d} (user median ${m:.2f}, threshold ${t:.2f}) "
            f"within {self.lookahead_hours}h of first use — possible ATO"
            for a, d, m, t in zip(hits["amount"], hits["device_id"], hits["median"], hits["threshold"])
        ]
        hits["severity"] = 5
        return hits[FLAG_COLUMNS]
