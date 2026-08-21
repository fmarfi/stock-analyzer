"""Shared event-detection plumbing for the strategy scanners (squeeze.py,
bounce.py): turn a boolean condition Series into a handful of genuinely
distinct events instead of every bar a persistent/flickering condition holds
true for, and slice a window of bars around one for a snapshot chart.

A percentile-style threshold is met ~N% of the time by construction, and a
condition can flicker true/false/true across a few bars near its boundary --
naively reporting every qualifying bar produces dozens of near-duplicates a
few days apart. `anchored_events()` merges any True bars within
`min_gap_bars` of the previous one (even across brief False gaps) into one
cluster and keeps whichever bar in it best matches `priority`, so a strategy
scan reads as a short list of setups worth looking at.
"""

import pandas as pd


def anchored_events(qualifies: pd.Series, priority: pd.Series, min_gap_bars: int, mode: str = "min") -> list:
    """Positions (integer, oldest first) of one event per cluster of
    qualifying bars. `priority` picks the representative bar within a
    cluster: the lowest value if mode="min", the highest if mode="max".
    """
    true_positions = [i for i, flag in enumerate(qualifies.to_numpy()) if flag]
    if not true_positions:
        return []

    values = priority.to_numpy()
    better = (lambda a, b: a if values[a] <= values[b] else b) if mode == "min" \
        else (lambda a, b: a if values[a] >= values[b] else b)

    clusters = [[true_positions[0]]]
    for pos in true_positions[1:]:
        if pos - clusters[-1][-1] <= min_gap_bars:
            clusters[-1].append(pos)
        else:
            clusters.append([pos])

    result = []
    for cluster in clusters:
        best = cluster[0]
        for pos in cluster[1:]:
            best = better(best, pos)
        result.append(best)
    return result


def event_window(df: pd.DataFrame, pos: int, pre_bars: int = 40, post_bars: int = 20) -> pd.DataFrame:
    """Slice `df` to a window around index position `pos`: some bars of
    history before the event plus "a little bit future" after it, for a
    snapshot chart. Silently truncates at either end of the available data
    (a recent event may not have `post_bars` of future data yet).
    """
    start = max(0, pos - pre_bars)
    end = min(len(df), pos + post_bars + 1)
    return df.iloc[start:end]
