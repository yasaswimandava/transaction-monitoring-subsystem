"""Threshold sensitivity sweep for the 5 rules.

For each rule's main calibration knob, run the rule with a few alternative
values and report pre-budget candidate counts. Lets a reviewer see directly
how a threshold choice interacts with the 1,000-flag budget, which is what
the spec asks for under "thresholds tuned against the review budget".

Run from the repo root:

    python scripts/sensitivity.py

Reads data/transactions.csv by default. The table printed here is pasted
verbatim into docs/RULES.md; re-run and refresh it whenever a rule's default
threshold changes.
"""
from __future__ import annotations

from pathlib import Path

from tms.ingest import load_transactions
from tms.rules import (
    AmountAnomalyRule,
    CardTestingRule,
    DeviceSharingRule,
    NewDeviceRule,
    VelocityRule,
)


def main() -> None:
    txns_path = Path("data/transactions.csv")
    df, report = load_transactions(txns_path)
    print(f"Loaded {report.final_rows:,} clean rows\n")

    sweeps: list[tuple[str, str, list[tuple[str, object]]]] = [
        (
            "R1",
            "burst_count (10-min window)",
            [
                ("5", VelocityRule(burst_count=5)),
                ("6 (chosen)", VelocityRule(burst_count=6)),
                ("7", VelocityRule(burst_count=7)),
                ("8", VelocityRule(burst_count=8)),
            ],
        ),
        (
            "R2",
            "amount floor ($)",
            [
                ("50", NewDeviceRule(floor=50.0)),
                ("100", NewDeviceRule(floor=100.0)),
                ("150 (chosen)", NewDeviceRule(floor=150.0)),
                ("300", NewDeviceRule(floor=300.0)),
            ],
        ),
        (
            "R3",
            "amount floor ($)",
            [
                ("150", AmountAnomalyRule(floor=150.0)),
                ("200", AmountAnomalyRule(floor=200.0)),
                ("300 (chosen)", AmountAnomalyRule(floor=300.0)),
                ("500", AmountAnomalyRule(floor=500.0)),
            ],
        ),
        (
            "R4",
            "distinct_merchants (30-min window)",
            [
                ("4", CardTestingRule(distinct_merchants=4)),
                ("5 (chosen)", CardTestingRule(distinct_merchants=5)),
                ("6", CardTestingRule(distinct_merchants=6)),
            ],
        ),
        (
            "R5",
            "user_threshold (distinct users per device)",
            [
                ("3", DeviceSharingRule(user_threshold=3)),
                ("4 (chosen)", DeviceSharingRule(user_threshold=4)),
                ("5", DeviceSharingRule(user_threshold=5)),
                ("6", DeviceSharingRule(user_threshold=6)),
            ],
        ),
    ]

    header = f"{'Rule':<5} {'Knob':<42} {'Value':<16} {'Pre-budget':>12}"
    print(header)
    print("-" * len(header))
    for rule_id, knob, variants in sweeps:
        for i, (val, rule) in enumerate(variants):
            flags = rule.apply(df)
            rid_cell = rule_id if i == 0 else ""
            knob_cell = knob if i == 0 else ""
            print(f"{rid_cell:<5} {knob_cell:<42} {val:<16} {len(flags):>12,}")
        print()


if __name__ == "__main__":
    main()
