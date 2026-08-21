"""Bollinger Squeeze + confluence-alignment "edge point" detection.

A squeeze event is a bar where Bollinger Bandwidth (BB_width) is unusually
low relative to its own trailing history (the bands have contracted --
classically a precursor to a volatility expansion) *and* that day's
confluence score is fully aligned bull or bear (every registered indicator
agrees -- see indicators.REGISTRY). Nearby qualifying bars are collapsed
into a single event anchored on the tightest-bandwidth bar among them (see
events.anchored_events), so a persistent squeeze doesn't produce weeks of
near-duplicate rows.

Operates on the same per-ticker DataFrame engine.analyze_ticker() already
builds (result["df"]) -- no separate fetch/indicator path, so this can never
drift from what the scoreboard/report show for the same ticker.
"""

import pandas as pd

from stock_analyzer import events, indicators


def find_events(df: pd.DataFrame, align_threshold: int, horizon: int,
                 bw_lookback: int = 252, bw_percentile: float = 10.0, min_gap_bars: int = 20) -> list:
    """Scan `df` (must have BB_width, confluence, Close, and the registry's
    `{name}_signal` columns) for squeeze + full-alignment events. Returns a
    list of event dicts, oldest first.
    """
    if "BB_width" not in df.columns or len(df) < 10:
        return []

    bw_threshold = df["BB_width"].rolling(
        bw_lookback, min_periods=max(10, bw_lookback // 4),
    ).quantile(bw_percentile / 100.0)

    squeeze_flag = df["BB_width"] <= bw_threshold
    aligned_flag = df["confluence"].abs() == align_threshold
    qualifies = (squeeze_flag & aligned_flag).fillna(False)

    fwd_close = df["Close"].shift(-horizon)
    positions = events.anchored_events(qualifies, df["BB_width"], min_gap_bars, mode="min")
    return [_build_event(df, pos, horizon, fwd_close) for pos in positions]


def _build_event(df: pd.DataFrame, pos: int, horizon: int, fwd_close: pd.Series) -> dict:
    row = df.iloc[pos]
    date = df.index[pos]
    confluence = int(row["confluence"])
    direction = "bull" if confluence > 0 else "bear"
    close = float(row["Close"])

    fwd = fwd_close.iloc[pos]
    has_forward = not pd.isna(fwd)
    fwd_return_pct = ((float(fwd) / close) - 1) * 100.0 if has_forward else None
    hit = None
    if has_forward:
        hit = (fwd_return_pct > 0) if direction == "bull" else (fwd_return_pct < 0)

    return {
        "position": pos,
        "date": date,
        "date_str": date.strftime("%Y-%m-%d"),
        "confluence": confluence,
        "direction": direction,
        "votes": indicators.votes_json_for_row(row),
        "bb_width": float(row["BB_width"]),
        "close": close,
        "horizon": horizon,
        "has_forward": has_forward,
        "fwd_close": float(fwd) if has_forward else None,
        "fwd_return_pct": fwd_return_pct,
        "hit": hit,
    }
