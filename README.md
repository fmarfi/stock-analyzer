# Stock Analyzer

A confluence-based technical analysis engine for US and Borsa Istanbul equities: it scores every ticker against five independent indicators, backtests whether that score actually predicts forward returns, and surfaces the results through both a scheduler-friendly CLI and a multi-page Dash dashboard.

## What it does

- **Confluence scoring.** Five indicators — moving-average cross, RSI, MACD, Stochastic, and DMI/ADX — each cast one directional vote per bar. A ticker is "aligned" when every registered indicator agrees, and that alignment score is the signal the rest of the package is built around.
- **Statistically-checked backtesting.** For every ticker, `backtest.py` compares the forward-return hit rate on fully-aligned bars against the naive base rate (how often price rises regardless of the indicators), reporting the edge in percentage points rather than just "buy" / "sell".
- **Pattern and setup detection.**
  - *Bollinger Squeeze* — tight bandwidth plus full confluence alignment, flagged as a volatility-expansion setup.
  - *Bollinger Bounce* — a band touch-and-reject in a ranging (non-aligned) market.
  - *Triangle patterns* — ascending/descending/symmetrical triangles found by brute-force fitting trendlines through swing pivots and picking the pair with the fewest breaches against the full High/Low series, not a least-squares line that a chunk of candles could violate.
- **Strategy comparison with multiple-comparisons correction.** `strategy_compare.py` ranks Confluence vs. Squeeze vs. Bounce vs. a blended Combined strategy per ticker and per GICS sector, but a strategy is only tagged "best" if its hit rate clears an exact two-sided binomial test against 50% *and* survives Bonferroni correction across every comparison in the scan — not just whichever number happened to be numerically highest.
- **Portfolio tracking.** A buy/sell transaction ledger, not a hand-edited holdings snapshot — current quantity, average cost, and realized P&L are derived by replaying transactions in order.
- **Two entrypoints, one engine.** `run_scan.py` (CLI, Task Scheduler-ready, no `input()` calls, exit code reflects success/failure for alerting) and `dashboard.py` (multi-page Dash app: Home, Scoreboard, Portfolio) both call the same `engine.analyze_ticker()` / `engine.run_scan()`, so the CLI report and the live dashboard can never drift apart.
- **Incremental, cached data.** `fetch.py` asks SQLite for the newest stored date per ticker and only requests the gap from yfinance, instead of re-downloading years of history on every run.

## Architecture

```
stock_analyzer/
  engine.py            Shared orchestration: fetch -> indicators -> backtest -> persist
  fetch.py              yfinance download + incremental SQLite cache
  indicators.py         Registry of confluence-vote indicators (extensible: register once, wired everywhere)
  backtest.py            Forward-return hit-rate / edge statistics (pure functions, no DB/network/UI)
  squeeze.py / bounce.py / triangle.py   Setup and pattern detectors, all built on the same per-ticker DataFrame
  strategy_compare.py    Cross-strategy ranking with binomial + Bonferroni significance testing
  sector.py             GICS sector lookup, cached indefinitely in SQLite
  events.py              Shared event-clustering logic used by squeeze/bounce
  presentation.py        Framework-agnostic badge/color/label helpers shared by the dashboard and HTML reports
  db.py                  Single owner of the SQLite schema and all SQL
  run_scan.py            CLI entrypoint (Task Scheduler-ready)
  dashboard.py            Dash multi-page app shell
  dashboard_shared.py     Chart builders and helpers shared across pages
  pages/                  Home, Scoreboard, Portfolio Dash pages
  reporting/               HTML/CSV report generators (scan, squeeze, bounce, triangle, strategy)
```

The indicator registry (`indicators.py`) is the main extensibility point: adding a new confluence vote is writing one `compute(df, params)` function and calling `register(...)` once — `backtest.py`, `engine.py`, `reporting/*`, and `dashboard.py` all loop over the registry instead of hardcoding indicator names, so nothing else needs to change.

## Tech stack

Python, pandas / numpy, [yfinance](https://pypi.org/project/yfinance/) for market data, Plotly + Dash for the interactive dashboard, SQLite for local caching and portfolio/scan persistence.

## Setup

```
pip install -r requirements.txt
python run_scan.py --watchlist core10
```

This fetches data for the `core10` watchlist, persists it to a local SQLite cache (`data/stock_analyzer.db`), and writes an HTML + CSV scan report to `reports/`.

To use a custom ticker list instead of a named watchlist:

```
python run_scan.py --tickers AAPL,MSFT,TSLA
```

## Dashboard

```
python dashboard.py
```

Then open the printed local URL. The dashboard has three pages:

- **Home** — quick ticker search, a personal watchlist with live price/confluence movers, and the Scoreboard's freshness status.
- **Scoreboard** — a filterable/sortable card grid across a ticker selection (confluence range, RSI range, hit-rate floor, direction, ticker substring), backed by the same `engine.run_scan()` the CLI uses.
- **Portfolio** — a transaction ledger with positions marked to market via live confluence/price data.

## Watchlists

Two built-in watchlists ship in `config.py`: `core10` (a small US + BIST sample) and `us_mega40` (40 large-cap US names spread across every GICS sector, for sector-wise strategy comparisons with enough tickers per sector to be meaningful). A `bist_yildiz` list covers the Borsa Istanbul Star Market tier, cross-checked against two independent sources before being added.

## Notes

- No API keys required — market data comes from yfinance.
- `data/` (SQLite cache) and `reports/` (generated HTML/CSV output) are gitignored; both are regenerated on first run.
- Report retention keeps only the most recent run per report type — generating a new report prunes the old ones.
