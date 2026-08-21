"""Static HTML report: one self-contained dark-themed file per scan.

Header shows run params (MA periods, horizon, threshold, indicator set,
universe) pulled straight from the engine.run_scan() result, so the report
is self-documenting. Body is a wrapping grid of mini-cards -- badges built
generically from indicators.REGISTRY (via presentation.py, so this can never
visually drift from dashboard.py's cards), confluence score, RSI, overall
hit rate, bull/bear edge with n=. Optional per-ticker chart is gated behind
`include_charts` (CLI: --no-charts flips this off) and reuses
dashboard_shared.build_chart_fig() so the charts show the exact same bands/
MAs the live dashboard would.

Each ticker's chart is written as its own standalone HTML file under
charts/<ticker>.html (a static report has no server, so "open in a new
window" means a real second file, not a route) and the card just links to
it with target="_blank" -- a dedicated page for the chart alone, not an
inline expand sharing space with the card's stats.
"""

import datetime
import html as html_escape
import logging
import os

from stock_analyzer import config, indicators, presentation
from stock_analyzer.reporting import cleanup, csv_report

logger = logging.getLogger(__name__)

_CSS = """
:root { color-scheme: dark; }
* { box-sizing: border-box; }
body {
    margin: 0; padding: 24px; background-color: %(page_bg)s; color: white;
    font-family: Arial, Helvetica, sans-serif;
}
h1 { font-size: 22px; margin: 0 0 4px 0; }
h2 { font-size: 16px; margin: 0 0 16px 0; color: %(muted)s; font-weight: normal; }
.run-meta {
    background-color: %(card_bg)s; border-radius: 10px; padding: 14px 18px;
    margin-bottom: 22px; font-size: 13px; color: %(muted)s; line-height: 1.6;
}
.run-meta b { color: white; }
.failures {
    background-color: #3a2020; border-radius: 8px; padding: 10px 16px;
    margin-bottom: 18px; font-size: 13px; color: %(red)s;
}
.grid { display: flex; flex-wrap: wrap; gap: 14px; }
.card {
    background-color: %(card_bg)s; padding: 14px; border-radius: 10px;
    color: white; width: 220px; box-shadow: 0 2px 8px rgba(0,0,0,0.4);
}
.card-head { display: flex; justify-content: space-between; align-items: center; }
.card-head h4 { margin: 0; font-size: 16px; }
.badges { display: flex; gap: 6px; margin: 8px 0; flex-wrap: wrap; }
.badge {
    color: white; padding: 2px 10px; border-radius: 10px;
    font-weight: bold; font-size: 12px; display: inline-block;
}
.summary-line { font-size: 12px; color: %(muted)s; margin-bottom: 4px; }
.edge-lines { display: flex; flex-direction: column; gap: 2px; margin-bottom: 6px; }
.edge-line { font-size: 12px; font-weight: bold; }
.view-chart-btn {
    display: block; text-align: center; margin-top: 8px; padding: 6px 12px;
    background-color: %(blue)s; color: white; border-radius: 6px;
    font-size: 12px; font-weight: bold; text-decoration: none;
}
""" % {
    "page_bg": config.PAGE_BG, "card_bg": config.CARD_BG, "muted": config.MUTED_TEXT,
    "red": config.RED, "blue": config.BLUE,
}


def _badge_html(text, color):
    return f'<span class="badge" style="background-color:{color};">{html_escape.escape(text)}</span>'


def _card_html(result: dict, align_threshold: int, chart_paths: dict) -> str:
    ticker = result["ticker"]
    confluence = result["confluence"]
    stats = result["stats"]

    badges_html = "".join(
        _badge_html(text, color) for text, color in presentation.indicator_badges(result["votes"])
    )
    confluence_badge = _badge_html(
        presentation.confluence_badge_text(confluence),
        presentation.confluence_color(confluence, align_threshold),
    )
    summary_line = presentation.hit_rate_text(stats.overall_hit_rate, stats.n_overall, result["rsi"])
    bull_line = presentation.edge_text("bull edge", stats.bull_edge, stats.n_bull)
    bear_line = presentation.edge_text("bear edge", stats.bear_edge, stats.n_bear)
    bull_color = presentation.edge_color(stats.bull_edge)
    bear_color = presentation.edge_color(stats.bear_edge)

    chart_html = ""
    chart_rel_path = chart_paths.get(ticker)
    if chart_rel_path:
        chart_html = (
            f'<a class="view-chart-btn" href="{chart_rel_path}" target="_blank" rel="noopener">'
            "View Chart</a>"
        )

    return f"""
    <div class="card">
      <div class="card-head">
        <h4>{html_escape.escape(ticker)}</h4>
        {confluence_badge}
      </div>
      <div class="badges">{badges_html}</div>
      <div class="summary-line">{html_escape.escape(summary_line)}</div>
      <div class="edge-lines">
        <span class="edge-line" style="color:{bull_color};">{html_escape.escape(bull_line)}</span>
        <span class="edge-line" style="color:{bear_color};">{html_escape.escape(bear_line)}</span>
      </div>
      {chart_html}
    </div>
    """


def _write_ticker_charts(scan_result: dict, reports_dir: str, include_charts: bool) -> dict:
    """Write one standalone chart HTML file per successful ticker under
    reports_dir/charts/<ticker>.html (reusing dashboard_shared.build_chart_fig()
    so it matches the live dashboard exactly), and return {ticker: relative_path}
    for whichever ones succeeded -- "View Chart" links to these instead of
    embedding the chart in the report itself, so it opens as its own page.
    Imported lazily (and guarded) so a report can still be generated in an
    environment where Dash isn't installed, just without chart links.
    """
    if not include_charts:
        return {}

    try:
        from stock_analyzer.dashboard_shared import build_chart_fig, CHART_POST_SCRIPTS, CHART_CONFIG, default_indicator_instances
    except Exception:
        logger.warning("Could not import chart builder (dash not installed?) - skipping charts")
        return {}

    charts_dir = os.path.join(reports_dir, "charts")
    os.makedirs(charts_dir, exist_ok=True)

    params = scan_result["params"]
    instances = default_indicator_instances(params)
    chart_paths = {}
    for result in scan_result["results"]:
        ticker = result["ticker"]
        try:
            fig = build_chart_fig(result["df"], ticker, instances)
            fig.write_html(
                os.path.join(charts_dir, f"{ticker}.html"),
                include_plotlyjs="cdn", config=CHART_CONFIG, post_script=CHART_POST_SCRIPTS,
            )
            chart_paths[ticker] = f"charts/{ticker}.html"
        except Exception:
            logger.exception("Failed building chart file for %s", ticker)

    return chart_paths


def _run_meta_html(scan_result: dict) -> str:
    params = scan_result["params"]
    indicator_set = [ind.label for ind in indicators.REGISTRY]
    n_ok = len(scan_result["results"])
    n_fail = len(scan_result["failures"])

    failures_html = ""
    if scan_result["failures"]:
        items = "".join(
            f'<li>{html_escape.escape(f["ticker"])}: {html_escape.escape(f["error"])}</li>'
            for f in scan_result["failures"]
        )
        failures_html = f'<div class="failures"><b>{n_fail} ticker(s) failed:</b><ul>{items}</ul></div>'

    return f"""
    <h1>Stock Analyzer Scan Report</h1>
    <h2>run #{scan_result['run_id']} &middot; {html_escape.escape(scan_result['run_timestamp'])}</h2>
    <div class="run-meta">
      <b>Universe:</b> {html_escape.escape(scan_result.get('universe_label') or 'n/a')} &middot;
      <b>Tickers scanned:</b> {n_ok + n_fail} ({n_ok} ok, {n_fail} failed)<br>
      <b>MA short/long:</b> {params['ma_short']} / {params['ma_long']} &middot;
      <b>RSI period:</b> {params['rsi_period']} &middot;
      <b>Horizon:</b> {params['horizon']} bars &middot;
      <b>Align threshold:</b> {params['align_threshold']}<br>
      <b>Indicator set:</b> {html_escape.escape(', '.join(indicator_set))}
    </div>
    {failures_html}
    """


def generate_html(scan_result: dict, chart_paths: dict) -> str:
    """Build the full self-contained HTML document string for a scan.
    `chart_paths` is the {ticker: relative_path} dict from
    _write_ticker_charts() -- pass {} for a report with no chart links.
    """
    params = scan_result["params"]
    align_threshold = params["align_threshold"]
    cards_html = "".join(
        _card_html(r, align_threshold, chart_paths) for r in scan_result["results"]
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Stock Analyzer Scan Report</title>
<style>{_CSS}</style>
</head>
<body>
{_run_meta_html(scan_result)}
<div class="grid">
{cards_html}
</div>
</body>
</html>
"""


def write_html_report(scan_result: dict, path: str, chart_paths: dict) -> str:
    html_doc = generate_html(scan_result, chart_paths)
    with open(path, "w", encoding="utf-8") as f:
        f.write(html_doc)
    return path


def write_reports(scan_result: dict, reports_dir: str = None, include_charts: bool = True):
    """Write both the timestamped HTML+CSV files and overwrite latest.html /
    latest.csv, plus one chart file per ticker under charts/ that "View
    Chart" links open in a new tab. Returns (latest_html_path, latest_csv_path).
    """
    reports_dir = reports_dir or config.REPORTS_DIR
    os.makedirs(reports_dir, exist_ok=True)

    chart_paths = _write_ticker_charts(scan_result, reports_dir, include_charts)

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    stamped_html = os.path.join(reports_dir, f"scan_report_{timestamp}.html")
    stamped_csv = os.path.join(reports_dir, f"scan_report_{timestamp}.csv")
    latest_html = os.path.join(reports_dir, "latest.html")
    latest_csv = os.path.join(reports_dir, "latest.csv")

    write_html_report(scan_result, stamped_html, chart_paths)
    write_html_report(scan_result, latest_html, chart_paths)

    csv_report.write_csv_report(scan_result, stamped_csv)
    csv_report.write_csv_report(scan_result, latest_csv)

    cleanup.prune_old_reports(reports_dir, "scan_report_*.html", keep=config.REPORT_RETENTION)
    cleanup.prune_old_reports(reports_dir, "scan_report_*.csv", keep=config.REPORT_RETENTION)

    return latest_html, latest_csv
