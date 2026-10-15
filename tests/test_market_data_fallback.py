"""US history falls through to yfinance, and paper signals keep a close."""

from __future__ import annotations

import json
import os
import sys
import types

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _bars(closes):
    idx = pd.date_range("2024-01-01", periods=len(closes), freq="B")
    return pd.DataFrame(
        {
            "open": closes,
            "high": [value + 1 for value in closes],
            "low": [value - 1 for value in closes],
            "close": closes,
            "volume": [1000] * len(closes),
        },
        index=idx,
    )


def test_us_history_uses_yfinance_when_tiger_and_china_are_empty(monkeypatch):
    from backend.data_engine.market_data import MarketDataEngine
    import backend.data_engine.market_data as market_mod

    engine = MarketDataEngine()
    frame = _bars([10, 11, 12, 13, 14])
    monkeypatch.setattr(engine, "_history_from_tiger", lambda *args, **kwargs: pd.DataFrame())
    monkeypatch.setattr(engine, "_history_from_yfinance", lambda *args, **kwargs: frame)
    monkeypatch.setattr(
        market_mod.china_data_adapter,
        "get_historical_data",
        lambda *args, **kwargs: pd.DataFrame(),
    )

    out = engine.get_historical_data("AAPL", period="2y", interval="1d")

    assert float(out["close"].iloc[-1]) == 14
    assert "close" in out.columns


def test_tiger_symbol_error_does_not_disable_quotes():
    from backend.data_engine.market_data import MarketDataEngine

    class _Quote:
        def get_bars(self, **kwargs):
            raise RuntimeError("unknown symbol")

    engine = MarketDataEngine()
    engine._tiger_quote = _Quote()
    out = engine._history_from_tiger("AAPL", "2y")

    assert out.empty
    assert getattr(engine, "_tiger_quote_failed", False) is False
    assert engine._tiger_quote is not None


def test_tiger_millisecond_bars_become_daily_ohlcv():
    from backend.data_engine.market_data import MarketDataEngine

    class _Quote:
        def get_bars(self, **kwargs):
            return pd.DataFrame(
                {
                    "symbol": ["AAPL", "AAPL"],
                    "time": [1_704_067_200_000, 1_704_153_600_000],
                    "open": [10, 11],
                    "high": [12, 13],
                    "low": [9, 10],
                    "close": [11, 12.5],
                    "volume": [100, 110],
                }
            )

    engine = MarketDataEngine()
    engine._tiger_quote = _Quote()
    out = engine._history_from_tiger("AAPL", "2y")

    assert isinstance(out.index, pd.DatetimeIndex)
    assert float(out["close"].iloc[-1]) == 12.5
    assert out.index.tz is None


def test_tiger_permission_error_disables_quotes():
    from backend.data_engine.market_data import MarketDataEngine

    class _Quote:
        def get_bars(self, **kwargs):
            raise RuntimeError("quote permission denied")

    engine = MarketDataEngine()
    engine._tiger_quote = _Quote()
    engine._history_from_tiger("AAPL", "2y")

    assert engine._tiger_quote_failed is True
    assert engine._tiger_quote is None


def test_warm_history_caches_yfinance_batch(monkeypatch):
    from backend.data_engine.market_data import MarketDataEngine

    engine = MarketDataEngine()
    monkeypatch.setattr(engine, "_warm_from_tiger_batch", lambda *args, **kwargs: 0)

    idx = pd.date_range("2024-01-01", periods=3, freq="B")
    columns = pd.MultiIndex.from_product(
        [["AAPL", "MSFT"], ["Open", "High", "Low", "Close", "Volume"]]
    )
    raw = pd.DataFrame(
        [
            [10, 11, 9, 10.5, 100, 20, 21, 19, 20.5, 200],
            [10.5, 12, 10, 11.5, 110, 20.5, 22, 20, 21.5, 210],
            [11.5, 13, 11, 12.5, 120, 21.5, 23, 21, 22.5, 220],
        ],
        index=idx,
        columns=columns,
    )

    yfinance = types.ModuleType("yfinance")
    yfinance.download = lambda **kwargs: raw
    monkeypatch.setitem(sys.modules, "yfinance", yfinance)

    filled = engine.warm_history(["AAPL", "MSFT"], period="2y", interval="1d")

    assert filled == 2
    cached = engine.cache["AAPL_2y_1d"]
    assert float(cached["close"].iloc[-1]) == 12.5
    assert float(engine.cache["MSFT_2y_1d"]["close"].iloc[-1]) == 22.5


def test_record_daily_window_appends_jsonl(tmp_path):
    from shared.nn_samples import record_daily_window

    frame = _bars([10, 11, 12.5])
    row = record_daily_window("AAPL", frame, root=tmp_path)
    lines = (tmp_path / "windows.jsonl").read_text(encoding="utf-8").strip().splitlines()

    assert row is not None
    assert len(lines) == 1
    saved = json.loads(lines[0])
    assert saved["ticker"] == "AAPL"
    assert saved["close"] == 12.5
    assert saved["rows"] == 3
    assert len(saved["log_returns"]) == 2


def test_signal_gets_close_and_return_score():
    from trading_pipeline import TradingPipeline

    closes = list(range(100, 130))
    data = {"AAPL": {"close": 129.0, "ohlcv": _bars(closes)}}
    signals = [{"ticker": "AAPL", "signal": 0.4}]
    TradingPipeline._attach_latest_prices(signals, data)

    assert signals[0]["price"] == 129.0

    row = {"ticker": "AAPL", "close": 129.0, "volume": 1000}
    TradingPipeline._stamp_return_score(row, data["AAPL"]["ohlcv"])
    assert "F001" in row
    assert row["F001"] != 0
