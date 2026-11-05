"""Shared fixtures: small synthetic transaction frames for rule tests."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest


def _ts(minutes: int, base: datetime | None = None) -> pd.Timestamp:
    base = base or datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc)
    return pd.Timestamp(base + timedelta(minutes=minutes))


def make_df(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    for col in ("txn_id", "user_id", "device_id", "merchant_name"):
        df[col] = df[col].astype("string")
    df["amount"] = df["amount"].astype(float)
    df = df.sort_values(["user_id", "timestamp"], kind="stable").reset_index(drop=True)
    return df


@pytest.fixture
def ts():
    return _ts
