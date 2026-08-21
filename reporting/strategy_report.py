"""Static HTML report: which strategy (Confluence / Squeeze / Bounce) had
the best historical hit rate per ticker, grouped by sector (see
strategy_compare.run_strategy_comparison()).

Reuses html_report.py's CSS/badge helpers so this reads as part of the same
report family as the scan/squeeze/bounce reports instead of a one-off design.
"""

import html as html_escape
import datetime
import logging
import os

from stock_analyzer import config
from stock_analyzer.reporting import cleanup
from stock_analyzer.reporting.html_report import _CSS, _badge_html

logger = logging.getLogger(__name__)

_EXTRA_CSS = """
.sector-heading { margin: 26px 0 6px 0; font-size: 18px; }
.sector-summary { font-size: 12px; color: %(muted)s; margin-bottom: 14px; }
.strategy-table { border-collapse: collapse; margin-bottom: 20px; width: 100%%; max-width: 720px; }
.strategy-table th, .strategy-table td {
    text-align: left; padding: 6px 12px; font-size: 13px; border-bottom: 1px solid %(border)s;
}
.strategy-table th { color: %(muted)s; font-weight: normal; }
.strategy-row-best { background-color: rgba(66, 165, 245, 0.12); }
.no-tickers { color: %(muted)s; font-size: 13px; margin-bottom: 18px; }
""" % {"muted": config.MUTED_TEXT, "border": config.BORDER_COLOR}

_STRATEGY_LABELS = {
    "confluence": "Confluence", "squeeze": "Squeeze", "bounce": "Bounce",
    "combined": "Combined (Squeeze+Bounce)",
}
_STRATEGY_ORDER = ("confluence", "squeeze", "bounce", "combined")


def _strategy_cell(name: str, stat: dict, is_best: bool, min_events: int) -> str:
    if stat["hit_rate"] is None or stat["n"] < min_events:
        rate_text = f"insufficient data (n={stat['n']} &lt; {min_events})"
        color = config.MUTED_TEXT
    else:
        ci_text = (
            f", 95% CI {stat['ci_low'] * 100:.0f}-{stat['ci_high'] * 100:.0f}%"
            if stat["ci_low"] is not None else ""
        )
        rate_text = f"{stat['hit_rate'] * 100:.0f}% (n={stat['n']}{ci_text})"
        color = config.GREEN if is_best else config.MUTED_TEXT
    best_badge = _badge_html("BEST", config.BLUE) if is_best else ""
    return f'<td style="color:{color};">{rate_text} {best_badge}</td>'


def _ticker_row_html(entry: dict, min_events: int) -> str:
    best = entry["best_strategy"]
    row_class = "strategy-row-best" if best else ""
    cells = "".join(
        _strategy_cell(name, entry["strategies"][name], name == best, min_events)
        for name in _STRATEGY_ORDER
    )
    return f"""
    <tr class="{row_class}">
      <td><b>{html_escape.escape(entry['ticker'])}</b></td>
      <td>{entry['close']:.2f}</td>
      {cells}
    </tr>
    """


def _sector_summary_html(entries: list) -> str:
    counts = {name: 0 for name in _STRATEGY_LABELS}
    for entry in entries:
        if entry["best_strategy"]:
            counts[entry["best_strategy"]] += 1
    parts = [f"{_STRATEGY_LABELS[name]}: {count}" for name, count in counts.items() if count]
    if not parts:
        return "No ticker in this sector had a strategy that was both statistically significant and beat 50%."
    return "Best-strategy wins in this sector -- " + " &middot; ".join(parts)


def _sector_html(sector: str, entries: list, min_events: int) -> str:
    heading = f'<h3 class="sector-heading">{html_escape.escape(sector)} &middot; {len(entries)} ticker(s)</h3>'
    summary = f'<div class="sector-summary">{_sector_summary_html(entries)}</div>'
    rows = "".join(_ticker_row_html(entry, min_events) for entry in entries)
    table = f"""
    <table class="strategy-table">
      <tr><th>Ticker</th><th>Close</th><th>Confluence</th><th>Squeeze</th><th>Bounce</th><th>Combined</th></tr>
      {rows}
    </table>
    """
    return heading + summary + table


def _run_meta_html(scan_result: dict) -> str:
    params = scan_result["params"]
    n_ok = len(scan_result["tickers"])
    n_fail = len(scan_result["failures"])
    n_sectors = len(scan_result["sectors"])

    failures_html = ""
    if scan_result["failures"]:
        items = "".join(
            f'<li>{html_escape.escape(f["ticker"])}: {html_escape.escape(f["error"])}</li>'
            for f in scan_result["failures"]
        )
        failures_html = f'<div class="failures"><b>{n_fail} ticker(s) failed:</b><ul>{items}</ul></div>'

    return f"""
    <h1>Best Strategy by Sector</h1>
    <h2>{html_escape.escape(scan_result['run_timestamp'])}</h2>
    <div class="run-meta">
      <b>Tickers scanned:</b> {n_ok + n_fail} ({n_ok} ok, {n_fail} failed) across {n_sectors} sector(s)<br>
      <b>Minimum events to be eligible:</b> {scan_result['min_events']} &middot;
      <b>Squeeze percentile:</b> {scan_result['bw_percentile']:.0f} &middot;
      <b>Bounce confirm bars:</b> {scan_result['confirm_bars']}<br>
      <b>MA short/long:</b> {params['ma_short']} / {params['ma_long']} &middot;
      <b>Outcome horizon:</b> {params['horizon']} bars forward<br>
      <b>Significance test:</b> {scan_result['total_tests']} strategy/ticker comparisons run this scan &rarr;
      Bonferroni-corrected threshold p &lt; {scan_result['alpha_corrected']:.2e} (from an uncorrected 0.05).
      "BEST" requires clearing this AND hit_rate &gt; 50% -- a ticker with no strategy clearing the bar
      shows no BEST tag rather than a forced pick.<br>
      <b>Caveat:</b> every number here is in-sample (the history used to find an event is the same
      history used to score it) -- a statistically significant edge here is "worth testing out-of-sample",
      not a validated trading signal. This is not financial advice.
    </div>
    {failures_html}
    """


def generate_html(scan_result: dict) -> str:
    """Build the full self-contained HTML document string for a strategy
    comparison scan (the dict returned by strategy_compare.run_strategy_comparison())."""
    sections = "".join(
        _sector_html(sector, entries, scan_result["min_events"])
        for sector, entries in sorted(scan_result["sectors"].items())
    )
    if not sections:
        sections = '<div class="no-tickers">No tickers succeeded in this scan.</div>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Best Strategy by Sector</title>
<style>{_CSS}{_EXTRA_CSS}</style>
</head>
<body>
{_run_meta_html(scan_result)}
{sections}
</body>
</html>
"""


def write_reports(scan_result: dict, reports_dir: str = None) -> str:
    """Write both a timestamped file and overwrite latest_strategy.html.
    Returns the latest_strategy.html path.
    """
    reports_dir = reports_dir or config.REPORTS_DIR
    os.makedirs(reports_dir, exist_ok=True)

    html_doc = generate_html(scan_result)

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    stamped_path = os.path.join(reports_dir, f"strategy_report_{timestamp}.html")
    latest_path = os.path.join(reports_dir, "latest_strategy.html")

    for path in (stamped_path, latest_path):
        with open(path, "w", encoding="utf-8") as f:
            f.write(html_doc)

    cleanup.prune_old_reports(reports_dir, "strategy_report_*.html", keep=config.REPORT_RETENTION)

    return latest_path
