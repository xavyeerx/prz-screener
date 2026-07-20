"""Scan the watchlist, apply the BUY proximity filter, pick best per stock.

Filter (PRD §5 — [DEVIATION] proximity concept, not in Pine):
  A stock PASSES if it has >=1 BULLISH pattern whose PRZ is either
    (a) already containing close (prz_lo <= close <= prz_hi), OR
    (b) close is ABOVE the PRZ within proximity_pct heading down toward it
        i.e. 0 < (close - prz_hi)/prz_hi*100 <= proximity_pct
  Valid/invalid is reported but NOT a pass condition.

Best-pattern selection per stock (Pine f_pickBest priority):
  1. valid > invalid   2. closer to price   3. XABCD (all are here)   4. score.

Chart, however, shows ALL detected PRZ (buy AND sell) — selection only ranks
the "best buy" for the summary. See chart_render.py.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional
import numpy as np
import pandas as pd

from .config import Config
from .patterns import Detection, scan_points
from .zigzag import compute_zigzag


@dataclass
class StockResult:
    ticker: str
    df: pd.DataFrame
    all_dets: List[Detection]      # every detection (buy+sell) for charting
    best_buy: Optional[Detection]  # ranked best bullish for summary
    passed: bool
    realtime_close: Optional[float] = None  # harga real-time (5m delayed), None jika tidak tersedia


def _dedup(dets: List[Detection]) -> List[Detection]:
    """Collapse near-identical detections (same pattern/dir/PRZ) across
    depth+tolerance passes, keeping the higher score (prefer strict)."""
    seen: Dict[tuple, Detection] = {}
    for d in dets:
        key = (d.pattern, d.bull, round(d.prz_lo, 4), round(d.prz_hi, 4))
        cur = seen.get(key)
        if cur is None or d.score > cur.score or (d.is_strict and not cur.is_strict):
            seen[key] = d
    return list(seen.values())


def scan_stock(ticker: str, df: pd.DataFrame, cfg: Config,
               realtime_price: Optional[float] = None) -> StockResult:
    """Scan one stock. realtime_price overrides last candle close for proximity
    check & display — pattern detection always uses the full historical array."""
    high = df["High"].to_numpy(dtype=float)
    low = df["Low"].to_numpy(dtype=float)
    close = df["Close"].to_numpy(dtype=float)
    # Pakai harga real-time untuk proximity & display jika tersedia.
    # Pattern detection (zigzag, XABCD) tetap pakai seluruh array historis.
    last_close = realtime_price if realtime_price is not None else close[-1]

    dets: List[Detection] = []
    tol_passes = []
    if cfg.enable_strict:
        tol_passes.append((cfg.tol_strict, True))
    if cfg.enable_loose:
        tol_passes.append((cfg.tol_loose, False))

    for depth in cfg.depths:
        pts = compute_zigzag(high, low, depth)
        for tol_val, is_strict in tol_passes:
            found = scan_points(ticker, pts, high, low, close,
                                tol_val, is_strict, cfg)
            for d in found:
                d.depth = depth
            dets.extend(found)

    dets = _dedup(dets)

    # ---- proximity filter on BULLISH detections ----
    def prox_ok(d: Detection) -> bool:
        if not d.bull:
            return False
        if d.prz_lo <= last_close <= d.prz_hi:
            return True  # inside PRZ
        # above PRZ, heading down toward it, within proximity_pct
        if last_close > d.prz_hi:
            gap = (last_close - d.prz_hi) / d.prz_hi * 100
            return gap <= cfg.proximity_pct
        return False

    buy_candidates = [d for d in dets if prox_ok(d)]
    passed = len(buy_candidates) > 0

    best_buy = None
    if buy_candidates:
        # Pine f_pickBest: valid first, then nearest to price, then score.
        def rank(d: Detection):
            inside = d.prz_lo <= last_close <= d.prz_hi
            dist = 0.0 if inside else abs(last_close - d.prz_hi) / d.prz_hi
            return (0 if d.valid else 1, dist, -d.score)
        best_buy = sorted(buy_candidates, key=rank)[0]

    return StockResult(ticker=ticker, df=df, all_dets=dets,
                       best_buy=best_buy, passed=passed,
                       realtime_close=realtime_price)


def scan_watchlist(data: Dict[str, pd.DataFrame], cfg: Config,
                   realtime_prices: Dict[str, float] = None) -> List[StockResult]:
    """Scan all tickers. realtime_prices dict {ticker -> price} overrides
    last candle close for proximity check and display."""
    if realtime_prices is None:
        realtime_prices = {}
    results = []
    for ticker, df in data.items():
        try:
            rt_price = realtime_prices.get(ticker)
            res = scan_stock(ticker, df, cfg, realtime_price=rt_price)
            if res.passed:
                results.append(res)
        except Exception as e:
            print(f"[WARN] scan failed {ticker}: {e}")
    # order: inside-PRZ first, then nearest, then score
    def order(r: StockResult):
        d = r.best_buy
        return (abs(d.dist_pct), -d.score)
    results.sort(key=order)
    return results
