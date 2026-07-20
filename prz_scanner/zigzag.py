"""Multi-depth zigzag — 1:1 port of the Pine ZIGZAG D* blocks.

Pine uses `ta.pivothigh(high, depth, depth)` / `ta.pivotlow(low, depth, depth)`:
a bar is a pivot high iff its `high` is strictly greater than the `high` of the
`depth` bars to its LEFT and the `depth` bars to its RIGHT (symmetric window).
The pivot is only *confirmed* `depth` bars after it occurs (lookahead-safe delay)
— but since we scan on the last bar over a fully-formed history, we simply detect
all confirmed pivots by scanning bars whose right window fits within the data.

After detecting each raw pivot, Pine folds consecutive same-direction pivots into
one, keeping the more extreme (higher high / lower low). We replicate that exactly,
including the `time[depth]` bookkeeping (here: the integer bar index of the pivot).
"""

from typing import List, Tuple
import numpy as np


# A zigzag point: (price, bar_index, is_high)
ZPoint = Tuple[float, int, bool]


def _pivot_high(high: np.ndarray, i: int, depth: int) -> bool:
    """True if bar i is a pivot high with symmetric window `depth`.

    Matches ta.pivothigh: high[i] must be >= all in left window and >= all in
    right window, and strictly greater than at least the immediate neighbours.
    ta.pivothigh treats the pivot as the strict local max; ties on either side
    disqualify it. We use strict > against both windows (Pine semantics).
    """
    hv = high[i]
    for j in range(i - depth, i):
        if high[j] >= hv:
            return False
    for j in range(i + 1, i + depth + 1):
        if high[j] >= hv:
            return False
    return True


def _pivot_low(low: np.ndarray, i: int, depth: int) -> bool:
    lv = low[i]
    for j in range(i - depth, i):
        if low[j] <= lv:
            return False
    for j in range(i + 1, i + depth + 1):
        if low[j] <= lv:
            return False
    return True


def compute_zigzag(high: np.ndarray, low: np.ndarray, depth: int,
                   max_points: int = 20) -> List[ZPoint]:
    """Return the zigzag pivot list for a given depth.

    Replicates Pine's per-depth array (p*p / p*b / p*t) capped at `max_points`
    (Pine keeps the last 20 via `while size > 20: shift`).
    """
    n = len(high)
    pts: List[ZPoint] = []  # each: [price, bar_index, is_high]

    # Iterate bars left->right; a pivot at i is confirmable once i+depth < n.
    # Pine processes bars in order and the "current" pivot is reported at bar
    # i+depth (time[depth] = the pivot's own bar). Order of detection here is
    # by pivot bar-index ascending, matching Pine's temporal push order.
    for i in range(depth, n - depth):
        is_ph = _pivot_high(high, i, depth)
        is_pl = _pivot_low(low, i, depth)

        # A bar can't be both; if degenerate, prefer high (Pine evals ph first).
        if is_ph:
            _merge(pts, high[i], i, True)
        if is_pl:
            _merge(pts, low[i], i, False)

    # Keep only the last `max_points` (Pine: while size>20 shift from front).
    if len(pts) > max_points:
        pts = pts[-max_points:]
    return [(p[0], p[1], p[2]) for p in pts]


def _merge(pts: list, price: float, bar_idx: int, is_high: bool) -> None:
    """Fold consecutive same-direction pivots, keeping the more extreme one.

    Mirrors the Pine push/set logic:
      if last pivot same direction: replace only if new is more extreme
      else: push new pivot.
    """
    if pts:
        last = pts[-1]
        if last[2] == is_high:
            if is_high:
                if price > last[0]:
                    pts[-1] = [price, bar_idx, is_high]
            else:
                if price < last[0]:
                    pts[-1] = [price, bar_idx, is_high]
            return
    pts.append([price, bar_idx, is_high])
