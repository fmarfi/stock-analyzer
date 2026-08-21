"""Ticker universe sourcing: S&P 500 Wikipedia scrape (needs lxml) with a
graceful fallback to a small hardcoded list, plus named watchlists.

Ported conceptually from scoreboard_app.py's get_ticker_list() (not imported
from it -- that module has top-level side effects that make it unsafe to
import). Unlike scoreboard_app.py, the scrape here is *not* run at import
time -- callers opt in explicitly, so importing this module never triggers
network access.
"""

import logging

from stock_analyzer import config

logger = logging.getLogger(__name__)


def get_sp500_tickers() -> list:
    """Scrape the current S&P 500 constituent list from Wikipedia. Requires
    `lxml` (used by pandas.read_html under the hood) and network access.
    Falls back to config.FALLBACK_UNIVERSE on any failure -- missing lxml,
    no network, Wikipedia rejecting the request (it 403s a bare urllib/
    pandas request with no User-Agent, hence the explicit header below), or
    the page structure changing.
    """
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    try:
        import io
        import pandas as pd  # local import: only needed for this scrape
        import requests

        response = requests.get(
            url, headers={"User-Agent": "Mozilla/5.0 (stock_analyzer/1.0)"}, timeout=10,
        )
        response.raise_for_status()
        tables = pd.read_html(io.StringIO(response.text))
        table = tables[0]
        tickers = sorted(table["Symbol"].str.replace(".", "-", regex=False).tolist())
        if not tickers:
            raise ValueError("Wikipedia scrape returned no tickers")
        return tickers
    except Exception as exc:
        logger.warning(
            "S&P 500 Wikipedia scrape failed (%s); falling back to hardcoded list", exc
        )
        return list(config.FALLBACK_UNIVERSE)


def get_watchlist(name: str = None) -> list:
    """Look up a named watchlist from config.WATCHLISTS. Falls back to the
    default watchlist if `name` is None or unknown.
    """
    if name and name in config.WATCHLISTS:
        return list(config.WATCHLISTS[name])
    if name:
        logger.warning("Unknown watchlist '%s'; using default '%s'", name, config.DEFAULT_WATCHLIST_NAME)
    return list(config.WATCHLISTS[config.DEFAULT_WATCHLIST_NAME])


def resolve_universe(tickers_csv: str = None, watchlist_name: str = None) -> list:
    """Resolve a ticker universe from CLI-style inputs: an explicit
    comma-separated ticker list takes priority over a named watchlist,
    which takes priority over the default watchlist.
    """
    if tickers_csv:
        return [t.strip().upper() for t in tickers_csv.split(",") if t.strip()]
    return get_watchlist(watchlist_name)
