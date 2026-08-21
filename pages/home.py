"""Home page: the dashboard's actual dashboard -- a quick ticker search, a
personal watchlist with live price/confluence movers, and the Scoreboard's
freshness/status in one panel. `layout` is a function (not a static object)
so Dash rebuilds the static parts -- report-freshness timestamp, watchlist
add-control options -- every time you land on this page; the watchlist
table itself is filled in by a callback (see render_watchlist below), not
computed inline in layout(), specifically so landing on Home stays instant
even though pricing/confluence data for a watchlist ticker can mean a
network round trip (analyze_ticker -> fetch.fetch_and_load) the very first
time it's requested each day.

Squeeze/Bounce/Triangles/Strategy-by-Sector/Snapshots used to each get a
card in a "Go to" grid here; with those pages removed (see dashboard.py),
Scoreboard is the only other destination in the app, so it gets one
purpose-built status panel instead of a one-item leftover grid.
"""

import datetime
import os

import dash
from dash import ALL, Input, Output, State, dcc, html

from stock_analyzer import config, db, engine
from stock_analyzer.dashboard_shared import DROPDOWN_TICKERS, badge, presentation

dash.register_page(__name__, path="/", name="Home", title="Stock Analyzer")

_SCOREBOARD_REPORT = "latest.html"


def _relative_time(mtime: float) -> str:
    delta = datetime.datetime.now() - datetime.datetime.fromtimestamp(mtime)
    seconds = delta.total_seconds()
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{int(seconds // 60)} min ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)} hr ago"
    return f"{int(seconds // 86400)} day(s) ago"


def _scoreboard_panel():
    path = os.path.join(config.REPORTS_DIR, _SCOREBOARD_REPORT)
    if os.path.exists(path):
        status_text = f"Last scan generated {_relative_time(os.path.getmtime(path))}"
        status_color = config.MUTED_TEXT
    else:
        status_text = "No scan generated yet"
        status_color = config.RED

    return html.Div([
        html.Div([
            html.Div(style={"width": "36px", "height": "4px", "backgroundColor": config.BLUE,
                             "borderRadius": "2px", "marginBottom": "12px"}),
            html.H3("Scoreboard", style={"color": "white", "margin": "0 0 6px 0", "fontSize": "18px"}),
            html.Div(
                "Latest-bar confluence read (Trend/Momentum/Volume/MACD) for tickers you pick, with a "
                "one-click chart popup per ticker.",
                style={"color": config.MUTED_TEXT, "fontSize": "13px", "lineHeight": "1.5",
                       "marginBottom": "14px", "maxWidth": "440px"},
            ),
            html.Div(status_text, style={"color": status_color, "fontSize": "12px"}),
        ]),
        html.Div([
            dcc.Link("Open Scoreboard", href="/scoreboard", className="btn", style={
                "backgroundColor": config.BLUE, "color": "white", "textDecoration": "none",
                "display": "inline-block",
            }),
            html.A("View last report", href="/reports/latest.html", target="_blank",
                   className="btn btn-outline", style={"textDecoration": "none", "display": "inline-block"}),
        ], style={"display": "flex", "gap": "10px", "marginTop": "16px"}),
    ], className="hover-card", style={
        "backgroundColor": config.CARD_BG, "borderRadius": "12px", "padding": "24px",
        "border": f"1px solid {config.BORDER_COLOR}", "maxWidth": "560px", "flex": "1",
        "boxShadow": "0 2px 8px rgba(0,0,0,0.4)",
    })


# --- portfolio preview -------------------------------------------------------
# A compact read-only summary -- adding/editing/removing holdings all happen
# on the Portfolio page itself (pages/portfolio.py), not here. Same
# "compute in a callback, not in layout()" split as the watchlist panel
# below, and for the same reason (marking holdings to market means an
# analyze_ticker() call per holding, which can mean a real network fetch).

_PORTFOLIO_PREVIEW_ROWS = 3


def _portfolio_preview_empty():
    return html.Div(
        "No holdings yet -- track what you actually own on the Portfolio page.",
        style={"color": config.MUTED_TEXT, "fontSize": "13px", "lineHeight": "1.5", "maxWidth": "440px"},
    )


def _portfolio_preview_body(total_value, total_pnl, total_pnl_pct, top_holdings):
    pnl_color = config.GREEN if total_pnl >= 0 else config.RED
    pnl_pct_text = f"{total_pnl_pct:+.2f}%" if total_pnl_pct is not None else "n/a"

    mover_rows = [
        html.Div([
            html.Span(ticker, style={"color": "white", "fontSize": "13px"}),
            html.Span(f"{pnl:+,.2f} ({pnl_pct:+.2f}%)" if pnl_pct is not None else f"{pnl:+,.2f}", style={
                "color": config.GREEN if pnl >= 0 else config.RED, "fontSize": "12px", "fontWeight": 600,
            }),
        ], style={"display": "flex", "justifyContent": "space-between", "padding": "6px 0",
                   "borderBottom": f"1px solid {config.BORDER_COLOR}"})
        for ticker, pnl, pnl_pct in top_holdings
    ]

    return html.Div([
        html.Div([
            html.Span(f"{total_value:,.2f}", style={"color": "white", "fontSize": "22px", "fontWeight": 700}),
            html.Span(" market value", style={"color": config.MUTED_TEXT, "fontSize": "13px"}),
        ]),
        html.Div(f"{total_pnl:+,.2f} unrealized P&L ({pnl_pct_text})", style={
            "color": pnl_color, "fontSize": "13px", "fontWeight": 600, "marginBottom": "10px",
        }),
        html.Div(mover_rows, style={"marginBottom": "4px"}),
    ])


def _portfolio_preview_panel():
    return html.Div([
        html.Div([
            html.Div(style={"width": "36px", "height": "4px", "backgroundColor": "#ab47bc",
                             "borderRadius": "2px", "marginBottom": "12px"}),
            html.H3("Portfolio", style={"color": "white", "margin": "0 0 6px 0", "fontSize": "18px"}),
            html.Div(
                "What you actually own, marked to the latest cached price for live market value and P&L.",
                style={"color": config.MUTED_TEXT, "fontSize": "13px", "lineHeight": "1.5",
                       "marginBottom": "14px", "maxWidth": "440px"},
            ),
            dcc.Loading(html.Div(id="portfolio-preview"), type="circle", color="#ab47bc"),
        ]),
        html.Div([
            dcc.Link("Open Portfolio", href="/portfolio", className="btn", style={
                "backgroundColor": "#ab47bc", "color": "white", "textDecoration": "none",
                "display": "inline-block",
            }),
        ], style={"display": "flex", "gap": "10px", "marginTop": "16px"}),

        # Mount trigger only -- fires the preview callback once per landing
        # on Home (see the module docstring on why this isn't in layout()).
        dcc.Store(id="portfolio-preview-init", data=True),
    ], className="hover-card", style={
        "backgroundColor": config.CARD_BG, "borderRadius": "12px", "padding": "24px",
        "border": f"1px solid {config.BORDER_COLOR}", "maxWidth": "400px", "flex": "1",
        "boxShadow": "0 2px 8px rgba(0,0,0,0.4)",
    })


# --- watchlist row/table rendering -----------------------------------------

_COL_WIDTHS = ["1.3fr", "0.9fr", "0.9fr", "1fr", "0.7fr", "0.9fr", "40px"]
_COL_TEMPLATE = " ".join(_COL_WIDTHS)


def _watchlist_grid_row(cells, header=False):
    return html.Div(cells, style={
        "display": "grid", "gridTemplateColumns": _COL_TEMPLATE, "gap": "10px",
        "alignItems": "center", "padding": "10px 14px",
        "borderBottom": f"1px solid {config.BORDER_COLOR}",
        "fontSize": "12px" if header else "13px",
        "color": config.MUTED_TEXT if header else "white",
        "textTransform": "uppercase" if header else "none",
        "letterSpacing": "0.4px" if header else "normal",
    })


def _watchlist_header():
    return _watchlist_grid_row([
        html.Span("Ticker"), html.Span("Price"), html.Span("Chg %"),
        html.Span("Confluence"), html.Span("RSI"), html.Span(""), html.Span(""),
    ], header=True)


def _watchlist_row(ticker: str, result: dict, chg_pct, align_threshold: int):
    confluence = result["confluence"]
    rsi = result["rsi"]
    chg_color = config.GREEN if (chg_pct or 0) >= 0 else config.RED
    chg_text = f"{chg_pct:+.2f}%" if chg_pct is not None else "-"

    return _watchlist_grid_row([
        html.Span(ticker, style={"fontWeight": 600}),
        html.Span(f"{result['close']:.2f}"),
        html.Span(chg_text, style={"color": chg_color, "fontWeight": 600}),
        badge(presentation.confluence_badge_text(confluence),
              presentation.confluence_color(confluence, align_threshold)),
        html.Span(f"{rsi:.1f}" if rsi is not None else "-"),
        html.A("Chart", href=f"/chart/{ticker}", target="_blank", className="btn btn-outline",
               style={"textDecoration": "none", "padding": "4px 10px", "fontSize": "12px",
                      "textAlign": "center"}),
        html.Button("×", id={"type": "watchlist-remove-btn", "index": ticker}, n_clicks=0,
                    title=f"Remove {ticker}", style={
                        "backgroundColor": "transparent", "color": config.MUTED_TEXT,
                        "border": "none", "cursor": "pointer", "fontSize": "16px", "lineHeight": 1,
                    }),
    ])


def _watchlist_error_row(ticker: str, message: str):
    return _watchlist_grid_row([
        html.Span(ticker, style={"fontWeight": 600}),
        html.Span(message, style={"color": config.RED, "fontSize": "12px", "gridColumn": "span 4"}),
        html.Span(""),
        html.Button("×", id={"type": "watchlist-remove-btn", "index": ticker}, n_clicks=0,
                    title=f"Remove {ticker}", style={
                        "backgroundColor": "transparent", "color": config.MUTED_TEXT,
                        "border": "none", "cursor": "pointer", "fontSize": "16px", "lineHeight": 1,
                    }),
    ])


def _watchlist_empty_state():
    return html.Div(
        "Your watchlist is empty -- add a ticker above to start tracking its price and confluence score.",
        style={"color": config.MUTED_TEXT, "fontSize": "13px", "padding": "20px 14px"},
    )


def _watchlist_panel_body(rows):
    if not rows:
        return _watchlist_empty_state()
    return html.Div([_watchlist_header(), *rows])


def _watchlist_panel():
    return html.Div([
        html.Div([
            html.H3("Watchlist", style={"color": "white", "margin": 0, "fontSize": "18px"}),
        ], style={"marginBottom": "10px"}),

        html.Div([
            dcc.Dropdown(
                id="watchlist-add-dropdown",
                options=[{"label": t, "value": t} for t in DROPDOWN_TICKERS],
                placeholder="Select a ticker...",
                style={"width": "240px"},
            ),
            html.Div("or", style={"color": config.MUTED_TEXT, "fontSize": "13px"}),
            dcc.Input(
                id="watchlist-add-input", type="text", placeholder="...type any ticker",
                debounce=False, n_submit=0, style={
                    "width": "200px", "backgroundColor": config.INPUT_BG, "color": "white",
                    "border": f"1px solid {config.BORDER_COLOR}", "borderRadius": "6px", "padding": "8px 10px",
                },
            ),
            html.Button("Add to Watchlist", id="watchlist-add-btn", n_clicks=0, className="btn", style={
                "backgroundColor": config.BLUE, "color": "white",
            }),
        ], style={"display": "flex", "gap": "12px", "alignItems": "center", "marginBottom": "8px"}),

        html.Div(id="watchlist-status", style={"color": config.RED, "fontSize": "12px", "marginBottom": "10px"}),

        dcc.Loading(html.Div(id="watchlist-panel", style={
            "backgroundColor": config.CARD_BG, "borderRadius": "10px",
            "border": f"1px solid {config.BORDER_COLOR}", "maxWidth": "760px", "overflow": "hidden",
        }), type="circle", color=config.BLUE),
    ], style={"marginBottom": "32px"})


def layout():
    return html.Div([
        html.H1("Stock Analyzer", style={"color": "white", "marginBottom": "4px",
                                          "fontWeight": 700, "letterSpacing": "-0.4px"}),
        html.Div(
            "Confluence scoring across BIST 100 and Yildiz Pazar, reading from the same engine as the CLI.",
            style={"color": config.MUTED_TEXT, "fontSize": "14px", "marginBottom": "28px"},
        ),

        # --- quick ticker search --------------------------------------------
        # Select from the known BIST list or type any ticker (the free-text
        # box stays open-ended on purpose, e.g. for a name not in the list
        # yet) -- either one opens the same standalone chart window "View
        # Chart" does elsewhere, using config.py's default MA/BB/Stoch
        # periods since this is a quick look, not meant to duplicate every
        # indicator control from the other pages.
        html.Div([
            dcc.Dropdown(
                id="home-ticker-dropdown",
                options=[{"label": t, "value": t} for t in DROPDOWN_TICKERS],
                placeholder="Select a ticker...", persistence=True, persistence_type="local",
                style={"width": "260px"},
            ),
            html.Div("or", style={"color": config.MUTED_TEXT, "fontSize": "13px"}),
            dcc.Input(
                id="home-ticker-input", type="text", placeholder="...type any ticker, e.g. GARAN.IS",
                debounce=False, n_submit=0, style={
                    "width": "260px", "backgroundColor": config.INPUT_BG, "color": "white",
                    "border": f"1px solid {config.BORDER_COLOR}", "borderRadius": "6px", "padding": "8px 10px",
                },
            ),
            html.Button("View Chart", id="home-view-chart-btn", n_clicks=0, className="btn", style={
                "backgroundColor": config.BLUE, "color": "white",
            }),
        ], style={"display": "flex", "gap": "12px", "alignItems": "center", "marginBottom": "8px"}),

        html.Div(id="home-chart-status", style={"color": config.MUTED_TEXT,
                                                 "fontSize": "12px", "marginBottom": "28px"}),

        dcc.Store(id="home-chart-defaults", data={
            "ma_short": config.MA_SHORT, "ma_long": config.MA_LONG,
            "bb_period": config.BB_PERIOD, "bb_stddev": config.BB_STDDEV,
            "stoch_mode": config.STOCH_MODE, "stoch_k_period": config.STOCH_K_PERIOD,
            "stoch_d_period": config.STOCH_D_PERIOD, "stoch_smoothing": config.STOCH_SLOWING,
        }),

        # --- watchlist --------------------------------------------------------
        _watchlist_panel(),

        # --- scoreboard status + portfolio preview -----------------------------
        html.Div([
            _scoreboard_panel(),
            _portfolio_preview_panel(),
        ], style={"display": "flex", "gap": "16px", "flexWrap": "wrap"}),
    ])


# Opens the standalone chart window from the search bar above -- same
# assets/chart_window.js function family as "View Chart" elsewhere, for the
# same reason (an inline JS string intermittently failed to register in
# this multi-page app). Fires on either the button click or pressing Enter
# in the text box.
dash.clientside_callback(
    dash.ClientsideFunction(namespace="clientside", function_name="openTickerSearchChart"),
    dash.Output("home-chart-status", "children"),
    dash.Input("home-view-chart-btn", "n_clicks"),
    dash.Input("home-ticker-input", "n_submit"),
    dash.State("home-ticker-input", "value"),
    dash.State("home-ticker-dropdown", "value"),
    dash.State("home-chart-defaults", "data"),
    prevent_initial_call=True,
)


@dash.callback(
    Output("watchlist-panel", "children"),
    Output("watchlist-status", "children"),
    Output("watchlist-add-input", "value"),
    Input("watchlist-add-btn", "n_clicks"),
    Input("watchlist-add-input", "n_submit"),
    Input({"type": "watchlist-remove-btn", "index": ALL}, "n_clicks"),
    State("watchlist-add-dropdown", "value"),
    State("watchlist-add-input", "value"),
    prevent_initial_call=False,
)
def render_watchlist(_add_clicks, _add_submit, _remove_clicks, dropdown_value, input_value):
    """One callback drives every watchlist mutation (add via button/Enter,
    remove via a row's x) and always re-renders the full table from the DB
    afterward -- simpler than patching individual rows client-side, and
    cheap enough since a watchlist is realistically a handful of tickers,
    not hundreds. `prevent_initial_call=False` (the default) also makes
    this fire once on page mount with every Input at its initial value, so
    the table fills in right after the page paints instead of needing a
    separate "on load" trigger -- the whole reason this lives in a callback
    and not in layout() directly is so that wait (analyze_ticker can mean a
    real network fetch) happens after the page is already visible, not
    before.
    """
    triggered = dash.callback_context.triggered_id
    conn = db.get_connection()
    db.init_db(conn)
    status = ""
    cleared_input = dash.no_update
    try:
        if triggered in ("watchlist-add-btn", "watchlist-add-input"):
            ticker = (input_value or "").strip().upper() or dropdown_value
            if ticker:
                db.add_to_watchlist(conn, ticker, datetime.datetime.now().isoformat())
                cleared_input = ""
            else:
                status = "Pick a ticker from the list or type one first."
        elif isinstance(triggered, dict) and triggered.get("type") == "watchlist-remove-btn":
            db.remove_from_watchlist(conn, triggered["index"])

        tickers = db.get_watchlist(conn)
        if not tickers:
            return _watchlist_empty_state(), status, cleared_input

        params = engine.resolve_params({})
        rows = []
        for ticker in tickers:
            try:
                result = engine.analyze_ticker(conn, ticker, params)
            except engine.TickerAnalysisError as exc:
                rows.append(_watchlist_error_row(ticker, str(exc)))
                continue
            closes = result["df"]["Close"]
            prev_close = float(closes.iloc[-2]) if len(closes) >= 2 else None
            chg_pct = ((result["close"] - prev_close) / prev_close * 100) if prev_close else None
            rows.append(_watchlist_row(ticker, result, chg_pct, params["align_threshold"]))

        return _watchlist_panel_body(rows), status, cleared_input
    finally:
        conn.close()


@dash.callback(
    Output("portfolio-preview", "children"),
    Input("portfolio-preview-init", "data"),
    prevent_initial_call=False,
)
def render_portfolio_preview(_data):
    """Read-only summary of db.get_portfolio_positions() marked to market --
    recording buys/sells all happens on the Portfolio page, not here. Fires
    once per landing on Home via portfolio-preview-init's initial value
    (see _portfolio_preview_panel).
    """
    conn = db.get_connection()
    db.init_db(conn)
    try:
        positions = db.get_portfolio_positions(conn)
        holdings = {t: p for t, p in positions.items() if p["quantity"] > 1e-9}
        if not holdings:
            return _portfolio_preview_empty()

        params = engine.resolve_params({})
        total_value = 0.0
        total_cost = 0.0
        movers = []
        for ticker, pos in holdings.items():
            try:
                result = engine.analyze_ticker(conn, ticker, params)
            except engine.TickerAnalysisError:
                continue
            price = result["close"]
            value = pos["quantity"] * price
            cost = pos["quantity"] * pos["avg_cost"]
            pnl = value - cost
            pnl_pct = (pnl / cost * 100) if cost else None
            total_value += value
            total_cost += cost
            movers.append((ticker, value, pnl, pnl_pct))

        total_pnl = total_value - total_cost
        total_pnl_pct = (total_pnl / total_cost * 100) if total_cost else None
        movers.sort(key=lambda m: -m[1])
        top_holdings = [(ticker, pnl, pnl_pct) for ticker, _value, pnl, pnl_pct in movers[:_PORTFOLIO_PREVIEW_ROWS]]

        return _portfolio_preview_body(total_value, total_pnl, total_pnl_pct, top_holdings)
    finally:
        conn.close()
