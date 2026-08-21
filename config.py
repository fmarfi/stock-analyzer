"""Single source of default configuration for the stock_analyzer package.

Both the CLI (run_scan.py) and the dashboard (dashboard.py) import these
defaults and may override individual values (via CLI flags or dashboard
inputs) without editing this file. Keeping every tunable in one place is
what lets fetch.py, indicators.py, backtest.py, engine.py, and the reporting
modules all agree on the same numbers without duplicating literals.
"""

import os

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(PACKAGE_DIR, "data")
REPORTS_DIR = os.path.join(PACKAGE_DIR, "reports")
DB_PATH = os.path.join(DATA_DIR, "stock_analyzer.db")

# ---------------------------------------------------------------------------
# Indicator parameters
# ---------------------------------------------------------------------------
MA_SHORT = 5
MA_LONG = 20
RSI_PERIOD = 14
VOL_MA_PERIOD = 20

# MACD: standard 12/26/9 EMA periods. Registered as a confluence vote (see
# indicators.macd_cross_signal), unlike Bollinger Bands below.
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9

# Stochastic Oscillator: standard 14/3/3. STOCH_MODE picks which variant is
# computed -- "fast" is the raw %K with %D = SMA(%K, d_period); "slow"
# smooths %K first with a fixed 3-period average before taking %D from that
# (what most platforms mean by "the stochastic" by default); "full" is the
# same shape as slow but with a user-chosen smoothing period (STOCH_SLOWING)
# instead of the fixed 3, for when you want to tune it yourself. Registered
# as a confluence vote (see indicators.stochastic_signal), unlike Bollinger
# Bands below.
STOCH_K_PERIOD = 14
STOCH_D_PERIOD = 3
STOCH_SLOWING = 3  # only used when STOCH_MODE == "full"
STOCH_MODE = "slow"  # "fast", "slow", or "full"

# Directional Movement Index: standard Wilder 14-period smoothing for
# +DI/-DI/ADX. Registered as a confluence vote (see indicators.di_signal).
DI_PERIOD = 14

# Bollinger Bands: chart-overlay only (see indicators.py / dashboard.py),
# not part of the confluence vote registry.
BB_PERIOD = 20
BB_STDDEV = 2

# ---------------------------------------------------------------------------
# Backtest parameters
# ---------------------------------------------------------------------------
HORIZON = 10           # bars forward to evaluate hit-rate/edge over
ALIGN_THRESHOLD = None  # None => resolved at runtime to len(REGISTRY) via
                         # indicators.default_align_threshold()

# ---------------------------------------------------------------------------
# Fetch / cache parameters
# ---------------------------------------------------------------------------
DEFAULT_START_DATE = "2017-01-01"   # first-ever fetch for a new ticker
DEFAULT_END_DATE = ""               # "" => up to today

# ---------------------------------------------------------------------------
# Color palette (shared by presentation.py -> dashboard.py + html_report.py)
# ---------------------------------------------------------------------------
GREEN = "#26a69a"
RED = "#ef5350"
BLUE = "#42a5f5"
GRAY = "#616161"
CARD_BG = "#1e1e1e"
PAGE_BG = "#121212"
MUTED_TEXT = "#9e9e9e"
BORDER_COLOR = "#444"
INPUT_BG = "#2a2a2a"

# ---------------------------------------------------------------------------
# Report retention
# ---------------------------------------------------------------------------
# Timestamped report files (scan_report_*, squeeze_report_*, bounce_report_*)
# accumulate one per run alongside latest.*; every write prunes down to just
# the N most recent of each -- generating a new report removes the old ones.
REPORT_RETENTION = 1

# ---------------------------------------------------------------------------
# Default watchlist(s)
# ---------------------------------------------------------------------------
DEFAULT_WATCHLIST_NAME = "core10"

WATCHLISTS = {
    "core10": [
        "AAPL", "MSFT", "GOOGL", "AMZN", "TSLA",
        "NVDA", "META", "JPM", "V", "WMT",
        "TTKOM.IS",  # Turk Telekomunikasyon A.S., Borsa Istanbul
    ],
    # 40 major US-exchange-listed mega/large-caps, spread across GICS sectors
    # (not just tech) so a sector-wise strategy comparison has enough
    # tickers per sector to be meaningful rather than comparing sectors of one.
    "us_mega40": [
        # Technology
        "AAPL", "MSFT", "NVDA", "AVGO", "ORCL", "CRM", "ADBE",
        # Communication Services
        "GOOGL", "META", "NFLX", "DIS",
        # Consumer Discretionary
        "AMZN", "TSLA", "HD", "MCD", "NKE",
        # Consumer Staples
        "WMT", "PG", "KO", "PEP",
        # Financials
        "JPM", "V", "MA", "BAC", "GS",
        # Healthcare
        "UNH", "JNJ", "LLY", "ABBV", "MRK",
        # Industrials
        "CAT", "BA", "HON", "UPS",
        # Energy
        "XOM", "CVX", "COP",
        # Utilities
        "NEE", "DUK",
        # Materials
        "LIN",
    ],
    # Borsa Istanbul Yildiz Pazar (Star Market) tier, unioned with the BIST
    # 100 (XU100) index -- sourced from getmidas.com's XU100 constituent
    # list, cross-checked against a second independent source
    # (uzmanpara.milliyet.com.tr) with zero disagreements (only a smaller
    # subset), then every single ticker below bulk-validated against live
    # yfinance data before being added -- same standing practice as the
    # original Yildiz Pazar list (whose own Borsa Istanbul source file
    # turned out to be stale, containing long-delisted names like KIPA).
    # Not guaranteed to track index reconstitutions going forward -- refresh
    # from a current source if BIST 100 membership changes.
    "bist_yildiz": [
        "ADEL.IS", "AEFES.IS", "AFYON.IS", "AKBNK.IS", "AKCNS.IS", "AKENR.IS",
        "AKGRT.IS", "AKSA.IS", "AKSEN.IS", "ALARK.IS", "ALBRK.IS", "ALCTL.IS",
        "ALKIM.IS", "ALTNY.IS", "ANHYT.IS", "ANSGR.IS", "ARCLK.IS", "ASELS.IS",
        "ASTOR.IS", "AVHOL.IS", "AYGAZ.IS", "BAGFS.IS", "BALSU.IS", "BERA.IS",
        "BIMAS.IS", "BIZIM.IS", "BJKAS.IS", "BRISA.IS", "BRSAN.IS", "BRYAT.IS",
        "BSOKE.IS", "BTCIM.IS", "BUCIM.IS", "CANTE.IS", "CCOLA.IS", "CIMSA.IS",
        "CLEBI.IS", "CRFSA.IS", "CVKMD.IS", "CWENE.IS", "DAPGM.IS", "DEVA.IS",
        "DOAS.IS", "DOCO.IS", "DOHOL.IS", "DSTKF.IS", "ECILC.IS", "ECZYT.IS",
        "EFOR.IS", "EGEEN.IS", "EKGYO.IS", "ENERY.IS", "ENJSA.IS", "ENKAI.IS",
        "ERBOS.IS", "EREGL.IS", "ESEN.IS", "EUPWR.IS", "EUREN.IS", "FENER.IS",
        "FROTO.IS", "GARAN.IS", "GENIL.IS", "GESAN.IS", "GIPTA.IS", "GLRMK.IS", "GLYHO.IS",
        "GOLTS.IS", "GOODY.IS", "GRSEL.IS", "GRTHO.IS", "GSDHO.IS", "GSRAY.IS",
        "GUBRF.IS", "HALKB.IS", "HEKTS.IS", "HRKET.IS", "IEYHO.IS", "IHLAS.IS",
        "INDES.IS", "ISCTR.IS", "ISFIN.IS", "ISMEN.IS", "IZENR.IS", "IZMDC.IS",
        "KARSN.IS", "KARTN.IS", "KCHOL.IS", "KLRHO.IS", "KONYA.IS", "KORDS.IS",
        "KRDMA.IS", "KRDMB.IS", "KRDMD.IS", "KTLEV.IS", "KUYAS.IS", "LOGO.IS",
        "MAGEN.IS", "MAVI.IS", "METRO.IS", "MGROS.IS", "MIATK.IS", "MPARK.IS",
        "NETAS.IS", "NTHOL.IS", "NUHCM.IS", "OBAMS.IS", "ODAS.IS", "ODINE.IS",
        "OTKAR.IS", "OYAKC.IS", "PAHOL.IS", "PASEU.IS", "PATEK.IS", "PETKM.IS",
        "PETUN.IS", "PGSUS.IS", "PNSUT.IS", "PRKME.IS", "PSGYO.IS", "QUAGR.IS",
        "RALYH.IS", "REEDR.IS", "SAHOL.IS", "SARKY.IS", "SASA.IS", "SELEC.IS",
        "SISE.IS", "SKBNK.IS", "SOKM.IS", "TATGD.IS", "TAVHL.IS", "TCELL.IS",
        "THYAO.IS", "TKFEN.IS", "TKNSA.IS", "TMSN.IS", "TOASO.IS", "TRALT.IS",
        "TRCAS.IS", "TRENJ.IS", "TRMET.IS", "TSKB.IS", "TTKOM.IS", "TTRAK.IS",
        "TUKAS.IS", "TUPRS.IS", "TURSG.IS", "ULKER.IS", "VAKBN.IS", "VESBE.IS",
        "VESTL.IS", "YKBNK.IS", "ZOREN.IS",
    ],
}

# Small hardcoded fallback used by universe.py when the S&P 500 Wikipedia
# scrape isn't available (no network, or lxml missing).
FALLBACK_UNIVERSE = WATCHLISTS["core10"]
