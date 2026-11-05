"""R5 — Device shared across many users (point-in-time).

Pattern: mule ring / account farming. One device operating many accounts is a
strong tell: shared family phones exist, but a device serving >= N distinct
users is overwhelmingly fraud infrastructure in consumer fintech.

Flag: transactions on a device whose *running* distinct-user count has reached
``user_threshold`` as of (and including) that transaction. The first
``top_n_per_device`` qualifying txns per device by timestamp are surfaced.

Point-in-time correctness: we count distinct users seen on the device so far,
not its eventual lifetime count. A txn from the first user on a device cannot
be flagged just because that device later serves many users. The per-device
top-N selection is also time-ordered — we take the first N qualifying txns on
each device rather than the N highest-amount ones, so a later large purchase
can never retroactively displace an earlier qualifying one from the output.
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
        # Work on a subset sorted by (device_id, timestamp) so cumsum can act
        # as a running distinct-user count.
        tmp = df[["device_id", "user_id", "timestamp", "txn_id", "amount"]].copy()
        tmp = tmp.sort_values(["device_id", "timestamp"], kind="stable").reset_index(drop=True)

        is_first_combo = ~tmp.duplicated(subset=["device_id", "user_id"], keep="first")
        tmp["_first"] = is_first_combo.astype(int)
        tmp["users_so_far"] = tmp.groupby("device_id", sort=False)["_first"].cumsum()

        mask = tmp["users_so_far"] >= self.user_threshold
        if not mask.any():
            return pd.DataFrame(columns=FLAG_COLUMNS)

        # ``tmp`` is already sorted by (device_id, timestamp); preserve that
        # order through the mask so the per-device head() takes the first N
        # qualifying txns by time, not the N largest. Sorting by amount here
        # would let a later large purchase retroactively displace an earlier
        # qualifying txn — a form of look-ahead in the output.
        candidates = tmp.loc[
            mask, ["txn_id", "device_id", "timestamp", "amount", "user_id", "users_so_far"]
        ].copy()
        candidates = candidates.groupby("device_id", sort=False).head(self.top_n_per_device)

        candidates["rule_id"] = self.id
        candidates["reason"] = [
            f"device {d} had {n} distinct users as of this txn "
            f"(threshold {self.user_threshold}) — possible mule ring; "
            f"this ${a:.2f} txn by user {u}"
            for d, n, a, u in zip(
                candidates["device_id"],
                candidates["users_so_far"],
                candidates["amount"],
                candidates["user_id"],
            )
        ]
        candidates["severity"] = 3
        return candidates[FLAG_COLUMNS].reset_index(drop=True)
