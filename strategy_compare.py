"""Compare the package's strategies -- Confluence (trend+momentum+volume,
fully aligned), Bollinger Squeeze (tight bandwidth + full alignment),
Bollinger Bounce (band touch + rejection in a ranging market), and Combined
(Squeeze and Bounce blended into one adaptive signal) -- on the same
ticker's history, and report which one had the best historical hit rate.
Grouped by sector (sector.py) so a "does X work better for tech than for
utilities" question has an answer.

Each strategy is reduced to the same numbers -- hit_rate, n, and hits (how
many of those n forward returns agreed with the signal's direction) -- so
they're directly comparable despite being structurally different (confluence
is a continuous daily read with hundreds+ of observations; squeeze/bounce/
combined are sparse events, often under 100). Comparing a stable, well-
powered ~50% estimate against a noisy small-sample estimate and picking
whichever number is numerically highest is a classic multiple-comparisons
trap -- across a 40-ticker x 4-strategy scan that's ~150 comparisons, and a
handful will look like a "winner" from variance alone even with zero real
edge, especially the thinnest-sample strategies (squeeze/bounce), since a
noisy estimate is disproportionately likely to be the one that spikes high.

So "best" isn't just "highest hit_rate among strategies with >= min_events":
each strategy's hit_rate is tested against a 50% null with an exact
two-sided binomial test, and only strategies whose p-value clears a
Bonferroni-corrected threshold (0.05 / total tests run across the whole
scan) *and* beat 50% are eligible to be tagged "best". A ticker with no
strategy that clears that bar gets best_strategy=None rather than a
manufactured winner. A Wilson score 95% CI is reported alongside every
hit_rate so the uncertainty is visible even where the p-value isn't quoted.

Squeeze requires confluence to be fully aligned that day; Bounce requires it
NOT be (a ranging read) -- those two conditions are mutually exclusive by
construction, so no bar can ever qualify as both, which is what makes their
union ("Combined") a well-defined single adaptive signal rather than a
category error: Squeeze covers the trending/breakout regime, Bounce covers
the ranging one, and Combined is "trade whichever applies."

None of this is a substitute for out-of-sample/walk-forward validation --
every number here is in-sample (the same history used to find an event is
the history used to score it), which this module does not attempt to correct
for. Treat a statistically significant in-sample edge as "worth testing
further", not as a validated trading signal.
"""

import datetime
import logging
import math

import numpy as np

from stock_analyzer import backtest as backtest_mod
from stock_analyzer import bounce, engine, sector as sector_mod, squeeze

logger = logging.getLogger(__name__)

STRATEGY_NAMES = ("confluence", "squeeze", "bounce", "combined")

ALPHA = 0.05  # family-wise significance level before Bonferroni correction


def _wilson_interval(k: int, n: int, z: float = 1.96) -> tuple:
    """95% Wilson score confidence interval for a binomial proportion --
    better-behaved than the naive Wald interval at the small n's (event
    counts in the teens-to-hundreds) this module deals with.
    """
    if n == 0:
        return None, None
    phat = k / n
    denom = 1 + z ** 2 / n
    center = phat + z ** 2 / (2 * n)
    margin = z * math.sqrt(phat * (1 - phat) / n + z ** 2 / (4 * n ** 2))
    return max(0.0, (center - margin) / denom), min(1.0, (center + margin) / denom)


def _log_binom_pmf(n: int, k: int, p: float) -> float:
    """log P(X=k) for X ~ Binomial(n, p), via log-gamma rather than
    math.comb(n, k) -- confluence routinely has n in the thousands, where
    comb(n, n//2) is a many-hundred-digit integer that overflows a float
    the moment it's multiplied by p**k. lgamma stays in float space the
    whole way through, so it never hits that overflow.
    """
    log_choose = math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)
    return log_choose + k * math.log(p) + (n - k) * math.log(1 - p)


def _binomial_two_sided_pvalue(k: int, n: int, p: float = 0.5) -> float:
    """Exact two-sided binomial test p-value against H0: true rate == p --
    sums the probability of every outcome at least as extreme as the
    observed one under Binomial(n, p) (the same "minlike" method R's
    binom.test / the old scipy.stats.binom_test use). No scipy dependency
    needed: this is exact, not a normal approximation.
    """
    if n == 0:
        return 1.0
    log_pmf = [_log_binom_pmf(n, x, p) for x in range(n + 1)]
    observed = log_pmf[k]
    tol = 1e-9
    return min(1.0, sum(math.exp(lp) for lp in log_pmf if lp <= observed + tol))


def _confluence_hit_rate(df, align_threshold: int, horizon: int):
    """Confluence's comparable strategy: trade whenever confluence is fully
    aligned, direction = sign(confluence). hit = forward return agreed with
    that direction. This is backtest.py's bull/bear hit-rate logic, just
    combined into one number so it lines up with squeeze/bounce's framing.
    """
    with_returns = backtest_mod.compute_forward_returns(df, horizon)
    valid = with_returns.dropna(subset=["fwd_return", "confluence"])
    aligned = valid[valid["confluence"].abs() == align_threshold]
    if len(aligned) == 0:
        return None, 0, 0
    hits = np.where(aligned["confluence"] > 0, aligned["fwd_return"] > 0, aligned["fwd_return"] < 0)
    n = int(len(aligned))
    k = int(hits.sum())
    return k / n, n, k


def _event_hit_rate(events_found: list):
    with_forward = [e for e in events_found if e["has_forward"]]
    if not with_forward:
        return None, 0, 0
    n = len(with_forward)
    k = sum(1 for e in with_forward if e["hit"])
    return k / n, n, k


def _strategy_stat(hit_rate, n: int, k: int) -> dict:
    ci_low, ci_high = _wilson_interval(k, n) if n else (None, None)
    p_value = _binomial_two_sided_pvalue(k, n) if n else None
    return {
        "hit_rate": hit_rate, "n": n, "k": k,
        "ci_low": ci_low, "ci_high": ci_high, "p_value": p_value,
    }


def evaluate_ticker(conn, ticker: str, params: dict, bw_percentile: float = 10.0,
                     confirm_bars: int = 3) -> dict:
    """Run all strategies on one ticker's full history (via
    engine.analyze_ticker(), so this never sees different indicator numbers
    than the scoreboard/reports do). Does NOT decide a winner -- that needs
    the Bonferroni correction factor computed across the whole scan, which
    only run_strategy_comparison() has visibility into.
    """
    result = engine.analyze_ticker(conn, ticker, params)
    df = result["df"]

    conf_hit, conf_n, conf_k = _confluence_hit_rate(df, params["align_threshold"], params["horizon"])
    squeeze_events = squeeze.find_events(
        df, align_threshold=params["align_threshold"], horizon=params["horizon"], bw_percentile=bw_percentile,
    )
    sq_hit, sq_n, sq_k = _event_hit_rate(squeeze_events)
    bounce_events = bounce.find_events(
        df, align_threshold=params["align_threshold"], horizon=params["horizon"], confirm_bars=confirm_bars,
    )
    bc_hit, bc_n, bc_k = _event_hit_rate(bounce_events)

    # Squeeze requires confluence to be FULLY aligned that day; Bounce
    # requires it NOT be (a ranging read) -- the two conditions are mutually
    # exclusive by construction, so a bar can never qualify as both. That
    # makes their union a well-defined "trade whichever applies" adaptive
    # signal: Squeeze for a trending/breakout regime, Bounce for a ranging
    # one, blended into one combined hit rate instead of picking just one.
    combo_hit, combo_n, combo_k = _event_hit_rate(squeeze_events + bounce_events)

    strategies = {
        "confluence": _strategy_stat(conf_hit, conf_n, conf_k),
        "squeeze": _strategy_stat(sq_hit, sq_n, sq_k),
        "bounce": _strategy_stat(bc_hit, bc_n, bc_k),
        "combined": _strategy_stat(combo_hit, combo_n, combo_k),
    }

    return {
        "ticker": ticker,
        "sector": sector_mod.get_sector(conn, ticker),
        "close": result["close"],
        "strategies": strategies,
        "best_strategy": None,  # filled in by run_strategy_comparison()
    }


def run_strategy_comparison(conn, tickers, params: dict = None, bw_percentile: float = 10.0,
                             confirm_bars: int = 3, min_events: int = 30) -> dict:
    """Evaluate every ticker, then decide each one's "best" strategy using a
    Bonferroni-corrected significance test across the *whole* scan (not per
    ticker) -- the correction factor depends on how many strategy/ticker
    comparisons were actually run, so it can only be computed once every
    ticker is in. Same "hand-picked tickers only" scoping as
    run_squeeze_scan/run_bounce_scan: this walks full history three times
    per ticker, so it's a lot slower than a latest-bar scoreboard update.
    """
    params = engine.resolve_params(params)
    run_timestamp = datetime.datetime.now().isoformat(timespec="seconds")

    tickers_out = []
    failures = []
    for ticker in tickers:
        try:
            tickers_out.append(evaluate_ticker(
                conn, ticker, params, bw_percentile=bw_percentile, confirm_bars=confirm_bars,
            ))
        except engine.TickerAnalysisError as exc:
            logger.warning("Strategy comparison skipping %s: %s", ticker, exc)
            failures.append({"ticker": ticker, "error": str(exc)})
        except Exception as exc:  # noqa: BLE001 - one bad ticker must not kill the scan
            logger.exception("Unexpected error evaluating %s for strategy comparison", ticker)
            failures.append({"ticker": ticker, "error": str(exc)})

    total_tests = sum(
        1 for entry in tickers_out for stat in entry["strategies"].values()
        if stat["n"] >= min_events
    )
    alpha_corrected = (ALPHA / total_tests) if total_tests else ALPHA

    for entry in tickers_out:
        significant = {
            name: stat for name, stat in entry["strategies"].items()
            if stat["n"] >= min_events and stat["hit_rate"] is not None
            and stat["hit_rate"] > 0.5 and stat["p_value"] is not None
            and stat["p_value"] < alpha_corrected
        }
        entry["best_strategy"] = (
            max(significant, key=lambda name: significant[name]["hit_rate"]) if significant else None
        )

    sectors = {}
    for entry in tickers_out:
        sectors.setdefault(entry["sector"], []).append(entry)
    for entries in sectors.values():
        entries.sort(key=lambda e: e["ticker"])

    return {
        "run_timestamp": run_timestamp,
        "params": params,
        "bw_percentile": bw_percentile,
        "confirm_bars": confirm_bars,
        "min_events": min_events,
        "total_tests": total_tests,
        "alpha_corrected": alpha_corrected,
        "sectors": sectors,
        "tickers": tickers_out,
        "failures": failures,
    }
