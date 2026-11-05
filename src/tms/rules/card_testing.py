"""R4 — Micro-charge card testing across merchants.

Pattern: post-breach BIN-validation sweep. An attacker with a batch of stolen
cards makes small charges across many merchants to see which cards are still
live. Legitimate users don't spray $1 charges across 5+ merchants in half an hour.

Flag: within a ``window`` minute rolling window, a user has >= ``distinct_merchants``
micro-charges (<$ ``micro_threshold``) across distinct merchants.

We use merchant *normalized* names here — see ingest.py — so that
``"STARBUCKS #41"`` and ``"starbucks"`` don't both count.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .base import FLAG_COLUMNS


@dataclass
class CardTestingRule:
    id: str = "R4"
    name: str = "micro_charge_card_testing"
    priority: int = 2
    window_minutes: int = 30
    micro_threshold: float = 2.0
    distinct_merchants: int = 5

    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        micro = df[df["amount"] < self.micro_threshold]
        if micro.empty:
            return pd.DataFrame(columns=FLAG_COLUMNS)

        window = f"{self.window_minutes}min"
        # Factorize merchant names to integers so we can count uniques via a
        # cheap rolling nunique approximation (count of unique codes).
        merchant_codes, _ = pd.factorize(micro["merchant_name"])
        tmp = micro[["user_id", "timestamp", "txn_id"]].assign(
            merchant_code=merchant_codes
        )
        # For a true "distinct merchants in window" count we'd need rolling
        # unique, which pandas doesn't have natively. Approximation: count of
        # unique codes in the window using a groupby + rolling + apply(nunique).
        # This is small (only rows below micro_threshold) so cost is bounded.
        distinct = (
            tmp.set_index("timestamp")
            .groupby("user_id", sort=False)["merchant_code"]
            .rolling(window, closed="both")
            .apply(lambda a: len(np.unique(a)), raw=True)
        )
        distinct = distinct.reset_index(level=0, drop=True).reindex(tmp.set_index("timestamp").index)
        distinct_arr = distinct.to_numpy()
        mask = distinct_arr >= self.distinct_merchants
        if not mask.any():
            return pd.DataFrame(columns=FLAG_COLUMNS)

        tmp_indexed = tmp.set_index("timestamp")
        hits = tmp_indexed.loc[mask, ["txn_id"]].copy()
        hit_distinct = distinct_arr[mask].astype(int)
        hits["rule_id"] = self.id
        hits["reason"] = [
            f"{d} distinct merchants with micro-charges (<${self.micro_threshold:.2f}) "
            f"in {self.window_minutes} min — possible BIN-testing sweep"
            for d in hit_distinct
        ]
        hits["severity"] = 5
        return hits.reset_index(drop=True)[FLAG_COLUMNS]
