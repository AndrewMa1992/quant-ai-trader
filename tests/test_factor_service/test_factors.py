"""tests/test_factor_service/test_factors.py – Tests for factor implementations."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from services.factor_service.factors.technical import (
    Ret1M, Ret3M, RSI14, MACDHistogram, Vol21D, VolumeRatio,
    SMA50Bias, BollingerBandwidth, ATR14, CCI20,
)
from services.factor_service.factors.fundamental import (
    PERatio, ROE, GrossMargin, DebtToEquity, CurrentRatio,
)
from services.factor_service.factors.microstructure import (
    BidAskSpread, AmihudIlliquidity, OrderImbalance,
)


class TestTechnicalFactors:
    """Tests for technical factor computations."""

    @pytest.fixture
    def df(self) -> pd.DataFrame:
        np.random.seed(42)
        dates = pd.date_range("2024-01-01", periods=300, freq="B")
        close = pd.Series(np.random.randn(300).cumsum() * 0.5 + 150, index=dates)
        return pd.DataFrame({
            "open": close * (1 + np.random.randn(300) * 0.005),
            "high": close * (1 + np.abs(np.random.randn(300) * 0.01)),
            "low": close * (1 - np.abs(np.random.randn(300) * 0.01)),
            "close": close,
            "adj_close": close,
            "volume": np.random.randint(1000000, 50000000, 300),
        }, index=dates)

    def test_ret_1m_output_shape(self, df: pd.DataFrame):
        factor = Ret1M()
        result = factor.compute(df)
        assert len(result) == len(df)
        assert isinstance(result, pd.Series)

    def test_ret_3m_output_shape(self, df: pd.DataFrame):
        result = Ret3M().compute(df)
        assert len(result) == len(df)

    def test_rsi_range(self, df: pd.DataFrame):
        result = RSI14().compute(df).dropna()
        assert 0 <= result.min() <= 100
        assert 0 <= result.max() <= 100

    def test_macd_histogram(self, df: pd.DataFrame):
        result = MACDHistogram().compute(df).dropna()
        assert len(result) > 0

    def test_vol_21d_positive(self, df: pd.DataFrame):
        result = Vol21D().compute(df).dropna()
        assert (result >= 0).all()

    def test_volume_ratio_positive(self, df: pd.DataFrame):
        result = VolumeRatio().compute(df).dropna()
        assert (result > 0).all()

    def test_bollinger_bandwidth_range(self, df: pd.DataFrame):
        result = BollingerBandwidth().compute(df).dropna()
        assert (result >= 0).all()

    def test_atr_positive(self, df: pd.DataFrame):
        result = ATR14().compute(df).dropna()
        assert (result > 0).all()


class TestFundamentalFactors:
    """Tests for fundamental factor computations."""

    @pytest.fixture
    def df(self) -> pd.DataFrame:
        np.random.seed(42)
        dates = pd.date_range("2024-01-01", periods=252, freq="B")
        close = pd.Series(np.random.randn(252).cumsum() * 0.5 + 150, index=dates)
        return pd.DataFrame({
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "adj_close": close,
            "volume": np.random.randint(1000000, 50000000, 252),
            "eps": np.random.randn(252).cumsum() * 0.1 + 5,
            "book_value_per_share": np.random.randn(252).cumsum() * 0.05 + 30,
        }, index=dates)

    def test_pe_ratio_requires_fundamentals(self, df: pd.DataFrame):
        result = PERatio().compute(df).dropna()
        assert len(result) > 0


class TestMicrostructureFactors:
    """Tests for microstructure factor computations."""

    @pytest.fixture
    def df(self) -> pd.DataFrame:
        np.random.seed(42)
        dates = pd.date_range("2024-01-01", periods=252, freq="B")
        close = pd.Series(np.random.randn(252).cumsum() * 0.5 + 150, index=dates)
        return pd.DataFrame({
            "open": close * (1 + np.random.randn(252) * 0.003),
            "high": close * (1 + np.abs(np.random.randn(252) * 0.008)),
            "low": close * (1 - np.abs(np.random.randn(252) * 0.008)),
            "close": close,
            "adj_close": close,
            "volume": np.random.randint(1000000, 50000000, 252),
        }, index=dates)

    def test_bid_ask_spread(self, df: pd.DataFrame):
        result = BidAskSpread().compute(df).dropna()
        assert len(result) > 0

    def test_amihud_illiquidity_positive(self, df: pd.DataFrame):
        result = AmihudIlliquidity().compute(df).dropna()
        assert (result >= 0).all()

    def test_order_imbalance(self, df: pd.DataFrame):
        result = OrderImbalance().compute(df).dropna()
        assert len(result) > 0
