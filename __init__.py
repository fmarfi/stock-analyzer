"""stock_analyzer: persistent, extensible technical-analysis app.

A package that scans a watchlist of tickers, computes a registry-driven set
of technical indicators (trend/momentum/volume "confluence" voting plus a
Bollinger Bands chart overlay), backtests the historical hit-rate of those
signals, persists both price history and scan results in SQLite, and can
render the results either as a static HTML/CSV report (``run_scan.py``) or
an interactive Dash dashboard (``dashboard.py``) -- both driven by the same
``engine.py`` orchestration layer.

See the approved design plan for full rationale; this package is purely
additive and does not import from ``trial01.ipynb`` or ``scoreboard_app.py``.
"""
