"""R5 — Device shared across many unrelated users.

Pattern: mule ring / account farming. One device operating many accounts is a
strong tell: shared family phones exist, but a device serving >= N distinct
users is overwhelmingly fraud infrastructure in consumer fintech.

Flag: transactions on a device whose lifetime distinct user count >=
``user_threshold``. To keep the flag count bounded we only surface the N
highest-amount txns per such device.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .base import FLAG_COLUMNS


@dataclass
class DeviceSharingRule:
    id: str = "R5"
    name: str = "device_sharing"
    priority: int = 3
    user_threshold: int = 4
    top_n_per_device: int = 5

    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        user_counts = df.groupby("device_id", sort=False)["user_id"].transform("nunique")
        mask = user_counts >= self.user_threshold
        if not mask.any():
            return pd.DataFrame(columns=FLAG_COLUMNS)

        candidates = df.loc[mask, ["txn_id", "device_id", "amount", "user_id"]].copy()
        candidates["device_user_count"] = user_counts[mask]

        # Keep only the top-N by amount per device to respect the budget and
        # surface the most material txns to an analyst.
        candidates = (
            candidates.sort_values(["device_id", "amount"], ascending=[True, False])
            .groupby("device_id", sort=False)
            .head(self.top_n_per_device)
        )

        candidates["rule_id"] = self.id
        candidates["reason"] = [
            f"device {d} used by {n} distinct users (threshold {self.user_threshold}) "
            f"— possible mule ring; this ${a:.2f} txn by user {u}"
            for d, n, a, u in zip(
                candidates["device_id"],
                candidates["device_user_count"],
                candidates["amount"],
                candidates["user_id"],
            )
        ]
        candidates["severity"] = 3
        return candidates[FLAG_COLUMNS].reset_index(drop=True)
