"""Chart Snapshots page: pick ticker(s), each one's chart is saved to an
HTML file under reports/snapshots/ as soon as it's selected -- no button.
"""

import logging
import os

import dash
from dash import dcc, html, Input, Output, State

from stock_analyzer import config, db, engine
from stock_analyzer.dashboard_shared import (
    DROPDOWN_TICKERS, SNAPSHOTS_DIR, build_chart_fig, CHART_POST_SCRIPTS, CHART_CONFIG,
    default_indicator_instances, number_input, page_header, stoch_controls,
)

logger = logging.getLogger(__name__)

dash.register_page(__name__, path="/snapshots", name="Snapshots", title="Snapshots")


layout = html.Div([
    page_header(
        "Chart Snapshots",
        "Pick ticker(s) below and each one's chart is saved to an HTML file under "
        "reports/snapshots/ right away -- no button, saving happens as soon as you select. "
        "Re-selecting a ticker overwrites its existing snapshot rather than piling up copies.",
    ),

    dcc.Dropdown(
        id="snapshot-ticker-dropdown",
        options=[{"label": t, "value": t} for t in DROPDOWN_TICKERS],
        value=[],
        multi=True,
        placeholder="Choose ticker(s) to snapshot...",
        style={"marginBottom": "16px"},
    ),

    html.Div([
        number_input("Short EMA", "snapshot-ma-short-input", config.MA_SHORT, 1),
        number_input("Long EMA", "snapshot-ma-long-input", config.MA_LONG, 2),
        number_input("BB Period", "snapshot-bb-period-input", config.BB_PERIOD, 2),
        number_input("BB Std Dev", "snapshot-bb-stddev-input", config.BB_STDDEV, 0.5, step=0.5),
        stoch_controls("snapshot"),
    ], style={"display": "flex", "gap": "20px", "marginBottom": "16px", "color": "white",
              "fontFamily": "Arial, sans-serif", "flexWrap": "wrap", "alignItems": "flex-end"}),

    html.Div(id="snapshot-status", style={"color": config.MUTED_TEXT, "fontFamily": "Arial, sans-serif",
                                           "fontSize": "13px"}),
])


@dash.callback(
    Output("snapshot-status", "children"),
    Input("snapshot-ticker-dropdown", "value"),
    State("snapshot-ma-short-input", "value"),
    State("snapshot-ma-long-input", "value"),
    State("snapshot-bb-period-input", "value"),
    State("snapshot-bb-stddev-input", "value"),
    State("snapshot-stoch-mode-input", "value"),
    State("snapshot-stoch-k-period-input", "value"),
    State("snapshot-stoch-d-period-input", "value"),
    State("snapshot-stoch-smoothing-input", "value"),
    prevent_initial_call=True,
)
def save_chart_snapshots(tickers, ma_short, ma_long, bb_period, bb_stddev,
                          stoch_mode, stoch_k_period, stoch_d_period, stoch_smoothing):
    """Fires on every change to the snapshot dropdown's selection (not a
    button) -- saving is the direct effect of picking a ticker. Each
    ticker's chart is written as a standalone HTML file (same
    build_chart_fig() the rest of the app uses), overwriting any previous
    snapshot for that ticker rather than accumulating one file per selection.
    """
    if not tickers:
        return "No tickers selected."

    params = engine.resolve_params({
        "ma_short": ma_short, "ma_long": ma_long,
        "bb_period": bb_period, "bb_stddev": bb_stddev, "stoch_mode": stoch_mode,
        "stoch_k_period": stoch_k_period, "stoch_d_period": stoch_d_period, "stoch_slowing": stoch_smoothing,
    })

    os.makedirs(SNAPSHOTS_DIR, exist_ok=True)
    conn = db.get_connection()
    db.init_db(conn)
    saved, failed = [], []
    try:
        for ticker in tickers:
            try:
                result = engine.analyze_ticker(conn, ticker, params)
            except engine.TickerAnalysisError as exc:
                logger.warning("Snapshot skipping %s: %s", ticker, exc)
                failed.append(ticker)
                continue
            fig = build_chart_fig(result["df"], ticker, default_indicator_instances(params))
            path = os.path.join(SNAPSHOTS_DIR, f"{ticker}.html")
            fig.write_html(path, include_plotlyjs="cdn", config=CHART_CONFIG, post_script=CHART_POST_SCRIPTS)
            logger.info("Saved chart snapshot for %s -> %s", ticker, path)
            saved.append(ticker)
    finally:
        conn.close()

    parts = []
    if saved:
        parts.append(f"Saved {len(saved)} snapshot(s) to {SNAPSHOTS_DIR}: {', '.join(saved)}")
    if failed:
        parts.append(f"Skipped (no data): {', '.join(failed)}")
    return " | ".join(parts) if parts else "Nothing saved."
