"""Klien Indodax Trade API 2.0 (TAPIv2).

API key yang dibuat di https://indodax.com/trade_api sekarang adalah key TAPIv2. Key ini HANYA bisa dipakai di
https://api.indodax.com/api/v2/... dengan header `X-APIKEY` dan tanda tangan HMAC-SHA256. Endpoint lama
(`/tapi`, yang dipakai ccxt) menolaknya dengan error `invalid_version_key`.

Kelas ini meniru bagian kecil antarmuka ccxt yang dipakai IndodaxBroker:
`load_markets`, `fetch_balance`, `fetch_ticker`, `amount_to_precision`, `create_order`.
Data publik (daftar pasar, harga, waktu server) tetap diambil lewat ccxt tanpa key.

Dokumentasi: https://github.com/btcid/indodax-official-api-docs/blob/master/INDODAX-TradeAPI-2.md
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
import urllib.error
import urllib.parse
import urllib.request

BASE_URL = "https://api.indodax.com"

# Pesan yang lebih jelas untuk kode error yang paling mungkin ditemui pengguna
FRIENDLY_ERRORS = {
    -1002: "API key tidak dikenali atau sudah kedaluwarsa. Buat ulang key di indodax.com/trade_api.",
    -1021: "Jam laptop tidak sinkron dengan server Indodax. Sinkronkan jam Windows lalu coba lagi.",
    -1022: "Tanda tangan ditolak. Periksa INDODAX_SECRET_KEY, pastikan tidak ada spasi atau karakter terpotong.",
    -2014: "API key tidak terkirim. Periksa INDODAX_API_KEY.",
    -2015: "Akses ditolak. Pastikan izin Trading Spot aktif dan key sudah diaktifkan lewat tautan di email.",
    -2010: "Order ditolak Indodax, biasanya karena saldo tidak cukup.",
    -1003: "Terlalu banyak permintaan ke Indodax. Tunggu sebentar.",
    -1016: "Pasar sedang ditangguhkan (maintenance).",
    -1121: "Pasangan koin tidak dikenal oleh Indodax.",
}


class IndodaxAPIError(RuntimeError):
    def __init__(self, code, msg: str, status: int | None = None):
        self.code = code
        self.status = status
        friendly = FRIENDLY_ERRORS.get(code) if isinstance(code, int) else None
        text = f"Indodax error {code}: {msg}"
        if friendly:
            text += f"\n{friendly}"
        super().__init__(text)


class IndodaxV2Client:
    def __init__(self, api_key: str, secret: str, public=None, timeout: float = 20.0, recv_window: int = 10_000):
        if public is None:
            import ccxt
            public = ccxt.indodax({"enableRateLimit": True, "timeout": int(timeout * 1000)})
        self.api_key = api_key.strip()
        self.secret = secret.strip()
        self.public = public
        self.timeout = timeout
        self.recv_window = recv_window
        self._offset_ms = 0
        self.markets: dict = {}

    # ------------------------------------------------------------ data publik
    def load_markets(self):
        self.markets = self.public.load_markets()
        self.sync_time()
        return self.markets

    def sync_time(self) -> int:
        """Hitung selisih jam laptop dan server, supaya timestamp request tidak ditolak."""
        try:
            local = int(time.time() * 1000)
            server = int(self.public.fetch_time())
            self._offset_ms = server - local
        except Exception:  # noqa: BLE001
            self._offset_ms = 0
        return self._offset_ms

    def fetch_ticker(self, symbol: str) -> dict:
        return self.public.fetch_ticker(symbol)

    def amount_to_precision(self, symbol: str, amount: float) -> str:
        return self.public.amount_to_precision(symbol, amount)

    def _v2_symbol(self, symbol: str) -> str:
        if not self.markets:
            self.load_markets()
        m = self.public.market(symbol)
        return f"{m['baseId']}{m['quoteId']}".upper()

    # ------------------------------------------------------------ request bertanda tangan
    def _signed(self, method: str, path: str, params: dict | None = None) -> dict:
        params = {k: v for k, v in (params or {}).items() if v is not None}
        params["timestamp"] = int(time.time() * 1000) + self._offset_ms
        params["recvWindow"] = self.recv_window
        query = urllib.parse.urlencode(params)
        signature = hmac.new(self.secret.encode("utf-8"), query.encode("utf-8"), hashlib.sha256).hexdigest()
        # User-Agent wajib: tanpa ini firewall Indodax membalas halaman HTML 403
        headers = {"Accept": "application/json", "X-APIKEY": self.api_key, "Sign": signature,
                   "User-Agent": "trading-ai/1.0 (+python)"}
        url = BASE_URL + path
        data = None
        if method == "POST":
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            data = query.encode("utf-8")
        else:
            url += "?" + query
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8")
                status = resp.status
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            status = exc.code
        try:
            payload = json.loads(body) if body else {}
        except json.JSONDecodeError:
            raise IndodaxAPIError("?", f"respons bukan JSON (HTTP {status}): {body[:200]}", status)
        if isinstance(payload, dict) and "code" in payload and payload.get("code") not in (0, 200, None):
            raise IndodaxAPIError(payload.get("code"), str(payload.get("msg", "")), status)
        if status >= 400:
            raise IndodaxAPIError(status, body[:200], status)
        return payload

    # ------------------------------------------------------------ akun & order
    def fetch_balance(self) -> dict:
        data = self._signed("GET", "/api/v2/account", {"omitZeroBalances": "true"})
        out: dict = {"info": data, "IDR": {"free": 0.0, "used": 0.0, "total": 0.0}}
        for b in data.get("balances", []):
            asset = str(b.get("asset", "")).upper()
            free = float(b.get("free") or 0)
            used = float(b.get("locked") or 0)
            out[asset] = {"free": free, "used": used, "total": free + used}
        return out

    def create_order(self, symbol: str, type: str, side: str, amount: float, price: float | None = None,
                     params: dict | None = None) -> dict:
        if type != "market":
            raise ValueError("Aplikasi hanya memakai order MARKET")
        params = params or {}
        body = {
            "symbol": self._v2_symbol(symbol),
            "side": side.upper(),
            "type": "MARKET",
            "newClientOrderId": f"tai-{side.lower()}-{int(time.time() * 1000)}",
        }
        if side.lower() == "buy":
            cost = params.get("cost")
            if cost is None:
                if price is None:
                    raise ValueError("Order beli market butuh nilai Rupiah (cost)")
                cost = amount * price
            body["quoteOrderQty"] = int(cost)
        else:
            qty = self.amount_to_precision(symbol, amount)
            body["quantity"] = qty.rstrip("0").rstrip(".") if "." in qty else qty
        data = self._signed("POST", "/api/v2/order", body)
        return {"id": str(data.get("orderId")), "clientOrderId": data.get("clientOrderId"), "info": data}

    def fetch_order(self, symbol: str, order_id: str) -> dict:
        return self._signed("GET", "/api/v2/order", {"symbol": self._v2_symbol(symbol), "orderId": order_id})
