from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

from tms.pipeline import _merge_flags, _trim_to_budget, run


BASE = datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc)


def _iso(mins: int) -> str:
    return (BASE + timedelta(minutes=mins)).isoformat().replace("+00:00", "Z")


def test_merge_combines_rules_and_reasons():
    a = pd.DataFrame(
        [{"txn_id": "t1", "rule_id": "R1", "reason": "burst", "severity": 4}]
    )
    b = pd.DataFrame(
        [{"txn_id": "t1", "rule_id": "R2", "reason": "new device", "severity": 5}]
    )
    merged = _merge_flags({"R1": a, "R2": b})
    assert len(merged) == 1
    row = merged.iloc[0]
    assert row["rules_fired"] == "R1,R2"
    assert "burst" in row["reason"] and "new device" in row["reason"]
    assert row["severity"] == 5


def test_trim_prefers_multi_rule_hits_and_severity():
    rows = pd.DataFrame([
        {"txn_id": "t1", "rules_fired": "R1", "reason": "x", "severity": 2},
        {"txn_id": "t2", "rules_fired": "R1,R2", "reason": "y", "severity": 2},
        {"txn_id": "t3", "rules_fired": "R1", "reason": "z", "severity": 5},
    ])
    trimmed = _trim_to_budget(rows, budget=2)
    kept = set(trimmed["txn_id"])
    assert "t2" in kept  # multi-rule wins
    assert "t3" in kept  # higher severity wins over single-rule low severity
    assert "t1" not in kept


def test_run_end_to_end_on_synthetic_csv(tmp_path: Path):
    rows = []
    # 100 baseline txns for u1 at $10 (enough that p99 isn't skewed by the outlier)
    for i in range(100):
        rows.append(f"t{i},u1,{_iso(i)},SHELL,10.0,d1")
    # Big txn on new device within 24h of first use => R2 and R3 should both fire
    rows.append(f"big,u1,{_iso(100 + 60)},AIRLINE,900.0,d2")
    # Velocity burst for u2: 7 txns in 5 minutes
    for i in range(7):
        rows.append(f"v{i},u2,{_iso(200 + i)},SHELL,5.0,d3")

    csv = tmp_path / "txns.csv"
    csv.write_text(
        "txn_id,user_id,timestamp,merchant_name,amount,device_id\n" + "\n".join(rows) + "\n"
    )
    fraud = tmp_path / "fraud.csv"
    fraud.write_text("txn_id\nbig\n")

    out = tmp_path / "out"
    metrics = run(csv, fraud, out, budget=1000)

    assert metrics["clean_rows"] == 108
    assert metrics["final_flags"] > 0
    flagged = pd.read_csv(out / "flagged.csv")
    assert "big" in set(flagged["txn_id"])
    # big should carry both R2 and R3
    big_row = flagged[flagged["txn_id"] == "big"].iloc[0]
    assert "R2" in big_row["rules_fired"]
    assert "R3" in big_row["rules_fired"]
    assert metrics["recall_against_confirmed_fraud"]["post_budget"]["recall"] == 1.0
    # Per-rule survival dict should exist and contain entries for all 5 rules.
    survival = metrics["per_rule_budget_survival"]
    assert set(survival.keys()) == {"R1", "R2", "R3", "R4", "R5"}
