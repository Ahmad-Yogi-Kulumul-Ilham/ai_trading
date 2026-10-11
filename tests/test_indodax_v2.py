"""Tes klien Indodax Trade API 2.0 tanpa koneksi internet (urlopen dipalsukan)."""
import hashlib
import hmac
import io
import json
import urllib.error
import urllib.parse

import pytest

from app.live import indodax_v2
from app.live.indodax_v2 import IndodaxAPIError, IndodaxV2Client


class FakePublic:
    def load_markets(self):
        return {"BTC/IDR": {}}

    def fetch_time(self):
        import time
        return int(time.time() * 1000)

    def market(self, symbol):
        base, quote = symbol.lower().split("/")
        return {"baseId": base, "quoteId": quote}

    def amount_to_precision(self, symbol, amount):
        return f"{int(amount * 1e8) / 1e8:.8f}"

    def fetch_ticker(self, symbol):
        return {"last": 1_500_000_000.0}


class FakeResponse(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def client(monkeypatch):
    calls = []
    replies = []

    def fake_urlopen(req, timeout=None):
        calls.append(req)
        status, body = replies.pop(0)
        if status >= 400:
            raise urllib.error.HTTPError(req.full_url, status, "err", {}, io.BytesIO(json.dumps(body).encode()))
        return FakeResponse(json.dumps(body).encode())

    monkeypatch.setattr(indodax_v2.urllib.request, "urlopen", fake_urlopen)
    c = IndodaxV2Client("KEY-123", "secret-abc", public=FakePublic())
    c.load_markets()
    return c, calls, replies


def _params(req):
    raw = req.data.decode() if req.data else urllib.parse.urlsplit(req.full_url).query
    return raw, dict(urllib.parse.parse_qsl(raw))


def test_balance_request_is_signed_with_sha256(client):
    c, calls, replies = client
    replies.append((200, {"canTrade": True, "balances": [{"asset": "IDR", "free": "98335", "locked": "0"},
                                                          {"asset": "BTC", "free": "0.0001", "locked": "0.00002"}]}))
    bal = c.fetch_balance()
    req = calls[0]
    raw, params = _params(req)
    assert req.get_method() == "GET"
    assert req.full_url.startswith("https://api.indodax.com/api/v2/account?")
    assert req.headers["X-apikey"] == "KEY-123"
    assert req.headers["Sign"] == hmac.new(b"secret-abc", raw.encode(), hashlib.sha256).hexdigest()
    assert "User-agent" in req.headers
    assert "timestamp" in params and "recvWindow" in params
    assert bal["IDR"]["free"] == 98335.0
    assert bal["BTC"]["total"] == pytest.approx(0.00012)


def test_market_buy_uses_quote_amount(client):
    c, calls, replies = client
    replies.append((200, {"symbol": "BTCIDR", "orderId": 77, "clientOrderId": "x"}))
    r = c.create_order("BTC/IDR", "market", "buy", 0.0, None, {"cost": 50_000.7})
    raw, params = _params(calls[0])
    assert calls[0].get_method() == "POST"
    assert params["symbol"] == "BTCIDR" and params["side"] == "BUY" and params["type"] == "MARKET"
    assert params["quoteOrderQty"] == "50000"
    assert "quantity" not in params
    assert r["id"] == "77"


def test_market_sell_uses_base_quantity(client):
    c, calls, replies = client
    replies.append((200, {"orderId": 78}))
    c.create_order("BTC/IDR", "market", "sell", 0.0000332333)
    _, params = _params(calls[0])
    assert params["side"] == "SELL"
    assert params["quantity"] == "0.00003323"
    assert "quoteOrderQty" not in params


def test_error_is_translated(client):
    c, _, replies = client
    replies.append((403, {"code": -2015, "msg": "Access denied"}))
    with pytest.raises(IndodaxAPIError) as exc:
        c.fetch_balance()
    assert exc.value.code == -2015
    assert "Trading Spot" in str(exc.value)


def test_limit_orders_are_refused(client):
    c, calls, _ = client
    with pytest.raises(ValueError):
        c.create_order("BTC/IDR", "limit", "buy", 1, 1)
    assert calls == []
