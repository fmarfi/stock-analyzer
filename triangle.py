"""Triangle chart-pattern detection: ascending, descending, and symmetrical
triangles, found by fitting trendlines through swing highs and swing lows
within a sliding lookback window and checking that the two lines are
genuinely converging -- not just two arbitrarily-sloped lines that happen
to both be present.

A swing high/low is a local extreme: High[i] (Low[i]) is the max (min) of
its own +/- `pivot_lookback` neighborhood. At least `min_pivots` of each
are required inside the window before a trendline is even attempted, so a
"triangle" needs real touches on both sides, not two points connected by
construction.

Trendline fit: NOT a least-squares regression through every pivot. A
regression line is an average through the points, and can end up violated
by a big chunk of the actual candles in the window (an early version of
this module had a case where the "support" line was broken by price on 16
of 61 bars) -- which defeats the point, since a support/resistance line's
whole definition is that price doesn't cross it. Instead, every pair of
pivot points is tried as a candidate line, and the pair whose line has the
fewest breaches against the *entire* High/Low series in the window (not
just the pivots) wins -- the same idea as a convex-hull boundary, just
computed by brute-force pair search since there are only a handful of
pivots per window. A small tolerance allows for a candle wick or two
grazing past the line; beyond `max_violations` the window is rejected
outright rather than accepted with a line that doesn't actually act as a
boundary.

Classification (slopes normalized by the window-average price, so the
thresholds mean the same thing regardless of the ticker's price level):
  - ascending:   upper trendline ~flat, lower trendline rising   (buyers stepping up into resistance)
  - descending:  lower trendline ~flat, upper trendline falling  (sellers stepping down into support)
  - symmetrical: upper falling AND lower rising                  (range compressing from both sides)

Like squeeze.py/bounce.py, nearby qualifying windows are collapsed into one
event via events.anchored_events, anchored on the tightest convergence in
the cluster (closest to the apex, i.e. closest to where a breakout would be
expected). Ascending/descending triangles have a textbook-expected breakout
direction, scored the same hit/miss way as squeeze/bounce; symmetrical
triangles don't (classic TA says they tend to continue whatever trend
preceded them, which this module doesn't try to determine), so their `hit`
is always None -- the forward return is still reported, just not graded.
"""

import numpy as np
import pandas as pd

FLAT_SLOPE_PCT = 0.0015    # per-bar slope, as a fraction of avg price, below which a line counts as "flat"
TREND_SLOPE_PCT = 0.0015   # per-bar slope magnitude required to count as genuinely rising/falling
MIN_CONVERGENCE = 0.30     # the gap between the lines must shrink by at least this fraction over the window
TOUCH_TOL_PCT = 0.003      # tolerance (as a fraction of avg price) for "on the line" / a minor wick breach
MAX_VIOLATIONS = 2         # a boundary line can be pierced by at most this many bars in the window


def _find_pivots(series: pd.Series, lookback: int, kind: str) -> np.ndarray:
    """Positions where `series` is a local max (kind="high") or min
    (kind="low") within +/- lookback bars of itself."""
    values = series.to_numpy()
    n = len(values)
    positions = []
    for i in range(lookback, n - lookback):
        window = values[i - lookback:i + lookback + 1]
        if kind == "high" and values[i] == window.max():
            positions.append(i)
        elif kind == "low" and values[i] == window.min():
            positions.append(i)
    return np.array(positions, dtype=int)


def _best_boundary_line(pivot_positions: np.ndarray, pivot_prices: np.ndarray,
                         all_positions: np.ndarray, all_prices: np.ndarray, side: str, tol: float):
    """Try every pair of pivot points as a candidate line; return the
    (slope, intercept, violations) whose line is breached the least by
    `all_prices` across the whole window -- side="upper": prices should
    stay <= line (breach = price above it); side="lower": prices should
    stay >= line (breach = price below it). None if fewer than 2 pivots.
    """
    n = len(pivot_positions)
    if n < 2:
        return None

    best = None
    for i in range(n):
        for j in range(i + 1, n):
            x1, y1 = pivot_positions[i], pivot_prices[i]
            x2, y2 = pivot_positions[j], pivot_prices[j]
            if x2 == x1:
                continue
            slope = (y2 - y1) / (x2 - x1)
            intercept = y1 - slope * x1
            line_vals = intercept + slope * all_positions
            if side == "upper":
                violations = int(np.sum(all_prices > line_vals + tol))
            else:
                violations = int(np.sum(all_prices < line_vals - tol))
            if best is None or violations < best[2]:
                best = (float(slope), float(intercept), violations)

    return best


def find_events(df: pd.DataFrame, horizon: int, window_bars: int = 60, pivot_lookback: int = 5,
                 min_pivots: int = 3, min_gap_bars: int = 15) -> list:
    """Scan `df` (needs High/Low/Close) for triangle formations. Returns a
    list of event dicts, oldest first.
    """
    from stock_analyzer import events  # local import: avoids a module-level cycle with squeeze/bounce's own imports

    n = len(df)
    if n < window_bars + pivot_lookback * 2 + 1:
        return []

    high_pivots = _find_pivots(df["High"], pivot_lookback, "high")
    low_pivots = _find_pivots(df["Low"], pivot_lookback, "low")
    highs = df["High"].to_numpy()
    lows = df["Low"].to_numpy()
    closes = df["Close"].to_numpy()
    fwd_close = df["Close"].shift(-horizon)

    qualifies = np.zeros(n, dtype=bool)
    gap_ratio = np.full(n, np.inf)
    triangle_type = [None] * n
    line_params = [None] * n

    for end in range(window_bars, n):
        start = end - window_bars

        h_pos = high_pivots[(high_pivots >= start) & (high_pivots <= end)]
        l_pos = low_pivots[(low_pivots >= start) & (low_pivots <= end)]
        if len(h_pos) < min_pivots or len(l_pos) < min_pivots:
            continue

        avg_price = closes[start:end + 1].mean()
        if avg_price <= 0:
            continue
        tol = avg_price * TOUCH_TOL_PCT

        all_pos = np.arange(start, end + 1)
        upper = _best_boundary_line(h_pos, highs[h_pos], all_pos, highs[start:end + 1], "upper", tol)
        lower = _best_boundary_line(l_pos, lows[l_pos], all_pos, lows[start:end + 1], "lower", tol)
        if upper is None or lower is None:
            continue
        h_slope, h_intercept, h_violations = upper
        l_slope, l_intercept, l_violations = lower
        if h_violations > MAX_VIOLATIONS or l_violations > MAX_VIOLATIONS:
            continue

        h_slope_pct = h_slope / avg_price
        l_slope_pct = l_slope / avg_price

        gap_start = (h_intercept + h_slope * start) - (l_intercept + l_slope * start)
        gap_end = (h_intercept + h_slope * end) - (l_intercept + l_slope * end)
        if gap_start <= 0 or gap_end <= 0:
            continue  # lines already crossed somewhere in-window -- not a still-forming triangle
        if gap_end > gap_start * (1 - MIN_CONVERGENCE):
            continue  # not converging enough to call it a triangle rather than two random lines

        if abs(h_slope_pct) < FLAT_SLOPE_PCT and l_slope_pct > TREND_SLOPE_PCT:
            ttype = "ascending"
        elif abs(l_slope_pct) < FLAT_SLOPE_PCT and h_slope_pct < -TREND_SLOPE_PCT:
            ttype = "descending"
        elif h_slope_pct < -TREND_SLOPE_PCT and l_slope_pct > TREND_SLOPE_PCT:
            ttype = "symmetrical"
        else:
            continue

        qualifies[end] = True
        gap_ratio[end] = gap_end / avg_price
        triangle_type[end] = ttype
        line_params[end] = (h_slope, h_intercept, l_slope, l_intercept, start, end)

    if not qualifies.any():
        return []

    priority = pd.Series(gap_ratio, index=df.index)
    positions = events.anchored_events(pd.Series(qualifies, index=df.index), priority, min_gap_bars, mode="min")

    return [
        _build_event(df, pos, horizon, fwd_close, triangle_type[pos], line_params[pos])
        for pos in positions
    ]


def _build_event(df: pd.DataFrame, pos: int, horizon: int, fwd_close: pd.Series, ttype: str, line_params: tuple) -> dict:
    h_slope, h_intercept, l_slope, l_intercept, win_start, win_end = line_params
    date = df.index[pos]
    close = float(df["Close"].iloc[pos])

    fwd = fwd_close.iloc[pos]
    has_forward = not pd.isna(fwd)
    fwd_return_pct = ((float(fwd) / close) - 1) * 100.0 if has_forward else None

    hit = None
    if has_forward and ttype == "ascending":
        hit = fwd_return_pct > 0
    elif has_forward and ttype == "descending":
        hit = fwd_return_pct < 0

    return {
        "position": pos,
        "date": date,
        "date_str": date.strftime("%Y-%m-%d"),
        "type": ttype,
        "close": close,
        "window_start": win_start,
        "window_end": win_end,
        "high_slope": h_slope, "high_intercept": h_intercept,
        "low_slope": l_slope, "low_intercept": l_intercept,
        "horizon": horizon,
        "has_forward": has_forward,
        "fwd_close": float(fwd) if has_forward else None,
        "fwd_return_pct": fwd_return_pct,
        "hit": hit,
    }
