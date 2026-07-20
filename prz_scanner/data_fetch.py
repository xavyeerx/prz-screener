"""yfinance wrapper — supports Daily, Weekly, and 4H (resampled) timeframes.

Validated behaviour for .JK tickers on yfinance:
  - Daily  ('1d') with period '2y'  : fully supported.
  - Weekly ('1wk') with period '5y' : fully supported natively. Weekly bars
    give ~260 candles over 5 years — plenty for all zigzag depths up to 20.
  - '4h' interval: NOT a native yfinance interval. yfinance exposes
    1m/2m/5m/15m/30m/60m/90m/1h/1d/1wk/1mo — there is no '4h'. So for the
    4H timeframe we fetch '60m' (capped ~60 days of history by yfinance for
    intraday) and RESAMPLE to 4H bars locally.
  - Intraday history is limited to ~60 days for sub-daily intervals.
"""

import time
import random
from typing import Dict, Optional
import pandas as pd

try:
    import yfinance as yf
except ImportError:  # pragma: no cover
    yf = None

from .config import Config, ticker_to_yf


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
    # yf.download multi-ticker returns MultiIndex columns; single-ticker flat.
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = df.columns.get_level_values(0)
    need = ["Open", "High", "Low", "Close"]
    if not all(c in df.columns for c in need):
        return None
    df = df[[c for c in ["Open", "High", "Low", "Close", "Volume"]
             if c in df.columns]].dropna(how="any")
    return df if len(df) > 0 else None


_RATE_LIMIT_ERRS = ("Too Many Requests", "Rate limited", "YFRateLimitError", "429")


def _is_rate_limit(exc: Exception) -> bool:
    return any(s in str(exc) for s in _RATE_LIMIT_ERRS)


def _download_with_retry(yt: str, period: str, interval: str,
                         retries: int = 3) -> Optional[pd.DataFrame]:
    """yf.download() with exponential backoff on rate-limit errors.
    Wait schedule: 10s, 30s, 60s (+ up to 5s jitter each time).
    """
    waits = [10, 30, 60]
    for attempt in range(retries):
        try:
            df = yf.download(yt, period=period, interval=interval,
                             auto_adjust=False, progress=False)
            return df
        except Exception as e:
            if _is_rate_limit(e) and attempt < retries - 1:
                wait = waits[attempt] + random.uniform(0, 5)
                print(f"[RATE-LIMIT] {yt} — tunggu {wait:.0f}s lalu retry "
                      f"({attempt+1}/{retries-1})...")
                time.sleep(wait)
            else:
                raise
    return None


def _ticker_history_fallback(yt: str, period: str, interval: str) -> Optional[pd.DataFrame]:
    """Fallback: pakai Ticker.history() jika yf.download() masih rate-limited."""
    try:
        t = yf.Ticker(yt)
        df = t.history(period=period, interval=interval, auto_adjust=False)
        if df is None or df.empty:
            return None
        # Ticker.history() pakai kolom Adj Close bukan Adj Close terpisah
        df = df.rename(columns={"Stock Splits": "Splits"}, errors="ignore")
        return df
    except Exception:
        return None


def fetch_one(code: str, cfg: Config) -> Optional[pd.DataFrame]:
    """Fetch a single ticker's OHLC for the configured timeframe.

    Supported cfg.timeframe values:
      '1d'  — Daily bars, ~2 years history.
      '1wk' — Weekly bars, ~5 years history (native yfinance interval).
      '4h'  — 4-hour bars via 60m fetch + resample, ~60 days history.

    Rate limiting strategy (penting untuk VPS):
      1. yf.download() dengan retry + exponential backoff (10s, 30s, 60s)
      2. Jika masih gagal -> fallback ke Ticker.history()
    """
    if yf is None:
        raise RuntimeError("yfinance not installed. pip install yfinance")
    yt = ticker_to_yf(code)

    def _fetch(period: str, interval: str) -> Optional[pd.DataFrame]:
        """Try download with retry, then fallback to Ticker.history()."""
        try:
            df = _download_with_retry(yt, period, interval)
            result = _normalize(df)
            if result is not None:
                return result
        except Exception as e:
            print(f"[WARN] download failed {code} after retries: {e}")
        # Fallback
        print(f"[FALLBACK] {code}: mencoba Ticker.history()...")
        df2 = _ticker_history_fallback(yt, period, interval)
        return _normalize(df2)

    try:
        if cfg.timeframe == "1d":
            return _fetch(cfg.period_daily, "1d")

        elif cfg.timeframe == "1wk":
            return _fetch(cfg.period_weekly, "1wk")

        else:  # "4h" -> fetch 60m and resample
            df = _fetch(cfg.period_intraday, "60m")
            if df is None:
                return None
            return _resample_4h(df)

    except Exception as e:
        print(f"[WARN] fetch failed {code}: {e}")
        return None


def fetch_all(cfg: Config, pause: float = 1.5) -> Dict[str, pd.DataFrame]:
    """Fetch every ticker in the watchlist. Skips failures, never crashes.

    pause=1.5s default (lebih lambat tapi aman di VPS — kurangi rate-limit error).
    """
    out: Dict[str, pd.DataFrame] = {}
    for code in cfg.watchlist:
        df = fetch_one(code, cfg)
        if df is not None and len(df) >= 40:
            out[code] = df
        else:
            print(f"[SKIP] {code}: no/insufficient data")
        time.sleep(pause + random.uniform(0, 0.5))  # jitter agar tidak terlihat bot
    return out


def fetch_realtime_prices(codes: list, pause: float = 0.0) -> Dict[str, float]:
    """Fetch the latest traded price for each ticker (real-time / ~5min delayed).

    Menggunakan interval '5m' period '1d' agar mendapatkan harga terkini,
    bukan harga close dari candle harian/weekly/H4 yang mungkin sudah stale.

    Ini penting untuk timeframe Weekly & Daily: candle terakhir belum tentu
    mencerminkan harga saat ini (misal Weekly close = Jumat lalu, padahal
    hari ini sudah ada pergerakan baru).

    Returns dict {code -> latest_price}. Ticker yang gagal tidak dimasukkan.
    """
    if yf is None:
        return {}
    if not codes:
        return {}

    prices: Dict[str, float] = {}

    # Batch download lebih efisien untuk banyak ticker
    # Gunakan period='2d' agar dapat data hari ini sekalipun market baru saja buka
    yt_codes = [ticker_to_yf(c) for c in codes]
    try:
        df = yf.download(
            yt_codes, period="2d", interval="5m",
            auto_adjust=False, progress=False, group_by="ticker"
        )
        if df is None or df.empty:
            return prices

        for code, yt in zip(codes, yt_codes):
            try:
                if isinstance(df.columns, pd.MultiIndex):
                    # Multi-ticker: kolom = (ticker, OHLCV)
                    closes = df[yt]["Close"].dropna()
                else:
                    # Single ticker — df langsung flat
                    closes = df["Close"].dropna()
                if len(closes) > 0:
                    prices[code] = float(closes.iloc[-1])
            except Exception:
                pass
    except Exception as e:
        print(f"[WARN] fetch_realtime_prices batch failed: {e}")
        # Fallback: coba satu-satu dengan fast_info
        for code in codes:
            try:
                yt = ticker_to_yf(code)
                t = yf.Ticker(yt)
                fi = t.fast_info
                p = fi.get("lastPrice") or fi.get("previousClose")
                if p:
                    prices[code] = float(p)
            except Exception:
                pass

    return prices

