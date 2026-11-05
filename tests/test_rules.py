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
    # With point-in-time features, 20 baseline $10 txns + 1 $500 txn fires
    # because prior p99 is $10, threshold = max($15, $300) = $300, and $500
    # > $300. This is the reviewer counterexample from the feedback round.
    rows = [
        *[{"txn_id": f"h{i}", "user_id": "u1", "timestamp": _iso(i),
           "merchant_name": "SHELL", "amount": 10.0, "device_id": "d1"} for i in range(20)],
        {"txn_id": "big", "user_id": "u1", "timestamp": _iso(100),
         "merchant_name": "AIRLINE", "amount": 500.0, "device_id": "d1"},
    ]
    df = make_df(rows)
    flags = AmountAnomalyRule(min_history=20, floor=300, multiplier=1.5).apply(df)
    assert "big" in set(flags["txn_id"])


def test_amount_anomaly_is_point_in_time():
    # If features were computed over the full period, p99 of twenty $10s plus
    # one $500 would be ~$402, and the $500 would NOT fire. The point-in-time
    # version should still fire — this test asserts the correct behaviour.
    rows = [
        *[{"txn_id": f"h{i}", "user_id": "u1", "timestamp": _iso(i),
           "merchant_name": "SHELL", "amount": 10.0, "device_id": "d1"} for i in range(20)],
        {"txn_id": "the_spike", "user_id": "u1", "timestamp": _iso(100),
         "merchant_name": "AIRLINE", "amount": 500.0, "device_id": "d1"},
    ]
    df = make_df(rows)
    flags = AmountAnomalyRule(min_history=20, floor=300, multiplier=1.5).apply(df)
    assert "the_spike" in set(flags["txn_id"])


def test_amount_anomaly_respects_floor():
    # Prior p99 = 10, 1.5x = 15, floor 300 wins. A $100 txn should NOT fire.
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

def test_device_sharing_fires_from_fourth_user_onward():
    # First three users on the device should NOT fire (threshold is 4). The
    # fourth user's txn and any subsequent txns on the device should fire.
    rows = [
        {"txn_id": "t0", "user_id": "u0", "timestamp": _iso(0),
         "merchant_name": "SHELL", "amount": 20.0, "device_id": "shared"},
        {"txn_id": "t1", "user_id": "u1", "timestamp": _iso(10),
         "merchant_name": "SHELL", "amount": 21.0, "device_id": "shared"},
        {"txn_id": "t2", "user_id": "u2", "timestamp": _iso(20),
         "merchant_name": "SHELL", "amount": 22.0, "device_id": "shared"},
        {"txn_id": "t3_fourth_user", "user_id": "u3", "timestamp": _iso(30),
         "merchant_name": "SHELL", "amount": 23.0, "device_id": "shared"},
        {"txn_id": "t4_same_user_later", "user_id": "u0", "timestamp": _iso(40),
         "merchant_name": "SHELL", "amount": 30.0, "device_id": "shared"},
    ]
    df = make_df(rows)
    flags = DeviceSharingRule(user_threshold=4, top_n_per_device=5).apply(df)
    flagged = set(flags["txn_id"])
    assert "t0" not in flagged
    assert "t1" not in flagged
    assert "t2" not in flagged
    assert "t3_fourth_user" in flagged
    assert "t4_same_user_later" in flagged


def test_device_sharing_quiet_on_single_user_device():
    rows = [
        {"txn_id": f"t{i}", "user_id": "u1", "timestamp": _iso(i),
         "merchant_name": "SHELL", "amount": 20.0, "device_id": "d1"}
        for i in range(5)
    ]
    df = make_df(rows)
    flags = DeviceSharingRule(user_threshold=4).apply(df)
    assert flags.empty
