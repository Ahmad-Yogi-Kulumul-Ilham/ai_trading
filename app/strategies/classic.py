"""Strategi klasik berbasis indikator teknikal."""
from __future__ import annotations

import numpy as np
import pandas as pd

from app import indicators as ind
from app.strategies.base import Param, Strategy


class SmaCross(Strategy):
    name = "SMA Crossover"
    description = "Long saat SMA cepat memotong ke atas SMA lambat, keluar saat memotong ke bawah. Cocok untuk pasar trending."
    params = [
        Param("fast", "SMA cepat", 20, 5, 100, 5),
        Param("slow", "SMA lambat", 50, 20, 300, 10),
    ]

    def validate(self):
        if self.p["fast"] >= self.p["slow"]:
            return "SMA cepat harus lebih kecil dari SMA lambat"

    def generate_signals(self, df):
        fast = ind.sma(df["close"], self.p["fast"])
        slow = ind.sma(df["close"], self.p["slow"])
        sig = (fast > slow).astype(int)
        sig[fast.isna() | slow.isna()] = 0
        return sig

    def overlays(self, df):
        return {
            f"SMA {self.p['fast']}": ind.sma(df["close"], self.p["fast"]),
            f"SMA {self.p['slow']}": ind.sma(df["close"], self.p["slow"]),
        }


class EmaCross(Strategy):
    name = "EMA Crossover"
    description = "Sama seperti SMA crossover tetapi memakai EMA sehingga lebih responsif."
    params = [
        Param("fast", "EMA cepat", 12, 5, 100, 1),
        Param("slow", "EMA lambat", 26, 10, 300, 2),
    ]

    def validate(self):
        if self.p["fast"] >= self.p["slow"]:
            return "EMA cepat harus lebih kecil dari EMA lambat"

    def generate_signals(self, df):
        fast = ind.ema(df["close"], self.p["fast"])
        slow = ind.ema(df["close"], self.p["slow"])
        sig = (fast > slow).astype(int)
        sig[fast.isna() | slow.isna()] = 0
        return sig

    def overlays(self, df):
        return {
            f"EMA {self.p['fast']}": ind.ema(df["close"], self.p["fast"]),
            f"EMA {self.p['slow']}": ind.ema(df["close"], self.p["slow"]),
        }


class RsiReversion(Strategy):
    name = "RSI Mean Reversion"
    description = "Beli saat RSI di bawah level oversold, jual saat RSI naik melewati level keluar. Cocok untuk pasar sideways."
    params = [
        Param("period", "Periode RSI", 14, 5, 50, 1),
        Param("oversold", "Level beli (oversold)", 30, 10, 45, 5),
        Param("exit", "Level jual", 55, 45, 90, 5),
    ]

    def validate(self):
        if self.p["oversold"] >= self.p["exit"]:
            return "Level beli harus lebih kecil dari level jual"

    def generate_signals(self, df):
        r = ind.rsi(df["close"], self.p["period"])
        pos = 0
        out = np.zeros(len(df), dtype=int)
        rv = r.to_numpy()
        for i in range(len(df)):
            if np.isnan(rv[i]):
                out[i] = 0
                continue
            if pos == 0 and rv[i] < self.p["oversold"]:
                pos = 1
            elif pos == 1 and rv[i] > self.p["exit"]:
                pos = 0
            out[i] = pos
        return pd.Series(out, index=df.index)

    def panels(self, df):
        return {f"RSI {self.p['period']}": ind.rsi(df["close"], self.p["period"])}


class MacdTrend(Strategy):
    name = "MACD Trend"
    description = "Long saat histogram MACD positif dan harga di atas EMA tren, keluar saat histogram negatif."
    params = [
        Param("fast", "MACD cepat", 12, 5, 30, 1),
        Param("slow", "MACD lambat", 26, 15, 60, 1),
        Param("signal", "Signal", 9, 3, 20, 1),
        Param("trend", "EMA tren (0 = tanpa filter)", 100, 0, 300, 20),
    ]

    def validate(self):
        if self.p["fast"] >= self.p["slow"]:
            return "MACD cepat harus lebih kecil dari MACD lambat"

    def generate_signals(self, df):
        _, _, hist = ind.macd(df["close"], self.p["fast"], self.p["slow"], self.p["signal"])
        cond = hist > 0
        if self.p["trend"] > 0:
            trend = ind.ema(df["close"], self.p["trend"])
            cond = cond & (df["close"] > trend)
            cond[trend.isna()] = False
        cond[hist.isna()] = False
        return cond.astype(int)

    def overlays(self, df):
        if self.p["trend"] > 0:
            return {f"EMA {self.p['trend']}": ind.ema(df["close"], self.p["trend"])}
        return {}

    def panels(self, df):
        _, _, hist = ind.macd(df["close"], self.p["fast"], self.p["slow"], self.p["signal"])
        return {"MACD hist": hist}


class BollingerBreakout(Strategy):
    name = "Bollinger Breakout"
    description = "Long saat close menembus band atas, keluar saat close turun di bawah garis tengah."
    params = [
        Param("period", "Periode", 20, 10, 60, 5),
        Param("k", "Lebar band (std)", 2.0, 1.0, 3.5, 0.25, "float"),
    ]

    def generate_signals(self, df):
        lo, mid, hi = ind.bollinger(df["close"], self.p["period"], self.p["k"])
        c = df["close"].to_numpy()
        hi_v, mid_v = hi.to_numpy(), mid.to_numpy()
        out = np.zeros(len(df), dtype=int)
        pos = 0
        for i in range(len(df)):
            if np.isnan(hi_v[i]):
                continue
            if pos == 0 and c[i] > hi_v[i]:
                pos = 1
            elif pos == 1 and c[i] < mid_v[i]:
                pos = 0
            out[i] = pos
        return pd.Series(out, index=df.index)

    def overlays(self, df):
        lo, mid, hi = ind.bollinger(df["close"], self.p["period"], self.p["k"])
        return {"BB atas": hi, "BB tengah": mid, "BB bawah": lo}


class BuyAndHold(Strategy):
    name = "Buy & Hold"
    description = "Pembanding: beli di awal dan tahan sampai akhir."
    params = []

    def generate_signals(self, df):
        return pd.Series(1, index=df.index)
