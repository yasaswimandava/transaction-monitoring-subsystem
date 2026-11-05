"""R1 — Velocity burst.

Pattern: card testing / account-takeover. Legitimate users rarely make many
back-to-back charges in minutes. Attackers validating stolen cards or draining
a compromised account often do.

Flag: a user making >= ``burst_count`` transactions within ``window`` minutes.
Only the trigger transaction (the Nth in the window) is flagged, not every txn
in the burst — avoids spending the whole budget on one incident while still
surfacing it to the analyst.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .base import FLAG_COLUMNS


@dataclass
class VelocityRule:
    id: str = "R1"
    name: str = "velocity_burst"
    priority: int = 1
    window_minutes: int = 10
    burst_count: int = 6

    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        window = f"{self.window_minutes}min"
        # Rolling count of txns within the time window for each user. df must be
        # sorted by (user_id, timestamp) — we rely on ingest to guarantee that.
        # groupby(sort=False) preserves within-group order so the resulting
        # array aligns row-for-row with df.
        counts = (
            df.set_index("timestamp")
            .groupby("user_id", sort=False)["amount"]
            .rolling(window, closed="both")
            .count()
            .to_numpy()
        )
        counts_arr = counts
        mask = counts_arr >= self.burst_count
        if not mask.any():
            return pd.DataFrame(columns=FLAG_COLUMNS)

        hits = df.loc[mask, ["txn_id"]].copy()
        hit_counts = counts_arr[mask].astype(int)
        hits["rule_id"] = self.id
        hits["reason"] = [
            f"user made {c} transactions in {self.window_minutes} min "
            f"(threshold {self.burst_count}) — possible card-testing or ATO burst"
            for c in hit_counts
        ]
        hits["severity"] = 4
        return hits[FLAG_COLUMNS]
