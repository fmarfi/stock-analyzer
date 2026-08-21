"""Bollinger Squeeze / Edge Point report page."""

import logging

import dash
from dash import dcc, html, Input, Output, State

from stock_analyzer import config, db, engine
from stock_analyzer.dashboard_shared import (
    DROPDOWN_TICKERS, indicator_checklist, number_input, page_header, stoch_controls,
)
from stock_analyzer.reporting import squeeze_report

logger = logging.getLogger(__name__)

dash.register_page(__name__, path="/squeeze", name="Squeeze", title="Squeeze")


layout = html.Div([
    page_header(
        "Bollinger Squeeze / Edge Point Report",
        "Walks each chosen ticker's full history for bars where Bollinger Bandwidth was unusually "
        "tight and every indicator was fully aligned (bull or bear), then shows what actually "
        "happened afterward -- for checking assumptions against real outcomes, not just today's "
        "reading. Scoped to the tickers you pick here, since re-walking full history per ticker is "
        "a lot slower than a latest-bar scoreboard update.",
    ),

    dcc.Dropdown(
        id="squeeze-ticker-dropdown",
        options=[{"label": t, "value": t} for t in DROPDOWN_TICKERS],
        value=[],
        multi=True,
        placeholder="Choose ticker(s) to scan...",
        style={"marginBottom": "16px"},
    ),

    html.Div([
        number_input("Short EMA", "squeeze-ma-short-input", config.MA_SHORT, 1),
        number_input("Long EMA", "squeeze-ma-long-input", config.MA_LONG, 2),
        number_input("BB Period", "squeeze-bb-period-input", config.BB_PERIOD, 2),
        number_input("BB Std Dev", "squeeze-bb-stddev-input", config.BB_STDDEV, 0.5, step=0.5),
        number_input("Squeeze percentile (lower = tighter)", "squeeze-bw-percentile-input", 10, 1, step=1),
        stoch_controls("squeeze"),
    ], style={"display": "flex", "gap": "20px", "marginBottom": "16px", "color": "white",
              "fontFamily": "Arial, sans-serif", "flexWrap": "wrap", "alignItems": "flex-end"}),

    html.Div(indicator_checklist("squeeze-active-indicators-input"), style={"marginBottom": "16px"}),

    html.Button("Generate Squeeze Report", id="squeeze-report-btn", n_clicks=0, style={
        "backgroundColor": config.GREEN, "color": "white", "border": "none", "borderRadius": "6px",
        "padding": "8px 16px", "cursor": "pointer", "margin": "0 0 12px 0",
    }),

    html.Div(id="squeeze-report-status", style={"color": config.MUTED_TEXT, "fontFamily": "Arial, sans-serif",
                                                 "fontSize": "13px"}),
])


@dash.callback(
    Output("squeeze-report-status", "children"),
    Input("squeeze-report-btn", "n_clicks"),
    State("squeeze-ticker-dropdown", "value"),
    State("squeeze-ma-short-input", "value"),
    State("squeeze-ma-long-input", "value"),
    State("squeeze-bb-period-input", "value"),
    State("squeeze-bb-stddev-input", "value"),
    State("squeeze-bw-percentile-input", "value"),
    State("squeeze-stoch-mode-input", "value"),
    State("squeeze-stoch-k-period-input", "value"),
    State("squeeze-stoch-d-period-input", "value"),
    State("squeeze-stoch-smoothing-input", "value"),
    State("squeeze-active-indicators-input", "value"),
    prevent_initial_call=True,
)
def generate_squeeze_report(n_clicks, tickers, ma_short, ma_long, bb_period, bb_stddev, bw_percentile,
                             stoch_mode, stoch_k_period, stoch_d_period, stoch_smoothing, active_indicators):
    """Full-history squeeze + full-alignment scan for hand-picked tickers.
    Deliberately separate from the Scoreboard's "Generate Report": that one
    is a fast latest-bar scan, this one re-walks each ticker's entire
    history (rolling bandwidth percentile + event detection).
    """
    if not tickers:
        return "Select at least one ticker before generating a squeeze report."

    logger.info("Generating squeeze report for %d ticker(s): %s", len(tickers), ", ".join(tickers))
    params = engine.resolve_params({
        "ma_short": ma_short, "ma_long": ma_long,
        "bb_period": bb_period, "bb_stddev": bb_stddev, "stoch_mode": stoch_mode,
        "stoch_k_period": stoch_k_period, "stoch_d_period": stoch_d_period, "stoch_slowing": stoch_smoothing,
        "active_indicators": active_indicators,
    })

    conn = db.get_connection()
    db.init_db(conn)
    try:
        scan_result = engine.run_squeeze_scan(
            conn, tickers, params, bw_percentile=bw_percentile or 10.0,
        )
        report_path = squeeze_report.write_reports(scan_result)
    finally:
        conn.close()

    n_ok = len(scan_result["tickers"])
    n_fail = len(scan_result["failures"])
    n_events = sum(len(t["events"]) for t in scan_result["tickers"])
    logger.info(
        "Squeeze report written: %s (%d ticker(s), %d event(s), %d failed)",
        report_path, n_ok, n_events, n_fail,
    )
    return (
        f"Squeeze report written: {report_path} "
        f"({n_ok} ticker(s), {n_events} event(s) found, {n_fail} failed)."
    )
