"""Horizon/alignment backtest stats.

Pure function module: no DB, no network, no UI, so it's trivial to unit-test
in isolation. Written fresh for this package -- the conceptual questions it
answers (how often does price rise over the next N bars in general, and does
it rise/fall more often specifically when the indicators are fully aligned
in one direction) are the same ones explored ad hoc in scoreboard_app.py, but
the implementation here is decomposed differently (separate small helpers
for forward returns, subset selection, and hit-rate/edge arithmetic) rather
than ported line-for-line.

Terminology:
  - "forward return" for a given bar = close `horizon` bars later, vs today's
    close.
  - "base rate" = fraction of all valid bars where the forward return was
    positive, regardless of what the indicators said that day -- i.e. the
    naive "market went up" rate an indicator has to beat to be useful.
  - "bull-aligned" bar = confluence == +align_threshold (every registered
    indicator voted up that day). "bear-aligned" = confluence == -align_threshold.
  - "edge" = how much better (or worse) the aligned hit rate is than the
    relevant base rate, in percentage points.
"""

from dataclasses import dataclass, asdict

import numpy as np
import pandas as pd


def compute_forward_returns(df: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """Return a copy of `df` with two new columns:
      - fwd_return: (Close `horizon` bars ahead / Close today) - 1
      - fwd_up: bool, whether that forward return is positive
    Rows near the end of the series (where there's no future bar yet) get
    NaN and should be dropped by the caller before aggregating.
    """
    out = df.copy()
    out["fwd_return"] = out["Close"].shift(-horizon) / out["Close"] - 1
    out["fwd_up"] = out["fwd_return"] > 0
    return out


def _safe_mean(series: pd.Series) -> float:
    """Mean of a boolean/numeric series, NaN if there's nothing to average."""
    return float(series.mean()) if len(series) else float("nan")


def _hit_rate_bull(subset: pd.DataFrame) -> float:
    """Fraction of a bull-aligned subset whose forward return was positive."""
    return _safe_mean(subset["fwd_up"])


def _hit_rate_bear(subset: pd.DataFrame) -> float:
    """Fraction of a bear-aligned subset whose forward return was negative
    (a 'hit' for a bearish signal means price actually fell)."""
    return _safe_mean(subset["fwd_return"] < 0)


def _edge_pp(hit_rate: float, baseline: float, n: int) -> float:
    """Edge in percentage points: how much better the aligned hit rate did
    than its relevant baseline. NaN if the subset was empty."""
    if n == 0 or pd.isna(hit_rate) or pd.isna(baseline):
        return float("nan")
    return (hit_rate - baseline) * 100.0


def _directional_accuracy(valid: pd.DataFrame) -> tuple:
    """Among bars where confluence was non-zero (i.e. the indicators made
    *some* directional call, even if not fully aligned), what fraction of
    the time did the sign of confluence match the sign of the forward
    return? Returns (accuracy, n).
    """
    predicted = valid[valid["confluence"] != 0]
    if len(predicted) == 0:
        return float("nan"), 0
    matched = np.sign(predicted["confluence"]) == np.sign(predicted["fwd_return"])
    return float(matched.mean()), len(predicted)


@dataclass
class BacktestStats:
    base_rate_up: float
    bull_hit_rate: float
    bear_hit_rate: float
    bull_edge: float
    bear_edge: float
    overall_hit_rate: float
    n_bull: int
    n_bear: int
    n_overall: int
    n_bars: int

    def as_dict(self) -> dict:
        return asdict(self)


def run_backtest(df: pd.DataFrame, horizon: int, align_threshold: int) -> BacktestStats:
    """Compute historical hit-rate / edge stats for a ticker's indicator
    history.

    `df` must already have a `confluence` column (see indicators.apply_indicators).
    `horizon` is how many bars forward to measure returns over.
    `align_threshold` is the |confluence| value counted as "fully aligned"
    (normally len(indicators.REGISTRY), i.e. every registered vote agrees).

    Note on sample size: because horizons overlap (bar N's forward window
    shares days with bar N+1's), n_bull/n_bear/n_overall count aligned
    *bars*, not independent events -- the effective sample size is smaller
    than the raw count suggests. This mirrors the caveat raised in the
    original notebook prototype; we still report raw n for transparency.
    """
    with_returns = compute_forward_returns(df, horizon)
    valid = with_returns.dropna(subset=["fwd_return", "confluence"])

    n_bars = len(valid)
    base_rate_up = _safe_mean(valid["fwd_up"]) if n_bars else float("nan")

    bull_subset = valid[valid["confluence"] == align_threshold]
    bear_subset = valid[valid["confluence"] == -align_threshold]

    bull_hit = _hit_rate_bull(bull_subset)
    bear_hit = _hit_rate_bear(bear_subset)

    bear_baseline = (1 - base_rate_up) if not pd.isna(base_rate_up) else float("nan")
    bull_edge = _edge_pp(bull_hit, base_rate_up, len(bull_subset))
    bear_edge = _edge_pp(bear_hit, bear_baseline, len(bear_subset))

    overall_hit, n_overall = _directional_accuracy(valid)

    return BacktestStats(
        base_rate_up=base_rate_up,
        bull_hit_rate=bull_hit,
        bear_hit_rate=bear_hit,
        bull_edge=bull_edge,
        bear_edge=bear_edge,
        overall_hit_rate=overall_hit,
        n_bull=len(bull_subset),
        n_bear=len(bear_subset),
        n_overall=n_overall,
        n_bars=n_bars,
    )
