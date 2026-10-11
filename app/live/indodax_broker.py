"""Broker Indodax: mengirim order SUNGGUHAN (uang asli) lewat API Indodax via ccxt.

Prinsip keamanan:
- API key dibaca dari environment variable, tidak pernah disimpan di file pengaturan.
- Buat API key Indodax dengan izin TRADE saja. Jangan aktifkan izin withdraw.
- Setiap order beli dibatasi `max_order_idr` dan saldo Rupiah yang tersedia.
- Bot hanya menjual koin yang ia beli sendiri (dicatat lokal), bukan seluruh saldo koin di akun.
- Harga dan jumlah terisi dihitung dari perubahan saldo sebelum dan sesudah order, jadi fee sudah ikut terhitung.
"""
from __future__ import annotations

import logging
import math
import os
import time
from pathlib import Path

from app.config import DATA_DIR
from app.paper.broker import PaperBroker, _now

log = logging.getLogger(__name__)

LIVE_DB = DATA_DIR / "live_indodax.db"
MIN_ORDER_IDR = 10_000          # minimal order Indodax (perkiraan, berlaku untuk pasangan IDR)
ENV_KEY = "INDODAX_API_KEY"
ENV_SECRET = "INDODAX_SECRET_KEY"


def credentials_from_env() -> tuple[str, str] | None:
    key = os.environ.get(ENV_KEY, "").strip()
    secret = os.environ.get(ENV_SECRET, "").strip()
    return (key, secret) if key and secret else None


class IndodaxBroker(PaperBroker):
    is_live = True
    currency = "Rp"

    def __init__(self, api_key: str, secret: str, db_path: Path = LIVE_DB, fee_pct: float = 0.003,
                 max_order_idr: float = 50_000, exchange=None, fill_timeout_s: float = 15.0):
        super().__init__(db_path=db_path, initial_cash=0.0, fee_pct=fee_pct, slippage_pct=0.0)
        if exchange is None:
            import ccxt
            exchange = ccxt.indodax({"apiKey": api_key, "secret": secret, "enableRateLimit": True, "timeout": 20000})
        self.ex = exchange
        self.max_order_idr = float(max_order_idr)
        self.fill_timeout_s = fill_timeout_s
        self._balance: dict = {}

    # ---------------------------------------------------------------- saldo
    def connect(self) -> dict:
        """Muat daftar pasar dan saldo. Dipanggil di worker thread (butuh internet)."""
        self.ex.load_markets()
        self.refresh_balance()
        if self._meta("initial_idr") is None:
            self._set_meta("initial_idr", str(self._total("IDR")))
        return {"idr_free": self._free("IDR"), "idr_total": self._total("IDR")}

    def refresh_balance(self) -> dict:
        self._balance = self.ex.fetch_balance()
        return self._balance

    def _free(self, code: str) -> float:
        return float((self._balance.get(code) or {}).get("free") or 0.0)

    def _total(self, code: str) -> float:
        acc = self._balance.get(code) or {}
        total = acc.get("total")
        if total is None:
            total = float(acc.get("free") or 0) + float(acc.get("used") or 0)
        return float(total or 0.0)

    def _meta(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def _set_meta(self, key: str, value: str) -> None:
        self.conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value))
        self.conn.commit()

    @property
    def cash(self) -> float:
        """Saldo Rupiah yang bisa dipakai (dari cache saldo terakhir)."""
        return self._free("IDR")

    @property
    def initial_cash(self) -> float:
        v = self._meta("initial_idr")
        return float(v) if v else self._total("IDR")

    def equity(self, prices: dict[str, float]) -> float:
        total = self._total("IDR")
        for p in self.positions():
            total += p["qty"] * prices.get(p["symbol"], p["avg_price"])
        return total

    def reset(self, initial_cash: float) -> None:
        raise RuntimeError("Akun Indodax tidak bisa direset dari aplikasi.")

    # ---------------------------------------------------------------- order
    @staticmethod
    def _base(symbol: str) -> str:
        return symbol.split("/")[0]

    def _wait_fill(self, base: str, base_before: float, idr_before: float) -> tuple[float, float]:
        """Tunggu sampai saldo koin berubah. Kembalikan (perubahan koin, perubahan Rupiah)."""
        deadline = time.time() + self.fill_timeout_s
        while True:
            self.refresh_balance()
            d_base = self._total(base) - base_before
            d_idr = self._total("IDR") - idr_before
            if abs(d_base) > 0 or time.time() >= deadline:
                return d_base, d_idr
            time.sleep(1.0)

    def buy(self, symbol: str, qty: float, price: float, note: str = "") -> dict:
        self.refresh_balance()
        cost = min(qty * price, self.max_order_idr, self._free("IDR") * 0.999)
        cost = math.floor(cost)
        if cost < MIN_ORDER_IDR:
            raise ValueError(f"Nilai order Rp {cost:,.0f} di bawah minimal Rp {MIN_ORDER_IDR:,.0f}. "
                             f"Saldo Rupiah tersedia Rp {self._free('IDR'):,.0f}.")
        base = self._base(symbol)
        base_before, idr_before = self._total(base), self._total("IDR")
        log.warning("ORDER ASLI: BUY %s senilai Rp %s", symbol, f"{cost:,.0f}")
        order = self.ex.create_order(symbol, "market", "buy", cost / price, None, {"cost": cost})
        order_id = order.get("id")
        filled, d_idr = self._wait_fill(base, base_before, idr_before)
        if filled <= 0:
            raise RuntimeError(f"Order beli {order_id} terkirim tetapi belum terlihat terisi. Cek riwayat order di Indodax.")
        spent = -d_idr if d_idr < 0 else cost
        avg = spent / filled
        pos = self.position(symbol)
        if pos:
            new_qty = pos["qty"] + filled
            new_avg = (pos["qty"] * pos["avg_price"] + spent) / new_qty
            self.conn.execute("UPDATE positions SET qty = ?, avg_price = ? WHERE symbol = ?", (new_qty, new_avg, symbol))
        else:
            self.conn.execute("INSERT INTO positions (symbol, qty, avg_price, opened_at) VALUES (?, ?, ?, ?)",
                              (symbol, filled, avg, _now()))
        fee_est = spent * self.fee_pct
        self.conn.execute("INSERT INTO orders (ts, symbol, side, qty, price, fee, pnl, note) VALUES (?, ?, ?, ?, ?, ?, NULL, ?)",
                          (_now(), symbol, "BUY", filled, avg, fee_est, f"{note} | id {order_id}".strip(" |")))
        self.conn.commit()
        return {"side": "BUY", "symbol": symbol, "qty": filled, "price": avg, "fee": fee_est, "cost": spent, "id": order_id}

    def sell(self, symbol: str, qty: float | None, price: float, note: str = "") -> dict:
        pos = self.position(symbol)
        if not pos:
            raise ValueError(f"Bot tidak punya posisi {symbol} untuk dijual")
        self.refresh_balance()
        base = self._base(symbol)
        want = pos["qty"] if qty is None else min(qty, pos["qty"])
        qty = min(want, self._free(base))
        qty = float(self.ex.amount_to_precision(symbol, qty)) if qty > 0 else 0.0
        if qty <= 0:
            raise ValueError(f"Saldo {base} di Indodax kosong. Mungkin sudah dijual manual di aplikasi Indodax.")
        if qty * price < MIN_ORDER_IDR:
            raise ValueError(f"Nilai jual Rp {qty * price:,.0f} di bawah minimal Rp {MIN_ORDER_IDR:,.0f}.")
        base_before, idr_before = self._total(base), self._total("IDR")
        log.warning("ORDER ASLI: SELL %s %s", qty, symbol)
        order = self.ex.create_order(symbol, "market", "sell", qty)
        order_id = order.get("id")
        d_base, received = self._wait_fill(base, base_before, idr_before)
        sold = -d_base
        if sold <= 0:
            raise RuntimeError(f"Order jual {order_id} terkirim tetapi belum terlihat terisi. Cek riwayat order di Indodax.")
        avg_fill = received / sold if received > 0 else price
        pnl = received - sold * pos["avg_price"]
        remaining = pos["qty"] - sold
        if remaining * avg_fill < MIN_ORDER_IDR:
            # sisa terlalu kecil untuk dijual (debu), berhenti melacaknya
            self.conn.execute("DELETE FROM positions WHERE symbol = ?", (symbol,))
        else:
            self.conn.execute("UPDATE positions SET qty = ? WHERE symbol = ?", (remaining, symbol))
        fee_est = received * self.fee_pct
        self.conn.execute("INSERT INTO orders (ts, symbol, side, qty, price, fee, pnl, note) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                          (_now(), symbol, "SELL", sold, avg_fill, fee_est, pnl, f"{note} | id {order_id}".strip(" |")))
        self.conn.commit()
        return {"side": "SELL", "symbol": symbol, "qty": sold, "price": avg_fill, "fee": fee_est, "pnl": pnl, "id": order_id}

    def close_all(self, prices: dict[str, float] | None = None, note: str = "stop darurat") -> list[dict]:
        """Jual semua posisi milik bot. Dipakai tombol STOP DARURAT."""
        results = []
        for p in self.positions():
            price = (prices or {}).get(p["symbol"])
            if price is None:
                price = float(self.ex.fetch_ticker(p["symbol"])["last"])
            try:
                results.append(self.sell(p["symbol"], None, price, note=note))
            except Exception as exc:  # noqa: BLE001
                results.append({"side": "SELL", "symbol": p["symbol"], "error": str(exc)})
        return results
