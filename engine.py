"""Shared orchestration: fetch -> indicators -> backtest -> persist.

This is the module that makes "one engine, two entrypoints" true: both
run_scan.py (CLI) and dashboard.py (Dash UI) call analyze_ticker()/run_scan()
here instead of re-implementing fetch/score/backtest logic themselves. Any
future entrypoint (a Task Scheduler job, a Slack bot, etc.) would do the same.
"""

import datetime
import json
import logging

import pandas as pd

from stock_analyzer import backtest as backtest_mod
from stock_analyzer import bounce, config, db, fetch, indicators, squeeze, triangle

logger = logging.getLogger(__name__)


def resolve_params(overrides: dict = None) -> dict:
    """Merge caller-supplied overrides on top of config.py defaults, and
    resolve align_threshold to however many indicators are active (all of
    them, unless overrides sets "active_indicators" to a subset) if not
    explicitly set.
    """
    params = {
        "ma_short": config.MA_SHORT,
        "ma_long": config.MA_LONG,
        "rsi_period": config.RSI_PERIOD,
        "vol_ma_period": config.VOL_MA_PERIOD,
        "horizon": config.HORIZON,
        "align_threshold": config.ALIGN_THRESHOLD,
        "start_date": config.DEFAULT_START_DATE,
        "end_date": config.DEFAULT_END_DATE,
        "bb_period": config.BB_PERIOD,
        "bb_stddev": config.BB_STDDEV,
        "macd_fast": config.MACD_FAST,
        "macd_slow": config.MACD_SLOW,
        "macd_signal": config.MACD_SIGNAL,
        "stoch_mode": config.STOCH_MODE,
        "stoch_k_period": config.STOCH_K_PERIOD,
        "stoch_d_period": config.STOCH_D_PERIOD,
        "stoch_slowing": config.STOCH_SLOWING,
        "di_period": config.DI_PERIOD,
    }
    if overrides:
        params.update({k: v for k, v in overrides.items() if v is not None})

    if params.get("align_threshold") is None:
        params["align_threshold"] = indicators.default_align_threshold(params)

    return params


class TickerAnalysisError(Exception):
    """Raised (and caught by run_scan) when a single ticker can't be analyzed."""


def analyze_ticker(conn, ticker: str, params: dict) -> dict:
    """Fetch/cache a ticker's price history, compute indicators + backtest
    stats, and return a result dict describing its current state. Does not
    write to scan_results itself -- run_scan() does that, so analyze_ticker()
    stays reusable by the dashboard for a single "peek at one ticker" call
    that doesn't need to record a whole scan run.
    """
    frame, fetch_result = fetch.fetch_and_load(
        conn, ticker,
        default_start_date=params["start_date"],
        end_date=params["end_date"],
    )

    min_bars_needed = max(params["ma_long"], params["rsi_period"], params["vol_ma_period"]) + 1
    if frame.empty or len(frame) < min_bars_needed:
        raise TickerAnalysisError(
            f"{ticker}: insufficient price history ({len(frame)} bar(s), "
            f"need >= {min_bars_needed})"
        )

    with_indicators = indicators.apply_indicators(frame, params)
    with_bands = indicators.compute_bollinger_bands(
        with_indicators,
        period=params.get("bb_period", config.BB_PERIOD),
        num_std=params.get("bb_stddev", config.BB_STDDEV),
    )

    stats = backtest_mod.run_backtest(
        with_bands, horizon=params["horizon"], align_threshold=params["align_threshold"]
    )

    latest = with_bands.iloc[-1]
    votes = indicators.votes_json_for_row(latest)

    return {
        "ticker": ticker,
        "df": with_bands,
        "fetch_result": fetch_result,
        "as_of_date": with_bands.index[-1].strftime("%Y-%m-%d"),
        "close": float(latest["Close"]),
        "ma_short_value": float(latest["MA_short"]) if not pd.isna(latest["MA_short"]) else None,
        "ma_long_value": float(latest["MA_long"]) if not pd.isna(latest["MA_long"]) else None,
        "rsi": float(latest["RSI"]) if not pd.isna(latest["RSI"]) else None,
        "votes": votes,
        "confluence": int(latest["confluence"]),
        "stats": stats,
    }


def run_scan(conn, tickers, params: dict = None, universe_label: str = None,
             triggered_by: str = "manual", notes: str = None) -> dict:
    """Run a full scan across `tickers`: create one scan_runs row, analyze
    each ticker (logging but not crashing on a single ticker's failure), and
    persist one scan_results row per successful ticker.

    Returns:
        {
          "run_id": int,
          "results": [ per-ticker analyze_ticker() dict, ... ],   # successes only
          "failures": [ {"ticker": ..., "error": "..."}, ... ],
          "fetch_summary": [ fetch_result dict, ... ],            # all attempts
        }
    """
    params = resolve_params(params)
    indicator_set = [ind.name for ind in indicators.REGISTRY]

    run_timestamp = datetime.datetime.now().isoformat(timespec="seconds")
    run_id = db.insert_scan_run(
        conn,
        run_timestamp=run_timestamp,
        ma_short=params["ma_short"],
        ma_long=params["ma_long"],
        rsi_period=params["rsi_period"],
        horizon=params["horizon"],
        align_threshold=params["align_threshold"],
        indicator_set_json=json.dumps(indicator_set),
        universe_label=universe_label,
        triggered_by=triggered_by,
        notes=notes,
    )

    results = []
    failures = []
    fetch_summary = []

    for ticker in tickers:
        try:
            result = analyze_ticker(conn, ticker, params)
        except TickerAnalysisError as exc:
            logger.warning("Skipping %s: %s", ticker, exc)
            failures.append({"ticker": ticker, "error": str(exc)})
            continue
        except Exception as exc:  # noqa: BLE001 - one bad ticker must not kill the scan
            logger.exception("Unexpected error analyzing %s", ticker)
            failures.append({"ticker": ticker, "error": str(exc)})
            continue

        fetch_summary.append(result["fetch_result"])
        stats = result["stats"]
        db.insert_scan_result(
            conn,
            run_id=run_id,
            ticker=result["ticker"],
            as_of_date=result["as_of_date"],
            close=result["close"],
            ma_short_value=result["ma_short_value"],
            ma_long_value=result["ma_long_value"],
            rsi=result["rsi"],
            votes_json=json.dumps(result["votes"]),
            confluence=result["confluence"],
            base_rate_up=stats.base_rate_up,
            bull_hit_rate=stats.bull_hit_rate,
            bear_hit_rate=stats.bear_hit_rate,
            bull_edge=stats.bull_edge,
            bear_edge=stats.bear_edge,
            overall_hit_rate=stats.overall_hit_rate,
            n_bull=stats.n_bull,
            n_bear=stats.n_bear,
            n_overall=stats.n_overall,
            n_bars=stats.n_bars,
        )
        results.append(result)

    return {
        "run_id": run_id,
        "run_timestamp": run_timestamp,
        "universe_label": universe_label,
        "params": params,
        "results": results,
        "failures": failures,
        "fetch_summary": fetch_summary,
    }


def run_squeeze_scan(conn, tickers, params: dict = None, bw_lookback: int = 252,
                      bw_percentile: float = 10.0, min_gap_bars: int = 20) -> dict:
    """For each ticker, walk its full history (via analyze_ticker(), so this
    can never see different indicator/Bollinger numbers than the scoreboard
    does) looking for squeeze.find_events() -- bars where bandwidth was
    unusually tight *and* every registered indicator was fully aligned.
    Deliberately not tied to a watchlist: callers pass exactly the tickers
    they want scanned, since walking full history per ticker is much more
    expensive than a single-latest-bar scoreboard update.
    """
    params = resolve_params(params)
    run_timestamp = datetime.datetime.now().isoformat(timespec="seconds")

    tickers_out = []
    failures = []
    for ticker in tickers:
        try:
            result = analyze_ticker(conn, ticker, params)
        except TickerAnalysisError as exc:
            logger.warning("Squeeze scan skipping %s: %s", ticker, exc)
            failures.append({"ticker": ticker, "error": str(exc)})
            continue
        except Exception as exc:  # noqa: BLE001 - one bad ticker must not kill the scan
            logger.exception("Unexpected error analyzing %s for squeeze scan", ticker)
            failures.append({"ticker": ticker, "error": str(exc)})
            continue

        events = squeeze.find_events(
            result["df"], align_threshold=params["align_threshold"], horizon=params["horizon"],
            bw_lookback=bw_lookback, bw_percentile=bw_percentile, min_gap_bars=min_gap_bars,
        )
        tickers_out.append({"ticker": ticker, "df": result["df"], "events": events})

    return {
        "run_timestamp": run_timestamp,
        "params": params,
        "bw_lookback": bw_lookback,
        "bw_percentile": bw_percentile,
        "tickers": tickers_out,
        "failures": failures,
    }


def run_bounce_scan(conn, tickers, params: dict = None, confirm_bars: int = 3,
                     min_gap_bars: int = 20) -> dict:
    """For each ticker, walk its full history (via analyze_ticker()) looking
    for bounce.find_events() -- bars where price touched an outer Bollinger
    Band and closed back inside it while the market wasn't strongly
    trending. Same "hand-picked tickers only" scoping as run_squeeze_scan(),
    for the same reason: a full-history walk per ticker is a lot more
    expensive than a latest-bar scoreboard update.
    """
    params = resolve_params(params)
    run_timestamp = datetime.datetime.now().isoformat(timespec="seconds")

    tickers_out = []
    failures = []
    for ticker in tickers:
        try:
            result = analyze_ticker(conn, ticker, params)
        except TickerAnalysisError as exc:
            logger.warning("Bounce scan skipping %s: %s", ticker, exc)
            failures.append({"ticker": ticker, "error": str(exc)})
            continue
        except Exception as exc:  # noqa: BLE001 - one bad ticker must not kill the scan
            logger.exception("Unexpected error analyzing %s for bounce scan", ticker)
            failures.append({"ticker": ticker, "error": str(exc)})
            continue

        found = bounce.find_events(
            result["df"], align_threshold=params["align_threshold"], horizon=params["horizon"],
            confirm_bars=confirm_bars, min_gap_bars=min_gap_bars,
        )
        tickers_out.append({"ticker": ticker, "df": result["df"], "events": found})

    return {
        "run_timestamp": run_timestamp,
        "params": params,
        "confirm_bars": confirm_bars,
        "min_gap_bars": min_gap_bars,
        "tickers": tickers_out,
        "failures": failures,
    }


def run_triangle_scan(conn, tickers, params: dict = None, window_bars: int = 60,
                       pivot_lookback: int = 5, min_pivots: int = 3, min_gap_bars: int = 15) -> dict:
    """For each ticker, walk its full history (via analyze_ticker()) looking
    for triangle.find_events() -- ascending/descending/symmetrical trendline
    convergences. Same "hand-picked tickers only" scoping as the other scan
    functions: a full-history walk per ticker is a lot more expensive than a
    latest-bar scoreboard update.
    """
    params = resolve_params(params)
    run_timestamp = datetime.datetime.now().isoformat(timespec="seconds")

    tickers_out = []
    failures = []
    for ticker in tickers:
        try:
            result = analyze_ticker(conn, ticker, params)
        except TickerAnalysisError as exc:
            logger.warning("Triangle scan skipping %s: %s", ticker, exc)
            failures.append({"ticker": ticker, "error": str(exc)})
            continue
        except Exception as exc:  # noqa: BLE001 - one bad ticker must not kill the scan
            logger.exception("Unexpected error analyzing %s for triangle scan", ticker)
            failures.append({"ticker": ticker, "error": str(exc)})
            continue

        found = triangle.find_events(
            result["df"], horizon=params["horizon"], window_bars=window_bars,
            pivot_lookback=pivot_lookback, min_pivots=min_pivots, min_gap_bars=min_gap_bars,
        )
        tickers_out.append({"ticker": ticker, "df": result["df"], "events": found})

    return {
        "run_timestamp": run_timestamp,
        "params": params,
        "window_bars": window_bars,
        "pivot_lookback": pivot_lookback,
        "min_pivots": min_pivots,
        "min_gap_bars": min_gap_bars,
        "tickers": tickers_out,
        "failures": failures,
    }
