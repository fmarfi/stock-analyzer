"""OHLCV chart transformations that don't change what the underlying
indicators are computed from -- only how the price panel gets drawn:
resampling a daily DataFrame into weekly bars, and converting real OHLC
into Heikin Ashi OHLC.

Indicators (MA/RSI/Bollinger) are recomputed fresh on resampled OHLCV
rather than resampled themselves -- a 20-week MA is a genuinely different
number from resampling a daily MA20 down to weekly, and recomputing is what
a real weekly chart is expected to show. Heikin Ashi, by contrast, never
touches the indicator columns at all -- see compute_heikin_ashi().
"""

import numpy as np
import pandas as pd

from stock_analyzer import config, indicators

_OHLCV_AGG = {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}


def resample_ohlcv(df: pd.DataFrame, rule: str, params: dict) -> pd.DataFrame:
    """Resample df's OHLCV columns to `rule` (a pandas offset alias, e.g.
    "W" for weekly), dropping any bar with no trading days in it (holiday
    weeks at the edges), then recompute MA/RSI/Bollinger on the resampled
    series using the same params the daily chart used.
    """
    resampled = df[list(_OHLCV_AGG)].resample(rule).agg(_OHLCV_AGG).dropna(subset=["Close"])
    return prepare_with_indicators(resampled, params)


def prepare_with_indicators(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    """Compute MA/RSI/MACD/Stochastic/DI + Bollinger Bands on a raw OHLCV
    frame using the same params a daily chart would. Shared by
    resample_ohlcv() (weekly, derived from the daily frame) and the Hourly
    chart view (an independent yfinance fetch -- hourly bars can't be
    derived from daily ones the way weekly can, so that path calls this
    directly on its own fetched frame instead of going through resampling).
    """
    with_indicators = indicators.prepare_dataframe(df, params)
    return indicators.compute_bollinger_bands(
        with_indicators,
        period=params.get("bb_period", config.BB_PERIOD),
        num_std=params.get("bb_stddev", config.BB_STDDEV),
    )


def compute_heikin_ashi(df: pd.DataFrame) -> pd.DataFrame:
    """Replace Open/High/Low/Close with their Heikin Ashi equivalents:
    HA_Close is the average of the bar's real OHLC (smooths out noise);
    HA_Open is the midpoint of the *previous* Heikin Ashi bar's open/close,
    which is what chains bars together into HA's smoothed, trend-following
    look; HA_High/HA_Low extend the real High/Low to also cover HA_Open/
    HA_Close so a candle's wick never contradicts its own body.

    Any other columns (MA/RSI/MACD/etc, if already present) are left
    untouched -- only the candle body changes. Indicators should keep
    reading real price, not the smoothed Heikin Ashi representation, so
    call this last, purely for how the price panel gets drawn.
    """
    out = df.copy()
    n = len(out)
    open_ = out["Open"].to_numpy(dtype=float)
    high = out["High"].to_numpy(dtype=float)
    low = out["Low"].to_numpy(dtype=float)
    close = out["Close"].to_numpy(dtype=float)

    ha_close = (open_ + high + low + close) / 4
    ha_open = np.empty(n)
    if n > 0:
        ha_open[0] = (open_[0] + close[0]) / 2
        for i in range(1, n):
            ha_open[i] = (ha_open[i - 1] + ha_close[i - 1]) / 2
    ha_high = np.maximum.reduce([high, ha_open, ha_close])
    ha_low = np.minimum.reduce([low, ha_open, ha_close])

    out["Open"] = ha_open
    out["High"] = ha_high
    out["Low"] = ha_low
    out["Close"] = ha_close
    return out
