"""Best Strategy by Sector report page."""

import logging

import dash
from dash import dcc, html, Input, Output, State

from stock_analyzer import config, db, engine, strategy_compare
from stock_analyzer.dashboard_shared import (
    DROPDOWN_TICKERS, indicator_checklist, number_input, page_header, stoch_controls,
)
from stock_analyzer.reporting import strategy_report

logger = logging.getLogger(__name__)

dash.register_page(__name__, path="/strategy", name="Strategy by Sector", title="Strategy by Sector")


layout = html.Div([
    page_header(
        "Best Strategy by Sector",
        "Runs Confluence, Squeeze, Bounce, and Combined on every chosen ticker's full history, "
        "grouped by sector (fetched from yfinance and cached). A strategy only gets tagged BEST if "
        "it beats 50% AND clears a Bonferroni-corrected significance threshold across the whole scan "
        "-- comparing a handful of squeeze/bounce events against a 1000+-observation confluence "
        "baseline and just picking the numerically highest hit rate is a classic small-sample trap, "
        "so a ticker with no strategy that clears the bar shows no BEST tag rather than a forced pick. "
        "Defaults to a 40-name spread across BIST; the slowest report here since it walks full "
        "history three times per ticker.",
    ),

    dcc.Dropdown(
        id="strategy-ticker-dropdown",
        options=[{"label": t, "value": t} for t in DROPDOWN_TICKERS],
        value=DROPDOWN_TICKERS[:40],
        multi=True,
        placeholder="Choose ticker(s) to scan...",
        style={"marginBottom": "16px"},
    ),

    html.Div([
        number_input("Short EMA", "strategy-ma-short-input", config.MA_SHORT, 1),
        number_input("Long EMA", "strategy-ma-long-input", config.MA_LONG, 2),
        number_input("BB Period", "strategy-bb-period-input", config.BB_PERIOD, 2),
        number_input("BB Std Dev", "strategy-bb-stddev-input", config.BB_STDDEV, 0.5, step=0.5),
        number_input("Squeeze percentile", "strategy-bw-percentile-input", 10, 1, step=1),
        number_input("Bounce confirm bars", "strategy-confirm-bars-input", 3, 1, step=1),
        number_input("Min events to be eligible", "strategy-min-events-input", 30, 5, step=5),
        stoch_controls("strategy"),
    ], style={"display": "flex", "gap": "20px", "marginBottom": "16px", "color": "white",
              "fontFamily": "Arial, sans-serif", "flexWrap": "wrap", "alignItems": "flex-end"}),

    html.Div(indicator_checklist("strategy-active-indicators-input"), style={"marginBottom": "16px"}),

    html.Button("Generate Sector Strategy Report", id="strategy-report-btn", n_clicks=0, style={
        "backgroundColor": config.GREEN, "color": "white", "border": "none", "borderRadius": "6px",
        "padding": "8px 16px", "cursor": "pointer", "margin": "0 0 12px 0",
    }),

    html.Div(id="strategy-report-status", style={"color": config.MUTED_TEXT, "fontFamily": "Arial, sans-serif",
                                                  "fontSize": "13px"}),
])


@dash.callback(
    Output("strategy-report-status", "children"),
    Input("strategy-report-btn", "n_clicks"),
    State("strategy-ticker-dropdown", "value"),
    State("strategy-ma-short-input", "value"),
    State("strategy-ma-long-input", "value"),
    State("strategy-bb-period-input", "value"),
    State("strategy-bb-stddev-input", "value"),
    State("strategy-bw-percentile-input", "value"),
    State("strategy-confirm-bars-input", "value"),
    State("strategy-min-events-input", "value"),
    State("strategy-stoch-mode-input", "value"),
    State("strategy-stoch-k-period-input", "value"),
    State("strategy-stoch-d-period-input", "value"),
    State("strategy-stoch-smoothing-input", "value"),
    State("strategy-active-indicators-input", "value"),
    prevent_initial_call=True,
)
def generate_strategy_report(n_clicks, tickers, ma_short, ma_long, bb_period, bb_stddev,
                              bw_percentile, confirm_bars, min_events,
                              stoch_mode, stoch_k_period, stoch_d_period, stoch_smoothing, active_indicators):
    """Runs Confluence/Squeeze/Bounce/Combined on every chosen ticker and
    reports the best-performing (statistically significant) one per ticker,
    grouped by sector. The slowest report in the app -- three full-history
    walks per ticker plus a (cached) sector lookup.
    """
    if not tickers:
        return "Select at least one ticker before generating a strategy report."

    logger.info("Generating strategy comparison for %d ticker(s): %s", len(tickers), ", ".join(tickers))
    params = engine.resolve_params({
        "ma_short": ma_short, "ma_long": ma_long,
        "bb_period": bb_period, "bb_stddev": bb_stddev, "stoch_mode": stoch_mode,
        "stoch_k_period": stoch_k_period, "stoch_d_period": stoch_d_period, "stoch_slowing": stoch_smoothing,
        "active_indicators": active_indicators,
    })

    conn = db.get_connection()
    db.init_db(conn)
    try:
        scan_result = strategy_compare.run_strategy_comparison(
            conn, tickers, params, bw_percentile=bw_percentile or 10.0,
            confirm_bars=confirm_bars or 3, min_events=min_events or 30,
        )
        report_path = strategy_report.write_reports(scan_result)
    finally:
        conn.close()

    n_ok = len(scan_result["tickers"])
    n_fail = len(scan_result["failures"])
    n_sectors = len(scan_result["sectors"])
    logger.info(
        "Strategy report written: %s (%d ticker(s), %d sector(s), %d failed)",
        report_path, n_ok, n_sectors, n_fail,
    )
    return (
        f"Strategy report written: {report_path} "
        f"({n_ok} ticker(s) across {n_sectors} sector(s), {n_fail} failed)."
    )
