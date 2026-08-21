"""Triangle Formations report page."""

import logging

import dash
from dash import dcc, html, Input, Output, State

from stock_analyzer import config, db, engine
from stock_analyzer.dashboard_shared import BIST_YILDIZ_TICKERS, DROPDOWN_TICKERS, page_header
from stock_analyzer.reporting import triangle_report

logger = logging.getLogger(__name__)

dash.register_page(__name__, path="/triangles", name="Triangles", title="Triangles")


layout = html.Div([
    page_header(
        "Triangle Formations",
        "Walks each chosen ticker's full history fitting trendlines through swing highs and swing "
        "lows, looking for genuinely converging lines (not just two arbitrary slopes) -- ascending "
        "(flat top, rising bottom), descending (flat bottom, falling top), or symmetrical (both "
        "converging). Ascending/descending are graded against their textbook breakout direction; "
        "symmetrical isn't, since classic TA gives it no fixed expected direction. Defaults to the "
        "full BIST Yildiz Pazar list; deselect down to fewer tickers if you don't want the full scan.",
    ),

    dcc.Dropdown(
        id="triangle-ticker-dropdown",
        options=[{"label": t, "value": t} for t in DROPDOWN_TICKERS],
        value=BIST_YILDIZ_TICKERS,
        multi=True,
        placeholder="Choose ticker(s) to scan...",
        style={"marginBottom": "16px"},
    ),

    html.Button("Generate Triangle Report", id="triangle-report-btn", n_clicks=0, style={
        "backgroundColor": config.GREEN, "color": "white", "border": "none", "borderRadius": "6px",
        "padding": "8px 16px", "cursor": "pointer", "margin": "0 0 12px 0",
    }),

    html.Div(id="triangle-report-status", style={"color": config.MUTED_TEXT, "fontFamily": "Arial, sans-serif",
                                                  "fontSize": "13px"}),
])


@dash.callback(
    Output("triangle-report-status", "children"),
    Input("triangle-report-btn", "n_clicks"),
    State("triangle-ticker-dropdown", "value"),
    prevent_initial_call=True,
)
def generate_triangle_report(n_clicks, tickers):
    """Full-history triangle-pattern scan for the chosen tickers. Doesn't
    use MA/BB params -- trendline fitting only needs High/Low/Close -- so
    the ticker list is the only real input.
    """
    if not tickers:
        return "Select at least one ticker before generating a triangle report."

    logger.info("Generating triangle report for %d ticker(s)", len(tickers))
    params = engine.resolve_params({})

    conn = db.get_connection()
    db.init_db(conn)
    try:
        scan_result = engine.run_triangle_scan(conn, tickers, params)
        report_path = triangle_report.write_reports(scan_result)
    finally:
        conn.close()

    n_ok = len(scan_result["tickers"])
    n_fail = len(scan_result["failures"])
    n_events = sum(len(t["events"]) for t in scan_result["tickers"])
    logger.info(
        "Triangle report written: %s (%d ticker(s), %d event(s), %d failed)",
        report_path, n_ok, n_events, n_fail,
    )
    return (
        f"Triangle report written: {report_path} "
        f"({n_ok} ticker(s), {n_events} event(s) found, {n_fail} failed)."
    )
