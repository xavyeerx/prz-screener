"""Telegram notification module for PRZ Scanner.

Sends scan results (summary text + chart PNGs) to a Telegram group/chat.

Credentials are loaded from .env (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID),
or can be passed directly to TelegramSender().

Usage:
    tg = TelegramSender()          # loads from .env
    tg.send_summary(df, timeframe) # send summary table
    tg.send_chart(png_path, caption) # send one chart image
    tg.send_results(results, df, timeframe, out_dir) # all-in-one
"""

import os
import time
from typing import Optional, List
import requests
import pandas as pd

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv optional; fall back to os.environ

from .scanner import StockResult


class TelegramSender:
    """Send messages and photos to a Telegram chat via Bot API."""

    BASE_URL = "https://api.telegram.org/bot{token}/{method}"

    def __init__(self, token: Optional[str] = None, chat_id: Optional[str] = None):
        self.token = token or os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID", "")
        if not self.token:
            raise ValueError(
                "Telegram bot token tidak ditemukan. "
                "Set TELEGRAM_BOT_TOKEN di .env atau pass token= ke TelegramSender()."
            )
        if not self.chat_id:
            raise ValueError(
                "Telegram chat_id tidak ditemukan. "
                "Set TELEGRAM_CHAT_ID di .env atau pass chat_id= ke TelegramSender()."
            )

    def _url(self, method: str) -> str:
        return self.BASE_URL.format(token=self.token, method=method)

    def _post(self, method: str, data: dict = None, files=None, timeout: int = 30) -> dict:
        """POST to Telegram API, raise on HTTP error."""
        r = requests.post(self._url(method), data=data, files=files, timeout=timeout)
        r.raise_for_status()
        resp = r.json()
        if not resp.get("ok"):
            raise RuntimeError(f"Telegram API error: {resp}")
        return resp

    def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        """Send a plain text (or HTML) message."""
        try:
            self._post("sendMessage", data={
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": parse_mode,
            })
            return True
        except Exception as e:
            print(f"[WARN] Telegram sendMessage gagal: {e}")
            return False

    def send_photo(self, photo_path: str, caption: str = "",
                   parse_mode: str = "HTML") -> bool:
        """Send a PNG/JPG photo with optional caption."""
        try:
            with open(photo_path, "rb") as f:
                self._post("sendPhoto", data={
                    "chat_id": self.chat_id,
                    "caption": caption[:1024],   # Telegram caption limit
                    "parse_mode": parse_mode,
                }, files={"photo": f})
            return True
        except Exception as e:
            print(f"[WARN] Telegram sendPhoto gagal ({os.path.basename(photo_path)}): {e}")
            return False

    # ------------------------------------------------------------------
    # High-level helpers
    # ------------------------------------------------------------------

    def send_summary(self, df: pd.DataFrame, timeframe: str,
                     total_scanned: int = 0) -> bool:
        """Send the scan summary as a formatted HTML message."""
        tf_label = {"1d": "Daily", "1wk": "Weekly", "4h": "H4"}.get(timeframe, timeframe.upper())

        if df.empty:
            msg = (
                f"<b>PRZ Scanner - {tf_label}</b>\n"
                f"Tidak ada saham yang mendekati PRZ BUY zone saat ini."
            )
            return self.send_message(msg)

        lines = [
            f"<b>PRZ Scanner - {tf_label}</b>",
            f"<i>{len(df)} saham mendekati PRZ BUY zone"
            + (f" (dari {total_scanned} discan)" if total_scanned else "") + "</i>",
            "",
        ]

        for i, row in df.iterrows():
            inside = row.get("Zone", "") == "INSIDE"
            status_icon = "🟢" if inside else "🟡"
            valid_icon = "✅" if row.get("Valid", "") == "valid" else "⚠️"
            arrow = "⬇️" if row.get("Dist%", 0) > 0 else "📍"

            lines.append(
                f"{status_icon} <b>{row['Ticker']}</b> — {row['Pattern']} "
                f"({row.get('Tol','')}) {valid_icon}\n"
                f"   PRZ: <code>{row['PRZ_low']:.0f}–{row['PRZ_high']:.0f}</code>  "
                f"Close: <code>{row['Close']:.0f}</code>  "
                f"{arrow} <code>{row.get('Dist%', 0):.1f}%</code>\n"
                f"   Score: <code>{row.get('Score',0):.0f}</code>  "
                f"TP1: <code>{row.get('TP1',0):.0f}</code>  "
                f"Stop: <code>{row.get('Stop',0):.0f}</code>"
            )

        msg = "\n".join(lines)
        # Telegram message limit 4096 chars
        if len(msg) > 4096:
            msg = msg[:4050] + "\n\n<i>...truncated</i>"

        return self.send_message(msg)

    def send_results(self, results: List[StockResult], df: pd.DataFrame,
                     timeframe: str, total_scanned: int = 0,
                     pause: float = 1.5) -> int:
        """Send summary + all chart PNGs. Returns count of photos sent."""
        tf_label = {"1d": "Daily", "1wk": "Weekly", "4h": "H4"}.get(timeframe, timeframe.upper())
        print(f"  [TG] Mengirim summary ke Telegram...")
        self.send_summary(df, timeframe, total_scanned)
        time.sleep(0.5)

        sent = 0
        for r in results:
            if r.best_buy is None:
                continue
            bb = r.best_buy
            inside = bb.prz_lo <= float(r.df["Close"].iloc[-1]) <= bb.prz_hi
            status = "INSIDE PRZ" if inside else f"approaching ({bb.dist_pct:.1f}%)"
            valid_str = "valid" if bb.valid else "INVALID"
            caption = (
                f"<b>{r.ticker}</b> | {tf_label} | {bb.pattern} | {valid_str}\n"
                f"PRZ: {bb.prz_lo:.0f} - {bb.prz_hi:.0f}\n"
                f"Close: {float(r.df['Close'].iloc[-1]):.0f} | {status}\n"
                f"Score: {bb.score:.0f} | TP1: {bb.tp1:.0f} | Stop: {bb.stop:.0f}"
            )
            # Find chart file - it may have just been saved to out_dir
            import glob
            from datetime import datetime
            date = datetime.now().strftime("%Y%m%d")
            # Try to find matching PNG
            pattern_glob = os.path.join(r.df.attrs.get("out_dir", ""), f"{r.ticker}_*_{date}.png")
            matches = []
            if hasattr(r, "_chart_path") and r._chart_path:
                matches = [r._chart_path]
            if not matches:
                # Search common output dirs
                for base in ["output/daily", "output/weekly", "output/h4", "output"]:
                    g = glob.glob(os.path.join(base, f"{r.ticker}_*_{date}.png"))
                    matches.extend(g)
            if matches:
                chart_path = max(matches, key=os.path.getmtime)
                print(f"  [TG] Mengirim chart {r.ticker}...")
                ok = self.send_photo(chart_path, caption)
                if ok:
                    sent += 1
                time.sleep(pause)
            else:
                print(f"  [TG] Chart {r.ticker} tidak ditemukan, skip foto.")

        return sent
