"""Static HTML report: triangle chart-pattern formations for hand-picked
tickers (see triangle.find_events()) -- ascending, descending, and
symmetrical trendline convergences found by fitting lines through swing
highs/lows and checking they're genuinely closing in on each other.

Mirrors squeeze_report.py/bounce_report.py's structure and reuses their
badge/CSS/outcome-line helpers so all four strategy reports read as one
family. Unlike those two, the snapshot chart here is deliberately NOT
build_chart_fig() -- MA/Bollinger/RSI/Volume don't show the triangle, they
clutter it, so this draws a bare OHLC panel plus just the two fitted
trendlines, bounded to the pattern's own window (not projected into the
future) so what's drawn is the triangle as detected, not an extrapolation
of it.
"""

import datetime
import html as html_escape
import logging
import os

import plotly.graph_objects as go

from stock_analyzer import config, events, presentation
from stock_analyzer.reporting import cleanup
from stock_analyzer.reporting.html_report import _CSS, _badge_html
from stock_analyzer.reporting.squeeze_report import _EXTRA_CSS, _outcome_line

logger = logging.getLogger(__name__)

_TYPE_COLOR = {"ascending": config.GREEN, "descending": config.RED, "symmetrical": config.BLUE}
_TYPE_LABEL = {"ascending": "ASCENDING", "descending": "DESCENDING", "symmetrical": "SYMMETRICAL"}


def _type_badge(ttype: str) -> str:
    return _badge_html(_TYPE_LABEL[ttype], _TYPE_COLOR[ttype])


def _trendline_trace(df, slope: float, intercept: float, start_pos: int, end_pos: int, name: str, color: str):
    positions = [p for p in range(start_pos, end_pos + 1) if 0 <= p < len(df)]
    xs = [df.index[p] for p in positions]
    ys = [intercept + slope * p for p in positions]
    return go.Scatter(x=xs, y=ys, mode="lines", name=name, line=dict(color=color, width=2, dash="dash"))


def _build_triangle_fig(df, ticker: str, event: dict, pre_bars: int, post_bars: int):
    """Bare OHLC chart plus the two fitted trendlines -- no MA, no
    Bollinger, no RSI/Volume/Bandwidth panels, since none of those show the
    triangle, they'd just clutter it. `pre_bars`/`post_bars` only control
    how much OHLC context surrounds the pattern; the trendlines themselves
    are drawn exactly across [window_start, window_end] -- the pattern's
    actual extent as detected, not projected past it.
    """
    window = events.event_window(df, event["position"], pre_bars=pre_bars, post_bars=post_bars)
    color = _TYPE_COLOR[event["type"]]

    fig = go.Figure()
    fig.add_trace(go.Ohlc(
        x=window.index, open=window["Open"], high=window["High"],
        low=window["Low"], close=window["Close"], name=ticker,
    ))
    fig.add_trace(_trendline_trace(
        df, event["high_slope"], event["high_intercept"], event["window_start"], event["window_end"],
        "Upper trendline", color,
    ))
    fig.add_trace(_trendline_trace(
        df, event["low_slope"], event["low_intercept"], event["window_start"], event["window_end"],
        "Lower trendline", color,
    ))
    fig.add_vline(
        x=event["date"], line_dash="dot", line_color=color, line_width=1,
        annotation_text=f"{event['type']} triangle", annotation_position="top",
        annotation_font_color=color,
    )
    fig.update_layout(
        template="plotly_dark", height=500, xaxis_rangeslider_visible=False, showlegend=True,
        dragmode="zoom", newshape=dict(line_color="#ffca28", line_width=2),
    )
    # Triangle snapshots are always a daily-history window, never weekly, so
    # this is safe unconditionally (see build_chart_fig's timeframe param
    # for why it isn't safe on weekly-resampled data).
    fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])])
    return fig


def _build_snapshot_chart_html(df, ticker: str, event: dict, pre_bars: int, post_bars: int):
    try:
        from stock_analyzer.dashboard_shared import CHART_POST_SCRIPTS, CHART_CONFIG
    except Exception:
        logger.warning("Could not import chart config (dash not installed?) - skipping snapshot")
        return None

    try:
        fig = _build_triangle_fig(df, ticker, event, pre_bars, post_bars)
        return fig.to_html(
            full_html=False, include_plotlyjs="cdn", config=CHART_CONFIG, post_script=CHART_POST_SCRIPTS,
        )
    except Exception:
        logger.exception("Failed building triangle snapshot for %s @ %s", ticker, event["date_str"])
        return None


def _event_html(df, ticker: str, event: dict, pre_bars: int, post_bars: int) -> str:
    chart_html = _build_snapshot_chart_html(df, ticker, event, pre_bars, post_bars)
    chart_block = f'<div class="chart-wrap">{chart_html}</div>' if chart_html else ""
    outcome = _outcome_line(event) if event["type"] != "symmetrical" else (
        f"+{event['horizon']} bars later: {event['fwd_return_pct']:+.1f}% (not graded -- symmetrical "
        f"triangles don't have a textbook-expected direction)"
        if event["has_forward"] else f"+{event['horizon']} bars later: not enough history yet"
    )

    return f"""
    <div class="event-card">
      <div class="event-head">
        <h4>{html_escape.escape(event['date_str'])}</h4>
        {_type_badge(event['type'])}
      </div>
      <div class="event-line">Close {event['close']:.2f} at pattern anchor</div>
      <div class="event-line">{outcome}</div>
      {chart_block}
    </div>
    """


def _ticker_section_html(entry: dict, pre_bars: int, post_bars: int) -> str:
    ticker = entry["ticker"]
    ticker_events = entry["events"]
    heading = f'<h3 class="ticker-heading">{html_escape.escape(ticker)} &middot; {len(ticker_events)} event(s)</h3>'
    if not ticker_events:
        return heading + '<div class="no-events">No triangle formations found in this history.</div>'

    cards = "".join(
        _event_html(entry["df"], ticker, event, pre_bars, post_bars)
        for event in reversed(ticker_events)  # most recent first
    )
    return heading + cards


def _run_meta_html(scan_result: dict) -> str:
    params = scan_result["params"]
    n_ok = len(scan_result["tickers"])
    n_fail = len(scan_result["failures"])

    failures_html = ""
    if scan_result["failures"]:
        items = "".join(
            f'<li>{html_escape.escape(f["ticker"])}: {html_escape.escape(f["error"])}</li>'
            for f in scan_result["failures"]
        )
        failures_html = f'<div class="failures"><b>{n_fail} ticker(s) failed:</b><ul>{items}</ul></div>'

    return f"""
    <h1>Triangle Formations</h1>
    <h2>{html_escape.escape(scan_result['run_timestamp'])}</h2>
    <div class="run-meta">
      <b>Tickers scanned:</b> {n_ok + n_fail} ({n_ok} ok, {n_fail} failed)<br>
      <b>Window:</b> {scan_result['window_bars']} bars &middot;
      <b>Pivot lookback:</b> {scan_result['pivot_lookback']} bars &middot;
      <b>Min pivots per side:</b> {scan_result['min_pivots']}<br>
      <b>Outcome horizon:</b> {params['horizon']} bars forward<br>
      <b>Note:</b> ascending/descending triangles are graded HIT/MISS against their textbook-expected
      breakout direction; symmetrical triangles are shown with their forward return but not graded,
      since classic TA gives them no fixed expected direction. In-sample only -- see the squeeze/bounce
      reports' caveat, it applies here too.
    </div>
    {failures_html}
    """


def generate_html(scan_result: dict, pre_bars: int = None, post_bars: int = 20) -> str:
    """Build the full self-contained HTML document string for a triangle
    scan (the dict returned by engine.run_triangle_scan()). pre_bars
    defaults to the scan's own window_bars so a snapshot always shows the
    whole fitted window, not just part of it.
    """
    pre_bars = pre_bars if pre_bars is not None else scan_result["window_bars"]
    sections = "".join(
        _ticker_section_html(entry, pre_bars, post_bars) for entry in scan_result["tickers"]
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Triangle Formations</title>
<style>{_CSS}{_EXTRA_CSS}</style>
</head>
<body>
{_run_meta_html(scan_result)}
{sections}
</body>
</html>
"""


def write_reports(scan_result: dict, reports_dir: str = None, pre_bars: int = None, post_bars: int = 20) -> str:
    """Write both a timestamped file and overwrite latest_triangle.html.
    Returns the latest_triangle.html path.
    """
    reports_dir = reports_dir or config.REPORTS_DIR
    os.makedirs(reports_dir, exist_ok=True)

    html_doc = generate_html(scan_result, pre_bars=pre_bars, post_bars=post_bars)

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    stamped_path = os.path.join(reports_dir, f"triangle_report_{timestamp}.html")
    latest_path = os.path.join(reports_dir, "latest_triangle.html")

    for path in (stamped_path, latest_path):
        with open(path, "w", encoding="utf-8") as f:
            f.write(html_doc)

    cleanup.prune_old_reports(reports_dir, "triangle_report_*.html", keep=config.REPORT_RETENTION)

    return latest_path
