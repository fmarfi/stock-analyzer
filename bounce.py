"""Bollinger Bounce detection.

The strategy: price touches (or pierces) an outer Bollinger Band and then
closes back inside it -- a rejection -- with the expectation that it drifts
back toward the middle band. It's specifically a ranging-market play: in a
strong trend, price can "walk the band" for weeks without ever reverting, so
a touch-and-reject there isn't the same signal. "Ranging" is approximated
the same way the rest of this package reads trend strength: confluence is
*not* fully aligned (the registered indicators disagree, rather than all
pointing the same direction -- see indicators.REGISTRY).

Operates on the same per-ticker DataFrame engine.analyze_ticker() already
builds (result["df"]) -- no separate fetch/indicator path, so this can never
drift from what the scoreboard/report show for the same ticker.
"""

import pandas as pd

from stock_analyzer import events, indicators


def _forward_extreme(series: pd.Series, window: int, how: str) -> pd.Series:
    """max (how="max") or min (how="min") of `series` over [i, i+window-1],
    computed by reversing, rolling, and reversing back -- pandas has no
    built-in forward-looking rolling window.
    """
    reversed_series = series.iloc[::-1]
    rolled = reversed_series.rolling(window, min_periods=1).max() if how == "max" \
        else reversed_series.rolling(window, min_periods=1).min()
    return rolled.iloc[::-1]


def find_events(df: pd.DataFrame, align_threshold: int, horizon: int,
                 confirm_bars: int = 3, min_gap_bars: int = 20) -> list:
    """Scan `df` (needs BB_upper/BB_middle/BB_lower, confluence, OHLC, and
    the registry's `{name}_signal` columns) for bounce events. Returns a
    list of event dicts, oldest first.

    A bullish bounce bar: Low pierced BB_lower, Close climbed back above
    BB_lower within `confirm_bars` bars, and confluence wasn't fully
    aligned that day. A bearish bounce mirrors this off BB_upper.
    """
    required = {"BB_upper", "BB_middle", "BB_lower"}
    if not required.issubset(df.columns) or len(df) < 10:
        return []

    touched_lower = df["Low"] <= df["BB_lower"]
    touched_upper = df["High"] >= df["BB_upper"]

    future_max_close = _forward_extreme(df["Close"], confirm_bars + 1, "max")
    future_min_close = _forward_extreme(df["Close"], confirm_bars + 1, "min")
    confirmed_up = future_max_close > df["BB_lower"]
    confirmed_down = future_min_close < df["BB_upper"]

    ranging = df["confluence"].abs() < align_threshold

    bull_qualifies = (touched_lower & confirmed_up & ranging).fillna(False)
    bear_qualifies = (touched_upper & confirmed_down & ranging).fillna(False)

    fwd_close = df["Close"].shift(-horizon)

    bull_positions = events.anchored_events(bull_qualifies, df["Low"], min_gap_bars, mode="min")
    bear_positions = events.anchored_events(bear_qualifies, df["High"], min_gap_bars, mode="max")

    found = (
        [_build_event(df, pos, horizon, fwd_close, "bull") for pos in bull_positions]
        + [_build_event(df, pos, horizon, fwd_close, "bear") for pos in bear_positions]
    )
    found.sort(key=lambda e: e["position"])
    return found


def _build_event(df: pd.DataFrame, pos: int, horizon: int, fwd_close: pd.Series, direction: str) -> dict:
    row = df.iloc[pos]
    date = df.index[pos]
    close = float(row["Close"])
    band_value = float(row["BB_lower"]) if direction == "bull" else float(row["BB_upper"])

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
        "direction": direction,
        "confluence": int(row["confluence"]),
        "votes": indicators.votes_json_for_row(row),
        "band_value": band_value,
        "middle": float(row["BB_middle"]),
        "close": close,
        "horizon": horizon,
        "has_forward": has_forward,
        "fwd_close": float(fwd) if has_forward else None,
        "fwd_return_pct": fwd_return_pct,
        "hit": hit,
    }
