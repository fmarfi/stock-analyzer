"""Shared helpers for the multi-page dashboard app: chart building, ticker
lists, and small UI building blocks used by more than one page.

Split out of dashboard.py so page modules (stock_analyzer/pages/*.py) can
import what they need without importing the Dash `app` instance itself --
Dash's page system wants page modules to be import-safe on their own
(app.py imports pages, not the other way around).
"""

import logging
import os

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from dash import dcc, html

from stock_analyzer import config, indicators, presentation, universe

logger = logging.getLogger(__name__)


def configure_logging() -> None:
    """Mirror run_scan.py's terminal logging so `python dashboard.py` prints
    what the running dashboard is doing (scans, chart views, report
    generation) instead of going silent between Dash's own request logs.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


# ---------------------------------------------------------------------------
# Ticker lists shared across pages
# ---------------------------------------------------------------------------
BIST_YILDIZ_TICKERS = universe.get_watchlist("bist_yildiz")
# Non-BIST tickers added straight to the dropdowns (not into the bist_yildiz
# watchlist itself, which should stay actual BIST names only).
EXTRA_DROPDOWN_TICKERS = ["XRP-USD"]
# What every dropdown in the app offers (scoreboard, squeeze, bounce,
# triangle, snapshot, home, strategy) -- BIST-only plus EXTRA_DROPDOWN_TICKERS,
# no NASDAQ/US names in any of them.
DROPDOWN_TICKERS = BIST_YILDIZ_TICKERS + EXTRA_DROPDOWN_TICKERS

SNAPSHOTS_DIR = os.path.join(config.REPORTS_DIR, "snapshots")


# ---------------------------------------------------------------------------
# Chart building -- reused as-is by reporting/html_report.py's optional
# embedded per-ticker charts, so bands/MAs never drift between the two.
# ---------------------------------------------------------------------------
# Every addable indicator, in one flat list -- the "+ Add Indicator" menu
# (dashboard.py's settings form) offers exactly these, each instance
# carrying its own params/colors instead of one hardcoded slot per type.
# EMA/SMA/BB draw on the price row itself; everything else gets its own row,
# shared by every instance of that type (so a second RSI overlays the first
# in the same panel, the way a second EMA overlays the first on price --
# not a second stacked panel).
OVERLAY_TYPES = {"EMA", "SMA", "BB"}
PANEL_TYPE_ORDER = ["Volume", "RSI", "MACD", "Stochastic", "DI", "Bandwidth"]
INDICATOR_TYPES = ["EMA", "SMA", "BB", "Volume", "RSI", "MACD", "Stochastic", "DI", "Bandwidth"]
INDICATOR_LABELS = {
    "EMA": "EMA", "SMA": "SMA", "BB": "Bollinger Bands", "Volume": "Volume",
    "RSI": "RSI", "MACD": "MACD", "Stochastic": "Stochastic", "DI": "DI+/-  /  ADX",
    "Bandwidth": "Bollinger Bandwidth",
}
_PANEL_WEIGHT = {"Volume": 1.0, "RSI": 1.15, "MACD": 1.15, "Stochastic": 1.15, "DI": 1.15, "Bandwidth": 1.2}
_PRICE_WEIGHT = 3.2


def default_indicator_instances(params: dict) -> list:
    """The "classic" full chart, expressed as an indicator_instances list --
    for callers that just want the normal default view (squeeze/bounce
    report snapshots, the Snapshots page, embedded scan-report charts)
    without building their own list by hand. `params` is whatever dict
    those callers already have (engine.resolve_params()-shaped); every
    lookup falls back to config.py's default if the key isn't set.
    """
    return [
        {"type": "EMA", "period": params.get("ma_short", config.MA_SHORT), "color": DEFAULT_COLORS["ema_short"]},
        {"type": "EMA", "period": params.get("ma_long", config.MA_LONG), "color": DEFAULT_COLORS["ema_long"]},
        {"type": "BB", "period": params.get("bb_period", config.BB_PERIOD),
         "stddev": params.get("bb_stddev", config.BB_STDDEV), "color": DEFAULT_COLORS["bb"]},
        {"type": "Volume"},
        {"type": "RSI", "period": params.get("rsi_period", config.RSI_PERIOD), "color": DEFAULT_COLORS["rsi"]},
        {"type": "MACD", "fast": params.get("macd_fast", config.MACD_FAST),
         "slow": params.get("macd_slow", config.MACD_SLOW), "signal": params.get("macd_signal", config.MACD_SIGNAL),
         "color1": DEFAULT_COLORS["macd"], "color2": DEFAULT_COLORS["macd_signal"]},
        {"type": "Stochastic", "mode": params.get("stoch_mode", config.STOCH_MODE),
         "k_period": params.get("stoch_k_period", config.STOCH_K_PERIOD),
         "d_period": params.get("stoch_d_period", config.STOCH_D_PERIOD),
         "smoothing": params.get("stoch_slowing", config.STOCH_SLOWING),
         "color1": DEFAULT_COLORS["stoch_k"], "color2": DEFAULT_COLORS["stoch_d"]},
        {"type": "DI", "period": params.get("di_period", config.DI_PERIOD),
         "color1": DEFAULT_COLORS["di_plus"], "color2": DEFAULT_COLORS["di_minus"]},
        {"type": "Bandwidth", "period": params.get("bb_period", config.BB_PERIOD),
         "stddev": params.get("bb_stddev", config.BB_STDDEV), "color": DEFAULT_COLORS["bandwidth"]},
    ]


# Per-indicator-type default line colors -- only used to seed a brand-new
# row's color picker (see dashboard.py's "+ Add Indicator" menu) and by
# default_indicator_instances() above; once a row exists, its own color
# field is what build_chart_fig actually reads; nothing here is read at
# render time for a caller who already supplied full instances.
DEFAULT_COLORS = {
    "ema_short": "#42a5f5", "ema_long": "#ffca28", "bb": "#9575cd", "bandwidth": "#b39ddb",
    "rsi": "#ffa726", "macd": "#42a5f5", "macd_signal": "#ffca28",
    "stoch_k": "#42a5f5", "stoch_d": "#ffca28",
    "di_plus": config.GREEN, "di_minus": config.RED,
}


# ---------------------------------------------------------------------------
# Standalone indicator math -- deliberately separate from indicators.py's
# prepare_dataframe() (which computes one canonical RSI/MACD/Stochastic/DI
# per ticker for confluence scoring/backtesting) since an indicator_instances
# list can hold *any number* of each, each with its own periods -- these are
# chart-display-only and never touch confluence/votes_json/backtest.
# ---------------------------------------------------------------------------
def _compute_rsi(close, period):
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _compute_macd(close, fast, slow, signal):
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd = ema_fast - ema_slow
    macd_signal = macd.ewm(span=signal, adjust=False).mean()
    return macd, macd_signal, macd - macd_signal


def _compute_stochastic(high, low, close, mode, k_period, d_period, smoothing):
    lowest_low = low.rolling(k_period).min()
    highest_high = high.rolling(k_period).max()
    stoch_range = (highest_high - lowest_low).replace(0, np.nan)
    raw_k = 100 * (close - lowest_low) / stoch_range
    if mode == "fast":
        k = raw_k
    elif mode == "full":
        k = raw_k.rolling(smoothing).mean()
    else:
        k = raw_k.rolling(3).mean()
    d = k.rolling(d_period).mean()
    return k, d


def _compute_di_adx(high, low, close, period):
    prev_high, prev_low, prev_close = high.shift(1), low.shift(1), close.shift(1)
    up_move = high - prev_high
    down_move = prev_low - low
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    true_range = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1,
    ).max(axis=1)
    atr = true_range.ewm(alpha=1 / period, adjust=False).mean()
    plus_dm_smoothed = pd.Series(plus_dm, index=close.index).ewm(alpha=1 / period, adjust=False).mean()
    minus_dm_smoothed = pd.Series(minus_dm, index=close.index).ewm(alpha=1 / period, adjust=False).mean()
    atr_safe = atr.replace(0, np.nan)
    di_plus = 100 * plus_dm_smoothed / atr_safe
    di_minus = 100 * minus_dm_smoothed / atr_safe
    di_sum = (di_plus + di_minus).replace(0, np.nan)
    dx = 100 * (di_plus - di_minus).abs() / di_sum
    adx = dx.ewm(alpha=1 / period, adjust=False).mean()
    return di_plus, di_minus, adx


def _compute_bollinger(close, period, num_std):
    middle = close.rolling(period).mean()
    std = close.rolling(period).std()
    upper = middle + num_std * std
    lower = middle - num_std * std
    width = (upper - lower) / middle
    return upper, middle, lower, width


def _holiday_gap_values(index) -> list:
    """Weekdays within `index`'s span that have no bar at all -- exchange
    holidays, not weekends (the weekend rangebreak already handles those
    separately). Derived from the data itself rather than a hardcoded BIST
    holiday calendar: any Mon-Fri date between the first and last bar with
    zero rows is treated as a holiday, so this tracks whatever's actually
    missing in the cached series (including future additions/corrections)
    without needing yearly maintenance. Returned as a plain list of
    tz-naive midnight Timestamps, the shape Plotly's rangebreaks `values`
    wants.
    """
    if len(index) == 0:
        return []
    naive = index.tz_localize(None) if getattr(index, "tz", None) is not None else index
    observed_dates = set(pd.DatetimeIndex(naive).normalize().unique())
    full_bdays = pd.bdate_range(min(observed_dates), max(observed_dates))
    return [d for d in full_bdays if d not in observed_dates]


def build_chart_fig(df, ticker, indicator_instances=None, recent_window_bars=126,
                     timeframe="daily", chart_type="candle"):
    """Build the OHLC chart figure for one ticker: price row 1 always, plus
    whatever indicator_instances asks for. `df` must have Open/High/Low/
    Close/Volume; every indicator is computed fresh here (see _compute_*
    above) from whatever periods each instance specifies -- there's no
    hardcoded "the RSI column" the way indicators.py's confluence pipeline
    has one, so any number of instances of any type is fine.

    indicator_instances: list of {"type": ..., ...type-specific params...,
    ...color(s)...} -- see default_indicator_instances() for the exact
    per-type shape, or None for that same classic default set. EMA/SMA/BB
    (OVERLAY_TYPES) draw on the price row; everything else gets its own row,
    shared by every instance of that type (a second RSI overlays the first
    in the same panel, the way a second EMA overlays the first on price --
    not a second stacked panel). A row only exists if at least one instance
    of that type is present.

    timeframe="daily" (the default, matching every caller except the
    Daily/Weekly/Hourly chart window) hides Sat/Sun on the x-axis so
    non-trading weekends don't show up as a gap between Friday and Monday.
    "hourly" hides the same weekend gap plus the overnight gap between each
    day's trading session. Both skipped for weekly bars: pandas labels a
    resampled week on its ending Sunday, which would fall inside that same
    hidden range and make the bar vanish.

    chart_type="candle" draws Open/High/Low/Close as OHLC tick bars, same as
    always. chart_type="heikin_ashi" expects `df`'s O/H/L/C to already be
    Heikin Ashi values (see timeframe.compute_heikin_ashi) and draws them as
    filled candlesticks instead -- that's the standard way to read Heikin
    Ashi (a run of same-colored filled bodies is the whole point), whereas
    plain OHLC tick bars would bury it.
    """
    instances = indicator_instances if indicator_instances is not None else default_indicator_instances({})

    overlay_instances = [i for i in instances if i["type"] in OVERLAY_TYPES]
    panel_groups = {t: [i for i in instances if i["type"] == t] for t in PANEL_TYPE_ORDER}
    panel_types = [t for t in PANEL_TYPE_ORDER if panel_groups[t]]
    row_of = {t: i + 2 for i, t in enumerate(panel_types)}  # price is row 1

    price_title = f"{ticker} price" + (" (Heikin Ashi)" if chart_type == "heikin_ashi" else "")
    rows = 1 + len(panel_types)
    weights = [_PRICE_WEIGHT] + [_PANEL_WEIGHT[t] for t in panel_types]
    row_heights = [w / sum(weights) for w in weights]
    subplot_titles = [price_title] + [INDICATOR_LABELS[t] for t in panel_types]

    fig = make_subplots(
        rows=rows, cols=1, shared_xaxes=True, row_heights=row_heights, vertical_spacing=0.03,
        subplot_titles=subplot_titles,
    )

    if chart_type == "heikin_ashi":
        price_trace = go.Candlestick(
            x=df.index, open=df["Open"], high=df["High"], low=df["Low"], close=df["Close"],
            name=ticker, increasing_line_color=config.GREEN, decreasing_line_color=config.RED,
        )
    else:
        price_trace = go.Ohlc(
            x=df.index, open=df["Open"], high=df["High"],
            low=df["Low"], close=df["Close"], name=ticker,
        )
    fig.add_trace(price_trace, row=1, col=1)

    # Overlays (EMA/SMA/BB): open-ended, each instance its own type+params+
    # color -- no limit on how many stack (EMA9 + EMA21 + BB(20,2) +
    # BB(50,3) all at once, etc.), each independently addable/removable/
    # updatable via the "+ Add Indicator" menu. `overlay_range_series`
    # collects everything drawn here so the price y-range below can account
    # for a long/wide overlay instead of clipping it.
    #
    # Every line trace in this function uses go.Scatter, not go.Scattergl --
    # go.Scattergl was tried once for the large-dataset render-speed win,
    # but it needs a real WebGL context, and every single Scattergl trace
    # silently failed to draw (present in gd.data, invisible on screen,
    # zero console errors) the moment WebGL wasn't available/working, which
    # is exactly what "my indicators disappeared" turned out to be. Data
    # correctness beats the render speed here, so this stays plain SVG.
    overlay_range_series = []
    for inst in overlay_instances:
        t, color = inst["type"], inst["color"]
        if t == "EMA":
            series = df["Close"].ewm(span=inst["period"], adjust=False).mean()
            fig.add_trace(go.Scatter(x=df.index, y=series, name=f'EMA{inst["period"]}',
                                      line=dict(width=1, color=color)), row=1, col=1)
            overlay_range_series.append(series)
        elif t == "SMA":
            series = df["Close"].rolling(inst["period"]).mean()
            fig.add_trace(go.Scatter(x=df.index, y=series, name=f'SMA{inst["period"]}',
                                      line=dict(width=1, color=color)), row=1, col=1)
            overlay_range_series.append(series)
        elif t == "BB":
            upper, middle, lower, _ = _compute_bollinger(df["Close"], inst["period"], inst["stddev"])
            label = f'BB({inst["period"]},{inst["stddev"]})'
            fig.add_trace(go.Scatter(x=df.index, y=upper, name=f"{label} Upper",
                                      line=dict(width=1, dash="dot", color=color)), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=lower, name=f"{label} Lower",
                                      line=dict(width=1, dash="dot", color=color)), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=middle, name=f"{label} Middle",
                                      line=dict(width=2, color=color)), row=1, col=1)
            overlay_range_series.append(upper)
            overlay_range_series.append(lower)

    if "Volume" in row_of:
        r = row_of["Volume"]
        volume_colors = [config.GREEN if c >= o else config.RED for o, c in zip(df["Open"], df["Close"])]
        fig.add_trace(go.Bar(x=df.index, y=df["Volume"], name="Volume", marker_color=volume_colors), row=r, col=1)

    if "RSI" in row_of:
        r = row_of["RSI"]
        for inst in panel_groups["RSI"]:
            series = _compute_rsi(df["Close"], inst["period"])
            fig.add_trace(go.Scatter(x=df.index, y=series, name=f'RSI({inst["period"]})',
                                      line=dict(color=inst["color"])), row=r, col=1)
        fig.add_hline(y=70, line_dash="dot", line_color="red", row=r, col=1)
        fig.add_hline(y=30, line_dash="dot", line_color="green", row=r, col=1)
        fig.update_yaxes(range=[0, 100], row=r, col=1)

    # MACD: histogram (MACD - signal) plus the two lines it's the difference
    # of. Registered as a confluence vote (indicators.macd_cross_signal), so
    # this panel is what that vote actually looks like day to day.
    macd_range_series = []
    if "MACD" in row_of:
        r = row_of["MACD"]
        for inst in panel_groups["MACD"]:
            macd, macd_signal, macd_hist = _compute_macd(df["Close"], inst["fast"], inst["slow"], inst["signal"])
            label = f'MACD({inst["fast"]},{inst["slow"]},{inst["signal"]})'
            hist_colors = [config.GREEN if v >= 0 else config.RED for v in macd_hist]
            fig.add_trace(go.Bar(x=df.index, y=macd_hist, name=f"{label} Hist", marker_color=hist_colors), row=r, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=macd, name=label, line=dict(color=inst["color1"], width=1.5)), row=r, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=macd_signal, name=f"{label} Signal", line=dict(color=inst["color2"], width=1.5)), row=r, col=1)
            macd_range_series.extend([macd, macd_signal, macd_hist])
        fig.add_hline(y=0, line_dash="dot", line_color=config.MUTED_TEXT, row=r, col=1)

    # Stochastic %K/%D. Registered as a confluence vote (indicators.
    # stochastic_signal), so this panel is what that vote actually looks
    # like day to day.
    if "Stochastic" in row_of:
        r = row_of["Stochastic"]
        for inst in panel_groups["Stochastic"]:
            k, d = _compute_stochastic(df["High"], df["Low"], df["Close"],
                                        inst["mode"], inst["k_period"], inst["d_period"], inst["smoothing"])
            label = f'({inst["mode"]},{inst["k_period"]},{inst["d_period"]})'
            fig.add_trace(go.Scatter(x=df.index, y=k, name=f"%K{label}", line=dict(color=inst["color1"], width=1.5)), row=r, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=d, name=f"%D{label}", line=dict(color=inst["color2"], width=1.5)), row=r, col=1)
        fig.add_hline(y=80, line_dash="dot", line_color="red", row=r, col=1)
        fig.add_hline(y=20, line_dash="dot", line_color="green", row=r, col=1)
        fig.update_yaxes(range=[0, 100], row=r, col=1)

    # +DI/-DI/ADX (Wilder's Directional Movement Index). Registered as a
    # confluence vote (indicators.di_signal: +1 when +DI > -DI), so this
    # panel is what that vote actually looks like day to day. ADX (trend
    # strength, not direction) rides along dashed on the same scale for
    # context rather than getting its own panel. Fixed 0-100, same as RSI/
    # Stochastic -- +DI/-DI/ADX read on a conventional 0-100 scale on every
    # platform that plots them, not a range auto-zoomed to wherever this
    # window's values happen to sit; 25 is the standard "trend strength"
    # reference threshold for ADX (below it, a trend isn't established).
    if "DI" in row_of:
        r = row_of["DI"]
        for inst in panel_groups["DI"]:
            di_plus, di_minus, adx = _compute_di_adx(df["High"], df["Low"], df["Close"], inst["period"])
            label = f'({inst["period"]})'
            fig.add_trace(go.Scatter(x=df.index, y=di_plus, name=f"+DI{label}", line=dict(color=inst["color1"], width=1.5)), row=r, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=di_minus, name=f"-DI{label}", line=dict(color=inst["color2"], width=1.5)), row=r, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=adx, name=f"ADX{label}", line=dict(color="#ffca28", width=1.5, dash="dot")), row=r, col=1)
        fig.add_hline(y=25, line_dash="dot", line_color=config.MUTED_TEXT, row=r, col=1)
        fig.update_yaxes(range=[0, 100], row=r, col=1)

    # Bollinger Bandwidth: (upper - lower) / middle, its own panel since its
    # scale has nothing to do with price -- a rising line means the bands are
    # spreading (volatility expanding), a falling one means they're
    # squeezing, and it reads the same regardless of how far you've zoomed
    # into the price panel above.
    bandwidth_range_series = []
    if "Bandwidth" in row_of:
        r = row_of["Bandwidth"]
        for inst in panel_groups["Bandwidth"]:
            _, _, _, width = _compute_bollinger(df["Close"], inst["period"], inst["stddev"])
            fig.add_trace(go.Scatter(
                x=df.index, y=width, name=f'BB Width({inst["period"]},{inst["stddev"]})',
                line=dict(color=inst["color"]), fill="tozeroy", fillcolor="rgba(179,157,219,0.15)",
            ), row=r, col=1)
            bandwidth_range_series.append(width)

    # No trace shows its own floating hover tooltip box -- that trails the
    # cursor across the chart, which is exactly what shouldn't happen; the
    # DRAW_TOOLS_JS crosshair price tag (axis-anchored, never moves
    # horizontally) is the only value readout now. hoverinfo="none" (not
    # "skip"): confirmed live that "skip" excludes a trace from hover
    # detection entirely, which silently kills the spike lines too once
    # every trace is skipped (no trace left for Plotly to compute a
    # "nearest point" from) -- "none" keeps a trace eligible for hover/spike
    # purposes while suppressing only its own tooltip box.
    for trace in fig.data:
        trace.update(hoverinfo="none")

    fig.update_layout(
        template="plotly_dark", height=550 + 150 * len(panel_types),
        xaxis_rangeslider_visible=False, showlegend=True,
        # Legend moves to a horizontal strip above the price panel instead
        # of Plotly's default (outside the plot on the right) -- the y-axis
        # lives on the right now (see update_yaxes(side="right") below,
        # matching how price charts are usually read), so the default spot
        # would sit right on top of the axis labels.
        legend=dict(orientation="h", yanchor="bottom", y=1.01, xanchor="left", x=0),
        # dragmode stays "zoom" (the normal default) so box-zoom still works
        # out of the box -- the draw-tool buttons added to the modebar (see
        # CHART_CONFIG below) let you switch into annotate mode and back.
        # Shapes drawn this way live in the figure's layout, so they survive
        # zoom/pan instead of resetting.
        dragmode="zoom",
        newshape=dict(line_color="#ffca28", line_width=2),
        # hovermode="x": crosshair follows the x-position under the cursor
        # (not just the nearest single point), which is what makes the
        # spike lines below track continuously as you move the mouse.
        hovermode="x",
    )

    # Y-axis on the right, matching how price charts are conventionally
    # read (and where the horizontal-line price tags below now sit too).
    fig.update_yaxes(side="right")

    # Crosshair: a dashed line at the cursor's x-position spanning every
    # panel (spikemode="across"), plus one at the cursor's y-position within
    # whatever panel is being hovered. hoverinfo="skip" on every overlay/
    # indicator trace (see the individual add_trace calls above) leaves
    # only the price and volume traces' tooltips active, so hovering shows
    # one clean OHLC readout instead of a stack of a dozen boxes (one per
    # EMA/band/indicator line) -- the crosshair lines themselves still track
    # every panel regardless of which traces keep their tooltip.
    #
    # x spikesnap="data": jumps bar-to-bar (the nearest actual candle),
    # not a continuous pixel position -- reading a specific bar's exact
    # date/OHLC is the point on the x-axis. y stays "cursor" (continuous):
    # price isn't discretized the way bars are, so a horizontal line should
    # track wherever you're actually pointing, not snap to the nearest
    # traded price.
    fig.update_xaxes(showspikes=True, spikemode="across", spikesnap="data",
                      spikecolor="#9e9e9e", spikethickness=1, spikedash="dot")
    fig.update_yaxes(showspikes=True, spikemode="across", spikesnap="cursor",
                      spikecolor="#9e9e9e", spikethickness=1, spikedash="dot")

    # Default the initial view to the last ~6 months instead of full history.
    # Plotly autoranges the y-axes to fit ALL data in the trace regardless of
    # what x-range is shown, so a chart going back to 2017 squashes recent
    # day-to-day fluctuations into a thin band near the top/bottom of a huge
    # multi-year price axis. Full history is still reachable by panning/
    # zooming/scrolling out -- this only sets what you see on first load.
    recent = df.iloc[-recent_window_bars:] if len(df) > recent_window_bars else df

    x_start, x_end = recent.index[0], recent.index[-1]
    if len(recent) > 1:
        x_pad = (x_end - x_start) * 0.02
        x_start, x_end = x_start - x_pad, x_end + x_pad
        fig.update_xaxes(range=[x_start, x_end])

    # Y-ranges must be computed from this same padded window, not the
    # stricter `recent` slice -- otherwise the extra days x_pad reveals at
    # the left edge can carry a value the y-range never accounted for,
    # poking a peak/trough past the panel border.
    visible = df[(df.index >= x_start) & (df.index <= x_end)]

    def _visible_slice(series):
        return series[(series.index >= x_start) & (series.index <= x_end)]

    price_lo, price_hi = visible["Low"].min(), visible["High"].max()
    for series in overlay_range_series:
        visible_series = _visible_slice(series)
        if visible_series.notna().any():
            price_lo = min(price_lo, visible_series.min())
            price_hi = max(price_hi, visible_series.max())
    price_pad = (price_hi - price_lo) * 0.08 or price_hi * 0.02 or 1
    # rangemode="nonnegative": a price can't go below 0, so neither should
    # this axis -- besides bounding the initial range just below (which
    # only covers first load), this is what keeps Plotly's OWN native
    # autorange (e.g. the modebar's "Reset axes"/double-click, which picks
    # its own padding independent of anything computed here) from dipping
    # negative too.
    fig.update_yaxes(range=[max(0, price_lo - price_pad), price_hi + price_pad],
                      rangemode="nonnegative", row=1, col=1)

    if "Volume" in row_of:
        vol_hi = visible["Volume"].max()
        fig.update_yaxes(range=[0, vol_hi * 1.15 if vol_hi else 1],
                          rangemode="nonnegative", row=row_of["Volume"], col=1)

    if macd_range_series:
        visible_macd = [_visible_slice(s) for s in macd_range_series]
        macd_lo = min(s.min() for s in visible_macd)
        macd_hi = max(s.max() for s in visible_macd)
        macd_pad = (macd_hi - macd_lo) * 0.1 or abs(macd_hi) * 0.1 or 0.01
        fig.update_yaxes(range=[macd_lo - macd_pad, macd_hi + macd_pad], row=row_of["MACD"], col=1)

    if bandwidth_range_series:
        visible_bw = [_visible_slice(s) for s in bandwidth_range_series]
        bw_lo = min(s.min() for s in visible_bw)
        bw_hi = max(s.max() for s in visible_bw)
        bw_pad = (bw_hi - bw_lo) * 0.1 or bw_hi * 0.1 or 0.01
        fig.update_yaxes(range=[max(0, bw_lo - bw_pad), bw_hi + bw_pad],
                          rangemode="nonnegative", row=row_of["Bandwidth"], col=1)

    if timeframe in ("daily", "hourly"):
        # Weekends, plus whatever weekdays have no bar at all -- exchange
        # holidays (New Year's, Republic Day, religious holidays, etc.) --
        # derived straight from the data (see _holiday_gap_values) rather
        # than a hardcoded calendar, so a gap around any actual non-trading
        # day gets collapsed the same way a weekend does instead of leaving
        # a visible dead band in the middle of the chart.
        rangebreaks = [dict(bounds=["sat", "mon"]), dict(values=_holiday_gap_values(df.index))]
        if timeframe == "hourly":
            # BIST's continuous session runs ~09:30-18:30 Istanbul time (see
            # fetch.fetch_hourly_ohlcv, which returns bars in that tz) --
            # hiding the overnight gap keeps consecutive trading hours
            # visually adjacent instead of a wide empty band each day.
            rangebreaks.append(dict(bounds=[18.5, 9.5], pattern="hour"))
        fig.update_xaxes(rangebreaks=rangebreaks)

    return fig


# Modebar config shared by the inline dcc.Graph and the standalone /chart/
# window: adds line/rect/circle/freeform draw buttons (for marking up the
# chart) plus an eraser, on top of Plotly's default zoom/pan/reset buttons.
# scrollZoom is OFF: Plotly's native wheel-zoom always moves x and y
# together with no way to split them, which is exactly the "scrolling over
# the chart shouldn't also drag the y-axis around" complaint DRAW_TOOLS_JS's
# own wheel handler fixes -- scroll over the plot area zooms x only, scroll
# over a panel's y-axis tick strip zooms just that axis, never both from the
# same gesture. AUTO_RESCALE_ON_ZOOM_JS still rescales the other panels'
# y-axes to match whatever x-window an x-only wheel-zoom lands on.
CHART_CONFIG = {
    "responsive": True,
    "scrollZoom": False,
    "modeBarButtonsToAdd": [
        "drawline", "drawopenpath", "drawclosedpath", "drawcircle", "drawrect", "eraseshape",
    ],
}


# Pass as `post_script=AUTO_RESCALE_ON_ZOOM_JS` to fig.to_html()/write_html()
# everywhere a chart is rendered. Every panel's y-range is set once, from
# whatever window was "visible" at build time (see build_chart_fig) --
# Plotly does not recompute a panel's y-range when you interactively zoom
# the (shared) x-axis, so zooming into a narrow window leaves panels like
# MACD still scaled to the old, wider range: the line flattens near
# whatever value it happened to be at across that bigger range, and
# crossovers become impossible to see. This listens for the x-axis range
# actually changing and rescales every non-fixed-scale panel's y-axis to
# fit just what's visible now. RSI/Stochastic are skipped on purpose --
# their fixed 0-100 scale is the point, not a bug to fix. A double-click
# reset (which Plotly reports as `xaxis.autorange`) restores every panel
# back to full autorange symmetrically.
#
# A box-zoom drag on the price panel reports BOTH an xaxis.range and a
# yaxis.range in the same relayout event -- if that axis's range is left
# out of the skip-check below, this listener immediately stomps the y-range
# the user just drew back to the visible window's full high/low, so the
# price axis looks "stuck" and un-adjustable. Any axis whose range this
# specific event already set manually is left alone; only axes the event
# didn't touch get recomputed from the new x-window.
AUTO_RESCALE_ON_ZOOM_JS = """
var gd = document.getElementById('{plot_id}');

// Plotly serializes numeric trace arrays as {dtype, bdata} (base64 of a
// typed array), not plain JS arrays, once a figure has enough points --
// trace.y[i]/trace.low[i] silently read as undefined against that shape,
// so this decodes back to a plain array before anything indexes into it.
// Cached per trace+field (WeakMap keyed on the trace object, which Plotly
// doesn't recreate across relayout calls) since every pan/zoom step was
// otherwise re-running the same base64 decode over the same thousands of
// points it had already decoded on the previous step -- a real, avoidable
// cost on top of the box-zoom drag itself feeling slow.
var _decodeCache = new WeakMap();
function decodeArray(val) {
    if (!val || Array.isArray(val)) { return val; }
    if (typeof val === 'object' && typeof val.bdata === 'string' && val.dtype) {
        var binary = atob(val.bdata);
        var bytes = new Uint8Array(binary.length);
        for (var i = 0; i < binary.length; i++) { bytes[i] = binary.charCodeAt(i); }
        var ctor = {
            f8: Float64Array, f4: Float32Array,
            i1: Int8Array, u1: Uint8Array,
            i2: Int16Array, u2: Uint16Array,
            i4: Int32Array, u4: Uint32Array,
        }[val.dtype] || Float64Array;
        return Array.from(new ctor(bytes.buffer));
    }
    return val;
}
function decodeCached(trace, field) {
    var val = trace[field];
    if (!val || Array.isArray(val)) { return val; }
    var cache = _decodeCache.get(trace);
    if (!cache) { cache = {}; _decodeCache.set(trace, cache); }
    if (!(field in cache)) { cache[field] = decodeArray(val); }
    return cache[field];
}

// x as millisecond timestamps, computed once and cached alongside the
// decoded arrays above -- re-parsing every point's ISO date string with
// `new Date(...).getTime()` on every single pan/zoom step (thousands of
// points x however many traces, every step) was real, measurable overhead
// on top of the O(n) scan it was embedded in.
function numericX(trace) {
    var cache = _decodeCache.get(trace);
    if (!cache) { cache = {}; _decodeCache.set(trace, cache); }
    if (!cache.xNum) {
        var xArr = decodeCached(trace, 'x');
        var xNum = new Array(xArr.length);
        for (var i = 0; i < xArr.length; i++) { xNum[i] = new Date(xArr[i]).getTime(); }
        cache.xNum = xNum;
    }
    return cache.xNum;
}

// First index where arr[index] >= target -- arr is chronological (every
// trace's x is sorted ascending), so this replaces an O(n) full-array scan
// with an O(log n) search for where the visible window starts; the caller
// still only walks the points actually inside [x0, x1], not the whole
// trace, however far zoomed in.
function lowerBound(arr, target) {
    var lo = 0, hi = arr.length;
    while (lo < hi) {
        var mid = (lo + hi) >>> 1;
        if (arr[mid] < target) { lo = mid + 1; } else { hi = mid; }
    }
    return lo;
}

gd.on('plotly_relayout', function(eventData) {
    function isFixedScale(axisName) {
        var axisLayout = gd.layout[axisName];
        return !!(axisLayout && axisLayout.range && axisLayout.range.length === 2 &&
                  axisLayout.range[0] === 0 && axisLayout.range[1] === 100);
    }

    // Hard floor for price/volume/DI/bandwidth axes (rangemode:
    // "nonnegative" in the Python layout -- see build_chart_fig): that
    // rangemode only constrains Plotly's OWN autorange, not a manual drag.
    // A box-zoom with a downward vertical component, or plain dragging in
    // Pan mode, sets `<axis>.range[0]` directly in this same event and
    // would otherwise still be free to drag the view into negative
    // territory. Bounce it back to 0 (keeping the same zoom span, just
    // shifted up) whenever that happens, before anything else runs.
    var floorFix = {};
    Object.keys(gd.layout).forEach(function(key) {
        if (!/^yaxis\\d*$/.test(key)) { return; }
        var axisLayout = gd.layout[key];
        if (!axisLayout || axisLayout.rangemode !== 'nonnegative') { return; }
        var lo = eventData[key + '.range[0]'];
        if (lo === undefined || lo >= 0) { return; }
        var hi = eventData[key + '.range[1]'] !== undefined ? eventData[key + '.range[1]'] : axisLayout.range[1];
        floorFix[key + '.range[0]'] = 0;
        floorFix[key + '.range[1]'] = hi - lo;
    });
    if (Object.keys(floorFix).length) {
        Plotly.relayout(gd, floorFix);
        return;
    }

    if (eventData['xaxis.autorange']) {
        var resetUpdate = {};
        Object.keys(gd.layout).forEach(function(key) {
            if (/^yaxis\\d*$/.test(key) && !isFixedScale(key)) {
                resetUpdate[key + '.autorange'] = true;
            }
        });
        if (Object.keys(resetUpdate).length) { Plotly.relayout(gd, resetUpdate); }
        return;
    }

    // Set by DRAW_TOOLS_JS's wheel handler right before its own x-only
    // scroll-zoom relayout -- that gesture is meant to leave every y-range
    // exactly as it was (scrolling the timeline shouldn't jostle the price
    // scale), so this listener's usual "re-fit y to what's now visible"
    // reaction is skipped for just this one relayout call. Box-zoom/pan
    // (dragmode="zoom"/"pan") never set this flag, so those still re-fit
    // as before -- this only mutes the wheel-zoom case.
    if (gd.__skipAutoRescale) {
        gd.__skipAutoRescale = false;
        return;
    }

    var x0 = eventData['xaxis.range[0]'], x1 = eventData['xaxis.range[1]'];
    if (x0 === undefined || x1 === undefined) { return; }
    x0 = new Date(x0).getTime();
    x1 = new Date(x1).getTime();

    var rowRanges = {};
    gd.data.forEach(function(trace) {
        var yaxis = trace.yaxis || 'y';
        var axisName = yaxis === 'y' ? 'yaxis' : 'yaxis' + yaxis.slice(1);
        var userSetThisAxis = eventData[axisName + '.range[0]'] !== undefined ||
                               eventData[axisName + '.range[1]'] !== undefined ||
                               eventData[axisName + '.range'] !== undefined;
        if (isFixedScale(axisName) || !trace.x || userSetThisAxis) { return; }
        var xNum = numericX(trace);
        var yArr = decodeCached(trace, 'y');
        var lowArr = decodeCached(trace, 'low');
        var highArr = decodeCached(trace, 'high');
        var lo = null, hi = null;
        var startIdx = lowerBound(xNum, x0);
        for (var i = startIdx; i < xNum.length; i++) {
            if (xNum[i] > x1) { break; }
            if (lowArr !== undefined && highArr !== undefined) {
                if (lowArr[i] != null && (lo === null || lowArr[i] < lo)) { lo = lowArr[i]; }
                if (highArr[i] != null && (hi === null || highArr[i] > hi)) { hi = highArr[i]; }
            } else if (yArr && yArr[i] != null) {
                if (lo === null || yArr[i] < lo) { lo = yArr[i]; }
                if (hi === null || yArr[i] > hi) { hi = yArr[i]; }
            }
        }
        if (lo !== null) {
            if (!rowRanges[axisName]) { rowRanges[axisName] = {lo: lo, hi: hi}; }
            else {
                if (lo < rowRanges[axisName].lo) { rowRanges[axisName].lo = lo; }
                if (hi > rowRanges[axisName].hi) { rowRanges[axisName].hi = hi; }
            }
        }
    });

    var update = {};
    Object.keys(rowRanges).forEach(function(axisName) {
        var lo = rowRanges[axisName].lo, hi = rowRanges[axisName].hi;
        var pad = (hi - lo) * 0.1 || Math.abs(hi) * 0.1 || 1;
        // If the actual data in view never goes negative (price, volume,
        // DI/ADX, bandwidth), padding shouldn't push the lower bound below
        // 0 either -- a stock price axis dipping negative on zoom reads as
        // a real bug, not headroom. MACD (and anything else whose true
        // low IS negative) is untouched, since this only floors axes where
        // lo was already >= 0 to begin with.
        var paddedLo = lo - pad;
        update[axisName + '.range[0]'] = lo >= 0 ? Math.max(0, paddedLo) : paddedLo;
        update[axisName + '.range[1]'] = hi + pad;
        update[axisName + '.autorange'] = false;
    });
    if (Object.keys(update).length) { Plotly.relayout(gd, update); }
});
"""


# Pass alongside AUTO_RESCALE_ON_ZOOM_JS (see CHART_POST_SCRIPTS below).
# Plotly's native draw tools (line/rect/circle/freeform, added via
# CHART_CONFIG's modeBarButtonsToAdd) only draw at any angle -- there's no
# built-in "horizontal line" button in Plotly's modebar, so this adds one as
# a plain HTML button above the chart plus a real DOM click listener (not
# plotly_click, which only fires near an actual data point) that converts
# the click's pixel position to a data y-value using each panel's own
# domain/range, so the line lands exactly where clicked in ANY panel, not
# just near a candle. Each line's price is labeled directly on it (see
# `label` below) so it's readable without hovering. The color picker next
# to it drives BOTH this custom tool and Plotly's native draw tools via
# `newshape.line.color`, since that's the one layout property controlling
# the default color of any new shape drawn through the modebar too -- one
# control, every drawn line.
#
# Every hline this tool draws is tagged `name: 'user-hline'` so it can be
# told apart from a diagonal line drawn with Plotly's own native "Draw
# line" tool -- Plotly's built-in "Erase active shape" modebar button
# doesn't reliably grab shapes added via a raw `Plotly.relayout` call the
# way it does ones drawn interactively through its own draw-tool, so
# deleting needs its own path here too: a "Delete Horizontal Line" mode
# (click near a line to remove just that one, matched by closest pixel
# distance within a small tolerance) plus a one-click "Clear All Horizontal
# Lines" for wiping every hline at once.
DRAW_TOOLS_JS = """
var gd = document.getElementById('{plot_id}');
(function() {
    var HLINE_NAME = 'user-hline';
    var bar = document.createElement('div');
    bar.style.cssText = 'padding:6px 20px;font-family:Arial, sans-serif;display:flex;' +
        'align-items:center;gap:10px;background-color:#121212;';

    var hBtn = document.createElement('button');
    var delBtn = document.createElement('button');
    var hlineMode = false;
    var deleteMode = false;

    function btnStyle(active) {
        return 'padding:6px 14px;border-radius:6px;border:none;cursor:pointer;' +
            'font-size:12.5px;color:white;background-color:' + (active ? '#42a5f5' : '#333') + ';';
    }
    var setButtons = function() {
        hBtn.textContent = hlineMode ? 'Click chart to place line...' : 'Draw Horizontal Line';
        hBtn.style.cssText = btnStyle(hlineMode);
        delBtn.textContent = deleteMode ? 'Click a line to delete it...' : 'Delete Horizontal Line';
        delBtn.style.cssText = btnStyle(deleteMode);
    };
    setButtons();
    hBtn.onclick = function() { hlineMode = !hlineMode; deleteMode = false; setButtons(); };
    delBtn.onclick = function() { deleteMode = !deleteMode; hlineMode = false; setButtons(); };

    var clearBtn = document.createElement('button');
    clearBtn.textContent = 'Clear All Horizontal Lines';
    clearBtn.style.cssText = btnStyle(false);
    clearBtn.onclick = function() {
        var keptShapes = (gd.layout.shapes || []).filter(function(s) { return s.name !== HLINE_NAME; });
        var keptAnnotations = (gd.layout.annotations || []).filter(function(a) { return a.name !== HLINE_NAME; });
        Plotly.relayout(gd, {shapes: keptShapes, annotations: keptAnnotations});
    };

    var colorLabel = document.createElement('span');
    colorLabel.textContent = 'Draw color:';
    colorLabel.style.cssText = 'color:#9e9e9e;font-size:12.5px;';

    var colorInput = document.createElement('input');
    colorInput.type = 'color';
    var currentColor = (gd.layout.newshape && gd.layout.newshape.line &&
                         gd.layout.newshape.line.color) || '#ffca28';
    colorInput.value = currentColor;
    colorInput.oninput = function() {
        currentColor = colorInput.value;
        Plotly.relayout(gd, {'newshape.line.color': currentColor});
    };

    bar.appendChild(hBtn);
    bar.appendChild(delBtn);
    bar.appendChild(clearBtn);
    bar.appendChild(colorLabel);
    bar.appendChild(colorInput);
    gd.parentNode.insertBefore(bar, gd);

    // Shared: which panel (yaxis) pixel `clickY` falls in, and the data
    // value at `clickY` within that panel's current range -- used by both
    // add (below) and delete (further below).
    function locateClick(clickY) {
        var fl = gd._fullLayout;
        var plotHeight = fl.height - fl.margin.t - fl.margin.b;
        var axisKeys = Object.keys(fl).filter(function(k) { return /^yaxis\\d*$/.test(k); });
        for (var i = 0; i < axisKeys.length; i++) {
            var key = axisKeys[i];
            var ax = fl[key];
            if (!ax.domain) { continue; }
            var top = fl.margin.t + (1 - ax.domain[1]) * plotHeight;
            var bottom = fl.margin.t + (1 - ax.domain[0]) * plotHeight;
            if (clickY < top || clickY > bottom) { continue; }
            var frac = (bottom - clickY) / (bottom - top);
            var range = ax.range;
            return {
                suffix: key.replace('yaxis', ''), range: range,
                yVal: range[0] + frac * (range[1] - range[0]),
                pxPerUnit: (bottom - top) / (range[1] - range[0]),
            };
        }
        return null;
    }

    // Scroll to zoom, x and y kept deliberately separate rather than
    // mixed into one gesture (CHART_CONFIG turns Plotly's own scrollZoom
    // off specifically because it always moves both together with no way
    // to split them): scrolling over the plot area zooms the shared x-axis
    // only, scrolling over a panel's y-axis tick-label strip (the margin to
    // the right of the plot, since the axis lives on the right -- see
    // update_yaxes(side="right")) zooms JUST that one panel's y-axis. Both
    // keep the cursor's value fixed as the zoom anchor (scroll up = zoom
    // in, scroll down = zoom out).
    gd.addEventListener('wheel', function(evt) {
        var bbox = gd.getBoundingClientRect();
        var clickX = evt.clientX - bbox.left;
        var clickY = evt.clientY - bbox.top;
        var fl = gd._fullLayout;
        var zoomFactor = evt.deltaY < 0 ? 0.9 : 1.1;

        if (clickX >= fl.width - fl.margin.r) {
            // Axis tick-label strip: y-only, scoped to whichever panel row
            // the cursor is next to.
            var hit = locateClick(clickY);
            if (!hit) { return; }
            evt.preventDefault();
            evt.stopPropagation();
            var lo = hit.range[0], hi = hit.range[1], val = hit.yVal;
            var axisKey = 'yaxis' + hit.suffix;
            var update = {};
            update[axisKey + '.range[0]'] = val - (val - lo) * zoomFactor;
            update[axisKey + '.range[1]'] = val + (hi - val) * zoomFactor;
            update[axisKey + '.autorange'] = false;
            Plotly.relayout(gd, update);
            return;
        }

        // Main plot area: x-only, using the shared xaxis (every row's x is
        // the same axis object via shared_xaxes=True) -- no y key in this
        // update at all, so every panel's y-range is left exactly as is.
        if (clickX < fl.margin.l || clickY < fl.margin.t || clickY > fl.height - fl.margin.b) { return; }
        evt.preventDefault();
        evt.stopPropagation();
        var plotWidth = fl.width - fl.margin.l - fl.margin.r;
        var xFrac = (clickX - fl.margin.l) / plotWidth;
        var xRange = gd.layout.xaxis.range;
        var x0 = new Date(xRange[0]).getTime(), x1 = new Date(xRange[1]).getTime();
        var xVal = x0 + xFrac * (x1 - x0);
        var newX0 = xVal - (xVal - x0) * zoomFactor;
        var newX1 = xVal + (x1 - xVal) * zoomFactor;
        // AUTO_RESCALE_ON_ZOOM_JS's own plotly_relayout listener reacts to
        // ANY xaxis.range change by re-fitting every other panel's y-range
        // to whatever's now visible -- exactly right for a deliberate
        // box-zoom selection, but it was fighting this handler's whole
        // point (scrolling the timeline shouldn't jostle the price scale):
        // every wheel-zoom step nudged y a little via that "re-fit", which
        // is what "still adjusting itself" was. gd.__skipAutoRescale tells
        // that listener to sit this one relayout out; it clears the flag
        // itself right after, so box-zoom/pan is unaffected.
        gd.__skipAutoRescale = true;
        Plotly.relayout(gd, {
            'xaxis.range[0]': new Date(newX0).toISOString(),
            'xaxis.range[1]': new Date(newX1).toISOString(),
        });
    }, {passive: false});

    gd.addEventListener('click', function(evt) {
        if (!hlineMode && !deleteMode) { return; }
        var bbox = gd.getBoundingClientRect();
        var clickY = evt.clientY - bbox.top;
        var hit = locateClick(clickY);
        if (!hit) { return; }
        var yref = 'y' + hit.suffix;

        if (hlineMode) {
            var newShape = {
                name: HLINE_NAME,
                type: 'line', xref: 'x' + hit.suffix + ' domain', yref: yref,
                x0: 0, x1: 1, y0: hit.yVal, y1: hit.yVal,
                line: {color: currentColor, width: 1.5, dash: 'dash'},
            };
            // A shape's own `label` only positions relative to the line's
            // MIDPOINT for a domain-referenced line (xanchor/textposition
            // don't relocate it, no matter what they're set to) -- for a
            // full-width line that's the horizontal center of the chart,
            // nowhere near the y-axis. A separate annotation, anchored at
            // x=1 on the same "x domain" reference, is what actually lands
            // right at the axis (the y-axis lives on the right -- see
            // update_yaxes(side="right") in build_chart_fig) where the
            // price is easy to read at a glance. Tagged with the same
            // HLINE_NAME so delete/clear-all can find and remove it
            // alongside its line.
            var newAnnotation = {
                name: HLINE_NAME,
                x: 1, xref: 'x' + hit.suffix + ' domain', xanchor: 'right',
                y: hit.yVal, yref: yref, yanchor: 'middle',
                text: hit.yVal.toFixed(2), showarrow: false,
                font: {color: '#000', size: 11}, bgcolor: currentColor, borderpad: 3,
            };
            Plotly.relayout(gd, {
                shapes: (gd.layout.shapes || []).concat([newShape]),
                annotations: (gd.layout.annotations || []).concat([newAnnotation]),
            });
            return;
        }

        // deleteMode: remove the closest user-drawn hline (and its price
        // annotation) on this same panel, as long as the click landed
        // within ~8px of it -- close enough to feel forgiving without
        // deleting an unrelated line you merely clicked near.
        var shapes = gd.layout.shapes || [];
        var bestIdx = -1, bestDist = Infinity, bestY = null;
        for (var j = 0; j < shapes.length; j++) {
            var s = shapes[j];
            if (s.name !== HLINE_NAME || s.yref !== yref) { continue; }
            var dist = Math.abs(s.y0 - hit.yVal) * hit.pxPerUnit;
            if (dist < bestDist) { bestDist = dist; bestIdx = j; bestY = s.y0; }
        }
        if (bestIdx !== -1 && bestDist <= 8) {
            var remainingShapes = shapes.slice(0, bestIdx).concat(shapes.slice(bestIdx + 1));
            var remainingAnnotations = (gd.layout.annotations || []).filter(function(a) {
                return !(a.name === HLINE_NAME && a.yref === yref && a.y === bestY);
            });
            Plotly.relayout(gd, {shapes: remainingShapes, annotations: remainingAnnotations});
        }
    });

    // Crosshair price readout: showspikes (see build_chart_fig) draws the
    // dashed crosshair lines themselves, but Plotly has no built-in "tag
    // the exact value at the cursor" -- the OHLC hover tooltip shows that
    // bar's open/high/low/close, not the raw price the horizontal spike
    // line is actually sitting on. This tracks the cursor the same way the
    // hline tool's click handler locates a click (locateClick, reused
    // as-is), but renders as a plain positioned <div> updated via direct
    // style mutation -- NOT a Plotly annotation. An annotation would mean
    // a Plotly.relayout() call on every mousemove (up to ~60/sec while the
    // mouse is moving), and relayout always re-diffs Plotly's full layout
    // object regardless of how small the actual change is; that was a real,
    // measurable source of chart sluggishness. A plain div's style updates
    // don't touch Plotly at all, so this is effectively free by comparison.
    var crosshairTagEl = document.createElement('div');
    crosshairTagEl.style.cssText = 'position:fixed;display:none;background:#333;color:white;' +
        'font-family:Arial, sans-serif;font-size:11px;padding:3px 5px;border-radius:2px;' +
        'pointer-events:none;z-index:1000;transform:translateY(-50%);white-space:nowrap;';
    document.body.appendChild(crosshairTagEl);

    gd.addEventListener('mousemove', function(evt) {
        if (hlineMode || deleteMode) { crosshairTagEl.style.display = 'none'; return; }
        var bbox = gd.getBoundingClientRect();
        var moveY = evt.clientY - bbox.top;
        var hit = locateClick(moveY);
        if (!hit) { crosshairTagEl.style.display = 'none'; return; }
        var fl = gd._fullLayout;
        crosshairTagEl.textContent = hit.yVal.toFixed(2);
        crosshairTagEl.style.left = (bbox.left + fl.width - fl.margin.r) + 'px';
        crosshairTagEl.style.top = evt.clientY + 'px';
        crosshairTagEl.style.display = 'block';
    });
    gd.addEventListener('mouseleave', function() { crosshairTagEl.style.display = 'none'; });

    // Click-for-details: hoverinfo is set to "none" on every trace (see
    // build_chart_fig) specifically to kill the floating OHLC tooltip that
    // used to trail the cursor -- but that also removed any way to read a
    // bar's actual numbers. This restores that on click instead of hover: a
    // small panel, positioned near the click and left on screen (not tied
    // to mousemove) until dismissed, showing the clicked candle's O/H/L/C
    // (+ change) or, for a Bar trace (Volume, MACD histogram), its value.
    // Reuses Plotly's own plotly_click event rather than reimplementing
    // hit-testing: Plotly still finds the nearest point and populates
    // pt.open/high/low/close/y for us even with hoverinfo="none" (that
    // flag only suppresses the tooltip's own text, not point detection --
    // same distinction that mattered for the crosshair spike lines).
    var detailBoxEl = document.createElement('div');
    detailBoxEl.style.cssText = 'position:fixed;display:none;background:#1e1e1e;color:white;' +
        'font-family:Arial, sans-serif;font-size:12px;padding:8px 10px;border-radius:6px;' +
        'border:1px solid #444;z-index:1001;box-shadow:0 2px 10px rgba(0,0,0,0.5);' +
        'min-width:150px;';
    document.body.appendChild(detailBoxEl);

    function hideDetailBox() { detailBoxEl.style.display = 'none'; }

    function fmtNum(v) {
        return (v === undefined || v === null || isNaN(v)) ? '-' :
            Number(v).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2});
    }

    gd.on('plotly_click', function(data) {
        if (hlineMode || deleteMode) { return; }
        if (!data || !data.points || !data.points.length) { return; }
        // hovermode="x" reports every trace sharing the clicked x column
        // within that row (e.g. clicking the price panel also matches
        // whichever moving average/BB line happens to sit closest to the
        // click's y), ordered by y-distance -- closest first, not
        // necessarily the candle. A click anywhere in the price row should
        // read as "show me this candle", so the OHLC trace wins whenever
        // it's one of the matches; otherwise fall back to the nearest
        // point (a single Bar trace in the Volume/MACD-hist row, or an
        // indicator line with no OHLC of its own).
        var pt = data.points.find(function(p) {
            var t = gd.data[p.curveNumber];
            return t && (t.type === 'ohlc' || t.type === 'candlestick');
        }) || data.points[0];
        var trace = gd.data[pt.curveNumber] || {};

        var rows = [];
        if (pt.open !== undefined && pt.close !== undefined) {
            var chg = pt.close - pt.open;
            var chgPct = pt.open ? (chg / pt.open * 100) : 0;
            var chgColor = chg >= 0 ? '#26a69a' : '#ef5350';
            rows.push(['Open', fmtNum(pt.open)]);
            rows.push(['High', fmtNum(pt.high)]);
            rows.push(['Low', fmtNum(pt.low)]);
            rows.push(['Close', fmtNum(pt.close)]);
            rows.push(['Change', '<span style="color:' + chgColor + ';">' +
                (chg >= 0 ? '+' : '') + fmtNum(chg) + ' (' + (chgPct >= 0 ? '+' : '') + chgPct.toFixed(2) + '%)</span>']);
        } else {
            rows.push([trace.name || 'Value', fmtNum(pt.y)]);
        }

        var html = '<div style="display:flex;justify-content:space-between;align-items:center;' +
            'margin-bottom:6px;gap:16px;"><b>' + String(pt.x) + '</b>' +
            '<span data-role="detail-box-close" style="cursor:pointer;color:#9e9e9e;padding:0 2px;">&times;</span></div>';
        rows.forEach(function(r) {
            html += '<div style="display:flex;justify-content:space-between;gap:16px;">' +
                '<span style="color:#9e9e9e;">' + r[0] + '</span><span>' + r[1] + '</span></div>';
        });
        detailBoxEl.innerHTML = html;

        var evt = data.event || {};
        var clientX = evt.clientX !== undefined ? evt.clientX : (window.innerWidth / 2);
        var clientY = evt.clientY !== undefined ? evt.clientY : (window.innerHeight / 2);
        detailBoxEl.style.left = Math.min(clientX + 14, window.innerWidth - 190) + 'px';
        detailBoxEl.style.top = Math.min(clientY + 14, window.innerHeight - 140) + 'px';
        detailBoxEl.style.display = 'block';

        var closeEl = detailBoxEl.querySelector('[data-role="detail-box-close"]');
        if (closeEl) { closeEl.onclick = hideDetailBox; }
    });

    document.addEventListener('click', function(evt) {
        if (detailBoxEl.style.display === 'none') { return; }
        if (detailBoxEl.contains(evt.target) || gd.contains(evt.target)) { return; }
        hideDetailBox();
    });
    document.addEventListener('keydown', function(evt) {
        if (evt.key === 'Escape') { hideDetailBox(); }
    });
})();
"""

# Pass as `post_script=CHART_POST_SCRIPTS` to fig.to_html()/write_html()
# everywhere a chart is rendered -- fig.to_html() accepts a list here and
# chains each one after Plotly.newPlot() (see plotly.io._html.to_html), so
# both the auto-rescale-on-zoom listener and the draw-tools toolbar attach
# to the same figure.
CHART_POST_SCRIPTS = [AUTO_RESCALE_ON_ZOOM_JS, DRAW_TOOLS_JS]


# ---------------------------------------------------------------------------
# UI building blocks
# ---------------------------------------------------------------------------
def badge(text, color):
    return html.Span(text, style={
        "backgroundColor": color, "color": "white", "padding": "2px 10px",
        "borderRadius": "10px", "fontWeight": "bold", "fontSize": "12px",
    })


def _edge_span(label, edge_value, n):
    return html.Span(presentation.edge_text(label, edge_value, n), style={
        "fontSize": "12px", "color": presentation.edge_color(edge_value), "fontWeight": "bold",
    })


def build_mini_card(result: dict, align_threshold: int):
    """Build one scoreboard card from an engine.analyze_ticker()-shaped
    result dict. `result["stats"]` must be a plain dict (BacktestStats.
    as_dict()), not the dataclass itself -- this is what lets a card get
    rebuilt from a dcc.Store round-trip (JSON only holds plain dicts) as
    well as from a fresh scan, which is what the scoreboard's client-side
    filter/sort re-render relies on. Badges loop indicators.REGISTRY (via
    presentation.indicator_badges) so a newly-registered indicator appears
    automatically -- no per-indicator hand-written badge call here.
    """
    ticker = result["ticker"]
    confluence = result["confluence"]
    stats = result["stats"]

    return html.Div([
        html.Div([
            html.H4(ticker, style={"margin": 0}),
            badge(presentation.confluence_badge_text(confluence),
                  presentation.confluence_color(confluence, align_threshold)),
        ], style={"display": "flex", "justifyContent": "space-between", "alignItems": "center"}),

        html.Div([
            badge(text, color) for text, color in presentation.indicator_badges(result["votes"])
        ], style={"display": "flex", "gap": "6px", "margin": "8px 0", "flexWrap": "wrap"}),

        html.Div(
            presentation.hit_rate_text(stats["overall_hit_rate"], stats["n_overall"], result["rsi"]),
            style={"fontSize": "12px", "color": config.MUTED_TEXT, "marginBottom": "4px"},
        ),

        html.Div([
            _edge_span("bull edge", stats["bull_edge"], stats["n_bull"]),
            _edge_span("bear edge", stats["bear_edge"], stats["n_bear"]),
        ], style={"display": "flex", "flexDirection": "column", "gap": "2px", "marginBottom": "10px"}),

        html.Button("View Chart", id={"type": "view-btn", "index": ticker}, n_clicks=0, className="btn", style={
            "backgroundColor": config.BLUE, "color": "white", "width": "100%",
        }),
    ], className="hover-card", style={
        "backgroundColor": config.CARD_BG, "padding": "14px", "borderRadius": "10px",
        "color": "white", "width": "220px",
        "boxShadow": "0 2px 8px rgba(0,0,0,0.4)",
    })


def number_input(label, input_id, value, min_value, step=1):
    return html.Div([
        html.Label(label, style={"color": config.MUTED_TEXT, "fontSize": "12px", "display": "block"}),
        # persistence: remembers whatever the user last typed here in the
        # browser's localStorage, keyed by this component's id -- without
        # it, every parameter input snaps back to config.py's default the
        # moment the tab/dashboard is closed and reopened.
        dcc.Input(id=input_id, type="number", value=value, min=min_value, step=step,
                  persistence=True, persistence_type="local", style={
                      "width": "80px", "backgroundColor": config.INPUT_BG, "color": "white",
                      "border": f"1px solid {config.BORDER_COLOR}", "borderRadius": "4px", "padding": "4px",
                  }),
    ])


def stoch_mode_selector(input_id: str, value: str = config.STOCH_MODE):
    """Fast/Slow/Full radio picker for the Stochastic Oscillator (see
    indicators.stochastic_signal). Fast is raw %K/%D. Slow smooths %K with
    a fixed 3-period average before %D (what most platforms mean by "the
    stochastic" by default). Full is the same shape as Slow but reads the
    smoothing period from the Smoothing input in stoch_controls() below
    instead of the fixed 3 -- pick Full when you want to tune it yourself.
    """
    return html.Div([
        html.Label("Stochastic", style={"color": config.MUTED_TEXT, "fontSize": "12px", "display": "block"}),
        dcc.RadioItems(
            id=input_id,
            options=[
                {"label": " Fast", "value": "fast"},
                {"label": " Slow", "value": "slow"},
                {"label": " Full", "value": "full"},
            ],
            value=value, inline=True, persistence=True, persistence_type="local",
            style={"color": "white", "fontSize": "13px"},
            inputStyle={"marginRight": "4px", "marginLeft": "10px"},
            labelStyle={"marginRight": "4px", "color": "white"},
        ),
    ])


def stoch_controls(prefix: str, mode_value: str = config.STOCH_MODE):
    """Full Stochastic control group for one page: the Fast/Slow/Full mode
    picker plus the periods only Full mode actually reads (%K lookback and
    %D period apply to every mode; Smoothing only takes effect when Full is
    selected -- Fast has no smoothing step and Slow's is fixed at 3).
    Bundled into one helper since every page that has this needs all four
    controls together, not just the mode picker alone.
    """
    return html.Div([
        stoch_mode_selector(f"{prefix}-stoch-mode-input", mode_value),
        number_input("Stoch %K Period", f"{prefix}-stoch-k-period-input", config.STOCH_K_PERIOD, 1),
        number_input("Stoch %D Period", f"{prefix}-stoch-d-period-input", config.STOCH_D_PERIOD, 1),
        number_input("Stoch Smoothing (Full)", f"{prefix}-stoch-smoothing-input", config.STOCH_SLOWING, 1),
    ], style={"display": "flex", "gap": "12px", "flexWrap": "wrap", "alignItems": "flex-end"})


def indicator_checklist(input_id: str):
    """Which registered indicators (indicators.REGISTRY) count toward the
    confluence score -- all checked by default. Unchecking one doesn't hide
    it: its badge/vote still shows (votes_json_for_row always includes
    every registered indicator), it just stops counting toward confluence
    and the "fully aligned" threshold shrinks to match (see
    indicators.active_indicator_names). Unchecking everything is treated
    as "no restriction" -- confluence never silently goes to zero
    indicators.
    """
    return html.Div([
        html.Label("Confluence indicators", style={"color": config.MUTED_TEXT, "fontSize": "12px",
                                                     "display": "block"}),
        dcc.Checklist(
            id=input_id,
            options=[{"label": f" {ind.label}", "value": ind.name} for ind in indicators.REGISTRY],
            value=[ind.name for ind in indicators.REGISTRY],
            inline=True, persistence=True, persistence_type="local",
            style={"color": "white", "fontSize": "13px"},
            inputStyle={"marginRight": "4px", "marginLeft": "10px"},
            labelStyle={"color": "white"},
        ),
    ])


def page_header(title: str, description: str = None):
    """Consistent page title + optional description, used at the top of
    every page (including Home) so the app reads as one product instead of
    six differently-styled sections stapled together.
    """
    children = [html.H2(title, style={"color": "white", "marginTop": 0, "marginBottom": "6px",
                                       "fontWeight": 600, "letterSpacing": "-0.2px"})]
    if description:
        children.append(html.Div(description, style={
            "color": config.MUTED_TEXT, "fontSize": "13px",
            "marginBottom": "12px", "maxWidth": "720px", "lineHeight": "1.5",
        }))
    return html.Div(children, style={"marginBottom": "18px"})
