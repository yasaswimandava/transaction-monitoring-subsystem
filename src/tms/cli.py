"""Command-line entrypoint."""
from __future__ import annotations

import json
from pathlib import Path

import typer

from .pipeline import DEFAULT_BUDGET, run

app = typer.Typer(add_completion=False, help="Transaction monitoring subsystem")


@app.command()
def main(
    txns: Path = typer.Option(Path("data/transactions.csv"), help="Path to transactions CSV"),
    fraud: Path = typer.Option(Path("data/confirmed_fraud.csv"), help="Path to confirmed fraud CSV (optional)"),
    out: Path = typer.Option(Path("out"), help="Output directory"),
    budget: int = typer.Option(DEFAULT_BUDGET, help="Max flags to surface to analysts"),
):
    """Ingest the CSV, run all rules, and write flagged.csv + metrics.json."""
    fraud_path = fraud if fraud.exists() else None
    metrics = run(txns_path=txns, fraud_path=fraud_path, out_dir=out, budget=budget)
    typer.echo(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    app()
