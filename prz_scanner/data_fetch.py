"""yfinance wrapper — supports Daily, Weekly, and 4H (resampled) timeframes.

Rate Limiting & VPS Notes
--------------------------
yfinance >= 0.2.x TIDAK raise exception saat rate-limited — ia hanya print
warning dan return DataFrame kosong. Solusi terbaik:

1. **curl_cffi session** (primary): impersonate browser Chrome di level TLS.
   Paling efektif untuk bypass Yahoo Finance rate-limit di VPS/cloud IP.
   Install: pip install curl-cffi

2. **Custom User-Agent session** (fallback jika curl_cffi tidak ada):
   Kurang efektif di VPS tapi tetap dicoba.

3. **Retry dengan sleep** (ketika hasil kosong): sleep 15s/30s/60s lalu coba lagi
   karena rate-limit Yahoo bersifat sementara.
"""

import time
import random
import logging
from typing import Dict, Optional
import pandas as pd

try:
    import yfinance as yf
except ImportError:  # pragma: no cover
    yf = None

from .config import Config, ticker_to_yf

log = logging.getLogger(__name__)


# ── Session factory ──────────────────────────────────────────────────────────

def _make_session():
    """Buat HTTP session yang meminimalkan rate-limit dari Yahoo Finance.

    Prioritas:
    1. curl_cffi  — impersonate Chrome TLS, paling efektif di VPS
    2. requests   — dengan custom User-Agent sebagai fallback
    """
    try:
        from curl_cffi import requests as curl_requests
        session = curl_requests.Session(impersonate="chrome110")
        log.debug("Using curl_cffi session (Chrome TLS impersonation)")
        return session
    except ImportError:
        pass

    import requests as req_lib
    session = req_lib.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
    })
    log.debug("Using requests session (custom User-Agent)")
    return session


# Buat satu session global, di-reuse untuk semua request
_SESSION = None


def _get_session():
    global _SESSION
    if _SESSION is None:
        _SESSION = _make_session()
    return _SESSION


# ── OHLCV helpers ────────────────────────────────────────────────────────────

def _resample_4h(df: pd.DataFrame) -> pd.DataFrame:
    """Resample intraday (60m) bars to 4H OHLCV."""
    agg = {"Open": "first", "High": "max", "Low": "min",
           "Close": "last", "Volume": "sum"}
    out = df.resample("4h").agg(agg).dropna(how="any")
    return out


def _normalize(df: pd.DataFrame) -> Optional[pd.DataFrame]:
    """Ensure columns Open/High/Low/Close/Volume and drop NaN rows."""
    if df is None or df.empty:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = df.columns.get_level_values(0)
    need = ["Open", "High", "Low", "Close"]
    if not all(c in df.columns for c in need):
        return None
    df = df[[c for c in ["Open", "High", "Low", "Close", "Volume"]
             if c in df.columns]].dropna(how="any")
    return df if len(df) > 0 else None


# ── Download with retry ──────────────────────────────────────────────────────

def _download(yt: str, period: str, interval: str,
              session=None) -> Optional[pd.DataFrame]:
    """Single yf.download() call menggunakan session."""
    try:
        df = yf.download(
            yt, period=period, interval=interval,
            auto_adjust=False, progress=False,
            session=session,
        )
        return df
    except Exception as e:
        log.debug(f"download exception {yt}: {e}")
        return None


def _download_with_retry(yt: str, period: str, interval: str,
                          code: str = "") -> Optional[pd.DataFrame]:
    """Coba download, retry jika hasil kosong (rate-limited).

    yfinance TIDAK raise exception — ia return kosong dan print warning.
    Jadi kita deteksi dari hasil kosong, bukan dari exception.

    Strategi:
      attempt 1 : curl_cffi / custom-UA session
      attempt 2 : tunggu 15s, coba lagi dengan session baru
      attempt 3 : tunggu 30s, coba dengan Ticker.history()
    """
    sess = _get_session()
    label = code or yt

    # Attempt 1: pakai session
    df = _download(yt, period, interval, session=sess)
    result = _normalize(df)
    if result is not None:
        return result

    # Attempt 2: tunggu 15s, session baru
    wait2 = 15 + random.uniform(0, 5)
    print(f"  [RETRY] {label}: data kosong (rate-limit?), tunggu {wait2:.0f}s...")
    time.sleep(wait2)
    # Reset session supaya dapat koneksi baru
    global _SESSION
    _SESSION = _make_session()
    df = _download(yt, period, interval, session=_SESSION)
    result = _normalize(df)
    if result is not None:
        return result

    # Attempt 3: tunggu 30s lalu coba Ticker.history()
    wait3 = 30 + random.uniform(0, 10)
    print(f"  [RETRY] {label}: masih kosong, tunggu {wait3:.0f}s lalu Ticker.history()...")
    time.sleep(wait3)
    try:
        t = yf.Ticker(yt)
        df2 = t.history(period=period, interval=interval, auto_adjust=False)
        result2 = _normalize(df2)
        if result2 is not None:
            print(f"  [OK] {label}: berhasil via Ticker.history()")
            return result2
    except Exception as e:
        log.debug(f"Ticker.history() {yt}: {e}")

    print(f"  [FAIL] {label}: semua metode gagal, skip ticker ini.")
    return None


# ── Public API ───────────────────────────────────────────────────────────────

def fetch_one(code: str, cfg: Config) -> Optional[pd.DataFrame]:
    """Fetch a single ticker's OHLC for the configured timeframe."""
    if yf is None:
        raise RuntimeError("yfinance not installed. pip install yfinance")
    yt = ticker_to_yf(code)

    if cfg.timeframe == "1d":
        return _download_with_retry(yt, cfg.period_daily, "1d", code)

    elif cfg.timeframe == "1wk":
        return _download_with_retry(yt, cfg.period_weekly, "1wk", code)

    else:  # "4h" -> fetch 60m and resample
        df = _download_with_retry(yt, cfg.period_intraday, "60m", code)
        if df is None:
            return None
        return _resample_4h(df)


def fetch_all(cfg: Config, pause: float = 2.0) -> Dict[str, pd.DataFrame]:
    """Fetch every ticker in the watchlist. Skips failures, never crashes.

    pause=2.0s default untuk VPS (lebih konservatif agar tidak trigger rate-limit).
    """
    out: Dict[str, pd.DataFrame] = {}
    for code in cfg.watchlist:
        df = fetch_one(code, cfg)
        if df is not None and len(df) >= 40:
            out[code] = df
        else:
            print(f"[SKIP] {code}: no/insufficient data")
        time.sleep(pause + random.uniform(0, 1.0))  # jitter
    return out


def fetch_realtime_prices(codes: list, pause: float = 0.0) -> Dict[str, float]:
    """Fetch latest traded price for each ticker (~5min delayed).

    Pakai session yang sama (curl_cffi/custom-UA) untuk consistency.
    """
    if yf is None:
        return {}
    if not codes:
        return {}

    prices: Dict[str, float] = {}
    sess = _get_session()
    yt_codes = [ticker_to_yf(c) for c in codes]

    try:
        df = yf.download(
            yt_codes, period="2d", interval="5m",
            auto_adjust=False, progress=False,
            group_by="ticker", session=sess,
        )
        if df is None or df.empty:
            raise ValueError("empty realtime batch")

        for code, yt in zip(codes, yt_codes):
            try:
                if isinstance(df.columns, pd.MultiIndex):
                    closes = df[yt]["Close"].dropna()
                else:
                    closes = df["Close"].dropna()
                if len(closes) > 0:
                    prices[code] = float(closes.iloc[-1])
            except Exception:
                pass

    except Exception as e:
        log.debug(f"fetch_realtime_prices batch failed: {e}")
        # Fallback satu-satu via fast_info
        for code in codes:
            try:
                t = yf.Ticker(ticker_to_yf(code))
                fi = t.fast_info
                p = fi.get("lastPrice") or fi.get("previousClose")
                if p:
                    prices[code] = float(p)
            except Exception:
                pass

    return prices
