"""yfinance download + incremental cache logic.

This is the only module that talks to the network. The core idea: price
history for a ticker only ever grows a few rows per day once it has been
fetched once, so instead of re-downloading years of daily bars on every
run, we ask SQLite what the newest stored date is and only request the
(usually tiny) gap between that date and today.

Step-by-step per ticker, exactly as designed:
  1. Ask the DB what it already has (`db.get_last_date`).
  2. Decide the fetch window: full history from `default_start_date` if the
     ticker has never been fetched, otherwise a trailing overlap window
     before the last stored date forward (see INCREMENTAL_OVERLAP_DAYS --
     re-fetching just the single last date isn't enough of a safety margin
     against a batch download coming back with a hole for one business day).
  3. Call yfinance with that narrow start/end window.
  4. Upsert (INSERT OR REPLACE) into price_history, keyed on (ticker, date).
  5. Read back the *full* series from SQLite for indicators/backtest to use,
     regardless of whether it came from the network just now or was already
     cached from a prior run.
"""

import logging
from datetime import datetime, timedelta

import pandas as pd
import yfinance as yf

from stock_analyzer import config, db

logger = logging.getLogger(__name__)

# Flag a bar as a bad tick when its close deviates from BOTH neighbors by
# more than this, while those neighbors are themselves within
# BAD_TICK_REVERT_TOL of each other -- i.e. a one-day spike that fully
# reverts the next bar. Real BIST sessions are bound by daily price limits
# (single digits to ~20%), so a >50% spike-and-revert is a data glitch, not
# a real move; this shows up occasionally for thinly-traded/newly-listed
# names (seen on KTLEV.IS).
BAD_TICK_DEVIATION = 0.50
BAD_TICK_REVERT_TOL = 0.15


def _repair_bad_ticks(frame, ticker):
    """Repair (not drop, to keep the date series continuous) isolated
    single-bar price spikes yfinance occasionally serves. Returns `frame`
    unchanged if nothing qualifies."""
    if len(frame) < 3:
        return frame

    close = frame["Close"]
    prev_close = close.shift(1)
    next_close = close.shift(-1)

    dev_prev = (close - prev_close).abs() / prev_close
    dev_next = (close - next_close).abs() / next_close
    reverts = (next_close - prev_close).abs() / prev_close < BAD_TICK_REVERT_TOL

    bad = ((dev_prev > BAD_TICK_DEVIATION) & (dev_next > BAD_TICK_DEVIATION) & reverts).fillna(False)
    if not bad.any():
        return frame

    frame = frame.copy()
    interpolated = (prev_close + next_close) / 2
    for col in ["Open", "High", "Low", "Close"]:
        frame.loc[bad, col] = interpolated[bad]

    for ts in frame.index[bad]:
        date_str = ts.strftime("%Y-%m-%d") if hasattr(ts, "strftime") else str(ts)[:10]
        logger.warning(
            "%s: repaired suspected bad tick on %s (implausible single-day spike/revert)", ticker, date_str,
        )
    return frame


def _normalize_yf_frame(raw, ticker=None):
    """Convert a raw yfinance DataFrame into a list of
    (date_str, open, high, low, close, volume) tuples, dropping any rows
    with missing OHLCV data (e.g. a half day with no volume)."""
    if raw is None or raw.empty:
        return []

    frame = raw.copy()

    # yfinance can return a MultiIndex column frame in some code paths even
    # with multi_level_index=False depending on version; flatten defensively.
    if isinstance(frame.columns, pd.MultiIndex):
        frame.columns = frame.columns.get_level_values(0)

    frame = frame[["Open", "High", "Low", "Close", "Volume"]].dropna()
    frame = _repair_bad_ticks(frame, ticker)

    rows = []
    for ts, r in frame.iterrows():
        date_str = ts.strftime("%Y-%m-%d") if hasattr(ts, "strftime") else str(ts)[:10]
        rows.append((
            date_str,
            float(r["Open"]), float(r["High"]), float(r["Low"]), float(r["Close"]),
            int(r["Volume"]),
        ))
    return rows


# How far back an "incremental" fetch re-requests beyond the last stored
# date. Re-including just that single date isn't enough of a safety margin:
# a batch yfinance download has been observed to come back with a hole for
# one business day in the middle of an otherwise-contiguous range (e.g. 144
# of 154 cached tickers were missing 2026-08-19 specifically, sitting
# between correctly-stored 08-18 and 08-20 rows, after one bulk fetch) --
# re-requesting a trailing week and upserting (INSERT OR REPLACE, keyed on
# ticker+date) lets every incremental fetch self-heal a gap like that
# automatically instead of it staying silently missing until someone
# notices a chart looks wrong.
INCREMENTAL_OVERLAP_DAYS = 7


def fetch_and_update(conn, ticker, default_start_date=None, end_date=None):
    """Fetch the missing date range (plus a trailing overlap window, see
    INCREMENTAL_OVERLAP_DAYS) for `ticker` from yfinance and upsert it into
    SQLite. Returns a dict describing what happened, e.g.:

        {"ticker": "AAPL", "mode": "incremental", "start": "2026-08-01",
         "rows_fetched": 2, "rows_written": 2}

    `mode` is "full" the first time a ticker is ever fetched, "incremental"
    thereafter.
    """
    default_start_date = default_start_date or config.DEFAULT_START_DATE
    end_date = end_date if end_date else config.DEFAULT_END_DATE

    # --- Step 1: ask the DB what it already has ---
    last = db.get_last_date(conn, ticker)

    # --- Step 2: decide the fetch window ---
    if last is None:
        mode = "full"
        start = default_start_date
    else:
        mode = "incremental"
        last_dt = datetime.strptime(last, "%Y-%m-%d")
        start = (last_dt - timedelta(days=INCREMENTAL_OVERLAP_DAYS)).strftime("%Y-%m-%d")

    # --- Step 3: call yfinance with that narrow window ---
    download_kwargs = dict(
        start=start,
        interval="1d",
        multi_level_index=False,
        progress=False,
        auto_adjust=True,
    )
    if end_date:
        download_kwargs["end"] = end_date

    try:
        raw = yf.download(ticker, **download_kwargs)
    except Exception:
        logger.exception("yfinance download failed for %s", ticker)
        raw = None

    rows = _normalize_yf_frame(raw, ticker)

    # --- Step 4: upsert, don't append ---
    rows_written = db.upsert_price_rows(conn, ticker, rows)

    result = {
        "ticker": ticker,
        "mode": mode,
        "start": start,
        "rows_fetched": len(rows),
        "rows_written": rows_written,
    }
    logger.info(
        "%s: %s fetch from %s -> %d row(s) fetched/upserted",
        ticker, mode, start, rows_written,
    )
    return result


def load_full_history(conn, ticker, start=None, end=None):
    """Read the complete cached series for `ticker` back from SQLite as a
    pandas DataFrame with a DatetimeIndex and columns Open/High/Low/Close/Volume
    -- the shape indicators.py and backtest.py expect. Callers never need to
    know whether the underlying data came from the network just now or was
    already sitting in the DB.
    """
    start = start or config.DEFAULT_START_DATE
    end = end if end else None

    db_rows = db.load_price_history(conn, ticker, start=start, end=end)
    if not db_rows:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])

    frame = pd.DataFrame([dict(r) for r in db_rows])
    frame["date"] = pd.to_datetime(frame["date"])
    frame = frame.set_index("date").sort_index()
    frame = frame.rename(columns={
        "open": "Open", "high": "High", "low": "Low",
        "close": "Close", "volume": "Volume",
    })
    return frame[["Open", "High", "Low", "Close", "Volume"]]


def fetch_and_load(conn, ticker, default_start_date=None, end_date=None):
    """Convenience wrapper: fetch_and_update() then load_full_history().
    Returns (dataframe, fetch_result_dict).
    """
    fetch_result = fetch_and_update(conn, ticker, default_start_date, end_date)
    frame = load_full_history(conn, ticker, start=default_start_date, end=end_date)
    return frame, fetch_result


def fetch_hourly_ohlcv(ticker, period="180d"):
    """Fetch hourly OHLCV bars directly from yfinance for the standalone
    chart window's Hourly view -- deliberately NOT cached in SQLite the way
    daily bars are (fetch_and_update/load_full_history): hourly data has a
    fundamentally different shape (multiple bars per calendar day, which
    price_history's (ticker, date) primary key can't hold without a schema
    change) and Yahoo only serves a bounded lookback anyway (up to ~730
    days at the 60-minute interval, not full history), so there's much less
    to gain from persisting it -- one fresh request per chart open is cheap
    enough. Returns a DataFrame with a tz-aware (exchange-local) DatetimeIndex
    and Open/High/Low/Close/Volume columns, empty if yfinance has nothing.

    period defaults to 180d (~1500 bars), not yfinance's max of 730d
    (~6250 bars): the default Hourly view only ever shows the last ~160 bars
    on open (see _RECENT_WINDOW_BARS), and every extra bar past what's
    actually useful for pan-back is more data every trace carries, every
    zoom/pan step has to re-scan, and every KB the browser has to load and
    keep interactive -- 730 days of hourly detail is far more history than
    "hourly" is ever used to look at anyway.
    """
    try:
        raw = yf.download(
            ticker, period=period, interval="60m", multi_level_index=False,
            progress=False, auto_adjust=True,
        )
    except Exception:
        logger.exception("yfinance hourly download failed for %s", ticker)
        raw = None

    if raw is None or raw.empty:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])

    frame = raw.copy()
    if isinstance(frame.columns, pd.MultiIndex):
        frame.columns = frame.columns.get_level_values(0)
    return frame[["Open", "High", "Low", "Close", "Volume"]].dropna()
