"""Pengambilan data OHLCV dengan cache lokal.

Simbol Yahoo (BTC-USD, AAPL, EURUSD=X) diambil via yfinance.
Simbol Indodax (BTC/IDR) diambil via ccxt, harga dalam Rupiah.
"""
from __future__ import annotations

import logging
import pickle
import time
from pathlib import Path

import pandas as pd
import yfinance as yf

from app.config import CACHE_DIR
from app.data.symbols import INDODAX_INTERVALS, INTERVAL_SECONDS, is_indodax

log = logging.getLogger(__name__)

COLUMNS = ["open", "high", "low", "close", "volume"]


def _cache_path(symbol: str, interval: str, period: str) -> Path:
    safe = symbol.replace("=", "_").replace("/", "_")
    return CACHE_DIR / f"{safe}_{interval}_{period}.pkl"


def _cache_ttl(interval: str) -> int:
    """Cache dianggap segar selama kurang dari setengah bar (min 30 detik)."""
    return max(30, INTERVAL_SECONDS.get(interval, 3600) // 2)


def normalize(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=COLUMNS)
    df = df.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.rename(columns={c: str(c).lower() for c in df.columns})
    for c in COLUMNS:
        if c not in df.columns:
            df[c] = 0.0
    df = df[COLUMNS]
    idx = pd.to_datetime(df.index)
    if idx.tz is not None:
        idx = idx.tz_convert("UTC").tz_localize(None)
    df.index = idx
    df.index.name = "time"
    df = df[~df.index.duplicated(keep="last")].sort_index()
    df = df.dropna(subset=["open", "high", "low", "close"])
    df = df[df["close"] > 0]
    return df.astype(float)


PERIOD_DAYS = {"1d": 1, "5d": 5, "7d": 7, "1mo": 30, "3mo": 91, "6mo": 182, "1y": 365,
               "2y": 730, "5y": 1826, "10y": 3652, "max": 5000}

_indodax_public = None


def indodax_public():
    """Klien ccxt Indodax tanpa API key, untuk data publik (candle dan harga)."""
    global _indodax_public
    if _indodax_public is None:
        import ccxt
        _indodax_public = ccxt.indodax({"enableRateLimit": True, "timeout": 20000})
        _indodax_public.load_markets()
    return _indodax_public


def _fetch_indodax(symbol: str, interval: str, period: str) -> pd.DataFrame:
    tf = INDODAX_INTERVALS.get(interval)
    if tf is None:
        raise ValueError(f"Interval {interval} tidak tersedia di Indodax. Pilih salah satu: {', '.join(INDODAX_INTERVALS)}")
    ex = indodax_public()
    if symbol not in ex.markets:
        raise ValueError(f"Pasangan {symbol} tidak ada di Indodax")
    step_ms = INTERVAL_SECONDS[interval] * 1000
    now_ms = ex.milliseconds()
    start_ms = now_ms - PERIOD_DAYS.get(period, 365) * 86_400_000
    window = 1000 * step_ms
    rows: list[list] = []
    until_s = now_ms // 1000
    # Indodax membatasi jumlah candle per permintaan dan mengembalikan bagian terbarunya,
    # jadi halaman berikutnya selalu dimulai tepat sebelum candle tertua yang sudah diterima.
    for _ in range(100):
        since_ms = max(start_ms, until_s * 1000 - window)
        page = ex.fetch_ohlcv(symbol, tf, since=since_ms, limit=1000, params={"until": until_s})
        if not page:
            break
        rows.extend(page)
        oldest = min(r[0] for r in page)
        if oldest <= start_ms + step_ms:
            break
        until_s = oldest // 1000 - 1
    if not rows:
        return pd.DataFrame(columns=COLUMNS)
    raw = pd.DataFrame(rows, columns=["time", "open", "high", "low", "close", "volume"])
    raw = raw[raw["time"] >= start_ms]
    raw.index = pd.to_datetime(raw.pop("time"), unit="ms")
    return normalize(raw)


def fetch_ohlcv(symbol: str, interval: str = "1h", period: str = "1y", use_cache: bool = True) -> pd.DataFrame:
    """Ambil data OHLCV. Index: DatetimeIndex UTC naive. Kolom: open, high, low, close, volume."""
    path = _cache_path(symbol, interval, period)
    if use_cache and path.exists() and time.time() - path.stat().st_mtime < _cache_ttl(interval):
        try:
            with path.open("rb") as f:
                return pickle.load(f)
        except Exception:
            pass

    if is_indodax(symbol):
        log.info("Mengambil %s %s %s dari Indodax", symbol, interval, period)
        df = _fetch_indodax(symbol, interval, period)
    else:
        log.info("Mengambil %s %s %s dari Yahoo Finance", symbol, interval, period)
        raw = yf.Ticker(symbol).history(period=period, interval=interval, auto_adjust=False, actions=False)
        df = normalize(raw)
    if df.empty:
        raise ValueError(f"Tidak ada data untuk {symbol} ({interval}, {period}). Cek simbol atau koneksi internet.")
    try:
        with path.open("wb") as f:
            pickle.dump(df, f)
    except Exception as exc:
        log.warning("Gagal menulis cache: %s", exc)
    return df


def latest_price(symbol: str) -> float:
    """Harga terakhir (best effort). Fallback ke close bar 1 menit terakhir."""
    if is_indodax(symbol):
        last = indodax_public().fetch_ticker(symbol).get("last")
        if not last:
            raise ValueError(f"Tidak bisa mendapat harga terakhir untuk {symbol}")
        return float(last)
    ticker = yf.Ticker(symbol)
    try:
        fi = ticker.fast_info
        price = getattr(fi, "last_price", None)
        if price and price > 0:
            return float(price)
    except Exception:
        pass
    df = normalize(ticker.history(period="1d", interval="1m", auto_adjust=False, actions=False))
    if df.empty:
        df = normalize(ticker.history(period="5d", interval="1h", auto_adjust=False, actions=False))
    if df.empty:
        raise ValueError(f"Tidak bisa mendapat harga terakhir untuk {symbol}")
    return float(df["close"].iloc[-1])


def recent_news(symbol: str, limit: int = 8) -> list[dict]:
    """Berita terbaru dari Yahoo (best effort, bisa kosong)."""
    out: list[dict] = []
    if is_indodax(symbol):
        symbol = symbol.split("/")[0] + "-USD"  # berita koin yang sama dari Yahoo
    try:
        for item in (yf.Ticker(symbol).news or [])[:limit]:
            content = item.get("content", item) or {}
            title = content.get("title") or item.get("title")
            pub = content.get("pubDate") or item.get("providerPublishTime")
            provider = content.get("provider")
            source = provider.get("displayName") if isinstance(provider, dict) else item.get("publisher", "")
            if title:
                out.append({"title": title, "published": str(pub), "source": source or ""})
    except Exception as exc:
        log.debug("news gagal: %s", exc)
    return out
