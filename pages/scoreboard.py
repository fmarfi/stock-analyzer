"""Confluence Scoreboard page: multi-select ticker dropdown, dark-styled MA/
BB inputs, "Update Scoreboard" button, wrapping card grid, per-card "View
Chart" via a pattern-matching clientside callback that opens /chart/<ticker>
in a new tab. "Generate Report" calls the exact same engine.run_scan() +
reporting.* functions run_scan.py uses, so the dashboard and the CLI stay
one engine instead of two.

The card grid is filterable/sortable after the fact (confluence range, RSI
range, hit-rate floor, direction, ticker substring, sort order) without
re-scanning -- "Update Scoreboard" writes the full per-ticker result set
into scan-cache once, and a separate render callback rebuilds the grid from
that cache every time a filter control changes. Same split most of the app
already uses for chart panels/params: scan once, arrange the view as many
times as you want.
"""

import logging

import dash
from dash import dcc, html, Input, Output, State, ALL

from stock_analyzer import config, db, engine
from stock_analyzer.dashboard_shared import (
    DROPDOWN_TICKERS, BIST_YILDIZ_TICKERS, build_mini_card, indicator_checklist, number_input, page_header,
    stoch_controls,
)
from stock_analyzer.reporting import html_report

logger = logging.getLogger(__name__)

dash.register_page(__name__, path="/scoreboard", name="Scoreboard", title="Scoreboard")

_SORT_OPTIONS = [
    {"label": "Confluence (high to low)", "value": "confluence_desc"},
    {"label": "Confluence (low to high)", "value": "confluence_asc"},
    {"label": "Hit rate (high to low)", "value": "hit_rate_desc"},
    {"label": "RSI (high to low)", "value": "rsi_desc"},
    {"label": "RSI (low to high)", "value": "rsi_asc"},
    {"label": "Ticker (A-Z)", "value": "ticker_az"},
]
_DIRECTION_OPTIONS = [
    {"label": "All", "value": "all"},
    {"label": "Bullish (confluence > 0)", "value": "bullish"},
    {"label": "Bearish (confluence < 0)", "value": "bearish"},
    {"label": "Fully aligned only", "value": "aligned"},
]


def _filter_input(label, input_id, placeholder=None, value=None, input_type="number", width="90px", step=1):
    kwargs = {"type": input_type, "id": input_id, "value": value, "persistence": True,
              "persistence_type": "local", "style": {
                  "width": width, "backgroundColor": config.INPUT_BG, "color": "white",
                  "border": f"1px solid {config.BORDER_COLOR}", "borderRadius": "6px", "padding": "6px 8px",
              }}
    if input_type == "number":
        kwargs["step"] = step
    if placeholder:
        kwargs["placeholder"] = placeholder
    return html.Div([
        html.Label(label, style={"color": config.MUTED_TEXT, "fontSize": "12px", "display": "block",
                                  "marginBottom": "2px"}),
        dcc.Input(**kwargs),
    ])


layout = html.Div([
    page_header("Confluence Scoreboard", "Latest-bar read for the tickers you pick -- Trend/Momentum/"
                "Volume/MACD votes, confluence score, and historical hit rate/edge."),

    # persistence: remembers your last ticker selection (and the filter
    # controls, scan-cache, etc. below) in the browser's localStorage --
    # without it, closing the tab/dashboard and coming back meant starting
    # from BIST_YILDIZ_TICKERS[:10] and an empty grid every single time.
    dcc.Dropdown(
        id="ticker-dropdown",
        options=[{"label": t, "value": t} for t in DROPDOWN_TICKERS],
        value=BIST_YILDIZ_TICKERS[:10],
        multi=True, persistence=True, persistence_type="local",
        style={"marginBottom": "16px"},
    ),

    html.Div([
        number_input("Short EMA", "ma-short-input", config.MA_SHORT, 1),
        number_input("Long EMA", "ma-long-input", config.MA_LONG, 2),
        number_input("BB Period", "bb-period-input", config.BB_PERIOD, 2),
        number_input("BB Std Dev", "bb-stddev-input", config.BB_STDDEV, 0.5, step=0.5),
        stoch_controls("scoreboard"),
    ], style={"display": "flex", "gap": "20px", "marginBottom": "16px", "color": "white",
              "fontFamily": "Arial, sans-serif", "flexWrap": "wrap", "alignItems": "flex-end"}),

    html.Div(indicator_checklist("active-indicators-input"), style={"marginBottom": "16px"}),

    html.Div([
        html.Button("Update Scoreboard", id="update-btn", n_clicks=0, className="btn", style={
            "backgroundColor": config.BLUE, "color": "white",
        }),
        html.Button("Generate Report", id="report-btn", n_clicks=0, className="btn", style={
            "backgroundColor": config.GREEN, "color": "white",
        }),
        # /reports/latest.html always holds whatever "Generate Report" wrote
        # most recently (write_reports() overwrites it in place), so this
        # link never needs to react to state -- it's just always current.
        # Opens in a new tab, same reasoning as "View Chart" elsewhere.
        html.A("View Last Report", href="/reports/latest.html", target="_blank", className="btn btn-outline",
               style={"textDecoration": "none", "display": "inline-block"}),
    ], style={"display": "flex", "gap": "12px", "marginBottom": "20px", "alignItems": "center"}),

    html.Div(id="report-status", style={"color": config.MUTED_TEXT, "fontFamily": "Arial, sans-serif",
                                         "marginBottom": "12px", "fontSize": "13px"}),

    # --- filter/sort bar ---------------------------------------------------
    # Acts on whatever's already in scan-cache -- no re-scan, so every
    # control here fires instantly instead of round-tripping through
    # yfinance/backtest again.
    html.Div([
        _filter_input("Confluence min", "filter-confluence-min", placeholder="any"),
        _filter_input("Confluence max", "filter-confluence-max", placeholder="any"),
        _filter_input("RSI min", "filter-rsi-min", placeholder="any"),
        _filter_input("RSI max", "filter-rsi-max", placeholder="any"),
        _filter_input("Min hit rate %", "filter-hit-rate-min", placeholder="any"),
        html.Div([
            html.Label("Direction", style={"color": config.MUTED_TEXT, "fontSize": "12px", "display": "block",
                                            "marginBottom": "2px"}),
            dcc.Dropdown(id="filter-direction", options=_DIRECTION_OPTIONS, value="all", clearable=False,
                         persistence=True, persistence_type="local", style={"width": "200px"}),
        ]),
        html.Div([
            html.Label("Sort by", style={"color": config.MUTED_TEXT, "fontSize": "12px", "display": "block",
                                          "marginBottom": "2px"}),
            dcc.Dropdown(id="filter-sort-by", options=_SORT_OPTIONS, value="confluence_desc", clearable=False,
                         persistence=True, persistence_type="local", style={"width": "200px"}),
        ]),
        _filter_input("Ticker contains", "filter-ticker-search", placeholder="e.g. GARAN",
                      input_type="text", width="140px"),
    ], style={"display": "flex", "gap": "16px", "marginBottom": "10px", "flexWrap": "wrap",
              "alignItems": "flex-end"}),

    html.Div(id="filter-status", style={"color": config.MUTED_TEXT, "fontFamily": "Arial, sans-serif",
                                         "fontSize": "12px", "marginBottom": "12px"}),

    html.Div(id="scoreboard-grid", style={"display": "flex", "flexWrap": "wrap", "gap": "14px"}),

    # Full per-ticker result set from the last "Update Scoreboard" scan --
    # {"tickers": {ticker: {...build_mini_card()-shaped result...}},
    #  "align_threshold": int}. The filter/sort bar re-renders scoreboard-grid
    # from this without touching the engine again. storage_type="local"
    # (browser localStorage, not the default in-memory Store that clears on
    # every refresh) means the grid survives closing the tab or restarting
    # the dashboard -- reopening shows the last scan instead of a blank
    # page until you click "Update Scoreboard" again.
    dcc.Store(id="scan-cache", storage_type="local"),

    # Dummy output for the clientside callback below -- "View Chart" opens
    # the chart in its own browser tab/window (via the /chart/<ticker> Flask
    # route) instead of rendering inline, so this Store never holds anything
    # meaningful, it just gives window.open() a callback to live in.
    dcc.Store(id="chart-window-trigger"),
])


@dash.callback(
    Output("scan-cache", "data"),
    Input("update-btn", "n_clicks"),
    State("ticker-dropdown", "value"),
    State("ma-short-input", "value"),
    State("ma-long-input", "value"),
    State("bb-period-input", "value"),
    State("bb-stddev-input", "value"),
    State("scoreboard-stoch-mode-input", "value"),
    State("scoreboard-stoch-k-period-input", "value"),
    State("scoreboard-stoch-d-period-input", "value"),
    State("scoreboard-stoch-smoothing-input", "value"),
    State("active-indicators-input", "value"),
    prevent_initial_call=True,
)
def update_scoreboard(n_clicks, tickers, ma_short, ma_long, bb_period, bb_stddev,
                       stoch_mode, stoch_k_period, stoch_d_period, stoch_smoothing, active_indicators):
    """Runs the scan and writes the FULL per-ticker result set into
    scan-cache -- rendering scoreboard-grid from that (see
    render_scoreboard_grid below) is a separate callback so the filter/sort
    bar can re-render instantly without re-running this.
    """
    if not tickers:
        return None

    params = engine.resolve_params({
        "ma_short": ma_short, "ma_long": ma_long,
        "bb_period": bb_period, "bb_stddev": bb_stddev, "stoch_mode": stoch_mode,
        "stoch_k_period": stoch_k_period, "stoch_d_period": stoch_d_period, "stoch_slowing": stoch_smoothing,
        "active_indicators": active_indicators,
    })

    logger.info("Updating scoreboard for %d ticker(s): %s", len(tickers), ", ".join(tickers))
    conn = db.get_connection()
    db.init_db(conn)
    try:
        results = {}
        for ticker in tickers:
            try:
                result = engine.analyze_ticker(conn, ticker, params)
            except engine.TickerAnalysisError as exc:
                logger.warning("Dashboard skipping %s: %s", ticker, exc)
                continue
            results[ticker] = {
                "ticker": ticker, "confluence": result["confluence"], "rsi": result["rsi"],
                "votes": result["votes"], "stats": result["stats"].as_dict(),
            }
        return {"tickers": results, "align_threshold": params["align_threshold"]}
    finally:
        conn.close()


def _passes_filters(entry, confluence_min, confluence_max, rsi_min, rsi_max, hit_rate_min,
                     direction, ticker_search, align_threshold):
    confluence = entry["confluence"]
    rsi = entry["rsi"]
    hit_rate = entry["stats"]["overall_hit_rate"]

    if confluence_min is not None and confluence < confluence_min:
        return False
    if confluence_max is not None and confluence > confluence_max:
        return False
    if rsi_min is not None and (rsi is None or rsi < rsi_min):
        return False
    if rsi_max is not None and (rsi is None or rsi > rsi_max):
        return False
    if hit_rate_min is not None and (hit_rate is None or hit_rate * 100 < hit_rate_min):
        return False
    if direction == "bullish" and confluence <= 0:
        return False
    if direction == "bearish" and confluence >= 0:
        return False
    if direction == "aligned" and abs(confluence) < align_threshold:
        return False
    if ticker_search and ticker_search.strip().upper() not in entry["ticker"].upper():
        return False
    return True


_SORT_KEY = {
    "confluence_desc": lambda e: -e["confluence"],
    "confluence_asc": lambda e: e["confluence"],
    "hit_rate_desc": lambda e: -(e["stats"]["overall_hit_rate"] or -1),
    "rsi_desc": lambda e: -(e["rsi"] if e["rsi"] is not None else -1),
    "rsi_asc": lambda e: e["rsi"] if e["rsi"] is not None else float("inf"),
    "ticker_az": lambda e: e["ticker"],
}


@dash.callback(
    Output("scoreboard-grid", "children"),
    Output("filter-status", "children"),
    Input("scan-cache", "data"),
    Input("filter-confluence-min", "value"),
    Input("filter-confluence-max", "value"),
    Input("filter-rsi-min", "value"),
    Input("filter-rsi-max", "value"),
    Input("filter-hit-rate-min", "value"),
    Input("filter-direction", "value"),
    Input("filter-sort-by", "value"),
    Input("filter-ticker-search", "value"),
)
def render_scoreboard_grid(cache, confluence_min, confluence_max, rsi_min, rsi_max, hit_rate_min,
                            direction, sort_by, ticker_search):
    """Rebuilds the card grid from scan-cache on every filter/sort change --
    no re-scan, so this is instant regardless of how slow the original
    "Update Scoreboard" scan was.
    """
    if not cache or not cache.get("tickers"):
        return [], ""

    align_threshold = cache["align_threshold"]
    entries = list(cache["tickers"].values())
    filtered = [
        e for e in entries
        if _passes_filters(e, confluence_min, confluence_max, rsi_min, rsi_max, hit_rate_min,
                            direction, ticker_search, align_threshold)
    ]
    filtered.sort(key=_SORT_KEY.get(sort_by, _SORT_KEY["confluence_desc"]))

    if not filtered:
        return (
            [html.Div("No tickers match the current filters.", style={"color": "white"})],
            f"Showing 0 of {len(entries)} ticker(s).",
        )

    cards = [build_mini_card(e, align_threshold) for e in filtered]
    status = f"Showing {len(filtered)} of {len(entries)} ticker(s)."
    return cards, status


# "View Chart" opens the chart in a new browser tab/window (GET /chart/<ticker>,
# registered on the Flask server in dashboard.py) rather than rendering inline --
# this clientside callback just does the window.open(), no round trip through
# Python needed for that part. The function itself lives in
# assets/chart_window.js (dash.ClientsideFunction), not as an inline JS
# string here -- the inline-string form intermittently failed with "Cannot
# read properties of undefined (reading 'apply')" in this multi-page app;
# an assets/*.js file is loaded as a real <script> tag before dash-renderer
# starts, so the function is guaranteed to exist by call time.
dash.clientside_callback(
    dash.ClientsideFunction(namespace="clientside", function_name="openChartWindow"),
    Output("chart-window-trigger", "data"),
    Input({"type": "view-btn", "index": ALL}, "n_clicks"),
    State("ma-short-input", "value"),
    State("ma-long-input", "value"),
    State("bb-period-input", "value"),
    State("bb-stddev-input", "value"),
    State("scoreboard-stoch-mode-input", "value"),
    State("scoreboard-stoch-k-period-input", "value"),
    State("scoreboard-stoch-d-period-input", "value"),
    State("scoreboard-stoch-smoothing-input", "value"),
    prevent_initial_call=True,
)


@dash.callback(
    Output("report-status", "children"),
    Input("report-btn", "n_clicks"),
    State("ticker-dropdown", "value"),
    State("ma-short-input", "value"),
    State("ma-long-input", "value"),
    State("bb-period-input", "value"),
    State("bb-stddev-input", "value"),
    State("scoreboard-stoch-mode-input", "value"),
    State("scoreboard-stoch-k-period-input", "value"),
    State("scoreboard-stoch-d-period-input", "value"),
    State("scoreboard-stoch-smoothing-input", "value"),
    State("active-indicators-input", "value"),
    prevent_initial_call=True,
)
def generate_report(n_clicks, tickers, ma_short, ma_long, bb_period, bb_stddev,
                     stoch_mode, stoch_k_period, stoch_d_period, stoch_smoothing, active_indicators):
    """Calls the exact same engine.run_scan() + reporting.* functions
    run_scan.py uses -- this is what keeps the dashboard and CLI as one
    engine instead of two.
    """
    if not tickers:
        return "Select at least one ticker before generating a report."

    logger.info("Generating report for %d ticker(s): %s", len(tickers), ", ".join(tickers))
    params = engine.resolve_params({
        "ma_short": ma_short, "ma_long": ma_long,
        "bb_period": bb_period, "bb_stddev": bb_stddev, "stoch_mode": stoch_mode,
        "stoch_k_period": stoch_k_period, "stoch_d_period": stoch_d_period, "stoch_slowing": stoch_smoothing,
        "active_indicators": active_indicators,
    })

    conn = db.get_connection()
    db.init_db(conn)
    try:
        scan_result = engine.run_scan(
            conn, tickers, params, universe_label="dashboard-selection", triggered_by="dashboard",
        )
        html_path, csv_path = html_report.write_reports(scan_result, include_charts=True)
    finally:
        conn.close()

    n_ok = len(scan_result["results"])
    n_fail = len(scan_result["failures"])
    logger.info("Report written: %s and %s (%d succeeded, %d failed)", html_path, csv_path, n_ok, n_fail)
    return f"Report written: {html_path} and {csv_path} ({n_ok} ticker(s) succeeded, {n_fail} failed)."
