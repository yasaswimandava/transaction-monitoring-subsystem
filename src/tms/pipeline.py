"""Orchestrate ingest + rules + merge + budget trimming + output."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd

from .ingest import IngestReport, load_confirmed_fraud, load_transactions
from .rules import default_rules
from .rules.base import FLAG_COLUMNS


DEFAULT_BUDGET = 1000


@dataclass
class StageTiming:
    name: str
    seconds: float


def _merge_flags(per_rule: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Union per-rule flag frames and collapse multi-rule hits on the same
    ``txn_id`` to one row with combined rules and reasons."""
    non_empty = [d for d in per_rule.values() if not d.empty]
    if not non_empty:
        return pd.DataFrame(columns=["txn_id", "rules_fired", "reason", "severity"])
    combined = pd.concat(non_empty, ignore_index=True)
    grouped = combined.groupby("txn_id", sort=False).agg(
        rules_fired=("rule_id", lambda s: ",".join(sorted(set(s)))),
        reason=("reason", lambda s: " | ".join(s)),
        severity=("severity", "max"),
    )
    return grouped.reset_index()


def _trim_to_budget(flags: pd.DataFrame, budget: int) -> pd.DataFrame:
    if len(flags) <= budget:
        return flags
    # Prefer multi-rule hits (more corroborated signal) and higher severity.
    flags = flags.copy()
    flags["_rule_count"] = flags["rules_fired"].str.count(",") + 1
    flags = flags.sort_values(
        ["_rule_count", "severity"], ascending=[False, False]
    ).head(budget)
    return flags.drop(columns=["_rule_count"]).reset_index(drop=True)


def _recall(flags: pd.DataFrame, labels: set[str]) -> dict:
    if not labels:
        return {"labeled_fraud_count": 0, "flagged_labels": 0, "recall": None}
    flagged_ids = set(flags["txn_id"].tolist()) if not flags.empty else set()
    hit = flagged_ids & labels
    return {
        "labeled_fraud_count": len(labels),
        "flagged_labels": len(hit),
        "recall": round(len(hit) / len(labels), 4),
    }


def _pairwise_overlap(per_rule: dict[str, pd.DataFrame]) -> dict:
    ids = {rid: set(d["txn_id"]) for rid, d in per_rule.items()}
    out = {}
    rids = list(ids)
    for i, a in enumerate(rids):
        for b in rids[i + 1 :]:
            out[f"{a}&{b}"] = len(ids[a] & ids[b])
    return out


def run(
    txns_path: str | Path,
    fraud_path: str | Path | None,
    out_dir: str | Path,
    budget: int = DEFAULT_BUDGET,
    rules: Iterable | None = None,
) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    timings: list[StageTiming] = []

    def _time(name: str, fn):
        t0 = time.perf_counter()
        result = fn()
        timings.append(StageTiming(name, round(time.perf_counter() - t0, 3)))
        return result

    df, ingest_report = _time("ingest", lambda: load_transactions(txns_path))
    labels = set()
    if fraud_path:
        labels = _time("load_fraud", lambda: load_confirmed_fraud(fraud_path))

    rules = list(rules) if rules is not None else default_rules()
    per_rule: dict[str, pd.DataFrame] = {}
    for rule in rules:
        rule_df = _time(f"rule:{rule.id}", lambda r=rule: r.apply(df))
        per_rule[rule.id] = rule_df[FLAG_COLUMNS].copy()

    pre_merge_flags = _time("merge", lambda: _merge_flags(per_rule))
    pre_budget_count = len(pre_merge_flags)
    flags = _time("trim", lambda: _trim_to_budget(pre_merge_flags, budget))

    flagged_path = out_dir / "flagged.csv"
    _time("write", lambda: flags.to_csv(flagged_path, index=False))

    # Per-rule survival of the budget step. A rule's pre-budget count is the
    # distinct txns it contributed to pre_merge_flags; its survived count is
    # how many of those made it past the trim. Lets a reviewer see exactly
    # what each rule lost at the budget cut, not just the aggregate.
    final_txn_ids = set(flags["txn_id"]) if not flags.empty else set()
    budget_survival = {}
    for rid, d in per_rule.items():
        rule_ids = set(d["txn_id"]) if not d.empty else set()
        survived = rule_ids & final_txn_ids
        budget_survival[rid] = {
            "pre_budget": len(rule_ids),
            "survived_budget": len(survived),
            "dropped_by_budget": len(rule_ids) - len(survived),
            "survival_rate": round(len(survived) / len(rule_ids), 4) if rule_ids else None,
        }

    recall_pre = _recall(pre_merge_flags, labels)
    recall_post = _recall(flags, labels)

    metrics = {
        "input_rows": ingest_report.raw_rows,
        "clean_rows": ingest_report.final_rows,
        "ingest_report": ingest_report.as_dict(),
        "per_rule_counts": {rid: int(len(d)) for rid, d in per_rule.items()},
        "per_rule_budget_survival": budget_survival,
        "pre_budget_flags": pre_budget_count,
        "final_flags": int(len(flags)),
        "flag_rate_per_1M": round(len(flags) * 1_000_000 / ingest_report.final_rows, 2)
        if ingest_report.final_rows
        else 0,
        "budget": budget,
        "pairwise_overlap": _pairwise_overlap(per_rule),
        "recall_against_confirmed_fraud": {
            "pre_budget": recall_pre,
            "post_budget": recall_post,
        },
        "timings_seconds": {t.name: t.seconds for t in timings},
        "total_seconds": round(sum(t.seconds for t in timings), 3),
    }
    (out_dir / "metrics.json").write_text(json.dumps(metrics, indent=2))
    return metrics
