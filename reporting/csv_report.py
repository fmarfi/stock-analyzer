"""CSV export: one row per ticker per run, votes_json flattened into named
vote columns for readability (rather than a single JSON blob column).
"""

import csv

from stock_analyzer import indicators


def _fieldnames():
    vote_cols = [f"vote_{ind.name}" for ind in indicators.REGISTRY]
    return [
        "run_id", "ticker", "as_of_date", "close",
        "ma_short_value", "ma_long_value", "rsi",
        *vote_cols,
        "confluence", "base_rate_up", "bull_hit_rate", "bear_hit_rate",
        "bull_edge", "bear_edge", "overall_hit_rate",
        "n_bull", "n_bear", "n_overall", "n_bars",
    ]


def _row_for_result(run_id, result: dict) -> dict:
    stats = result["stats"]
    row = {
        "run_id": run_id,
        "ticker": result["ticker"],
        "as_of_date": result["as_of_date"],
        "close": result["close"],
        "ma_short_value": result["ma_short_value"],
        "ma_long_value": result["ma_long_value"],
        "rsi": result["rsi"],
        "confluence": result["confluence"],
        "base_rate_up": stats.base_rate_up,
        "bull_hit_rate": stats.bull_hit_rate,
        "bear_hit_rate": stats.bear_hit_rate,
        "bull_edge": stats.bull_edge,
        "bear_edge": stats.bear_edge,
        "overall_hit_rate": stats.overall_hit_rate,
        "n_bull": stats.n_bull,
        "n_bear": stats.n_bear,
        "n_overall": stats.n_overall,
        "n_bars": stats.n_bars,
    }
    for ind in indicators.REGISTRY:
        row[f"vote_{ind.name}"] = result["votes"].get(ind.name)
    return row


def write_csv_report(scan_result: dict, path: str) -> str:
    """Write `scan_result` (the dict returned by engine.run_scan()) as a CSV
    file at `path`. Returns `path` for convenience.
    """
    fieldnames = _fieldnames()
    rows = [_row_for_result(scan_result["run_id"], r) for r in scan_result["results"]]

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    return path
