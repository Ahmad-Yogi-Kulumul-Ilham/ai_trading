"""Indikator teknikal berbasis pandas (tanpa TA-Lib)."""
from __future__ import annotations

import numpy as np
import pandas as pd


def sma(s: pd.Series, n: int) -> pd.Series:
    n = int(n)
    return s.rolling(n, min_periods=n).mean()


def ema(s: pd.Series, n: int) -> pd.Series:
    n = int(n)
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def rsi(s: pd.Series, n: int = 14) -> pd.Series:
    n = int(n)
    delta = s.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    avg_loss = loss.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    # jika tidak ada loss sama sekali -> RSI 100; sebelum data cukup -> NaN
    out = out.where(avg_loss != 0, 100.0)
    out[avg_gain.isna()] = np.nan
    return out


def macd(s: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    line = ema(s, fast) - ema(s, slow)
    sig = line.ewm(span=int(signal), adjust=False).mean()
    hist = line - sig
    return line, sig, hist


def bollinger(s: pd.Series, n: int = 20, k: float = 2.0):
    n = int(n)
    mid = sma(s, n)
    std = s.rolling(n, min_periods=n).std(ddof=0)
    return mid - k * std, mid, mid + k * std


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    n = int(n)
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def returns(s: pd.Series, n: int = 1) -> pd.Series:
    return s.pct_change(int(n))


def feature_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Fitur untuk strategi ML. Semua fitur hanya memakai data sampai bar saat ini (tanpa lookahead)."""
    c = df["close"]
    f = pd.DataFrame(index=df.index)
    for n in (1, 2, 3, 5, 10):
        f[f"ret_{n}"] = returns(c, n)
    f["rsi_14"] = rsi(c, 14) / 100
    _, _, hist = macd(c)
    f["macd_hist"] = hist / c
    lo, mid, hi = bollinger(c)
    f["bb_pos"] = (c - lo) / (hi - lo).replace(0, np.nan)
    f["atr_n"] = atr(df) / c
    f["sma_ratio_20"] = c / sma(c, 20) - 1
    f["sma_ratio_50"] = c / sma(c, 50) - 1
    vol = df["volume"].replace(0, np.nan)
    f["vol_chg"] = (vol / vol.rolling(20).mean() - 1).fillna(0)
    f["hl_range"] = (df["high"] - df["low"]) / c
    return f.replace([np.inf, -np.inf], np.nan)
