"""Bollinger Bounce report page."""

import logging

import dash
from dash import dcc, html, Input, Output, State

from stock_analyzer import config, db, engine
from stock_analyzer.dashboard_shared import (
    DROPDOWN_TICKERS, indicator_checklist, number_input, page_header, stoch_controls,
)
from stock_analyzer.reporting import bounce_report

logger = logging.getLogger(__name__)

dash.register_page(__name__, path="/bounce", name="Bounce", title="Bounce")


layout = html.Div([
    page_header(
        "Bollinger Bounce Report",
        "Walks each chosen ticker's full history for bars where price touched the upper or lower "
        "band and closed back inside it while the market wasn't strongly trending (a ranging-market "
        "play -- buy near the lower band, sell near the upper band, expect a drift back toward the "
        "middle band), then shows what actually happened afterward.",
    ),

    dcc.Dropdown(
        id="bounce-ticker-dropdown",
        options=[{"label": t, "value": t} for t in DROPDOWN_TICKERS],
        value=[],
        multi=True,
        placeholder="Choose ticker(s) to scan...",
        style={"marginBottom": "16px"},
    ),

    html.Div([
        number_input("Short EMA", "bounce-ma-short-input", config.MA_SHORT, 1),
        number_input("Long EMA", "bounce-ma-long-input", config.MA_LONG, 2),
        number_input("BB Period", "bounce-bb-period-input", config.BB_PERIOD, 2),
        number_input("BB Std Dev", "bounce-bb-stddev-input", config.BB_STDDEV, 0.5, step=0.5),
        number_input("Confirm within (bars)", "bounce-confirm-bars-input", 3, 1, step=1),
        stoch_controls("bounce"),
    ], style={"display": "flex", "gap": "20px", "marginBottom": "16px", "color": "white",
              "fontFamily": "Arial, sans-serif", "flexWrap": "wrap", "alignItems": "flex-end"}),

    html.Div(indicator_checklist("bounce-active-indicators-input"), style={"marginBottom": "16px"}),

    html.Button("Generate Bounce Report", id="bounce-report-btn", n_clicks=0, style={
        "backgroundColor": config.GREEN, "color": "white", "border": "none", "borderRadius": "6px",
        "padding": "8px 16px", "cursor": "pointer", "margin": "0 0 12px 0",
    }),

    html.Div(id="bounce-report-status", style={"color": config.MUTED_TEXT, "fontFamily": "Arial, sans-serif",
                                                "fontSize": "13px"}),
])


@dash.callback(
    Output("bounce-report-status", "children"),
    Input("bounce-report-btn", "n_clicks"),
    State("bounce-ticker-dropdown", "value"),
    State("bounce-ma-short-input", "value"),
    State("bounce-ma-long-input", "value"),
    State("bounce-bb-period-input", "value"),
    State("bounce-bb-stddev-input", "value"),
    State("bounce-confirm-bars-input", "value"),
    State("bounce-stoch-mode-input", "value"),
    State("bounce-stoch-k-period-input", "value"),
    State("bounce-stoch-d-period-input", "value"),
    State("bounce-stoch-smoothing-input", "value"),
    State("bounce-active-indicators-input", "value"),
    prevent_initial_call=True,
)
def generate_bounce_report(n_clicks, tickers, ma_short, ma_long, bb_period, bb_stddev, confirm_bars,
                            stoch_mode, stoch_k_period, stoch_d_period, stoch_smoothing, active_indicators):
    """Full-history Bollinger Bounce scan for hand-picked tickers. Same
    "scoped to exactly what you pick" rationale as the squeeze report --
    a full-history walk per ticker is a lot slower than a latest-bar
    scoreboard update.
    """
    if not tickers:
        return "Select at least one ticker before generating a bounce report."

    logger.info("Generating bounce report for %d ticker(s): %s", len(tickers), ", ".join(tickers))
    params = engine.resolve_params({
        "ma_short": ma_short, "ma_long": ma_long,
        "bb_period": bb_period, "bb_stddev": bb_stddev, "stoch_mode": stoch_mode,
        "stoch_k_period": stoch_k_period, "stoch_d_period": stoch_d_period, "stoch_slowing": stoch_smoothing,
        "active_indicators": active_indicators,
    })

    conn = db.get_connection()
    db.init_db(conn)
    try:
        scan_result = engine.run_bounce_scan(
            conn, tickers, params, confirm_bars=confirm_bars or 3,
        )
        report_path = bounce_report.write_reports(scan_result)
    finally:
        conn.close()

    n_ok = len(scan_result["tickers"])
    n_fail = len(scan_result["failures"])
    n_events = sum(len(t["events"]) for t in scan_result["tickers"])
    logger.info(
        "Bounce report written: %s (%d ticker(s), %d event(s), %d failed)",
        report_path, n_ok, n_events, n_fail,
    )
    return (
        f"Bounce report written: {report_path} "
        f"({n_ok} ticker(s), {n_events} event(s) found, {n_fail} failed)."
    )
