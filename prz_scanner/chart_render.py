"""Render a candlestick chart per passing stock with all PRZ overlays.

Per PRD §5/§6: the chart shows ALL detected PRZ (BUY and SELL) for the stock —
not only the buy PRZ that made it pass — mirroring Pine drawing both bestBuy and
bestSell. Overlays: X-A-B-C-D lines, PRZ shaded boxes with labels, TP/SL of the
best buy pattern.
"""

import os
from datetime import datetime
from typing import List

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import mplfinance as mpf

from .patterns import Detection
from .scanner import StockResult


_PATTERN_COLOR = {
    "Gartley": "#2ca02c", "Bat": "#1f77b4", "Butterfly": "#9467bd",
    "Crab": "#ff7f0e", "Shark": "#d62728",
}


def _clip(idx: int, n: int) -> int:
    return max(0, min(idx, n - 1))


def render_chart(res: StockResult, *, timeframe: str, out_dir: str) -> str:
    """Render and save the chart PNG. Returns the file path."""
    df = res.df
    n = len(df)
    dfp = df.copy()
    dfp.index = pd.to_datetime(dfp.index)

    fig, axes = mpf.plot(
        dfp, type="candle", style="charles", volume=False,
        returnfig=True, figsize=(14, 8),
        title=f"{res.ticker}  {timeframe}",
        datetime_format="%Y-%m", xrotation=0,
    )
    ax = axes[0]

    # Rank detections for display: show best buy + best sell prominently,
    # but draw every deduped PRZ (buy and sell).
    buys = [d for d in res.all_dets if d.bull]
    sells = [d for d in res.all_dets if not d.bull]

    def draw(det: Detection, emphasize: bool):
        color = _PATTERN_COLOR.get(det.pattern, "gray")
        xs = [_clip(det.xi, n), _clip(det.ai, n),
              _clip(det.bi, n), _clip(det.ci, n)]
        ys = [det.xP, det.aP, det.bP, det.cP]
        lw = 1.8 if emphasize else 0.9
        alpha = 1.0 if emphasize else 0.5
        ax.plot(xs, ys, color=color, lw=lw, alpha=alpha,
                solid_capstyle="round")
        # XB / AC helper dashed lines
        ax.plot([xs[0], xs[2]], [ys[0], ys[2]], color=color, lw=0.6,
                ls=":", alpha=alpha * 0.6)
        ax.plot([xs[1], xs[3]], [ys[1], ys[3]], color=color, lw=0.6,
                ls=":", alpha=alpha * 0.6)

        # PRZ box from C to right edge
        left = _clip(det.ci, n)
        right = n - 1
        box_color = color
        box_alpha = 0.18 if emphasize else 0.08
        ax.axhspan(det.prz_lo, det.prz_hi, xmin=left / n, xmax=1.0,
                   color=box_color, alpha=box_alpha, zorder=0)

        arrow = "▲BUY" if det.bull else "▼SELL"
        status_txt = {0: "active", 1: "reversal✓", 2: "INVALID",
                      3: "FLIP⚠"}.get(det.status, "")
        star = "★" if det.is_strict else "☆"
        lbl = (f"{star}{arrow} {det.pattern} "
               f"{det.prz_lo:.0f}-{det.prz_hi:.0f} [{status_txt}]")
        ax.annotate(lbl, xy=(right, det.prz_hi),
                    xytext=(-4, 2), textcoords="offset points",
                    ha="right", va="bottom", fontsize=7,
                    color="white",
                    bbox=dict(boxstyle="round,pad=0.2", fc=color,
                              ec="none", alpha=0.85 if emphasize else 0.5))

    for d in sells:
        draw(d, emphasize=(d is _best(sells)))
    for d in buys:
        draw(d, emphasize=(d is res.best_buy))

    # TP/SL lines for best buy
    bb = res.best_buy
    if bb is not None:
        for lvl, name, c in [(bb.tp1, "TP1", "#2ca02c"),
                             (bb.tp2, "TP2", "#2ca02c"),
                             (bb.tp3, "TP3", "#2ca02c"),
                             (bb.stop, "SL", "#d62728")]:
            ax.axhline(lvl, color=c, lw=0.8, ls="--", alpha=0.7)
            ax.annotate(f"{name} {lvl:.0f}", xy=(0, lvl),
                        xytext=(2, 1), textcoords="offset points",
                        fontsize=6, color=c, va="bottom")

    os.makedirs(out_dir, exist_ok=True)
    date = datetime.now().strftime("%Y%m%d")
    path = os.path.join(out_dir, f"{res.ticker}_{timeframe}_{date}.png")
    fig.savefig(path, dpi=110, bbox_inches="tight")
    plt.close(fig)
    return path


def _best(dets: List[Detection]):
    if not dets:
        return None
    return sorted(dets, key=lambda d: -d.score)[0]
