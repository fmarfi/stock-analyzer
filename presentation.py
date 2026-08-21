"""Framework-agnostic badge/color/label helpers.

Both dashboard.py (Dash components) and reporting/html_report.py (raw HTML
strings) call into this module for color decisions and badge text so the
live dashboard and the static report can never visually drift apart. Nothing
here imports Dash or knows about HTML tags -- it hands back plain data
(colors, strings, tuples) that each renderer turns into its own markup.

Badge/label building loops indicators.REGISTRY rather than hardcoding
trend/momentum/volume, so a 4th registered indicator automatically gets a
badge everywhere this module is used, with no further edits required (the
Phase 3 extensibility goal).
"""

import math

from stock_analyzer import config, indicators


def is_aligned(confluence: int, align_threshold: int) -> bool:
    """True if every registered indicator voted the same direction."""
    return abs(confluence) == align_threshold


def confluence_color(confluence: int, align_threshold: int) -> str:
    """Blue when fully aligned (bull or bear), gray otherwise -- matches the
    scoreboard's existing convention that alignment (not just sign) is what's
    visually called out on the summary badge.
    """
    return config.BLUE if is_aligned(confluence, align_threshold) else config.GRAY


def signal_color(vote: int) -> str:
    """Green for a bullish (+1) vote, red for a bearish (-1) vote."""
    return config.GREEN if vote == 1 else config.RED


def edge_color(edge_value) -> str:
    """Green if the edge is positive, red if negative, gray if undefined
    (empty subset -> NaN).
    """
    if edge_value is None or (isinstance(edge_value, float) and math.isnan(edge_value)):
        return config.GRAY
    return config.GREEN if edge_value > 0 else config.RED


def indicator_badges(votes: dict) -> list:
    """Build (text, color) badge tuples for every registered indicator, in
    registry order, from a votes dict like {"trend": 1, "momentum": -1, ...}.
    Looping REGISTRY (rather than hand-listing trend/momentum/volume) is
    what lets the badge row grow automatically when a new indicator is
    registered.
    """
    badges = []
    for ind in indicators.REGISTRY:
        vote = votes.get(ind.name)
        if vote is None:
            continue
        short = ind.label[:1].upper()
        text = f"{short} {'UP' if vote == 1 else 'DN'}"
        badges.append((text, signal_color(vote)))
    return badges


def confluence_badge_text(confluence: int) -> str:
    return f"{confluence:+d}"


def edge_text(label: str, edge_value, n: int) -> str:
    """'{label}: +2.3 pp (n=14)' or '{label}: n/a (n=0)' -- shared string
    format so dashboard cards and report cards read identically.
    """
    if edge_value is None or (isinstance(edge_value, float) and math.isnan(edge_value)) or n == 0:
        return f"{label}: n/a (n=0)"
    return f"{label}: {edge_value:+.1f} pp (n={n})"


def hit_rate_text(overall_hit_rate, n_overall: int, rsi) -> str:
    """'RSI 62  |  hit 57% (n=210)' summary line."""
    rsi_part = f"RSI {rsi:.0f}" if rsi is not None and not (isinstance(rsi, float) and math.isnan(rsi)) else "RSI n/a"
    if overall_hit_rate is None or (isinstance(overall_hit_rate, float) and math.isnan(overall_hit_rate)):
        hit_part = "hit n/a"
    else:
        hit_part = f"hit {overall_hit_rate * 100:.0f}% (n={n_overall})"
    return f"{rsi_part}  |  {hit_part}"
