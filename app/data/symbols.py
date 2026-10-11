"""Daftar simbol preset per pasar. Semua format mengikuti Yahoo Finance."""

MARKETS = {
    "Crypto": ["BTC-USD", "ETH-USD", "SOL-USD", "BNB-USD", "XRP-USD", "DOGE-USD", "ADA-USD"],
    "Saham US": ["AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "GOOGL", "META", "SPY", "QQQ"],
    "Forex": ["EURUSD=X", "GBPUSD=X", "USDJPY=X", "AUDUSD=X", "USDCHF=X", "USDIDR=X"],
}

# interval -> daftar period yang didukung yfinance
INTERVAL_PERIODS = {
    "1m": ["1d", "5d", "7d"],
    "5m": ["1d", "5d", "1mo"],
    "15m": ["5d", "1mo"],
    "30m": ["5d", "1mo"],
    "1h": ["1mo", "3mo", "6mo", "1y"],   # batas Yahoo untuk 1h = 730 hari, "2y" sering ditolak
    "1d": ["6mo", "1y", "2y", "5y", "10y", "max"],
    "1wk": ["2y", "5y", "10y", "max"],
}

# rentang data yang dipakai loop paper trading per interval (cukup untuk indikator panjang, tetap ringan)
PAPER_PERIODS = {
    "1m": "5d", "5m": "1mo", "15m": "1mo", "30m": "1mo",
    "1h": "6mo", "1d": "2y", "1wk": "5y",
}

INTERVAL_SECONDS = {
    "1m": 60, "5m": 300, "15m": 900, "30m": 1800,
    "1h": 3600, "1d": 86400, "1wk": 604800,
}


def market_of(symbol: str) -> str:
    s = symbol.upper()
    if s.endswith("=X"):
        return "Forex"
    if s.endswith("-USD") or s.endswith("-USDT"):
        return "Crypto"
    return "Saham US"


def trading_seconds_per_year(market: str) -> float:
    """Berapa detik pasar buka dalam setahun (untuk anualisasi metrik)."""
    if market == "Crypto":
        return 365 * 24 * 3600
    if market == "Forex":
        return 52 * 5 * 24 * 3600
    return 252 * 6.5 * 3600


def bars_per_year(market: str, interval: str) -> float:
    secs = INTERVAL_SECONDS.get(interval, 86400)
    if interval in ("1d", "1wk"):
        days = 365 if market == "Crypto" else (260 if market == "Forex" else 252)
        return days if interval == "1d" else days / 5
    return trading_seconds_per_year(market) / secs
