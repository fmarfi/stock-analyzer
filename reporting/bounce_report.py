"""Static HTML report: Bollinger Bounce events for hand-picked tickers (see
bounce.find_events()) -- price touching an outer Bollinger Band and closing
back inside it while the market wasn't strongly trending, the "buy near the
lower band, sell near the upper band, expect a return toward the middle"
setup.

Mirrors squeeze_report.py's structure/CSS/chart-embedding approach (and
reuses its badge/outcome-line helpers directly) so the two strategy reports
read as one family instead of two one-off designs.
"""

import datetime
import html as html_escape
import logging
import os

from stock_analyzer import config, events, presentation
from stock_analyzer.reporting import cleanup
from stock_analyzer.reporting.html_report import _CSS, _badge_html
from stock_analyzer.reporting.squeeze_report import _EXTRA_CSS, _direction_badge, _outcome_line

logger = logging.getLogger(__name__)


def _build_snapshot_chart_html(df, ticker: str, event: dict, params: dict, pre_bars: int, post_bars: int):
    """Reuse dashboard.py's build_chart_fig() (lazily imported, same
    guard/rationale as squeeze_report.py's snapshots) so this matches what
    the live dashboard/report would show for that window.
    """
    try:
        from stock_analyzer.dashboard_shared import build_chart_fig, CHART_POST_SCRIPTS, CHART_CONFIG, default_indicator_instances
    except Exception:
        logger.warning("Could not import chart builder (dash not installed?) - skipping snapshot")
        return None

    window = events.event_window(df, event["position"], pre_bars=pre_bars, post_bars=post_bars)
    try:
        fig = build_chart_fig(window, ticker, default_indicator_instances(params))
        color = config.GREEN if event["direction"] == "bull" else config.RED
        fig.add_vline(
            x=event["date"], row="all", col=1,
            line_dash="dash", line_color=color, line_width=1.5,
            annotation_text=f"{event['direction']} bounce", annotation_position="top",
            annotation_font_color=color,
        )
        return fig.to_html(
            full_html=False, include_plotlyjs="cdn", config=CHART_CONFIG, post_script=CHART_POST_SCRIPTS,
        )
    except Exception:
        logger.exception("Failed building bounce snapshot for %s @ %s", ticker, event["date_str"])
        return None


def _event_html(df, ticker: str, event: dict, params: dict, pre_bars: int, post_bars: int) -> str:
    votes_html = "".join(_badge_html(text, color) for text, color in presentation.indicator_badges(event["votes"]))
    chart_html = _build_snapshot_chart_html(df, ticker, event, params, pre_bars, post_bars)
    chart_block = f'<div class="chart-wrap">{chart_html}</div>' if chart_html else ""
    band_label = "lower band" if event["direction"] == "bull" else "upper band"

    return f"""
    <div class="event-card">
      <div class="event-head">
        <h4>{html_escape.escape(event['date_str'])}</h4>
        {_direction_badge(event['direction'])}
        {_badge_html(f"confluence {event['confluence']:+d}", config.BLUE)}
        {votes_html}
      </div>
      <div class="event-line">
        Touched {band_label} at {event['band_value']:.2f} &middot; close {event['close']:.2f} &middot;
        middle band {event['middle']:.2f}
      </div>
      <div class="event-line">{_outcome_line(event)}</div>
      {chart_block}
    </div>
    """


def _ticker_section_html(entry: dict, params: dict, pre_bars: int, post_bars: int) -> str:
    ticker = entry["ticker"]
    ticker_events = entry["events"]
    heading = f'<h3 class="ticker-heading">{html_escape.escape(ticker)} &middot; {len(ticker_events)} event(s)</h3>'
    if not ticker_events:
        return heading + '<div class="no-events">No bounce events found in this history.</div>'

    cards = "".join(
        _event_html(entry["df"], ticker, event, params, pre_bars, post_bars)
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
    <h1>Bollinger Bounce Report</h1>
    <h2>{html_escape.escape(scan_result['run_timestamp'])}</h2>
    <div class="run-meta">
      <b>Tickers scanned:</b> {n_ok + n_fail} ({n_ok} ok, {n_fail} failed)<br>
      <b>Bounce definition:</b> price touched the upper/lower band and closed back inside it within
      {scan_result['confirm_bars']} bar(s), on a bar where confluence was NOT fully aligned
      (a ranging/non-trending read)<br>
      <b>MA short/long:</b> {params['ma_short']} / {params['ma_long']} &middot;
      <b>Outcome horizon:</b> {params['horizon']} bars forward
    </div>
    {failures_html}
    """


def generate_html(scan_result: dict, pre_bars: int = 40, post_bars: int = 20) -> str:
    """Build the full self-contained HTML document string for a bounce scan
    (the dict returned by engine.run_bounce_scan())."""
    params = scan_result["params"]
    sections = "".join(
        _ticker_section_html(entry, params, pre_bars, post_bars) for entry in scan_result["tickers"]
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Bollinger Bounce Report</title>
<style>{_CSS}{_EXTRA_CSS}</style>
</head>
<body>
{_run_meta_html(scan_result)}
{sections}
</body>
</html>
"""


def write_reports(scan_result: dict, reports_dir: str = None, pre_bars: int = 40, post_bars: int = 20) -> str:
    """Write both a timestamped file and overwrite latest_bounce.html.
    Returns the latest_bounce.html path.
    """
    reports_dir = reports_dir or config.REPORTS_DIR
    os.makedirs(reports_dir, exist_ok=True)

    html_doc = generate_html(scan_result, pre_bars=pre_bars, post_bars=post_bars)

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    stamped_path = os.path.join(reports_dir, f"bounce_report_{timestamp}.html")
    latest_path = os.path.join(reports_dir, "latest_bounce.html")

    for path in (stamped_path, latest_path):
        with open(path, "w", encoding="utf-8") as f:
            f.write(html_doc)

    cleanup.prune_old_reports(reports_dir, "bounce_report_*.html", keep=config.REPORT_RETENTION)

    return latest_path
