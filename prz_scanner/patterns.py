"""Harmonic XABCD detection + PRZ + validity — 1:1 port of prz.pine `scan()`.

Pine reference (prz.pine lines ~377-451). Each pattern in Pine:
  - checks B retracement (br = ab/xa) and C retracement (cr = bc/ab)
  - checks BC-projection gate (bcp = bc/ab) via bcGate
  - projects D as a single fixed multiple of XA from A (bull: A - k*XA)
  - builds a box D +/- r  (r a fixed fraction of XA)
  - filters by max_dist from close, and low>0
  - runs przStatus for validity/history/flip, then draws.

Helper equivalences:
  safeDiv, inR, inMM, bcGate  -> functions below.

[DEVIATION] additions (no Pine equivalent), clearly separated:
  - numeric `score` (fidelity/confluence/strictness/psy/sweet-spot)
  - PRZ width guard `prz_maxw`
  - TP1/TP2/TP3 & stop levels for the summary/chart
These do NOT change which patterns/PRZ are detected — only annotate them.
"""

from dataclasses import dataclass
from typing import List, Optional
import numpy as np

from .zigzag import ZPoint


# ---------------------------------------------------------------------------
# Pine helpers
# ---------------------------------------------------------------------------
def safe_div(a: float, b: float) -> float:
    return a / b if b != 0 else 0.0


def in_r(v: float, ideal: float, t: float) -> bool:
    """Pine inR: v within +/- t% of a single ideal ratio."""
    return ideal * (1 - t / 100) <= v <= ideal * (1 + t / 100)


def in_mm(v: float, lo: float, hi: float, t: float) -> bool:
    """Pine inMM: v within [lo*(1-t%), hi*(1+t%)]."""
    return lo * (1 - t / 100) <= v <= hi * (1 + t / 100)


def bc_gate(v: float, lo: float, hi: float, t: float, strict_bc: bool) -> bool:
    """Pine bcGate: if strict_bc OFF -> always true; else inMM."""
    return (not strict_bc) or in_mm(v, lo, hi, t)


# ---------------------------------------------------------------------------
# Pattern spec table (exactly as in Pine scan()).
#   name, color, B-check, C-check, BC-gate range, D projection k, box r-fraction
# B-check kinds: ("r", ideal) uses inR ; ("mm", lo, hi) uses inMM.
# Shark is special (two-sided PRZ), handled inline.
# ---------------------------------------------------------------------------
@dataclass
class Detection:
    ticker: str
    pattern: str
    color: str
    bull: bool
    depth: int
    is_strict: bool
    # geometry (bar indices into the OHLC arrays + prices)
    xi: int; xP: float
    ai: int; aP: float
    bi: int; bP: float
    ci: int; cP: float
    prz_hi: float
    prz_lo: float
    # ratios
    br: float
    cr: float
    bcp: float
    # validity (przStatus): 0 active, 1 confirmed-reversal, 2 invalid, 3 flip
    status: int = 0
    first_touch_idx: int = -1
    end_idx: int = -1
    # [DEVIATION] annotations
    score: float = 0.0
    dist_pct: float = 0.0        # signed % distance of close from PRZ mid
    tp1: float = 0.0
    tp2: float = 0.0
    tp3: float = 0.0
    stop: float = 0.0

    @property
    def valid(self) -> bool:
        # status 2 = invalid (broke against pattern & never recovered).
        return self.status != 2

    @property
    def prz_mid(self) -> float:
        return (self.prz_hi + self.prz_lo) / 2


# ---------------------------------------------------------------------------
# przStatus — 1:1 port of Pine przStatus (prz.pine lines ~82-133).
# Scans bars AFTER pivot C (startIdx) forward to last bar.
#   returns (status, first_touch_idx, end_idx)
# status: 0 active, 1 confirmed reversal (per pattern dir), 2 invalid, 3 flip.
# ---------------------------------------------------------------------------
def prz_status(high: np.ndarray, low: np.ndarray, close: np.ndarray,
               prz_hi: float, prz_lo: float, is_bull: bool,
               start_idx: int, rev_bars: int) -> tuple:
    n = len(high)
    result = 0
    touched = False
    broke = False
    touch_idx = -1
    first_touch = -1
    end_idx = start_idx

    # Pine scans from the pivot forward to now. start_idx is pivot C's bar.
    for i in range(start_idx + 1, n):
        h = high[i]; l = low[i]; c = close[i]
        if not touched:
            if l <= prz_hi and h >= prz_lo:
                touched = True
                touch_idx = i
                first_touch = i
                end_idx = i
        else:
            if l <= prz_hi and h >= prz_lo:
                end_idx = i
            bars_since = i - touch_idx
            if is_bull:
                if bars_since >= rev_bars and c > prz_hi:
                    result = 3 if broke else 1
                    end_idx = i
                    break
                if c < prz_lo * 0.97:
                    broke = True
                    end_idx = i
            else:
                if bars_since >= rev_bars and c < prz_lo:
                    result = 3 if broke else 1
                    end_idx = i
                    break
                if c > prz_hi * 1.03:
                    broke = True
                    end_idx = i

    if broke and result == 0:
        result = 2
    return result, first_touch, end_idx


# ---------------------------------------------------------------------------
# [DEVIATION] score + targets
# ---------------------------------------------------------------------------
def _power_near(k_used: float) -> float:
    """[DEVIATION] sweet-spot: closeness of the D-projection multiple to the
    0.886-1.13 'power zone'. 1.0 inside, decaying outside."""
    lo, hi = 0.886, 1.13
    if lo <= k_used <= hi:
        return 1.0
    d = (lo - k_used) if k_used < lo else (k_used - hi)
    return max(0.0, 1.0 - d / 0.5)


def _score(det: Detection, ideal_b: float, ideal_c: float, k_used: float,
           prz_width_pct: float) -> float:
    """[DEVIATION] 100*(0.42*fid+0.28*conf+0.12*strict+0.06*psy+0.12*sweet)."""
    fb = max(0.0, 1.0 - abs(det.br - ideal_b) / max(ideal_b, 1e-9))
    fc = max(0.0, 1.0 - abs(det.cr - ideal_c) / max(ideal_c, 1e-9))
    fidelity = (fb + fc) / 2
    confluence = max(0.0, 1.0 - prz_width_pct / 15.0)   # tighter box -> higher
    strictness = 1.0 if det.is_strict else 0.5
    psy = 0.0  # round-number bonus not in Pine; left neutral
    sweet = _power_near(k_used)
    return 100.0 * (0.42 * fidelity + 0.28 * confluence + 0.12 * strictness
                    + 0.06 * psy + 0.12 * sweet)


def _targets(det: Detection) -> None:
    """[DEVIATION] Fib-based TP/SL off the XA leg from D (PRZ mid)."""
    xa = abs(det.aP - det.xP)
    d = det.prz_mid
    if det.bull:
        det.tp1 = d + 0.382 * xa
        det.tp2 = d + 0.618 * xa
        det.tp3 = d + 1.000 * xa
        det.stop = det.prz_lo - 0.10 * xa
    else:
        det.tp1 = d - 0.382 * xa
        det.tp2 = d - 0.618 * xa
        det.tp3 = d - 1.000 * xa
        det.stop = det.prz_hi + 0.10 * xa


# ---------------------------------------------------------------------------
# Main scan over one zigzag point list — 1:1 port of Pine scan().
# ---------------------------------------------------------------------------
def scan_points(ticker: str, points: List[ZPoint],
                high: np.ndarray, low: np.ndarray, close: np.ndarray,
                tol_val: float, is_strict: bool, cfg) -> List[Detection]:
    dets: List[Detection] = []
    total = len(points)
    if total < 5:
        return dets

    last_close = close[-1]
    max_w = min(3, total - 4)   # Pine: maxW = min(3, totalP-4)

    for w in range(0, max_w + 1):
        idx = total - 4 - w
        if idx < 0:
            continue
        xP, xi, x_hi = points[idx]
        aP, ai, _ = points[idx + 1]
        bP, bi, _ = points[idx + 2]
        cP, ci, _ = points[idx + 3]
        bull = not x_hi

        # alternation check (Pine a1,a2,a3)
        t0 = points[idx][2]; t1 = points[idx + 1][2]
        t2 = points[idx + 2][2]; t3 = points[idx + 3][2]
        if not (t0 != t1 and t1 != t2 and t2 != t3):
            continue

        xa = abs(aP - xP)
        ab = abs(bP - aP)
        bc = abs(cP - bP)
        br = safe_div(ab, xa)
        cr = safe_div(bc, ab)
        bcp = safe_div(bc, ab)
        if xa <= 0:
            continue

        pe = cfg.patterns_enabled
        sbc = cfg.strict_bc

        def emit(name, color, d, r, ideal_b, ideal_c, k_used,
                 prz_hi=None, prz_lo=None):
            if prz_hi is None:
                prz_hi = d + r
                prz_lo = d - r
            if prz_lo <= 0:
                return
            mid = (prz_hi + prz_lo) / 2
            if abs((mid - last_close) / last_close) * 100 > cfg.max_dist:
                return
            width_pct = (prz_hi - prz_lo) / mid * 100
            if width_pct > cfg.prz_maxw:      # [DEVIATION] width guard
                return
            status, ft, ei = prz_status(high, low, close, prz_hi, prz_lo,
                                        bull, ci, cfg.rev_bars)
            det = Detection(
                ticker=ticker, pattern=name, color=color, bull=bull,
                depth=0, is_strict=is_strict,
                xi=xi, xP=xP, ai=ai, aP=aP, bi=bi, bP=bP, ci=ci, cP=cP,
                prz_hi=prz_hi, prz_lo=prz_lo, br=br, cr=cr, bcp=bcp,
                status=status, first_touch_idx=ft, end_idx=ei,
            )
            det.dist_pct = (last_close - mid) / mid * 100
            det.score = _score(det, ideal_b, ideal_c, k_used, width_pct)
            _targets(det)
            dets.append(det)

        # ---- GARTLEY: B=0.618 XA, D=0.786 XA, BC 1.13-1.618 ----
        if pe["Gartley"] and in_r(br, 0.618, tol_val) and \
                in_mm(cr, 0.382, 0.886, tol_val) and \
                bc_gate(bcp, 1.13, 1.618, tol_val, sbc):
            gd = aP - 0.786 * xa if bull else aP + 0.786 * xa
            emit("Gartley", "green", gd, xa * 0.03, 0.618, 0.634, 0.786)

        # ---- BAT: B=0.382-0.50 XA, D=0.886 XA, BC 1.618-2.618 ----
        if pe["Bat"] and in_mm(br, 0.382, 0.50, tol_val) and \
                in_mm(cr, 0.382, 0.886, tol_val) and \
                bc_gate(bcp, 1.618, 2.618, tol_val, sbc):
            bd = aP - 0.886 * xa if bull else aP + 0.886 * xa
            emit("Bat", "blue", bd, xa * 0.03, 0.441, 0.634, 0.886)

        # ---- BUTTERFLY: B=0.786 XA, D=1.27 XA, BC 1.618-2.24 ----
        if pe["Butterfly"] and in_r(br, 0.786, tol_val) and \
                in_mm(cr, 0.382, 0.886, tol_val) and \
                bc_gate(bcp, 1.618, 2.24, tol_val, sbc):
            fd = aP - 1.27 * xa if bull else aP + 1.27 * xa
            emit("Butterfly", "purple", fd, xa * 0.04, 0.786, 0.634, 1.27)

        # ---- CRAB: B=0.382-0.618 XA, D=1.618 XA, BC 2.24-3.618 ----
        if pe["Crab"] and in_mm(br, 0.382, 0.618, tol_val) and \
                in_mm(cr, 0.382, 0.886, tol_val) and \
                bc_gate(bcp, 2.24, 3.618, tol_val, sbc):
            cd = aP - 1.618 * xa if bull else aP + 1.618 * xa
            emit("Crab", "orange", cd, xa * 0.05, 0.5, 0.634, 1.618)

        # ---- SHARK: B=0.382-0.618, D=0.886-1.13 XA (two-sided), BC>=1.13 ----
        if pe["Shark"] and in_mm(br, 0.382, 0.618, tol_val) and \
                bcp >= 1.13 * (1 - tol_val / 100) and \
                bc_gate(bcp, 1.13, 1.618, tol_val, sbc):
            su = aP - 0.886 * xa if bull else aP + 0.886 * xa
            sl2 = aP - 1.13 * xa if bull else aP + 1.13 * xa
            shi = max(su, sl2); slo = min(su, sl2)
            emit("Shark", "red", None, None, 0.5, 0.634, 1.0,
                 prz_hi=shi, prz_lo=slo)

    return dets
