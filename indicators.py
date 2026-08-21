"""Raw metrics (MA/RSI/VolMA/Bollinger) + the indicator registry.

The registry is the extensibility point for this whole package: adding a new
confluence vote (e.g. MACD) later means writing one `compute(df, params)`
function and calling `register(...)` once -- nothing in backtest.py,
engine.py, reporting/*, or dashboard.py needs to change, since they all loop
`REGISTRY` instead of hardcoding indicator names.

Bollinger Bands are deliberately *not* registered here as a vote -- they are
a chart-overlay-only feature (see compute_bollinger_bands / dashboard.py) and
do not participate in `confluence` / `votes_json` / the backtest.
"""

from dataclasses import dataclass
from typing import Callable, List

import numpy as np
import pandas as pd

from stock_analyzer import config


@dataclass
class Indicator:
    name: str            # short key, used in votes_json
    label: str           # display label
    compute: Callable[[pd.DataFrame, dict], pd.Series]   # returns +1/-1 Series


REGISTRY: List[Indicator] = []


def register(indicator: Indicator) -> None:
    """Append an Indicator to the module-level REGISTRY, guarding against
    accidental duplicate names (which would silently corrupt votes_json)."""
    if any(existing.name == indicator.name for existing in REGISTRY):
        raise ValueError(f"Indicator '{indicator.name}' is already registered")
    REGISTRY.append(indicator)


# ---------------------------------------------------------------------------
# Raw metric columns (MA / RSI / VolMA / Bollinger) -- prepared once per
# ticker before any indicator's compute() runs, since several indicators
# depend on them.
# ---------------------------------------------------------------------------
def prepare_dataframe(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    """Add MA_short, MA_long, RSI, VolMA20, MACD/MACD_signal/MACD_hist
    columns to a raw OHLCV DataFrame. Does not mutate the caller's frame;
    returns a copy.

    MA_short/MA_long are exponential (EMA), not simple -- same `ewm(span=n,
    adjust=False)` form MACD's own internal EMAs already use below, so a
    5/22 EMA reacts to recent price the way traders actually mean when they
    say "EMA5/EMA22", not a same-period SMA (which lags it and can show a
    cross days later, or not yet, when the EMA pair already has).
    """
    out = df.copy()

    ma_short = params.get("ma_short", config.MA_SHORT)
    ma_long = params.get("ma_long", config.MA_LONG)
    rsi_period = params.get("rsi_period", config.RSI_PERIOD)
    vol_ma_period = params.get("vol_ma_period", config.VOL_MA_PERIOD)
    macd_fast = params.get("macd_fast", config.MACD_FAST)
    macd_slow = params.get("macd_slow", config.MACD_SLOW)
    macd_signal_period = params.get("macd_signal", config.MACD_SIGNAL)

    out["MA_short"] = out["Close"].ewm(span=ma_short, adjust=False).mean()
    out["MA_long"] = out["Close"].ewm(span=ma_long, adjust=False).mean()

    delta = out["Close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(rsi_period).mean()
    avg_loss = loss.rolling(rsi_period).mean()
    rs = avg_gain / avg_loss
    out["RSI"] = 100 - (100 / (1 + rs))

    out["VolMA20"] = out["Volume"].rolling(vol_ma_period).mean()

    ema_fast = out["Close"].ewm(span=macd_fast, adjust=False).mean()
    ema_slow = out["Close"].ewm(span=macd_slow, adjust=False).mean()
    out["MACD"] = ema_fast - ema_slow
    out["MACD_signal"] = out["MACD"].ewm(span=macd_signal_period, adjust=False).mean()
    out["MACD_hist"] = out["MACD"] - out["MACD_signal"]

    stoch_k_period = params.get("stoch_k_period", config.STOCH_K_PERIOD)
    stoch_d_period = params.get("stoch_d_period", config.STOCH_D_PERIOD)
    stoch_mode = params.get("stoch_mode", config.STOCH_MODE)

    lowest_low = out["Low"].rolling(stoch_k_period).min()
    highest_high = out["High"].rolling(stoch_k_period).max()
    stoch_range = (highest_high - lowest_low).replace(0, np.nan)
    raw_k = 100 * (out["Close"] - lowest_low) / stoch_range

    if stoch_mode == "fast":
        # Fast: %K is the raw, unsmoothed value -- no smoothing period applies.
        out["STOCH_K"] = raw_k
    elif stoch_mode == "full":
        # Full: like Slow, but the %K smoothing period is whatever the
        # caller asks for instead of the fixed conventional value -- this
        # is what "Full Stochastic" means on most platforms: same shape as
        # Slow, just every period is yours to tune.
        stoch_smoothing = params.get("stoch_slowing", config.STOCH_SLOWING)
        out["STOCH_K"] = raw_k.rolling(stoch_smoothing).mean()
    else:
        # Slow (the more common default on most platforms): %K is smoothed
        # with the conventional fixed 3-period average before %D smooths it
        # again. Fixed on purpose -- Full is what you reach for once you
        # want that smoothing period to be something other than 3.
        out["STOCH_K"] = raw_k.rolling(3).mean()
    out["STOCH_D"] = out["STOCH_K"].rolling(stoch_d_period).mean()

    di_period = params.get("di_period", config.DI_PERIOD)
    prev_high = out["High"].shift(1)
    prev_low = out["Low"].shift(1)
    prev_close = out["Close"].shift(1)

    up_move = out["High"] - prev_high
    down_move = prev_low - out["Low"]
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    true_range = pd.concat([
        out["High"] - out["Low"], (out["High"] - prev_close).abs(), (out["Low"] - prev_close).abs(),
    ], axis=1).max(axis=1)

    # Wilder's smoothing is an EMA with alpha = 1/period (not the plain
    # rolling mean the "14-period average" phrasing suggests) -- ewm's
    # `adjust=False` form is the standard pandas equivalent.
    atr = true_range.ewm(alpha=1 / di_period, adjust=False).mean()
    plus_dm_smoothed = pd.Series(plus_dm, index=out.index).ewm(alpha=1 / di_period, adjust=False).mean()
    minus_dm_smoothed = pd.Series(minus_dm, index=out.index).ewm(alpha=1 / di_period, adjust=False).mean()

    atr_safe = atr.replace(0, np.nan)
    out["DI_plus"] = 100 * plus_dm_smoothed / atr_safe
    out["DI_minus"] = 100 * minus_dm_smoothed / atr_safe

    di_sum = (out["DI_plus"] + out["DI_minus"]).replace(0, np.nan)
    dx = 100 * (out["DI_plus"] - out["DI_minus"]).abs() / di_sum
    out["ADX"] = dx.ewm(alpha=1 / di_period, adjust=False).mean()

    return out


def compute_bollinger_bands(df: pd.DataFrame, period: int = None, num_std: float = None) -> pd.DataFrame:
    """Add BB_middle / BB_upper / BB_lower / BB_width columns. Chart-overlay
    only -- does not feed into confluence/votes_json/backtest. BB_width is
    the normalized (upper - lower) / middle spread, i.e. band "bandwidth":
    it reads volatility directly instead of making you eyeball how far apart
    the raw bands are, which is what the bands alone stop conveying once
    you've zoomed into a narrow date range. Returns a copy.
    """
    period = period if period is not None else config.BB_PERIOD
    num_std = num_std if num_std is not None else config.BB_STDDEV

    out = df.copy()
    out["BB_middle"] = out["Close"].rolling(period).mean()
    rolling_std = out["Close"].rolling(period).std()
    out["BB_upper"] = out["BB_middle"] + num_std * rolling_std
    out["BB_lower"] = out["BB_middle"] - num_std * rolling_std
    out["BB_width"] = (out["BB_upper"] - out["BB_lower"]) / out["BB_middle"]
    return out


# ---------------------------------------------------------------------------
# Registered confluence-vote indicators
# ---------------------------------------------------------------------------
def trend_signal(df: pd.DataFrame, params: dict) -> pd.Series:
    """+1 if Close is above the long moving average, else -1."""
    return (df["Close"] > df["MA_long"]).astype(int) * 2 - 1


def momentum_signal(df: pd.DataFrame, params: dict) -> pd.Series:
    """+1 if RSI is above 50 (bullish momentum), else -1."""
    return (df["RSI"] > 50).astype(int) * 2 - 1


def volume_signal(df: pd.DataFrame, params: dict) -> pd.Series:
    """+1 if above-average volume confirms the day's own direction, or
    below-average volume fades it (i.e. a quiet down day is read as +1
    because the lack of volume undercuts conviction in the decline); -1
    for the opposite pairing. A flat (zero) day is treated as +1.
    """
    day_dir = np.sign(df["Close"] - df["Open"])
    vote = np.where(df["Volume"] > df["VolMA20"], day_dir, -day_dir)
    return pd.Series(vote, index=df.index).replace(0, 1).astype(int)


def macd_cross_signal(df: pd.DataFrame, params: dict) -> pd.Series:
    """+1 if MACD is above its signal line (bullish crossover state), else -1."""
    return (df["MACD"] > df["MACD_signal"]).astype(int) * 2 - 1


def stochastic_signal(df: pd.DataFrame, params: dict) -> pd.Series:
    """+1 if %K is above %D (bullish stochastic state), else -1. Which
    variant (fast/slow/full) %K/%D actually are is decided once, upstream, in
    prepare_dataframe() via params["stoch_mode"] -- this just reads
    whatever ended up in those columns.
    """
    return (df["STOCH_K"] > df["STOCH_D"]).astype(int) * 2 - 1


def di_signal(df: pd.DataFrame, params: dict) -> pd.Series:
    """+1 if +DI is above -DI (bullish directional-movement state), else -1."""
    return (df["DI_plus"] > df["DI_minus"]).astype(int) * 2 - 1


register(Indicator("trend", "Trend", trend_signal))
register(Indicator("momentum", "Momentum", momentum_signal))
register(Indicator("volume", "Volume", volume_signal))
register(Indicator("macd", "MACD", macd_cross_signal))
register(Indicator("stochastic", "Stochastic", stochastic_signal))
register(Indicator("di", "DI+/-", di_signal))


def active_indicator_names(params: dict) -> list:
    """Which registered indicators actually count toward `confluence` --
    params["active_indicators"] (a list of names) if the caller set one,
    else every registered indicator. Falls back to "every indicator" if the
    list is empty or names nothing real, so a bad/stale selection can never
    silently zero out confluence.
    """
    active = params.get("active_indicators")
    if not active:
        return [ind.name for ind in REGISTRY]
    valid_names = {ind.name for ind in REGISTRY}
    filtered = [name for name in active if name in valid_names]
    return filtered or [ind.name for ind in REGISTRY]


def apply_indicators(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    """Prepare raw metric columns, then loop the REGISTRY to compute each
    indicator's +1/-1 vote column, summing only the active ones (see
    active_indicator_names()) into `confluence`. Every indicator's signal
    column is still computed regardless of active/inactive -- votes_json
    stays complete either way -- only the confluence sum itself is scoped.
    """
    out = prepare_dataframe(df, params)
    for ind in REGISTRY:
        out[f"{ind.name}_signal"] = ind.compute(out, params)
    active_names = active_indicator_names(params)
    out["confluence"] = out[[f"{name}_signal" for name in active_names]].sum(axis=1)
    return out


def default_align_threshold(params: dict = None) -> int:
    """'All indicators agree' threshold -- derived from how many indicators
    are actually active (see active_indicator_names()) instead of a
    hardcoded 3, so it grows automatically as indicators are added and
    shrinks automatically when some are toggled off. `params=None` (the
    registry-size default) is for callers that don't have a params dict
    yet, e.g. at import time.
    """
    if params is not None:
        return len(active_indicator_names(params))
    return len(REGISTRY)


def votes_json_for_row(row) -> dict:
    """Build the {"trend": 1, "momentum": -1, ...} dict for one row (a
    pandas Series / dict-like with `{name}_signal` columns), looping the
    registry so it stays in sync automatically.
    """
    return {ind.name: int(row[f"{ind.name}_signal"]) for ind in REGISTRY}
