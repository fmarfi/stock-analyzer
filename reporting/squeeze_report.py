"""Static HTML report: Bollinger Squeeze + confluence-alignment "edge point"
events for hand-picked tickers (see squeeze.find_events()).

Unlike html_report.py's scan report -- every watchlist ticker, latest bar
only -- this walks each chosen ticker's *full* history looking for past
squeeze setups and shows what actually happened afterward, so an assumption
like "tight bands + full alignment tends to break out in that direction" can
be checked against real outcomes instead of just today's reading. Reuses
html_report.py's CSS/badge helpers so the two reports never visually drift,
and dashboard.py's build_chart_fig() for the same reason the scan report's
embedded charts do.
"""

import datetime
import html as html_escape
import logging
import os

from stock_analyzer import config, events, presentation
from stock_analyzer.reporting import cleanup
from stock_analyzer.reporting.html_report import _CSS, _badge_html

logger = logging.getLogger(__name__)

_EXTRA_CSS = """
.event-card {
    background-color: %(card_bg)s; padding: 14px 18px; border-radius: 10px;
    margin-bottom: 16px; max-width: 900px;
}
.event-head { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.event-head h4 { margin: 0; font-size: 15px; }
.event-line { font-size: 13px; color: %(muted)s; margin-top: 6px; }
.no-events { color: %(muted)s; font-size: 13px; margin-bottom: 18px; }
h3.ticker-heading { margin: 26px 0 10px 0; font-size: 18px; }
""" % {"card_bg": config.CARD_BG, "muted": config.MUTED_TEXT}


def _direction_badge(direction: str) -> str:
    color = config.GREEN if direction == "bull" else config.RED
    return _badge_html(direction.upper(), color)


def _outcome_line(event: dict) -> str:
    if not event["has_forward"]:
        return f"+{event['horizon']} bars later: not enough history yet"
    pct = event["fwd_return_pct"]
    verdict = "HIT" if event["hit"] else "MISS"
    color = config.GREEN if event["hit"] else config.RED
    return (
        f'<span style="color:{color};font-weight:bold;">'
        f"+{event['horizon']} bars later: {pct:+.1f}% ({verdict})</span>"
    )


def _build_snapshot_chart_html(df, ticker: str, event: dict, params: dict, pre_bars: int, post_bars: int):
    """Reuse dashboard.py's build_chart_fig() (lazily imported, same
    guard/rationale as html_report.py's embedded scan charts) so the
    snapshot matches what the live dashboard/report would show for that
    window -- just zoomed to the bars around the event instead of the
    default recent-6-months view.
    """
    try:
        from stock_analyzer.dashboard_shared import build_chart_fig, CHART_POST_SCRIPTS, CHART_CONFIG, default_indicator_instances
    except Exception:
        logger.warning("Could not import chart builder (dash not installed?) - skipping snapshot")
        return None

    window = events.event_window(df, event["position"], pre_bars=pre_bars, post_bars=post_bars)
    try:
        fig = build_chart_fig(window, ticker, default_indicator_instances(params))
        # build_chart_fig() already zooms to the full window (past + future
        # bars), but with no marker the "a little bit future" tail at the
        # right edge is easy to mistake for "chart just ends here." Mark the
        # squeeze bar itself, labeled with which condition fired (bandwidth
        # squeeze + which direction was fully aligned), so before/after and
        # *why* this bar qualified are both unmistakable at a glance.
        edge_color = config.GREEN if event["direction"] == "bull" else config.RED
        fig.add_vline(
            x=event["date"], row="all", col=1,
            line_dash="dash", line_color=edge_color, line_width=1.5,
            annotation_text=f"squeeze + {event['direction']} edge",
            annotation_position="top", annotation_font_color=edge_color,
        )
        return fig.to_html(
            full_html=False, include_plotlyjs="cdn", config=CHART_CONFIG, post_script=CHART_POST_SCRIPTS,
        )
    except Exception:
        logger.exception("Failed building squeeze snapshot for %s @ %s", ticker, event["date_str"])
        return None


def _event_html(df, ticker: str, event: dict, params: dict, pre_bars: int, post_bars: int) -> str:
    votes_html = "".join(_badge_html(text, color) for text, color in presentation.indicator_badges(event["votes"]))
    chart_html = _build_snapshot_chart_html(df, ticker, event, params, pre_bars, post_bars)
    chart_block = f'<div class="chart-wrap">{chart_html}</div>' if chart_html else ""

    return f"""
    <div class="event-card">
      <div class="event-head">
        <h4>{html_escape.escape(event['date_str'])}</h4>
        {_direction_badge(event['direction'])}
        {_badge_html(f"confluence {event['confluence']:+d}", config.BLUE)}
        {votes_html}
      </div>
      <div class="event-line">Bandwidth {event['bb_width']:.4f} &middot; close {event['close']:.2f}</div>
      <div class="event-line">{_outcome_line(event)}</div>
      {chart_block}
    </div>
    """


def _ticker_section_html(entry: dict, params: dict, pre_bars: int, post_bars: int) -> str:
    ticker = entry["ticker"]
    events = entry["events"]
    heading = f'<h3 class="ticker-heading">{html_escape.escape(ticker)} &middot; {len(events)} event(s)</h3>'
    if not events:
        return heading + '<div class="no-events">No squeeze + full-alignment events found in this history.</div>'

    cards = "".join(
        _event_html(entry["df"], ticker, event, params, pre_bars, post_bars)
        for event in reversed(events)  # most recent first
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
    <h1>Bollinger Squeeze / Edge Point Report</h1>
    <h2>{html_escape.escape(scan_result['run_timestamp'])}</h2>
    <div class="run-meta">
      <b>Tickers scanned:</b> {n_ok + n_fail} ({n_ok} ok, {n_fail} failed)<br>
      <b>Squeeze definition:</b> BB width in the bottom {scan_result['bw_percentile']:.0f}% of its trailing
      {scan_result['bw_lookback']}-bar range, on a bar where confluence was fully aligned
      (&plusmn;{params['align_threshold']})<br>
      <b>MA short/long:</b> {params['ma_short']} / {params['ma_long']} &middot;
      <b>Outcome horizon:</b> {params['horizon']} bars forward
    </div>
    {failures_html}
    """


def generate_html(scan_result: dict, pre_bars: int = 40, post_bars: int = 20) -> str:
    """Build the full self-contained HTML document string for a squeeze scan
    (the dict returned by engine.run_squeeze_scan())."""
    params = scan_result["params"]
    sections = "".join(
        _ticker_section_html(entry, params, pre_bars, post_bars) for entry in scan_result["tickers"]
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Bollinger Squeeze / Edge Point Report</title>
<style>{_CSS}{_EXTRA_CSS}</style>
</head>
<body>
{_run_meta_html(scan_result)}
{sections}
</body>
</html>
"""


def write_reports(scan_result: dict, reports_dir: str = None, pre_bars: int = 40, post_bars: int = 20) -> str:
    """Write both a timestamped file and overwrite latest_squeeze.html.
    Returns the latest_squeeze.html path.
    """
    reports_dir = reports_dir or config.REPORTS_DIR
    os.makedirs(reports_dir, exist_ok=True)

    html_doc = generate_html(scan_result, pre_bars=pre_bars, post_bars=post_bars)

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    stamped_path = os.path.join(reports_dir, f"squeeze_report_{timestamp}.html")
    latest_path = os.path.join(reports_dir, "latest_squeeze.html")

    for path in (stamped_path, latest_path):
        with open(path, "w", encoding="utf-8") as f:
            f.write(html_doc)

    cleanup.prune_old_reports(reports_dir, "squeeze_report_*.html", keep=config.REPORT_RETENTION)

    return latest_path
