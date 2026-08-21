"""Portfolio page: a buy/sell transaction ledger (db.portfolio_transactions),
not a hand-edited holdings snapshot -- current quantity, average cost, and
realized P&L per ticker are all derived by replaying transactions in date
order (db.get_portfolio_positions), the same "recompute from source facts"
approach scan_results already uses over price_history. Buying a ticker here
also adds it to the Watchlist automatically (see render_portfolio below) --
if you own it, you almost certainly want to be watching it too.

Same "compute in a callback, not in layout()" split as the Home page's
Watchlist panel, and for the same reason: marking every position to market
means an engine.analyze_ticker() call per ticker, which can mean a real
network fetch the first time that ticker's data is requested that day.
"""

import datetime

import dash
from dash import ALL, Input, Output, State, dcc, html

from stock_analyzer import config, db, engine
from stock_analyzer.dashboard_shared import DROPDOWN_TICKERS, page_header

dash.register_page(__name__, path="/portfolio", name="Portfolio", title="Portfolio")

_HOLDINGS_COL_WIDTHS = ["1fr", "0.8fr", "0.9fr", "0.9fr", "1fr", "1fr", "0.8fr", "0.9fr", "40px"]
_HOLDINGS_COL_TEMPLATE = " ".join(_HOLDINGS_COL_WIDTHS)

_TXN_COL_WIDTHS = ["0.9fr", "1fr", "0.6fr", "0.8fr", "0.8fr", "1fr", "40px"]
_TXN_COL_TEMPLATE = " ".join(_TXN_COL_WIDTHS)

_TXN_LOG_LIMIT = 15


def _grid_row(cells, template, header=False):
    return html.Div(cells, style={
        "display": "grid", "gridTemplateColumns": template, "gap": "10px",
        "alignItems": "center", "padding": "10px 14px",
        "borderBottom": f"1px solid {config.BORDER_COLOR}",
        "fontSize": "12px" if header else "13px",
        "color": config.MUTED_TEXT if header else "white",
        "textTransform": "uppercase" if header else "none",
        "letterSpacing": "0.4px" if header else "normal",
    })


def _remove_btn(comp_type, index, title):
    return html.Button("×", id={"type": comp_type, "index": index}, n_clicks=0, title=title, style={
        "backgroundColor": "transparent", "color": config.MUTED_TEXT,
        "border": "none", "cursor": "pointer", "fontSize": "16px", "lineHeight": 1,
    })


def _chart_link(ticker):
    return html.A("Chart", href=f"/chart/{ticker}", target="_blank", className="btn btn-outline", style={
        "textDecoration": "none", "padding": "4px 10px", "fontSize": "12px", "textAlign": "center",
    })


# --- holdings table ----------------------------------------------------------

def _holdings_header():
    return _grid_row([
        html.Span("Ticker"), html.Span("Qty"), html.Span("Avg Cost"), html.Span("Price"),
        html.Span("Value"), html.Span("P&L"), html.Span("P&L %"), html.Span(""), html.Span(""),
    ], _HOLDINGS_COL_TEMPLATE, header=True)


def _holding_row(ticker: str, quantity: float, avg_cost: float, price: float):
    value = quantity * price
    cost_basis = quantity * avg_cost
    pnl = value - cost_basis
    pnl_pct = (pnl / cost_basis * 100) if cost_basis else None
    pnl_color = config.GREEN if pnl >= 0 else config.RED

    return _grid_row([
        html.Span(ticker, style={"fontWeight": 600}),
        html.Span(f"{quantity:g}"),
        html.Span(f"{avg_cost:.2f}"),
        html.Span(f"{price:.2f}"),
        html.Span(f"{value:,.2f}"),
        html.Span(f"{pnl:+,.2f}", style={"color": pnl_color, "fontWeight": 600}),
        html.Span(f"{pnl_pct:+.2f}%" if pnl_pct is not None else "-",
                   style={"color": pnl_color, "fontWeight": 600}),
        _chart_link(ticker),
        html.Span(),  # holdings have no direct delete -- sell it via a transaction instead
    ], _HOLDINGS_COL_TEMPLATE)


def _holdings_error_row(ticker: str, message: str):
    return _grid_row([
        html.Span(ticker, style={"fontWeight": 600}),
        html.Span(message, style={"color": config.RED, "fontSize": "12px", "gridColumn": "span 6"}),
        html.Span(""),
        html.Span(),
    ], _HOLDINGS_COL_TEMPLATE)


def _holdings_empty_state():
    return html.Div(
        "No open positions -- record a buy above to start tracking one.",
        style={"color": config.MUTED_TEXT, "fontSize": "13px", "padding": "20px 14px"},
    )


def _stat_tile(value: str, label: str, color: str = "white"):
    return html.Div([
        html.Div(value, style={"fontSize": "22px", "fontWeight": 700, "color": color, "letterSpacing": "-0.3px"}),
        html.Div(label, style={"fontSize": "12px", "color": config.MUTED_TEXT, "marginTop": "3px"}),
    ], className="hover-card", style={
        "backgroundColor": config.CARD_BG, "borderRadius": "10px", "padding": "14px 18px",
        "minWidth": "160px", "flex": "1", "border": f"1px solid {config.BORDER_COLOR}",
    })


def _summary_tiles(total_value, total_cost, total_pnl, total_pnl_pct, realized_pnl):
    pnl_color = config.GREEN if total_pnl >= 0 else config.RED
    realized_color = config.GREEN if realized_pnl >= 0 else config.RED
    pnl_pct_text = f"{total_pnl_pct:+.2f}%" if total_pnl_pct is not None else "n/a"
    return html.Div([
        _stat_tile(f"{total_value:,.2f}", "Market value"),
        _stat_tile(f"{total_cost:,.2f}", "Cost basis"),
        _stat_tile(f"{total_pnl:+,.2f}", "Unrealized P&L", pnl_color),
        _stat_tile(pnl_pct_text, "Unrealized P&L %", pnl_color),
        _stat_tile(f"{realized_pnl:+,.2f}", "Realized P&L", realized_color),
    ], style={"display": "flex", "gap": "14px", "flexWrap": "wrap", "marginBottom": "20px"})


# --- transaction log -----------------------------------------------------------

def _txn_log_header():
    return _grid_row([
        html.Span("Date"), html.Span("Ticker"), html.Span("Side"), html.Span("Qty"),
        html.Span("Price"), html.Span("Total"), html.Span(""),
    ], _TXN_COL_TEMPLATE, header=True)


def _txn_row(txn):
    side = txn["side"]
    side_color = config.GREEN if side == "buy" else config.RED
    total = txn["quantity"] * txn["price"]
    return _grid_row([
        html.Span(txn["txn_date"]),
        html.Span(txn["ticker"], style={"fontWeight": 600}),
        html.Span(side.upper(), style={"color": side_color, "fontWeight": 600}),
        html.Span(f"{txn['quantity']:g}"),
        html.Span(f"{txn['price']:.2f}"),
        html.Span(f"{total:,.2f}"),
        _remove_btn("portfolio-txn-remove-btn", txn["id"], "Undo this transaction"),
    ], _TXN_COL_TEMPLATE)


def _txn_log_empty():
    return html.Div("No transactions yet.", style={
        "color": config.MUTED_TEXT, "fontSize": "13px", "padding": "20px 14px",
    })


def _resolve_txn_date(txn_date: str):
    """Blank -> today. A non-blank value must parse as YYYY-MM-DD (this is
    a plain text field, not a real date picker -- see the comment on
    portfolio-txn-date in layout() for why). Returns (date_str, error) where
    exactly one is None.
    """
    if not txn_date or not txn_date.strip():
        return datetime.date.today().isoformat(), None
    try:
        return datetime.date.fromisoformat(txn_date.strip()).isoformat(), None
    except ValueError:
        return None, f'"{txn_date}" isn\'t a valid date -- use YYYY-MM-DD, or leave it blank for today.'


def layout():
    return html.Div([
        page_header("Portfolio", "Record what you buy and sell -- current holdings, average cost, and "
                    "realized/unrealized P&L are all computed from this transaction log, marked to the "
                    "latest cached price. Buying a ticker also adds it to your Watchlist."),

        # --- record a transaction -----------------------------------------------
        html.Div([
            dcc.Dropdown(
                id="portfolio-txn-dropdown",
                options=[{"label": t, "value": t} for t in DROPDOWN_TICKERS],
                placeholder="Select a ticker...",
                style={"width": "200px"},
            ),
            html.Div("or", style={"color": config.MUTED_TEXT, "fontSize": "13px"}),
            dcc.Input(
                id="portfolio-txn-input", type="text", placeholder="...type any ticker",
                debounce=False, style={
                    "width": "150px", "backgroundColor": config.INPUT_BG, "color": "white",
                    "border": f"1px solid {config.BORDER_COLOR}", "borderRadius": "6px", "padding": "8px 10px",
                },
            ),
            dcc.RadioItems(
                id="portfolio-txn-side", options=[{"label": " Buy", "value": "buy"},
                                                   {"label": " Sell", "value": "sell"}],
                value="buy", inline=True, style={"color": "white", "fontSize": "13px"},
                inputStyle={"marginRight": "4px", "marginLeft": "10px"},
                labelStyle={"marginRight": "4px", "color": "white"},
            ),
            dcc.Input(
                id="portfolio-txn-qty", type="number", placeholder="Quantity", min=0, step="any",
                style={
                    "width": "100px", "backgroundColor": config.INPUT_BG, "color": "white",
                    "border": f"1px solid {config.BORDER_COLOR}", "borderRadius": "6px", "padding": "8px 10px",
                },
            ),
            dcc.Input(
                id="portfolio-txn-price", type="number", placeholder="Price", min=0, step="any",
                style={
                    "width": "100px", "backgroundColor": config.INPUT_BG, "color": "white",
                    "border": f"1px solid {config.BORDER_COLOR}", "borderRadius": "6px", "padding": "8px 10px",
                },
            ),
            # dcc.Input has no "date" type (Dash restricts type to a fixed
            # list -- text/number/password/email/range/search/tel/url/
            # hidden -- and silently letting "date" through as an invalid
            # prop sent React into a crash-recover-crash loop, hammering
            # the server with callback requests forever). Plain text with a
            # format hint, parsed/validated in render_portfolio, avoids
            # that entirely and skips pulling in dcc.DatePickerSingle's
            # separate (light-themed) calendar-popup styling for one field.
            dcc.Input(
                id="portfolio-txn-date", type="text", placeholder="YYYY-MM-DD (optional)", style={
                    "width": "150px", "backgroundColor": config.INPUT_BG, "color": "white",
                    "border": f"1px solid {config.BORDER_COLOR}", "borderRadius": "6px", "padding": "8px 10px",
                },
            ),
            html.Button("Record Transaction", id="portfolio-txn-btn", n_clicks=0, className="btn", style={
                "backgroundColor": config.BLUE, "color": "white",
            }),
        ], style={"display": "flex", "gap": "12px", "alignItems": "center", "marginBottom": "8px",
                  "flexWrap": "wrap"}),

        html.Div(id="portfolio-status", style={"color": config.RED, "fontSize": "12px", "marginBottom": "16px"}),

        html.Div(id="portfolio-summary"),

        dcc.Loading(html.Div(id="portfolio-table", style={
            "backgroundColor": config.CARD_BG, "borderRadius": "10px",
            "border": f"1px solid {config.BORDER_COLOR}", "maxWidth": "920px", "overflow": "hidden",
            "marginBottom": "28px",
        }), type="circle", color=config.BLUE),

        html.H3("Recent Transactions", style={"color": "white", "fontSize": "16px", "marginBottom": "10px"}),
        html.Div(id="portfolio-txn-log", style={
            "backgroundColor": config.CARD_BG, "borderRadius": "10px",
            "border": f"1px solid {config.BORDER_COLOR}", "maxWidth": "780px", "overflow": "hidden",
        }),
    ])


@dash.callback(
    Output("portfolio-table", "children"),
    Output("portfolio-summary", "children"),
    Output("portfolio-txn-log", "children"),
    Output("portfolio-status", "children"),
    Output("portfolio-txn-input", "value"),
    Output("portfolio-txn-qty", "value"),
    Output("portfolio-txn-price", "value"),
    Input("portfolio-txn-btn", "n_clicks"),
    Input({"type": "portfolio-txn-remove-btn", "index": ALL}, "n_clicks"),
    State("portfolio-txn-dropdown", "value"),
    State("portfolio-txn-input", "value"),
    State("portfolio-txn-side", "value"),
    State("portfolio-txn-qty", "value"),
    State("portfolio-txn-price", "value"),
    State("portfolio-txn-date", "value"),
    prevent_initial_call=False,
)
def render_portfolio(_txn_clicks, _remove_clicks, dropdown_value, input_value, side, quantity, price, txn_date):
    """Drives recording a transaction, undoing one, AND (via
    prevent_initial_call=False firing once on page mount) the initial load
    -- see the module docstring for why this lives in a callback instead of
    layout().
    """
    triggered = dash.callback_context.triggered_id
    conn = db.get_connection()
    db.init_db(conn)
    status = ""
    cleared = (dash.no_update, dash.no_update, dash.no_update)
    try:
        if triggered == "portfolio-txn-btn":
            ticker = (input_value or "").strip().upper() or dropdown_value
            resolved_date, date_error = _resolve_txn_date(txn_date)
            if not ticker:
                status = "Pick a ticker from the list or type one first."
            elif not quantity or quantity <= 0:
                status = "Enter a quantity greater than 0."
            elif price is None or price < 0:
                status = "Enter a price."
            elif date_error:
                status = date_error
            elif side == "sell":
                held = db.get_portfolio_positions(conn).get(ticker, {}).get("quantity", 0.0)
                if quantity > held + 1e-9:
                    status = f"Can't sell {quantity:g} {ticker} -- only {held:g} held."
                else:
                    db.add_portfolio_transaction(
                        conn, ticker, "sell", float(quantity), float(price),
                        resolved_date, datetime.datetime.now().isoformat(),
                    )
                    cleared = ("", None, None)
            else:
                db.add_portfolio_transaction(
                    conn, ticker, "buy", float(quantity), float(price),
                    resolved_date, datetime.datetime.now().isoformat(),
                )
                # Owning it means you almost certainly want to be watching
                # it too -- add_to_watchlist is a no-op (INSERT OR IGNORE)
                # if it's already there.
                db.add_to_watchlist(conn, ticker, datetime.datetime.now().isoformat())
                cleared = ("", None, None)
        elif isinstance(triggered, dict) and triggered.get("type") == "portfolio-txn-remove-btn":
            db.delete_portfolio_transaction(conn, triggered["index"])

        positions = db.get_portfolio_positions(conn)
        holdings = {t: p for t, p in positions.items() if p["quantity"] > 1e-9}
        realized_pnl = sum(p["realized_pnl"] for p in positions.values())

        txns = db.get_portfolio_transactions(conn, limit=_TXN_LOG_LIMIT)
        txn_log = html.Div([_txn_log_header(), *[_txn_row(t) for t in txns]]) if txns else _txn_log_empty()

        if not holdings:
            summary = _summary_tiles(0.0, 0.0, 0.0, None, realized_pnl)
            return _holdings_empty_state(), summary, txn_log, status, *cleared

        params = engine.resolve_params({})
        rows = []
        total_value = 0.0
        total_cost = 0.0
        for ticker, pos in holdings.items():
            try:
                result = engine.analyze_ticker(conn, ticker, params)
            except engine.TickerAnalysisError as exc:
                rows.append(_holdings_error_row(ticker, str(exc)))
                continue
            price_now = result["close"]
            rows.append(_holding_row(ticker, pos["quantity"], pos["avg_cost"], price_now))
            total_value += pos["quantity"] * price_now
            total_cost += pos["quantity"] * pos["avg_cost"]

        total_pnl = total_value - total_cost
        total_pnl_pct = (total_pnl / total_cost * 100) if total_cost else None
        table = html.Div([_holdings_header(), *rows])
        summary = _summary_tiles(total_value, total_cost, total_pnl, total_pnl_pct, realized_pnl)
        return table, summary, txn_log, status, *cleared
    finally:
        conn.close()
