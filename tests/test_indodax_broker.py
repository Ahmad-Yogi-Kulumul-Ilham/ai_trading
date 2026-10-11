"""Tes broker Indodax memakai exchange palsu. Tidak ada order sungguhan yang dikirim."""
import pytest

from app.config import RiskSettings
from app.live.indodax_broker import MIN_ORDER_IDR, IndodaxBroker
from app.paper.trader import PaperTrader


class FakeIndodax:
    """Meniru perilaku penting ccxt.indodax: order market langsung terisi, fee 0.3% dipotong dari hasil."""

    def __init__(self, idr=98_335.0, btc=0.0, price=1_500_000_000.0, fee=0.003):
        self.bal = {"IDR": idr, "BTC": btc}
        self.price = price
        self.fee = fee
        self.orders = []
        self.fail_next = False

    def load_markets(self):
        return {"BTC/IDR": {}}

    def fetch_balance(self):
        return {k: {"free": v, "used": 0.0, "total": v} for k, v in self.bal.items()}

    def fetch_ticker(self, symbol):
        return {"last": self.price}

    def amount_to_precision(self, symbol, amount):
        return f"{int(amount * 1e8) / 1e8:.8f}"

    def create_order(self, symbol, type, side, amount, price=None, params=None):
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("Insufficient balance")
        assert type == "market"
        self.orders.append((side, amount, dict(params or {})))
        if side == "buy":
            cost = params["cost"]
            assert cost <= self.bal["IDR"]
            self.bal["IDR"] -= cost
            self.bal["BTC"] += cost / self.price * (1 - self.fee)
        else:
            assert amount <= self.bal["BTC"] + 1e-12
            self.bal["BTC"] -= amount
            self.bal["IDR"] += amount * self.price * (1 - self.fee)
        return {"id": str(len(self.orders))}


@pytest.fixture
def setup(tmp_path):
    ex = FakeIndodax()
    b = IndodaxBroker("k", "s", db_path=tmp_path / "live.db", max_order_idr=50_000, exchange=ex, fill_timeout_s=0)
    b.connect()
    yield b, ex
    b.close()


def test_connect_reads_balance(setup):
    b, _ = setup
    assert b.cash == pytest.approx(98_335)
    assert b.initial_cash == pytest.approx(98_335)


def test_buy_is_capped_by_max_order(setup):
    b, ex = setup
    r = b.buy("BTC/IDR", qty=1.0, price=ex.price)  # minta 1 BTC, harus dibatasi Rp 50.000
    assert ex.orders[0][2]["cost"] == 50_000
    assert b.cash == pytest.approx(48_335)
    pos = b.position("BTC/IDR")
    assert pos["qty"] == pytest.approx(50_000 / ex.price * 0.997)
    # harga rata-rata sudah memasukkan fee
    assert pos["avg_price"] == pytest.approx(ex.price / 0.997)
    assert r["cost"] == pytest.approx(50_000)


def test_buy_below_minimum_is_rejected(setup):
    b, ex = setup
    with pytest.raises(ValueError):
        b.buy("BTC/IDR", qty=(MIN_ORDER_IDR - 1) / ex.price, price=ex.price)
    assert ex.orders == []


def test_sell_only_bot_quantity(setup):
    b, ex = setup
    ex.bal["BTC"] = 0.001  # koin milik pengguna sebelum bot berjalan
    b.buy("BTC/IDR", qty=1.0, price=ex.price)
    bot_qty = b.position("BTC/IDR")["qty"]
    b.sell("BTC/IDR", None, ex.price)
    assert ex.orders[-1][0] == "sell"
    # jumlah dibulatkan ke bawah 8 desimal sesuai presisi Indodax
    assert bot_qty - 1e-8 <= ex.orders[-1][1] <= bot_qty
    assert ex.bal["BTC"] == pytest.approx(0.001, rel=1e-4)  # koin pengguna tidak ikut terjual
    assert b.position("BTC/IDR") is None


def test_round_trip_pnl_includes_fees(setup):
    b, ex = setup
    b.buy("BTC/IDR", qty=1.0, price=ex.price)
    r = b.sell("BTC/IDR", None, ex.price)
    # beli dan jual di harga sama: rugi sekitar 2x fee
    assert r["pnl"] == pytest.approx(-50_000 * (1 - 0.997 ** 2), rel=1e-3)
    assert len(b.orders()) == 2


def test_reset_not_allowed(setup):
    b, _ = setup
    with pytest.raises(RuntimeError):
        b.reset(1000)


def test_close_all(setup):
    b, ex = setup
    b.buy("BTC/IDR", qty=1.0, price=ex.price)
    res = b.close_all()
    assert res and "error" not in res[0]
    assert b.positions() == []


def test_trader_reports_order_error_without_crashing(setup, monkeypatch):
    import pandas as pd
    import app.paper.trader as tr

    b, ex = setup
    idx = pd.date_range("2026-01-01", periods=60, freq="h")
    df = pd.DataFrame({"open": ex.price, "high": ex.price, "low": ex.price, "close": ex.price, "volume": 1.0}, index=idx)
    monkeypatch.setattr(tr, "fetch_ohlcv", lambda *a, **k: df)
    monkeypatch.setattr(tr, "latest_price", lambda s: ex.price)

    class AlwaysLong:
        name = "Selalu beli"

        def generate_signals(self, d):
            return pd.Series(1, index=d.index)

    trader = PaperTrader(b, RiskSettings(position_pct=0.95, stop_loss_pct=0.0, daily_loss_limit_pct=0.0))
    ex.fail_next = True
    res = trader.step("BTC/IDR", "1h", AlwaysLong())
    assert res.action == "ERROR"
    res = trader.step("BTC/IDR", "1h", AlwaysLong())
    assert res.action == "BUY"
    assert b.position("BTC/IDR") is not None
