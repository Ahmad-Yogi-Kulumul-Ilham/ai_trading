import pytest

from app.paper.broker import PaperBroker


@pytest.fixture
def broker(tmp_path):
    b = PaperBroker(tmp_path / "paper.db", initial_cash=1000, fee_pct=0.001, slippage_pct=0.0)
    yield b
    b.close()


def test_buy_sell_roundtrip(broker):
    broker.buy("BTC-USD", 0.01, 50_000)
    assert broker.position("BTC-USD")["qty"] == pytest.approx(0.01)
    assert broker.cash == pytest.approx(1000 - 500 - 0.5)
    r = broker.sell("BTC-USD", None, 55_000)
    assert broker.position("BTC-USD") is None
    assert r["pnl"] == pytest.approx(550 - 0.55 - 500)
    assert len(broker.orders()) == 2


def test_insufficient_cash(broker):
    with pytest.raises(ValueError):
        broker.buy("ETH-USD", 10, 3000)


def test_reset(broker):
    broker.buy("BTC-USD", 0.001, 50_000)
    broker.reset(5000)
    assert broker.cash == 5000
    assert broker.positions() == []
    assert broker.orders() == []


def test_equity_marks_to_market(broker):
    broker.buy("BTC-USD", 0.01, 50_000)
    assert broker.equity({"BTC-USD": 60_000}) == pytest.approx(broker.cash + 600)
