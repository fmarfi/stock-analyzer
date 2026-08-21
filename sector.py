"""Ticker -> GICS sector lookup, cached in SQLite (see db.ticker_sectors).

yfinance's .info endpoint is much slower than a price download and rate-
limits more aggressively, so this caches indefinitely rather than re-fetching
every scan -- sector classification essentially never changes day to day.
Delete the row from ticker_sectors manually if a ticker's classification
needs to be refreshed.
"""

import datetime
import logging

import yfinance as yf

from stock_analyzer import db as db_mod

logger = logging.getLogger(__name__)

UNKNOWN = "Unknown"


def get_sector(conn, ticker: str) -> str:
    """Sector for `ticker`: cached value if present, else fetched from
    yfinance and cached. Never raises -- returns UNKNOWN if yfinance has no
    sector for this ticker (ETFs, indices, delisted names, ...) or the
    lookup fails.
    """
    cached = db_mod.get_cached_sector(conn, ticker)
    if cached is not None:
        return cached

    sector, industry = UNKNOWN, None
    try:
        info = yf.Ticker(ticker).info
        sector = info.get("sector") or UNKNOWN
        industry = info.get("industry")
    except Exception:
        logger.warning("Could not fetch sector for %s; using '%s'", ticker, UNKNOWN)

    db_mod.upsert_sector(conn, ticker, sector, industry, datetime.datetime.now().isoformat(timespec="seconds"))
    return sector
