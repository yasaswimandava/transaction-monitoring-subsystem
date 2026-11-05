"""Edge-case tests for each rule, run on tiny synthetic frames."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd

from tms.rules import (
    AmountAnomalyRule,
    CardTestingRule,
    DeviceSharingRule,
    NewDeviceRule,
    VelocityRule,
)
from tests.conftest import make_df


BASE = datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc)


def _iso(mins: int) -> str:
    return (BASE + timedelta(minutes=mins)).isoformat().replace("+00:00", "Z")


# --------------------------------------------------------------------------- R1

def test_velocity_fires_when_burst_exceeds_threshold():
    rows = [
        {"txn_id": f"t{i}", "user_id": "u1", "timestamp": _iso(i),
         "merchant_name": "SHELL", "amount": 5.0, "device_id": "d1"}
        for i in range(7)
    ]
    df = make_df(rows)
    flags = VelocityRule(window_minutes=10, burst_count=6).apply(df)
    # 6th and 7th txns both have window counts >= 6
    assert set(flags["txn_id"]) == {"t5", "t6"}
    assert all(flags["rule_id"] == "R1")


def test_velocity_quiet_user_not_flagged():
    rows = [
        {"txn_id": "t1", "user_id": "u2", "timestamp": _iso(0),
         "merchant_name": "SHELL", "amount": 5.0, "device_id": "d1"},
        {"txn_id": "t2", "user_id": "u2", "timestamp": _iso(60),
         "merchant_name": "SHELL", "amount": 5.0, "device_id": "d1"},
    ]
    df = make_df(rows)
    flags = VelocityRule().apply(df)
    assert flags.empty


# --------------------------------------------------------------------------- R2

def test_new_device_spike_fires_on_new_device_big_txn():
    rows = [
        # 25 historical txns on d1 at $10 each
        *[{"txn_id": f"h{i}", "user_id": "u1", "timestamp": _iso(i),
           "merchant_name": "SHELL", "amount": 10.0, "device_id": "d1"} for i in range(25)],
        # First-ever txn on d2, 1 hour later, $500
        {"txn_id": "flag_me", "user_id": "u1", "timestamp": _iso(25 + 60),
         "merchant_name": "BESTBUY", "amount": 500.0, "device_id": "d2"},
    ]
    df = make_df(rows)
    flags = NewDeviceRule(min_history=20, multiple=5.0, floor=150.0).apply(df)
    assert "flag_me" in set(flags["txn_id"])


def test_new_device_rule_skips_users_with_short_history():
    rows = [
        {"txn_id": "t1", "user_id": "u1", "timestamp": _iso(0),
         "merchant_name": "SHELL", "amount": 10.0, "device_id": "d1"},
        {"txn_id": "t2", "user_id": "u1", "timestamp": _iso(10),
         "merchant_name": "SHELL", "amount": 500.0, "device_id": "d2"},
    ]
    df = make_df(rows)
    flags = NewDeviceRule(min_history=20).apply(df)
    assert flags.empty


# --------------------------------------------------------------------------- R3

def test_amount_anomaly_fires_when_amount_blows_p99():
    # Use enough baseline so p99 isn't dragged up by the single outlier:
    # p99 of 101 values is close to the baseline.
    rows = [
        *[{"txn_id": f"h{i}", "user_id": "u1", "timestamp": _iso(i),
           "merchant_name": "SHELL", "amount": 10.0, "device_id": "d1"} for i in range(100)],
        {"txn_id": "big", "user_id": "u1", "timestamp": _iso(1000),
         "merchant_name": "AIRLINE", "amount": 1500.0, "device_id": "d1"},
    ]
    df = make_df(rows)
    flags = AmountAnomalyRule(min_history=20, floor=300, multiplier=1.5).apply(df)
    assert "big" in set(flags["txn_id"])


def test_amount_anomaly_respects_floor():
    # p99 is 10, 1.5x = 15, floor 300 wins. A $100 txn should NOT fire.
    rows = [
        *[{"txn_id": f"h{i}", "user_id": "u1", "timestamp": _iso(i),
           "merchant_name": "SHELL", "amount": 10.0, "device_id": "d1"} for i in range(25)],
        {"txn_id": "mid", "user_id": "u1", "timestamp": _iso(100),
         "merchant_name": "AIRLINE", "amount": 100.0, "device_id": "d1"},
    ]
    df = make_df(rows)
    flags = AmountAnomalyRule(min_history=20, floor=300, multiplier=1.5).apply(df)
    assert "mid" not in set(flags["txn_id"])


# --------------------------------------------------------------------------- R4

def test_card_testing_fires_on_micro_charges_across_merchants():
    rows = [
        {"txn_id": f"t{i}", "user_id": "u1", "timestamp": _iso(i),
         "merchant_name": f"M{i}", "amount": 1.0, "device_id": "d1"}
        for i in range(5)
    ]
    df = make_df(rows)
    flags = CardTestingRule(window_minutes=30, micro_threshold=2.0, distinct_merchants=5).apply(df)
    assert not flags.empty
    assert "t4" in set(flags["txn_id"])


def test_card_testing_quiet_when_same_merchant():
    rows = [
        {"txn_id": f"t{i}", "user_id": "u1", "timestamp": _iso(i),
         "merchant_name": "SAME", "amount": 1.0, "device_id": "d1"}
        for i in range(10)
    ]
    df = make_df(rows)
    flags = CardTestingRule(distinct_merchants=5).apply(df)
    assert flags.empty


# --------------------------------------------------------------------------- R5

def test_device_sharing_fires_when_many_users_on_one_device():
    rows = [
        {"txn_id": f"t{u}", "user_id": f"u{u}", "timestamp": _iso(u * 10),
         "merchant_name": "SHELL", "amount": 20.0 + u, "device_id": "shared"}
        for u in range(4)
    ]
    df = make_df(rows)
    flags = DeviceSharingRule(user_threshold=4, top_n_per_device=5).apply(df)
    assert len(flags) == 4  # all four surfaced (<= top_n)
    assert all(f.startswith("device shared used by 4 distinct users") for f in flags["reason"])


def test_device_sharing_quiet_on_single_user_device():
    rows = [
        {"txn_id": f"t{i}", "user_id": "u1", "timestamp": _iso(i),
         "merchant_name": "SHELL", "amount": 20.0, "device_id": "d1"}
        for i in range(5)
    ]
    df = make_df(rows)
    flags = DeviceSharingRule(user_threshold=4).apply(df)
    assert flags.empty
