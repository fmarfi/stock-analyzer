"""SQLite connection + schema DDL. This is the only module that knows SQL.

Everything else (fetch.py, engine.py, reporting/*) goes through get_connection()
and the small set of read/write helpers here rather than writing raw SQL
inline, so the schema has exactly one owner.
"""

import os
import sqlite3

from stock_analyzer import config

SCHEMA_DDL = """
CREATE TABLE IF NOT EXISTS price_history (
    ticker TEXT NOT NULL, date TEXT NOT NULL,
    open REAL NOT NULL, high REAL NOT NULL, low REAL NOT NULL, close REAL NOT NULL,
    volume INTEGER NOT NULL,
    PRIMARY KEY (ticker, date)
);
CREATE INDEX IF NOT EXISTS idx_price_history_ticker_date ON price_history(ticker, date);

CREATE TABLE IF NOT EXISTS scan_runs (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_timestamp TEXT NOT NULL,
    ma_short INTEGER NOT NULL, ma_long INTEGER NOT NULL, rsi_period INTEGER NOT NULL DEFAULT 14,
    horizon INTEGER NOT NULL, align_threshold INTEGER NOT NULL,
    indicator_set TEXT NOT NULL,     -- JSON list, e.g. ["trend","momentum","volume"]
    universe_label TEXT, triggered_by TEXT, notes TEXT
);

CREATE TABLE IF NOT EXISTS scan_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES scan_runs(run_id),
    ticker TEXT NOT NULL, as_of_date TEXT NOT NULL,
    close REAL, ma_short_value REAL, ma_long_value REAL, rsi REAL,
    votes_json TEXT NOT NULL,        -- {"trend":1,"momentum":-1,"volume":1,...}
    confluence INTEGER NOT NULL,
    base_rate_up REAL, bull_hit_rate REAL, bear_hit_rate REAL,
    bull_edge REAL, bear_edge REAL, overall_hit_rate REAL,
    n_bull INTEGER, n_bear INTEGER, n_overall INTEGER, n_bars INTEGER,
    UNIQUE (run_id, ticker)
);
CREATE INDEX IF NOT EXISTS idx_scan_results_ticker_date ON scan_results(ticker, as_of_date);

-- Sector/industry classification barely ever changes, unlike price history,
-- so this cache has no expiry/refresh policy -- it just saves a yfinance
-- .info round-trip (much slower than a price download) on every scan.
CREATE TABLE IF NOT EXISTS ticker_sectors (
    ticker TEXT PRIMARY KEY,
    sector TEXT NOT NULL,
    industry TEXT,
    fetched_at TEXT NOT NULL
);

-- One flat list, not per-user (this app has no login) -- added_at only
-- controls display order (oldest add first), nothing prunes it over time.
CREATE TABLE IF NOT EXISTS watchlist (
    ticker TEXT PRIMARY KEY,
    added_at TEXT NOT NULL
);

-- Append-only ledger, not a holdings snapshot -- current position
-- (quantity, average cost, realized P&L) is derived by replaying every
-- ticker's transactions in date order (see get_portfolio_positions), the
-- same "one engine, recomputed from source facts" philosophy as
-- scan_results being derived from price_history rather than hand-edited.
-- This is average-cost accounting, not FIFO lot tracking: a buy blends
-- into the running average cost, a sell reduces quantity without changing
-- the remaining shares' average cost.
CREATE TABLE IF NOT EXISTS portfolio_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    side TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
    quantity REAL NOT NULL,
    price REAL NOT NULL,
    txn_date TEXT NOT NULL,     -- YYYY-MM-DD, user-editable (defaults to today)
    created_at TEXT NOT NULL    -- when the row was inserted, for tie-breaking same-day order
);
CREATE INDEX IF NOT EXISTS idx_portfolio_transactions_ticker ON portfolio_transactions(ticker);
"""


def get_connection(db_path=None):
    """Open (and create parent dir for) the SQLite database file. Each
    caller gets its own connection (never shared across threads/requests),
    so this is safe to call concurrently from the dashboard's threaded dev
    server -- WAL mode is what makes that concurrency not immediately hit
    "database is locked": SQLite's default rollback-journal mode blocks
    every reader while a single writer (e.g. one full-history scan) holds
    the file, WAL lets reads continue alongside a writer instead.
    """
    db_path = db_path or config.DB_PATH
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db(conn):
    """Create tables/indexes if they don't already exist. Idempotent."""
    conn.executescript(SCHEMA_DDL)
    conn.commit()
    return conn


def get_last_date(conn, ticker):
    """Return the most recent date (YYYY-MM-DD str) stored for `ticker`,
    or None if the ticker has never been fetched."""
    row = conn.execute(
        "SELECT MAX(date) FROM price_history WHERE ticker = ?", (ticker,)
    ).fetchone()
    return row[0] if row and row[0] is not None else None


def upsert_price_rows(conn, ticker, rows):
    """Insert-or-replace a batch of OHLCV rows for `ticker`.

    `rows` is an iterable of (date, open, high, low, close, volume) tuples.
    Returns the number of rows written.
    """
    rows = list(rows)
    if not rows:
        return 0
    conn.executemany(
        """
        INSERT OR REPLACE INTO price_history
            (ticker, date, open, high, low, close, volume)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [(ticker, *r) for r in rows],
    )
    conn.commit()
    return len(rows)


def load_price_history(conn, ticker, start=None, end=None):
    """Read back the full OHLCV series for `ticker` between start/end
    (inclusive, YYYY-MM-DD strings) as a list of sqlite3.Row, ordered by date.
    """
    query = "SELECT * FROM price_history WHERE ticker = ?"
    params = [ticker]
    if start:
        query += " AND date >= ?"
        params.append(start)
    if end:
        query += " AND date <= ?"
        params.append(end)
    query += " ORDER BY date"
    conn.row_factory = sqlite3.Row
    cur = conn.execute(query, params)
    result = cur.fetchall()
    conn.row_factory = None
    return result


def insert_scan_run(conn, run_timestamp, ma_short, ma_long, rsi_period,
                     horizon, align_threshold, indicator_set_json,
                     universe_label=None, triggered_by=None, notes=None):
    """Insert a new scan_runs row and return its run_id."""
    cur = conn.execute(
        """
        INSERT INTO scan_runs
            (run_timestamp, ma_short, ma_long, rsi_period, horizon,
             align_threshold, indicator_set, universe_label, triggered_by, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (run_timestamp, ma_short, ma_long, rsi_period, horizon,
         align_threshold, indicator_set_json, universe_label, triggered_by, notes),
    )
    conn.commit()
    return cur.lastrowid


def insert_scan_result(conn, run_id, ticker, as_of_date, close, ma_short_value,
                        ma_long_value, rsi, votes_json, confluence,
                        base_rate_up, bull_hit_rate, bear_hit_rate,
                        bull_edge, bear_edge, overall_hit_rate,
                        n_bull, n_bear, n_overall, n_bars):
    """Insert (or replace, on unique (run_id, ticker) conflict) one scan_results row."""
    conn.execute(
        """
        INSERT OR REPLACE INTO scan_results
            (run_id, ticker, as_of_date, close, ma_short_value, ma_long_value, rsi,
             votes_json, confluence, base_rate_up, bull_hit_rate, bear_hit_rate,
             bull_edge, bear_edge, overall_hit_rate, n_bull, n_bear, n_overall, n_bars)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (run_id, ticker, as_of_date, close, ma_short_value, ma_long_value, rsi,
         votes_json, confluence, base_rate_up, bull_hit_rate, bear_hit_rate,
         bull_edge, bear_edge, overall_hit_rate, n_bull, n_bear, n_overall, n_bars),
    )
    conn.commit()


def get_scan_results_for_run(conn, run_id):
    """Fetch all scan_results rows for a given run_id, as sqlite3.Row."""
    conn.row_factory = sqlite3.Row
    cur = conn.execute(
        "SELECT * FROM scan_results WHERE run_id = ? ORDER BY ticker", (run_id,)
    )
    result = cur.fetchall()
    conn.row_factory = None
    return result


def get_scan_run(conn, run_id):
    """Fetch a single scan_runs row by id."""
    conn.row_factory = sqlite3.Row
    cur = conn.execute("SELECT * FROM scan_runs WHERE run_id = ?", (run_id,))
    result = cur.fetchone()
    conn.row_factory = None
    return result


def get_cached_sector(conn, ticker):
    """Return `ticker`'s cached sector, or None if it hasn't been fetched yet."""
    row = conn.execute("SELECT sector FROM ticker_sectors WHERE ticker = ?", (ticker,)).fetchone()
    return row[0] if row else None


def upsert_sector(conn, ticker, sector, industry, fetched_at):
    conn.execute(
        """
        INSERT OR REPLACE INTO ticker_sectors (ticker, sector, industry, fetched_at)
        VALUES (?, ?, ?, ?)
        """,
        (ticker, sector, industry, fetched_at),
    )
    conn.commit()


def get_watchlist(conn):
    """Return watchlist tickers ordered oldest-added-first."""
    cur = conn.execute("SELECT ticker FROM watchlist ORDER BY added_at, ticker")
    return [row[0] for row in cur.fetchall()]


def add_to_watchlist(conn, ticker, added_at):
    """No-op (via INSERT OR IGNORE) if `ticker` is already on the list --
    re-adding an existing ticker shouldn't bump its display order.
    """
    conn.execute(
        "INSERT OR IGNORE INTO watchlist (ticker, added_at) VALUES (?, ?)", (ticker, added_at),
    )
    conn.commit()


def remove_from_watchlist(conn, ticker):
    conn.execute("DELETE FROM watchlist WHERE ticker = ?", (ticker,))
    conn.commit()


def add_portfolio_transaction(conn, ticker, side, quantity, price, txn_date, created_at):
    """Append one buy/sell row. Never validates against current position
    (e.g. "can't sell more than you hold") -- that's a UI-level concern
    (see pages/portfolio.py), not a data-layer one, since the ledger is
    meant to be an honest record of what was entered.
    """
    cur = conn.execute(
        """
        INSERT INTO portfolio_transactions (ticker, side, quantity, price, txn_date, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (ticker, side, quantity, price, txn_date, created_at),
    )
    conn.commit()
    return cur.lastrowid


def delete_portfolio_transaction(conn, txn_id):
    conn.execute("DELETE FROM portfolio_transactions WHERE id = ?", (txn_id,))
    conn.commit()


def get_portfolio_transactions(conn, limit=None):
    """Every transaction, newest first (txn_date, then insertion order as
    tie-break) -- used for the on-page transaction log, not for computing
    positions (see get_portfolio_positions, which reads chronologically).
    """
    conn.row_factory = sqlite3.Row
    query = "SELECT * FROM portfolio_transactions ORDER BY txn_date DESC, id DESC"
    if limit:
        query += f" LIMIT {int(limit)}"
    cur = conn.execute(query)
    result = cur.fetchall()
    conn.row_factory = None
    return result


def get_portfolio_positions(conn):
    """Replay every transaction in chronological order (oldest first) to
    derive each ticker's current quantity, average cost, and realized P&L
    under average-cost accounting: a buy blends into the running average
    cost; a sell reduces quantity without changing the remaining shares'
    average cost, and its realized P&L is (sell_price - avg_cost at that
    moment) * sell_qty. A sell for more than is currently held is clamped
    to whatever's held (defensive -- the UI is expected to reject that
    before it's ever inserted).

    Returns {ticker: {"quantity": float, "avg_cost": float, "realized_pnl": float}}
    for EVERY ticker ever transacted, including ones fully sold down to
    zero -- callers that only want current holdings should filter
    quantity > 0 themselves; a closed position's realized P&L still needs
    to count toward the portfolio-wide total.
    """
    conn.row_factory = sqlite3.Row
    cur = conn.execute(
        "SELECT ticker, side, quantity, price FROM portfolio_transactions ORDER BY txn_date, id"
    )
    rows = cur.fetchall()
    conn.row_factory = None

    positions = {}
    for row in rows:
        pos = positions.setdefault(row["ticker"], {"quantity": 0.0, "avg_cost": 0.0, "realized_pnl": 0.0})
        if row["side"] == "buy":
            new_qty = pos["quantity"] + row["quantity"]
            if new_qty > 0:
                pos["avg_cost"] = (pos["quantity"] * pos["avg_cost"] + row["quantity"] * row["price"]) / new_qty
            pos["quantity"] = new_qty
        else:
            sell_qty = min(row["quantity"], pos["quantity"])
            pos["realized_pnl"] += (row["price"] - pos["avg_cost"]) * sell_qty
            pos["quantity"] -= sell_qty
    return positions
