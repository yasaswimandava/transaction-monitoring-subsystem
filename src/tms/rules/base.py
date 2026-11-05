"""Rule protocol + flag helpers.

A Rule is a callable that takes the cleaned transaction DataFrame and returns
flags keyed by ``txn_id``. Rules must be pure and vectorized. No per-row Python
loops over the full frame.

A flag row has:
  - ``txn_id``       : the offending transaction
  - ``rule_id``      : stable identifier of the rule that fired (e.g. ``"R1"``)
  - ``reason``       : analyst-readable sentence
  - ``severity``     : int in [1, 5], used for budget ranking across rules
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

import pandas as pd


FLAG_COLUMNS = ["txn_id", "rule_id", "reason", "severity"]


class Rule(Protocol):
    id: str
    name: str
    priority: int  # 1 = highest, used as a tiebreak when trimming to budget

    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        """Return a DataFrame with FLAG_COLUMNS. Empty is fine."""


@dataclass
class RuleMeta:
    id: str
    name: str
    priority: int


def empty_flags() -> pd.DataFrame:
    return pd.DataFrame(columns=FLAG_COLUMNS)
