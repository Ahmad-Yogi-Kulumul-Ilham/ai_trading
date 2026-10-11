"""Asisten analisis pasar berbasis Claude.

AI di sini berperan sebagai analis/asisten, BUKAN eksekutor order. Ia menerima ringkasan data harga,
indikator, hasil backtest, dan berita, lalu memberi analisis dalam bahasa Indonesia.
Membutuhkan kredensial Anthropic (ANTHROPIC_API_KEY atau profil `ant auth login`).
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

import pandas as pd

from app import indicators as ind
from app.backtest.metrics import METRIC_LABELS, format_metric

SYSTEM_PROMPT = """Kamu adalah analis pasar yang hati-hati dan jujur untuk aplikasi trading pribadi (paper trading).
Pengguna adalah trader ritel pemula hingga menengah yang berbahasa Indonesia.

Prinsip:
- Jawab dalam bahasa Indonesia yang ringkas dan terstruktur.
- Analisis berdasarkan data yang diberikan (harga, indikator, hasil backtest, berita). Jangan mengarang angka.
- Jelaskan kondisi pasar (tren, momentum, volatilitas), kekuatan dan kelemahan strategi yang sedang diuji,
  dan risiko utama. Sebutkan level harga penting jika relevan.
- Jangan memberi jaminan atau prediksi pasti. Hasil backtest tidak menjamin hasil masa depan.
- Jika hasil backtest menunjukkan tanda overfitting (trade sangat sedikit, parameter ekstrem, hasil out-of-sample buruk), katakan.
- Selalu tutup dengan 2-4 saran konkret yang bisa dicoba pengguna di aplikasi (ubah parameter, interval, manajemen risiko).
"""


@dataclass
class AdvisorResult:
    text: str
    model: str
    refused: bool = False


def credentials_available() -> bool:
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return True
    cfg = os.path.join(os.path.expanduser("~"), ".config", "anthropic")
    return os.path.isdir(cfg) and any(os.scandir(cfg))


def build_context(symbol: str, interval: str, df: pd.DataFrame, strategy_name: str, strategy_params: str,
                  metrics: dict | None, news: list[dict] | None, extra: dict | None = None) -> str:
    c = df["close"]
    last = df.iloc[-1]
    rsi = ind.rsi(c, 14).iloc[-1]
    macd_line, macd_sig, macd_hist = ind.macd(c)
    lo, mid, hi = ind.bollinger(c)
    atr = ind.atr(df).iloc[-1]
    sma20, sma50, sma200 = ind.sma(c, 20).iloc[-1], ind.sma(c, 50).iloc[-1], ind.sma(c, 200).iloc[-1]

    def pct(n: int) -> str:
        if len(c) > n:
            return f"{(c.iloc[-1] / c.iloc[-1 - n] - 1) * 100:+.2f}%"
        return "n/a"

    snapshot = {
        "simbol": symbol,
        "interval": interval,
        "jumlah_bar": len(df),
        "rentang_data": f"{df.index[0]} s/d {df.index[-1]} (UTC)",
        "harga_terakhir": round(float(last["close"]), 6),
        "perubahan": {"5_bar": pct(5), "20_bar": pct(20), "50_bar": pct(50)},
        "high_low_50_bar": [round(float(df['high'].iloc[-50:].max()), 6), round(float(df['low'].iloc[-50:].min()), 6)],
        "indikator": {
            "RSI_14": None if pd.isna(rsi) else round(float(rsi), 2),
            "MACD_hist": None if pd.isna(macd_hist.iloc[-1]) else round(float(macd_hist.iloc[-1]), 6),
            "SMA_20": None if pd.isna(sma20) else round(float(sma20), 6),
            "SMA_50": None if pd.isna(sma50) else round(float(sma50), 6),
            "SMA_200": None if pd.isna(sma200) else round(float(sma200), 6),
            "Bollinger": None if pd.isna(hi.iloc[-1]) else {"atas": round(float(hi.iloc[-1]), 6), "bawah": round(float(lo.iloc[-1]), 6)},
            "ATR_14": None if pd.isna(atr) else round(float(atr), 6),
            "ATR_persen": None if pd.isna(atr) else round(float(atr / last["close"] * 100), 3),
        },
        "strategi": {"nama": strategy_name, "parameter": strategy_params},
    }
    if metrics:
        snapshot["hasil_backtest"] = {METRIC_LABELS.get(k, k): format_metric(k, v) for k, v in metrics.items()}
    if extra:
        snapshot["info_tambahan"] = extra
    if news:
        snapshot["berita_terbaru"] = [f"[{n.get('source', '')}] {n['title']}" for n in news]
    # 30 bar terakhir dalam bentuk ringkas
    tail = df.tail(30)[["open", "high", "low", "close", "volume"]].round(6)
    snapshot["ohlcv_30_bar_terakhir"] = [
        [str(ts), *row.tolist()] for ts, row in tail.iterrows()
    ]
    return json.dumps(snapshot, ensure_ascii=False, indent=1, default=str)


class MarketAdvisor:
    def __init__(self, model: str = "claude-opus-5-5", effort: str = "medium"):
        self.model = model
        self.effort = effort
        self._client = None

    def _get_client(self):
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic()
        return self._client

    def ask(self, context_json: str, question: str, history: list[dict] | None = None) -> AdvisorResult:
        import anthropic

        client = self._get_client()
        messages = list(history or [])
        user_text = (
            "Berikut data pasar dan konteks aplikasi dalam JSON:\n\n"
            f"{context_json}\n\n"
            f"Pertanyaan pengguna: {question.strip() or 'Analisis kondisi pasar dan strategi ini.'}"
        )
        messages.append({"role": "user", "content": user_text})

        kwargs = dict(
            model=self.model,
            max_tokens=8000,
            system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
            messages=messages,
            output_config={"effort": self.effort},
        )
        # Server-side fallback: jika model utama menolak karena safeguard, API otomatis memakai model fallback.
        use_fallback = self.model in ("claude-opus-5-5", "claude-fable-5-1", "claude-opus-5", "claude-sonnet-5-5")
        try:
            if use_fallback:
                with client.beta.messages.stream(
                    betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs
                ) as stream:
                    response = stream.get_final_message()
            else:
                with client.messages.stream(**kwargs) as stream:
                    response = stream.get_final_message()
        except anthropic.AuthenticationError:
            raise RuntimeError("API key Anthropic tidak valid. Set ANTHROPIC_API_KEY atau jalankan `ant auth login`.")
        except anthropic.RateLimitError:
            raise RuntimeError("Rate limit API tercapai. Coba lagi sebentar.")
        except anthropic.APIConnectionError:
            raise RuntimeError("Tidak bisa terhubung ke API Anthropic. Cek koneksi internet.")
        except anthropic.APIStatusError as exc:
            raise RuntimeError(f"API error {exc.status_code}: {exc.message}")

        if response.stop_reason == "refusal":
            return AdvisorResult("Model menolak menjawab permintaan ini.", response.model, refused=True)
        text = "".join(block.text for block in response.content if block.type == "text")
        return AdvisorResult(text.strip(), response.model)
