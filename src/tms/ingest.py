"""Load, clean, and normalize the transaction CSV.

Design choices (see docs/RULES.md for the full rationale):

- `txn_id` duplicates: keep first occurrence. 1,000 dupes in the provided file;
  treating them as the same event avoids double-flagging.
- Bad timestamps (e.g., literal ``"not_a_timestamp"``) and non-positive amounts:
  drop. These rows cannot be meaningfully evaluated and skewing stats around them
  would weaken every rule.
- Null amounts / merchants: drop. Same reason.
- Merchant normalization: upper-case + strip whitespace + collapse multiple spaces
  + strip trailing ``#<digits>`` tokens (e.g., ``"UNITED AIRLINES #1289"`` →
  ``"UNITED AIRLINES"``). Observed free-text chaos: ~135k distinct raw strings for
  what is almost certainly ~200 real merchants. Normalizing collapses noise so
  the card-testing rule can see a single user hitting many merchants.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd


MERCHANT_SUFFIX_RE = re.compile(r"\s+#\d+\s*$")
WHITESPACE_RE = re.compile(r"\s+")


@dataclass
class IngestReport:
    raw_rows: int
    duplicate_txn_ids: int
    bad_timestamps: int
    bad_amounts: int
    null_merchants: int
    final_rows: int

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def normalize_merchant(series: pd.Series) -> pd.Series:
    s = series.astype("string").str.strip().str.upper()
    s = s.str.replace(MERCHANT_SUFFIX_RE, "", regex=True)
    s = s.str.replace(WHITESPACE_RE, " ", regex=True)
    return s


def load_transactions(path: str | Path) -> tuple[pd.DataFrame, IngestReport]:
    """Load the transactions CSV and apply cleaning.

    Returns the cleaned DataFrame sorted by (user_id, timestamp) and a report
    describing what was dropped. The sort is done once here so rules can rely on
    it without re-sorting.
    """
    df = pd.read_csv(
        path,
        engine="pyarrow",
        dtype_backend="pyarrow",
    )
    raw_rows = len(df)

    # Drop duplicate txn_ids (keep first).
    dup_mask = df["txn_id"].duplicated(keep="first")
    duplicate_txn_ids = int(dup_mask.sum())
    df = df[~dup_mask]

    # Parse timestamps; coerce bad values to NaT then drop.
    ts = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
    bad_ts_mask = ts.isna()
    bad_timestamps = int(bad_ts_mask.sum())
    df = df.assign(timestamp=ts)
    df = df[~bad_ts_mask]

    # Drop non-positive and null amounts. Refunds (negatives) exist but rules
    # here target debit fraud; refund abuse is listed as a deferred rule.
    amount = pd.to_numeric(df["amount"], errors="coerce")
    bad_amount_mask = amount.isna() | (amount <= 0)
    bad_amounts = int(bad_amount_mask.sum())
    df = df.assign(amount=amount)
    df = df[~bad_amount_mask]

    # Drop null merchants; normalize the rest.
    null_merchant_mask = df["merchant_name"].isna()
    null_merchants = int(null_merchant_mask.sum())
    df = df[~null_merchant_mask]
    df = df.assign(merchant_name=normalize_merchant(df["merchant_name"]))

    # Cast IDs to pandas string dtype for predictable groupby behavior.
    for col in ("txn_id", "user_id", "device_id"):
        df[col] = df[col].astype("string")

    df = df.sort_values(["user_id", "timestamp"], kind="stable").reset_index(drop=True)

    report = IngestReport(
        raw_rows=raw_rows,
        duplicate_txn_ids=duplicate_txn_ids,
        bad_timestamps=bad_timestamps,
        bad_amounts=bad_amounts,
        null_merchants=null_merchants,
        final_rows=len(df),
    )
    return df, report


def load_confirmed_fraud(path: str | Path) -> set[str]:
    df = pd.read_csv(path)
    return set(df["txn_id"].astype(str).tolist())
