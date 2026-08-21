"""Dash app shell -- multi-page version of what used to be one long
scrolling single-page dashboard. Each report (Scoreboard, Squeeze, Bounce,
Triangles, Strategy by Sector, Snapshots) is its own page under
stock_analyzer/pages/, auto-discovered by Dash's `use_pages=True`; this
module only owns the app-wide shell (sidebar nav + page_container), the
standalone /chart/<ticker> Flask route (shared by every page's "View Chart"
button), and the run block.

Shared building blocks (build_chart_fig, CHART_CONFIG, ticker lists, small
UI helpers) live in dashboard_shared.py, not here -- page modules import
from there, not from this module, so there's no import cycle between the
app shell and the pages it hosts.

Unlike scoreboard_app.py, nothing expensive (a Wikipedia scrape, a yfinance
call) happens at import time -- ticker universes and price data are only
fetched inside callbacks, so `import stock_analyzer.dashboard` is safe and
cheap.
"""

import json
import logging
import os
import sys
from urllib.parse import quote, urlencode

# Allow `python stock_analyzer/dashboard.py` (direct script execution) to
# find the `stock_analyzer` package -- same rationale as run_scan.py.
if __package__ in (None, ""):
    _PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _PROJECT_ROOT not in sys.path:
        sys.path.insert(0, _PROJECT_ROOT)

import dash
from dash import Dash, dcc, html
from flask import request, send_from_directory

from stock_analyzer import config, db, engine, fetch
from stock_analyzer import timeframe as timeframe_mod
from stock_analyzer.dashboard_shared import (
    build_chart_fig, default_indicator_instances, CHART_POST_SCRIPTS, CHART_CONFIG,
    INDICATOR_LABELS, INDICATOR_TYPES, configure_logging,
)

logger = logging.getLogger(__name__)

app = Dash(
    __name__, use_pages=True, pages_folder=os.path.join(os.path.dirname(__file__), "pages"),
    # Required for multi-page Dash apps: each page only mounts its own
    # components into the DOM (the rest live in other pages' layouts,
    # never all present at once), but every page's callbacks are still
    # registered globally. Without this, Dash validates each callback's
    # Input/Output IDs against whatever page currently happens to be
    # mounted and throws "ID not found in layout" for every other page's
    # callbacks -- which is exactly the wall of console errors this fixes.
    suppress_callback_exceptions=True,
)

# Controls sidebar order -- dash.page_registry's own order follows module
# discovery order, not necessarily the workflow order a reader wants.
_NAV_ORDER = ["/", "/scoreboard", "/squeeze", "/bounce", "/triangles", "/strategy", "/snapshots"]


def _sidebar_link(page: dict, current_path: str):
    active = page["path"] == current_path
    return dcc.Link(page["name"], href=page["path"], style={
        "display": "block", "padding": "10px 16px", "borderRadius": "6px",
        "color": "white" if active else config.MUTED_TEXT,
        "backgroundColor": config.BLUE if active else "transparent",
        "textDecoration": "none", "fontFamily": "Arial, sans-serif", "fontSize": "14px",
        "marginBottom": "2px",
    })


def _ordered_pages():
    pages_by_path = {p["path"]: p for p in dash.page_registry.values()}
    return [pages_by_path[p] for p in _NAV_ORDER if p in pages_by_path]


# The sidebar's active-page highlight can't be computed from flask.request
# in the layout itself -- Dash evaluates a callable app.layout once at
# startup for validation, outside any HTTP request context, so
# flask.request.path raises "working outside of request context" there.
# dcc.Location + this callback is the standard Dash way to react to the
# current path client-side instead.
app.layout = html.Div([
    dcc.Location(id="_url"),
    html.Div([
        html.Div("Stock Analyzer", style={
            "color": "white", "fontFamily": "Arial, sans-serif", "fontWeight": "bold",
            "fontSize": "16px", "padding": "16px", "borderBottom": f"1px solid {config.BORDER_COLOR}",
        }),
        html.Div(id="sidebar-nav", style={"padding": "12px 8px"}),
    ], style={
        "width": "200px", "flexShrink": 0, "backgroundColor": config.CARD_BG,
        "minHeight": "100vh", "position": "sticky", "top": 0, "alignSelf": "flex-start",
    }),
    html.Div(dash.page_container, style={"flex": 1, "padding": "24px", "minWidth": 0}),
], style={"display": "flex", "backgroundColor": config.PAGE_BG, "minHeight": "100vh"})


@app.callback(dash.Output("sidebar-nav", "children"), dash.Input("_url", "pathname"))
def _render_sidebar(pathname):
    return [_sidebar_link(p, pathname or "/") for p in _ordered_pages()]


# ---------------------------------------------------------------------------
# Standalone chart window -- shared by every page's "View Chart" button.
# ---------------------------------------------------------------------------
# Weekly view zooms to ~2 years of weekly bars by default instead of daily's
# ~6 months of daily bars; Hourly zooms to ~1 month of hourly bars (~8
# trading hours/day) since the whole point of hourly is short-term detail,
# not a 6-month view -- 126 bars means something very different at each
# timeframe (see build_chart_fig's recent_window_bars).
_RECENT_WINDOW_BARS = {"daily": 126, "weekly": 104, "hourly": 160}


def _toggle_link_html(ticker: str, qs_base: dict, key: str, value: str, label: str, active: bool) -> str:
    qs = urlencode({**qs_base, key: value}, doseq=True)
    style = (
        f"background-color:{config.BLUE if active else config.CARD_BG};"
        "color:white;text-decoration:none;padding:6px 16px;border-radius:6px;"
        "font-family:Arial, sans-serif;font-size:13px;margin-right:8px;display:inline-block;"
    )
    return f'<a href="/chart/{quote(ticker)}?{qs}" style="{style}">{label}</a>'


def _tf_chart_type_bar_html(ticker: str, timeframe: str, chart_type: str, instances: list) -> str:
    """Daily/Weekly and Candles/Heikin Ashi toggle links -- plain <a> tags
    (full page reload) rather than a Dash control, since this page is a bare
    Flask route, not part of the Dash app. These two stay simple click
    toggles (they're not indicator parameters to arrange, just a binary
    choice); the current indicator list carries along as repeated `indicator`
    query params so switching timeframe or candle style doesn't reset it.
    """
    qs_base = {
        "indicator": [json.dumps(inst, separators=(",", ":")) for inst in instances],
        "settings_submitted": "1", "tf": timeframe, "chart_type": chart_type,
    }
    tf_links = "".join(
        _toggle_link_html(ticker, qs_base, "tf", tf_value, label, tf_value == timeframe)
        for tf_value, label in (("hourly", "Hourly"), ("daily", "Daily"), ("weekly", "Weekly"))
    )
    chart_type_links = "".join(
        _toggle_link_html(ticker, qs_base, "chart_type", ct_value, label, ct_value == chart_type)
        for ct_value, label in (("candle", "Candles"), ("heikin_ashi", "Heikin Ashi"))
    )
    return (
        f'<div style="background-color:{config.PAGE_BG};padding:16px 20px 8px 20px;">'
        f"{tf_links}"
        f'<span style="display:inline-block;width:16px;"></span>'
        f"{chart_type_links}"
        "</div>"
    )


# One entry per addable type: which numeric/select fields it has (in display
# order) and which color slot(s) it needs. Mirrored in the client-side JS
# below (TYPE_FIELDS/TYPE_COLORS) for building a brand-new row -- this
# Python copy is only for rendering rows that already exist (from the
# current indicator list) with their actual current values.
_FIELD_SCHEMA = {
    "EMA": [("period", "number")], "SMA": [("period", "number")],
    "BB": [("period", "number"), ("stddev", "number")], "Volume": [],
    "RSI": [("period", "number")],
    "MACD": [("fast", "number"), ("slow", "number"), ("signal", "number")],
    "Stochastic": [("mode", "select"), ("k_period", "number"), ("d_period", "number"), ("smoothing", "number")],
    "DI": [("period", "number")], "Bandwidth": [("period", "number"), ("stddev", "number")],
}
_COLOR_SCHEMA = {
    "EMA": ["color"], "SMA": ["color"], "BB": ["color"], "Volume": [],
    "RSI": ["color"], "MACD": ["color1", "color2"], "Stochastic": ["color1", "color2"],
    "DI": ["color1", "color2"], "Bandwidth": ["color"],
}


def _indicator_row_html(inst: dict) -> str:
    """One row in the indicator list -- every field is genuinely open-ended
    (any type, any number of instances, own params/colors), unlike the old
    one-hardcoded-box-per-type grid. Inputs carry `data-field` (not `name`):
    they're never submitted directly, the form's onsubmit handler (see
    INDICATOR_MENU_JS) walks each `.indicator-row` and serializes it into a
    single hidden `indicator` field as JSON -- see chart_window()'s parsing
    side for why (arbitrary per-type shapes don't fit cleanly into parallel
    query-param lists the way a single fixed field would). The remove
    button needs no server round-trip: it deletes its own row from the DOM
    before the form is ever submitted.
    """
    t = inst["type"]
    field_style = (
        f"width:44px;background-color:{config.INPUT_BG};color:white;border:1px solid {config.BORDER_COLOR};"
        "border-radius:4px;padding:2px 4px;margin-right:6px;"
    )
    fields_html = ""
    for key, kind in _FIELD_SCHEMA[t]:
        if kind == "select":
            options = "".join(
                f'<option value="{m}"{" selected" if m == inst[key] else ""}>{m.capitalize()}</option>'
                for m in ("fast", "slow", "full")
            )
            fields_html += f'<select data-field="{key}" style="{field_style}">{options}</select>'
        else:
            fields_html += (
                f'<span style="color:{config.MUTED_TEXT};font-size:10px;">{key}</span>'
                f'<input type="number" data-field="{key}" value="{inst[key]}" min="1" style="{field_style}">'
            )
    colors_html = "".join(
        f'<input type="color" data-field="{ck}" value="{inst[ck]}" style="width:24px;height:22px;padding:0;'
        'border:none;border-radius:4px;cursor:pointer;margin-right:4px;">'
        for ck in _COLOR_SCHEMA[t]
    )
    return (
        f'<div class="indicator-row" data-type="{t}" style="display:flex;align-items:center;gap:4px;'
        f'background-color:{config.CARD_BG};border-radius:6px;padding:6px 10px;margin-bottom:6px;'
        'flex-wrap:wrap;">'
        f'<span style="color:white;font-family:Arial, sans-serif;font-size:12.5px;min-width:80px;">'
        f'{INDICATOR_LABELS[t]}</span>'
        f"{fields_html}{colors_html}"
        '<button type="button" onclick="this.parentElement.remove()" '
        f'style="background:none;border:none;color:{config.RED};cursor:pointer;font-size:16px;'
        'margin-left:auto;padding:0 4px;">&times;</button>'
        "</div>"
    )


# Rotates through this for each new row "+ Add Indicator" creates, so
# stacking several of the same type doesn't default them all to one color.
_NEW_ROW_PALETTE = ["#42a5f5", "#ffca28", "#26a69a", "#ec407a", "#ab47bc", "#8d6e63", "#66bb6a", "#78909c"]


def _indicator_settings_form_html(ticker: str, timeframe: str, chart_type: str, instances: list) -> str:
    """The add/remove-by-parameters control: a list of indicator rows (see
    _indicator_row_html) plus a "+ Add Indicator" menu (pick a type, it
    appends a new row with that type's own default params/colors) -- not a
    fixed grid of one checkbox-box per hardcoded type. Bare
    <form method="get"> (full page reload), same architecture as the
    Daily/Weekly bar above it, since this page is a Flask route, not a Dash
    callback. `settings_submitted` is a hidden sentinel distinguishing "form
    submitted with every row removed" (show just price) from "no settings
    params at all yet" (a fresh View Chart link -- show the default set).
    """
    rows_html = "".join(_indicator_row_html(inst) for inst in instances)
    type_options = "".join(f'<option value="{t}">{INDICATOR_LABELS[t]}</option>' for t in INDICATOR_TYPES)
    palette_js = ", ".join(f"'{c}'" for c in _NEW_ROW_PALETTE)

    hidden = (
        f'<input type="hidden" name="tf" value="{timeframe}">'
        f'<input type="hidden" name="chart_type" value="{chart_type}">'
        '<input type="hidden" name="settings_submitted" value="1">'
    )
    select_style = (
        f"background-color:{config.INPUT_BG};color:white;border:1px solid {config.BORDER_COLOR};"
        "border-radius:4px;padding:5px 8px;margin-right:8px;"
    )

    menu_js = f"""
<script>
(function() {{
    var TYPE_FIELDS = {{
        EMA: [['period','number']], SMA: [['period','number']],
        BB: [['period','number'],['stddev','number']], Volume: [],
        RSI: [['period','number']],
        MACD: [['fast','number'],['slow','number'],['signal','number']],
        Stochastic: [['mode','select'],['k_period','number'],['d_period','number'],['smoothing','number']],
        DI: [['period','number']], Bandwidth: [['period','number'],['stddev','number']]
    }};
    var TYPE_COLORS = {{
        EMA: ['color'], SMA: ['color'], BB: ['color'], Volume: [],
        RSI: ['color'], MACD: ['color1','color2'], Stochastic: ['color1','color2'],
        DI: ['color1','color2'], Bandwidth: ['color']
    }};
    var TYPE_DEFAULTS = {{
        period: 20, stddev: 2, fast: 12, slow: 26, signal: 9,
        k_period: 14, d_period: 3, smoothing: 3, mode: 'slow'
    }};
    var TYPE_LABELS = {{
        EMA: 'EMA', SMA: 'SMA', BB: 'Bollinger Bands', Volume: 'Volume',
        RSI: 'RSI', MACD: 'MACD', Stochastic: 'Stochastic', DI: 'DI+/-  /  ADX', Bandwidth: 'Bollinger Bandwidth'
    }};
    var palette = [{palette_js}];
    var list = document.getElementById('indicator-list');
    var fieldStyle = 'width:44px;background-color:{config.INPUT_BG};color:white;' +
        'border:1px solid {config.BORDER_COLOR};border-radius:4px;padding:2px 4px;margin-right:6px;';

    function buildRow(type) {{
        var color = palette[list.children.length % palette.length];
        var row = document.createElement('div');
        row.className = 'indicator-row';
        row.dataset.type = type;
        row.style.cssText = 'display:flex;align-items:center;gap:4px;background-color:{config.CARD_BG};' +
            'border-radius:6px;padding:6px 10px;margin-bottom:6px;flex-wrap:wrap;';
        var html = '<span style="color:white;font-family:Arial, sans-serif;font-size:12.5px;min-width:80px;">' +
            TYPE_LABELS[type] + '</span>';
        (TYPE_FIELDS[type] || []).forEach(function(f) {{
            var key = f[0], kind = f[1];
            if (kind === 'select') {{
                html += '<select data-field="' + key + '" style="' + fieldStyle + '">' +
                    '<option value="fast">Fast</option><option value="slow" selected>Slow</option>' +
                    '<option value="full">Full</option></select>';
            }} else {{
                html += '<span style="color:#9e9e9e;font-size:10px;">' + key + '</span>' +
                    '<input type="number" data-field="' + key + '" value="' + TYPE_DEFAULTS[key] +
                    '" min="1" style="' + fieldStyle + '">';
            }}
        }});
        (TYPE_COLORS[type] || []).forEach(function(ck, i) {{
            var c = palette[(list.children.length + i + 1) % palette.length];
            html += '<input type="color" data-field="' + ck + '" value="' + c + '" style="width:24px;' +
                'height:22px;padding:0;border:none;border-radius:4px;cursor:pointer;margin-right:4px;">';
        }});
        html += '<button type="button" onclick="this.parentElement.remove()" style="background:none;' +
            'border:none;color:{config.RED};cursor:pointer;font-size:16px;margin-left:auto;padding:0 4px;">' +
            '&times;</button>';
        row.innerHTML = html;
        return row;
    }}

    document.getElementById('add-indicator-btn').addEventListener('click', function() {{
        var type = document.getElementById('add-indicator-type').value;
        list.appendChild(buildRow(type));
    }});

    document.getElementById('chart-settings-form').addEventListener('submit', function() {{
        var rows = list.querySelectorAll('.indicator-row');
        rows.forEach(function(row) {{
            var inst = {{type: row.dataset.type}};
            row.querySelectorAll('[data-field]').forEach(function(el) {{
                inst[el.dataset.field] = el.value;
            }});
            var hiddenInput = document.createElement('input');
            hiddenInput.type = 'hidden';
            hiddenInput.name = 'indicator';
            hiddenInput.value = JSON.stringify(inst);
            this.appendChild(hiddenInput);
        }}, this);
    }});
}})();
</script>
"""

    return f"""
<form method="get" action="/chart/{quote(ticker)}" id="chart-settings-form"
      style="background-color:{config.PAGE_BG};padding:0 20px 14px 20px;font-family:Arial, sans-serif;">
{hidden}
<div id="indicator-list" style="margin-bottom:10px;max-width:900px;">{rows_html}</div>
<div style="margin-bottom:10px;">
    <select id="add-indicator-type" style="{select_style}">{type_options}</select>
    <button type="button" id="add-indicator-btn" style="background-color:{config.BLUE};color:white;border:none;
            border-radius:6px;padding:6px 14px;cursor:pointer;font-size:12.5px;">+ Add Indicator</button>
</div>
<button type="submit" style="background-color:{config.GREEN};color:white;border:none;
        border-radius:6px;padding:8px 20px;cursor:pointer;font-size:13px;">Apply</button>
</form>
{menu_js}
"""


def _sanitize_indicator_instance(raw: dict):
    """Fill in/repair one indicator instance from freeform JSON (a hand-
    edited URL, or a row whose number input got cleared) against
    _INDICATOR_DEFAULTS, rather than letting a malformed field 500 the
    whole page inside build_chart_fig's math. Returns None for a type this
    app doesn't know.
    """
    t = raw.get("type") if isinstance(raw, dict) else None
    defaults = _INDICATOR_DEFAULTS.get(t)
    if defaults is None:
        return None
    out = {"type": t}
    for key, default in defaults.items():
        val = raw.get(key, default)
        if key in _INDICATOR_INT_FIELDS:
            try:
                val = int(val)
                if val < 1:
                    val = default
            except (TypeError, ValueError):
                val = default
        elif key == "stddev":
            try:
                val = float(val)
            except (TypeError, ValueError):
                val = default
        elif key == "mode" and val not in ("fast", "slow", "full"):
            val = default
        out[key] = val
    return out


_INDICATOR_DEFAULTS = {
    "EMA": {"period": 20, "color": "#42a5f5"}, "SMA": {"period": 20, "color": "#26a69a"},
    "BB": {"period": config.BB_PERIOD, "stddev": config.BB_STDDEV, "color": "#9575cd"},
    "Volume": {},
    "RSI": {"period": config.RSI_PERIOD, "color": "#ffa726"},
    "MACD": {"fast": config.MACD_FAST, "slow": config.MACD_SLOW, "signal": config.MACD_SIGNAL,
              "color1": "#42a5f5", "color2": "#ffca28"},
    "Stochastic": {"mode": config.STOCH_MODE, "k_period": config.STOCH_K_PERIOD,
                   "d_period": config.STOCH_D_PERIOD, "smoothing": config.STOCH_SLOWING,
                   "color1": "#42a5f5", "color2": "#ffca28"},
    "DI": {"period": config.DI_PERIOD, "color1": config.GREEN, "color2": config.RED},
    "Bandwidth": {"period": config.BB_PERIOD, "stddev": config.BB_STDDEV, "color": "#b39ddb"},
}
_INDICATOR_INT_FIELDS = {"period", "fast", "slow", "signal", "k_period", "d_period", "smoothing"}


@app.server.route("/chart/<ticker>")
def chart_window(ticker):
    """Standalone chart page opened by every page's "View Chart" button.
    Reuses build_chart_fig() so the popped-out chart matches the scoreboard
    cards exactly, and logs to the terminal so the running dashboard process
    shows which chart windows are being opened. ?tf=daily|weekly picks the
    bar timeframe and ?chart_type=candle|heikin_ashi picks the candle style
    (simple click toggles); the indicator list itself comes from repeated
    ?indicator=<json> params, one per row in the settings form below the
    chart, submitted together via Apply rather than toggled one click at a
    time. A fresh link with no ?indicator params at all (every existing
    "View Chart" button still sends the old ma_short/ma_long/bb_period/etc
    flat params, not a built indicator list) falls back to the classic
    default set built from those flat params -- see
    default_indicator_instances().
    """
    stoch_mode = request.args.get("stoch_mode")
    params = engine.resolve_params({
        "ma_short": request.args.get("ma_short", type=int),
        "ma_long": request.args.get("ma_long", type=int),
        "bb_period": request.args.get("bb_period", type=int),
        "bb_stddev": request.args.get("bb_stddev", type=float),
        "rsi_period": request.args.get("rsi_period", type=int),
        "macd_fast": request.args.get("macd_fast", type=int),
        "macd_slow": request.args.get("macd_slow", type=int),
        "macd_signal": request.args.get("macd_signal", type=int),
        "stoch_mode": stoch_mode if stoch_mode in ("fast", "slow", "full") else None,
        "stoch_k_period": request.args.get("stoch_k_period", type=int),
        "stoch_d_period": request.args.get("stoch_d_period", type=int),
        "stoch_slowing": request.args.get("stoch_smoothing", type=int),
        "di_period": request.args.get("di_period", type=int),
    })
    timeframe = request.args.get("tf", "daily")
    if timeframe not in _RECENT_WINDOW_BARS:
        timeframe = "daily"
    chart_type = request.args.get("chart_type", "candle")
    if chart_type not in ("candle", "heikin_ashi"):
        chart_type = "candle"

    conn = db.get_connection()
    db.init_db(conn)
    try:
        try:
            result = engine.analyze_ticker(conn, ticker, params)
        except engine.TickerAnalysisError as exc:
            logger.warning("Chart window requested for %s but analysis failed: %s", ticker, exc)
            return f"No data for {ticker}: {exc}", 404
    finally:
        conn.close()

    if timeframe == "hourly":
        # Hourly bars can't be derived from the daily frame the way weekly
        # can (resampling only coarsens, never creates sub-day granularity)
        # -- this is an independent yfinance fetch, not cached in SQLite
        # (see fetch.fetch_hourly_ohlcv).
        hourly_raw = fetch.fetch_hourly_ohlcv(ticker)
        if hourly_raw.empty:
            logger.warning("Chart window requested hourly data for %s but none was available", ticker)
            return f"No hourly data available for {ticker}.", 404
        df = timeframe_mod.prepare_with_indicators(hourly_raw, params)
    else:
        df = result["df"]
        if timeframe == "weekly":
            df = timeframe_mod.resample_ohlcv(df, "W", params)
    if chart_type == "heikin_ashi":
        df = timeframe_mod.compute_heikin_ashi(df)

    # "settings_submitted" distinguishes a real (possibly all-rows-removed)
    # form submission from a fresh View Chart link that has never touched
    # this at all -- only the latter falls back to the classic default set.
    if "settings_submitted" in request.args:
        instances = []
        for raw_json in request.args.getlist("indicator"):
            try:
                raw = json.loads(raw_json)
            except (TypeError, ValueError):
                continue
            sanitized = _sanitize_indicator_instance(raw) if isinstance(raw, dict) else None
            if sanitized:
                instances.append(sanitized)
    else:
        instances = default_indicator_instances(params)

    logger.info(
        "Opened %s %s chart window for %s: %s",
        timeframe, chart_type, ticker,
        ", ".join(f'{i["type"]}({i.get("period", "")})' for i in instances) or "no indicators",
    )
    fig = build_chart_fig(
        df, ticker, instances,
        recent_window_bars=_RECENT_WINDOW_BARS[timeframe], timeframe=timeframe, chart_type=chart_type,
    )
    chart_div = fig.to_html(
        full_html=False, include_plotlyjs="cdn", config=CHART_CONFIG, post_script=CHART_POST_SCRIPTS,
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>{ticker} chart</title></head>
<body style="margin:0;background-color:{config.PAGE_BG};">
{_tf_chart_type_bar_html(ticker, timeframe, chart_type, instances)}
{_indicator_settings_form_html(ticker, timeframe, chart_type, instances)}
{chart_div}
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Static report files -- "View Last Report" buttons (Scoreboard's for now)
# open these in a new tab. Report generation always overwrites the same
# latest.html/.csv in place (see reporting/html_report.py's write_reports),
# so a static link never goes stale across multiple "Generate Report" runs
# without needing any callback wiring to keep it current.
# ---------------------------------------------------------------------------
@app.server.route("/reports/<path:filename>")
def serve_report(filename):
    return send_from_directory(config.REPORTS_DIR, filename)


if __name__ == "__main__":
    configure_logging()
    logger.info("Starting dashboard on http://127.0.0.1:8050")
    # threaded=True: Werkzeug's dev server is single-threaded by default, so
    # a long full-history scan (Squeeze/Bounce/Triangle/Strategy across many
    # tickers) blocks it from answering anything else -- the sidebar nav
    # callback, the /chart/<ticker> route, another tab -- until that one
    # request finishes. A request that has to wait behind one of those scans
    # can look like "the server did not respond" client-side even though
    # nothing crashed; a genuinely large scan can still legitimately take
    # minutes (each ticker walks its full history), but at least the rest of
    # the app stays responsive while it runs.
    app.run(debug=True, port=8050, threaded=True)
