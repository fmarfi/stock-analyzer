"""Home page: the dashboard's actual dashboard -- live counts, report
freshness, and a card per section instead of a flat list of links. `layout`
is a function (not a static object) so Dash rebuilds it -- including the
report-freshness timestamps -- every time you land on this page.

Deliberately reads nothing expensive: watchlist sizes and the registry are
in-memory, and report freshness is just a file mtime check. Nothing here
fetches a ticker or runs a scan, so this page loads instantly regardless of
whether any report has ever been generated.
"""

import datetime
import os

import dash
from dash import dcc, html

from stock_analyzer import config, indicators
from stock_analyzer.dashboard_shared import BIST_YILDIZ_TICKERS, DROPDOWN_TICKERS, EXTRA_DROPDOWN_TICKERS

dash.register_page(__name__, path="/", name="Home", title="Stock Analyzer")


# label, report filename (relative to config.REPORTS_DIR), destination page path
_REPORTS = [
    ("Scoreboard scan", "latest.html", "/scoreboard"),
    ("Squeeze report", "latest_squeeze.html", "/squeeze"),
    ("Bounce report", "latest_bounce.html", "/bounce"),
    ("Triangle report", "latest_triangle.html", "/triangles"),
    ("Strategy by sector", "latest_strategy.html", "/strategy"),
]

# label, path, description -- the nav card grid. Order matches a natural
# workflow: check the board, dig into a strategy, compare, then archive.
_SECTIONS = [
    ("Scoreboard", "/scoreboard", config.BLUE,
     "Latest-bar confluence read (Trend/Momentum/Volume/MACD) for tickers you pick, with a "
     "one-click chart popup per ticker."),
    ("Squeeze", "/squeeze", config.GREEN,
     "Full-history scan for tight-bandwidth + fully-aligned setups, graded against what actually "
     "happened afterward."),
    ("Bounce", "/bounce", config.GREEN,
     "Full-history scan for band-touch rejections in a ranging market -- the mean-reversion "
     "counterpart to Squeeze."),
    ("Triangles", "/triangles", "#9575cd",
     "Full-history scan for ascending/descending/symmetrical trendline convergences, with the "
     "fitted lines drawn on each snapshot."),
    ("Strategy by Sector", "/strategy", config.RED,
     "Confluence vs. Squeeze vs. Bounce vs. Combined, compared with significance testing and "
     "grouped by GICS sector."),
    ("Snapshots", "/snapshots", config.MUTED_TEXT,
     "Pick tickers, get a saved chart HTML file per ticker under reports/snapshots/ -- no scan, "
     "just an archived view."),
]


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


def _stat_tile(value: str, label: str):
    return html.Div([
        html.Div(value, style={"fontSize": "28px", "fontWeight": "bold", "color": "white"}),
        html.Div(label, style={"fontSize": "12px", "color": config.MUTED_TEXT, "marginTop": "2px"}),
    ], style={
        "backgroundColor": config.CARD_BG, "borderRadius": "10px", "padding": "16px 20px",
        "minWidth": "160px", "flex": "1",
    })


def _report_row(label: str, filename: str, href: str):
    path = os.path.join(config.REPORTS_DIR, filename)
    if os.path.exists(path):
        status_text = f"generated {_relative_time(os.path.getmtime(path))}"
        status_color = config.MUTED_TEXT
    else:
        status_text = "not generated yet"
        status_color = config.RED

    return html.Div([
        html.Span(label, style={"color": "white", "fontSize": "13px"}),
        html.Span(status_text, style={"color": status_color, "fontSize": "12px"}),
        dcc.Link("Open ->", href=href, style={"color": config.BLUE, "fontSize": "12px", "textDecoration": "none"}),
    ], style={
        "display": "flex", "justifyContent": "space-between", "alignItems": "center",
        "padding": "10px 0", "borderBottom": f"1px solid {config.BORDER_COLOR}",
    })


def _section_card(title: str, href: str, accent: str, description: str):
    return dcc.Link(html.Div([
        html.Div(style={"width": "36px", "height": "4px", "backgroundColor": accent, "borderRadius": "2px",
                         "marginBottom": "10px"}),
        html.H4(title, style={"color": "white", "margin": "0 0 6px 0"}),
        html.Div(description, style={"color": config.MUTED_TEXT, "fontSize": "12.5px", "lineHeight": "1.5"}),
    ], style={
        "backgroundColor": config.CARD_BG, "borderRadius": "10px", "padding": "18px",
        "width": "260px", "boxShadow": "0 2px 8px rgba(0,0,0,0.4)", "cursor": "pointer",
        "transition": "transform 0.1s",
    }), href=href, style={"textDecoration": "none"})


def layout():
    n_bist = len(BIST_YILDIZ_TICKERS)
    n_extra = len(EXTRA_DROPDOWN_TICKERS)
    n_indicators = len(indicators.REGISTRY)
    indicator_names = ", ".join(ind.label for ind in indicators.REGISTRY)

    return html.Div([
        html.H1("Stock Analyzer", style={"color": "white", "fontFamily": "Arial, sans-serif", "marginBottom": "4px"}),
        html.Div(
            "Confluence scoring, pattern scans, and cross-strategy comparison across BIST 100 and "
            "Yildiz Pazar, all reading from the same engine as the CLI.",
            style={"color": config.MUTED_TEXT, "fontFamily": "Arial, sans-serif", "fontSize": "14px",
                   "marginBottom": "24px"},
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
                placeholder="Select a ticker...",
                style={"width": "260px"},
            ),
            html.Div("or", style={"color": config.MUTED_TEXT, "fontFamily": "Arial, sans-serif",
                                   "fontSize": "13px"}),
            dcc.Input(
                id="home-ticker-input", type="text", placeholder="...type any ticker, e.g. GARAN.IS",
                debounce=False, n_submit=0, style={
                    "width": "260px", "backgroundColor": config.INPUT_BG, "color": "white",
                    "border": f"1px solid {config.BORDER_COLOR}", "borderRadius": "6px", "padding": "8px",
                },
            ),
            html.Button("View Chart", id="home-view-chart-btn", n_clicks=0, style={
                "backgroundColor": config.BLUE, "color": "white", "border": "none", "borderRadius": "6px",
                "padding": "8px 16px", "cursor": "pointer",
            }),
        ], style={"display": "flex", "gap": "12px", "alignItems": "center", "marginBottom": "8px",
                  "fontFamily": "Arial, sans-serif"}),

        html.Div(id="home-chart-status", style={"color": config.MUTED_TEXT, "fontFamily": "Arial, sans-serif",
                                                 "fontSize": "12px", "marginBottom": "24px"}),

        dcc.Store(id="home-chart-defaults", data={
            "ma_short": config.MA_SHORT, "ma_long": config.MA_LONG,
            "bb_period": config.BB_PERIOD, "bb_stddev": config.BB_STDDEV,
            "stoch_mode": config.STOCH_MODE, "stoch_k_period": config.STOCH_K_PERIOD,
            "stoch_d_period": config.STOCH_D_PERIOD, "stoch_smoothing": config.STOCH_SLOWING,
        }),

        # --- stat tiles -----------------------------------------------------
        html.Div([
            _stat_tile(str(n_bist), "BIST tickers tracked"),
            _stat_tile(str(n_extra), "Extra tickers (crypto etc.)"),
            _stat_tile(str(n_indicators), f"Confluence indicators ({indicator_names})"),
        ], style={"display": "flex", "gap": "14px", "flexWrap": "wrap", "marginBottom": "28px",
                  "fontFamily": "Arial, sans-serif"}),

        # --- report freshness -------------------------------------------------
        html.H3("Report status", style={"color": "white", "fontFamily": "Arial, sans-serif",
                                         "fontSize": "16px", "marginBottom": "8px"}),
        html.Div(
            [_report_row(label, filename, href) for label, filename, href in _REPORTS],
            style={"backgroundColor": config.PAGE_BG, "marginBottom": "28px", "maxWidth": "640px",
                   "fontFamily": "Arial, sans-serif"},
        ),

        # --- section nav cards ------------------------------------------------
        html.H3("Go to", style={"color": "white", "fontFamily": "Arial, sans-serif",
                                 "fontSize": "16px", "marginBottom": "12px"}),
        html.Div(
            [_section_card(title, href, accent, desc) for title, href, accent, desc in _SECTIONS],
            style={"display": "flex", "flexWrap": "wrap", "gap": "14px", "fontFamily": "Arial, sans-serif"},
        ),
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
