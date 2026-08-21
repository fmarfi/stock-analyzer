#!/usr/bin/env python
"""CLI entrypoint for stock_analyzer: scan a ticker universe, persist
results to SQLite, and write an HTML + CSV report.

    run_scan.py [--tickers AAPL,MSFT,...] [--watchlist NAME]
                [--ma-short N] [--ma-long N] [--rsi-period N]
                [--horizon N] [--align-threshold N]
                [--start-date YYYY-MM-DD] [--db-path PATH] [--reports-dir PATH]
                [--no-charts] [--quiet]

No input() calls anywhere -- this is meant to be schedule-ready: a Windows
Task Scheduler trigger can point straight at
`python.exe stock_analyzer\\run_scan.py --watchlist core10` with no
interaction required. Exit code is 0 on any partial success, non-zero if
the resolved ticker universe was empty or every ticker failed, so a
scheduler can alert on exit code alone.
"""

import argparse
import logging
import os
import sys

# Allow `python stock_analyzer/run_scan.py` (direct script execution, as
# Task Scheduler will eventually invoke it) to find the `stock_analyzer`
# package even though the script's own directory (not the project root)
# is what ends up on sys.path in that mode. Running via `python -m
# stock_analyzer.run_scan` doesn't need this (__package__ is already set).
if __package__ in (None, ""):
    _PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _PROJECT_ROOT not in sys.path:
        sys.path.insert(0, _PROJECT_ROOT)

from stock_analyzer import config, db, engine, universe
from stock_analyzer.reporting import html_report


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_scan.py",
        description="Scan a ticker universe, persist results to SQLite, and write an HTML+CSV report.",
    )
    parser.add_argument("--tickers", default=None,
                         help="Comma-separated ticker list, e.g. AAPL,MSFT,TSLA. Overrides --watchlist.")
    parser.add_argument("--watchlist", default=None,
                         help=f"Named watchlist from config.WATCHLISTS (default: {config.DEFAULT_WATCHLIST_NAME}).")
    parser.add_argument("--ma-short", type=int, default=None, help=f"Short MA period (default: {config.MA_SHORT}).")
    parser.add_argument("--ma-long", type=int, default=None, help=f"Long MA period (default: {config.MA_LONG}).")
    parser.add_argument("--rsi-period", type=int, default=None, help=f"RSI period (default: {config.RSI_PERIOD}).")
    parser.add_argument("--horizon", type=int, default=None,
                         help=f"Forward-return horizon in bars (default: {config.HORIZON}).")
    parser.add_argument("--align-threshold", type=int, default=None,
                         help="|confluence| counted as fully aligned (default: len(indicator registry)).")
    parser.add_argument("--start-date", default=None,
                         help=f"First-fetch start date, YYYY-MM-DD (default: {config.DEFAULT_START_DATE}).")
    parser.add_argument("--db-path", default=None, help=f"SQLite DB path (default: {config.DB_PATH}).")
    parser.add_argument("--reports-dir", default=None, help=f"Reports output dir (default: {config.REPORTS_DIR}).")
    parser.add_argument("--no-charts", action="store_true",
                         help="Skip embedding per-ticker Plotly charts in the HTML report (faster, smaller file).")
    parser.add_argument("--quiet", action="store_true", help="Only print the final summary line.")
    return parser


def configure_logging(quiet: bool) -> None:
    logging.basicConfig(
        level=logging.WARNING if quiet else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def main(argv=None) -> int:
    args = build_arg_parser().parse_args(argv)
    configure_logging(args.quiet)
    logger = logging.getLogger("run_scan")

    tickers = universe.resolve_universe(args.tickers, args.watchlist)
    if not tickers:
        logger.error("Resolved ticker universe is empty -- nothing to scan.")
        return 1

    universe_label = args.watchlist or ("custom" if args.tickers else config.DEFAULT_WATCHLIST_NAME)
    logger.info("Scanning %d ticker(s): %s", len(tickers), ", ".join(tickers))

    params_overrides = {
        "ma_short": args.ma_short, "ma_long": args.ma_long, "rsi_period": args.rsi_period,
        "horizon": args.horizon, "align_threshold": args.align_threshold,
        "start_date": args.start_date,
    }

    conn = db.get_connection(args.db_path)
    db.init_db(conn)
    scan_result = engine.run_scan(
        conn, tickers, params_overrides,
        universe_label=universe_label, triggered_by="cli",
    )

    n_ok = len(scan_result["results"])
    n_fail = len(scan_result["failures"])

    for f in scan_result["fetch_summary"]:
        logger.info(
            "%s: %s fetch from %s -> %d row(s) written",
            f["ticker"], f["mode"], f["start"], f["rows_written"],
        )

    if n_ok == 0:
        logger.error("Every ticker failed (%d/%d) -- no report written.", n_fail, len(tickers))
        conn.close()
        return 1

    html_path, csv_path = html_report.write_reports(
        scan_result, reports_dir=args.reports_dir, include_charts=not args.no_charts,
    )
    conn.close()

    print(f"Scan complete: {n_ok} succeeded, {n_fail} failed, run_id={scan_result['run_id']}")
    print(f"HTML report: {html_path}")
    print(f"CSV report:  {csv_path}")
    if scan_result["failures"]:
        for f in scan_result["failures"]:
            print(f"  FAILED {f['ticker']}: {f['error']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
