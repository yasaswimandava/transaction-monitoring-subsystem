from __future__ import annotations

from pathlib import Path

import pandas as pd

from tms.ingest import load_transactions, normalize_merchant


def test_normalize_merchant_strips_suffix_and_normalizes_case():
    s = pd.Series(["UNITED AIRLINES #1289", "united airlines  #42", "shell", "Shell "])
    out = normalize_merchant(s).tolist()
    assert out == ["UNITED AIRLINES", "UNITED AIRLINES", "SHELL", "SHELL"]


def test_load_transactions_drops_dupes_bad_ts_and_bad_amounts(tmp_path: Path):
    csv = tmp_path / "txns.csv"
    csv.write_text(
        "txn_id,user_id,timestamp,merchant_name,amount,device_id\n"
        "t1,u1,2026-05-01T12:00:00Z,Shell,10.0,d1\n"
        "t1,u1,2026-05-01T12:00:00Z,Shell,10.0,d1\n"       # dup txn_id
        "t2,u1,not_a_timestamp,Shell,10.0,d1\n"             # bad ts
        "t3,u1,2026-05-01T12:05:00Z,Shell,0,d1\n"            # non-positive
        "t4,u1,2026-05-01T12:06:00Z,,10.0,d1\n"              # null merchant
        "t5,u1,2026-05-01T12:07:00Z,Shell,15.0,d1\n"
    )
    df, report = load_transactions(csv)
    assert report.raw_rows == 6
    assert report.duplicate_txn_ids == 1
    assert report.bad_timestamps == 1
    assert report.bad_amounts == 1
    assert report.null_merchants == 1
    assert report.final_rows == 2
    assert list(df["txn_id"]) == ["t1", "t5"]
