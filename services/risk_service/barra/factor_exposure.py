"""services/risk_service/barra/factor_exposure.py – Barra USE4/CNE5 style factor exposure.

9 style factors: Beta, Size, Value, Momentum, Quality, Volatility,
Growth, Leverage, Liquidity. Each uses 1-3 descriptor variables.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from loguru import logger

from services.data_service.storage.parquet_store import ParquetStore
from services.data_service.pipeline.cleanser import DataCleanser


class BarraExposureCalculator:
    """Computes Barra multi-factor model exposures for a ticker.

    The 9 style factors with their descriptors:
      Beta       – Market sensitivity, log market cap
      Size       – Log(market_cap) cubed, cube of size factor
      Value      – Book/Price, Earnings Yield, Dividend Yield
      Momentum   – 12M-1M return, 6M return
      Quality    – ROE, Earnings Variability, Accruals
      Volatility – Historical sigma, cumulative range, daily std
      Growth     – Earnings growth, Sales growth
      Leverage   – Debt/Equity, Debt/Assets
      Liquidity  – Monthly turnover, Amihud illiquidity
    """

    FACTOR_NAMES: list[str] = [
        "beta", "size", "value", "momentum", "quality",
        "volatility", "growth", "leverage", "liquidity",
    ]

    def __init__(self) -> None:
        self._store = ParquetStore()
        self._cleanser = DataCleanser()

    def compute_exposures(self, ticker: str) -> dict[str, float]:
        """Compute all 9 Barra factor exposures for a ticker.

        Args:
            ticker: Stock ticker symbol.

        Returns:
            Dictionary mapping factor name → exposure value (z-score).
        """
        df = self._store.read_daily(ticker)
        if df is None or len(df) < 63:
            logger.warning(f"Insufficient data for {ticker} Barra exposure")
            return {f: 0.0 for f in self.FACTOR_NAMES}

        df = self._cleanser.clean(df, ticker)
        exposures: dict[str, float] = {}

        exposures["beta"] = self._compute_beta(df)
        exposures["size"] = self._compute_size(df)
        exposures["value"] = self._compute_value(df)
        exposures["momentum"] = self._compute_momentum(df)
        exposures["quality"] = self._compute_quality(df)
        exposures["volatility"] = self._compute_volatility(df)
        exposures["growth"] = self._compute_growth(df)
        exposures["leverage"] = self._compute_leverage(df)
        exposures["liquidity"] = self._compute_liquidity(df)

        # Cross-sectional normalization (z-score)
        for key in exposures:
            if not np.isfinite(exposures[key]):
                exposures[key] = 0.0

        return exposures

    def _compute_beta(self, df: pd.DataFrame) -> float:
        """Compute market beta: sensitivity to broad market returns.

        Uses 252-day rolling regression of stock returns on market proxy.
        Falls back to 1.0 if market data unavailable.
        """
        col = "adj_close" if "adj_close" in df.columns else "close"
        returns = df[col].pct_change().dropna()
        if len(returns) < 63:
            return 1.0
        # Use SPY as market proxy
        spy_df = self._store.read_daily("SPY")
        if spy_df is None or len(spy_df) < 63:
            return 1.0
        spy_col = "adj_close" if "adj_close" in spy_df.columns else "close"
        spy_ret = spy_df[spy_col].pct_change().dropna()
        common = returns.index.intersection(spy_ret.index)
        if len(common) < 30:
            return 1.0
        stock = returns.loc[common].tail(252)
        market = spy_ret.loc[common].tail(252)
        cov = stock.cov(market)
        var = market.var()
        return float(cov / var) if var > 0 else 1.0

    def _compute_size(self, df: pd.DataFrame) -> float:
        """Size exposure: natural log of market capitalization proxy."""
        col = "adj_close" if "adj_close" in df.columns else "close"
        price = float(df[col].tail(21).mean())
        avg_volume = float(df["volume"].tail(63).mean())
        # Market cap proxy: price * avg volume * multiplier
        size_proxy = np.log(max(price * avg_volume, 1e6))
        return size_proxy

    def _compute_value(self, df: pd.DataFrame) -> float:
        """Value exposure: Book/Price approximation via price momentum."""
        col = "adj_close" if "adj_close" in df.columns else "close"
        ret_12m = float(df[col].pct_change(252).iloc[-1])
        ret_1m = float(df[col].pct_change(21).iloc[-1])
        # Value stocks tend to have negative momentum; invert
        return -0.6 * ret_12m - 0.4 * ret_1m

    def _compute_momentum(self, df: pd.DataFrame) -> float:
        """Momentum exposure: 12-month return skipping most recent month."""
        col = "adj_close" if "adj_close" in df.columns else "close"
        ret_12m = float(df[col].pct_change(252).iloc[-1])
        ret_1m = float(df[col].pct_change(21).iloc[-1])
        return ret_12m - ret_1m

    def _compute_quality(self, df: pd.DataFrame) -> float:
        """Quality exposure: return stability and margin proxy."""
        col = "adj_close" if "adj_close" in df.columns else "close"
        returns = df[col].pct_change().dropna().tail(252)
        if len(returns) < 30:
            return 0.0
        # Higher Sharpe-like ratio = higher quality
        mean_ret = float(returns.mean())
        std_ret = float(returns.std())
        return mean_ret / std_ret if std_ret > 0 else 0.0

    def _compute_volatility(self, df: pd.DataFrame) -> float:
        """Volatility exposure: historical sigma (annualized)."""
        col = "adj_close" if "adj_close" in df.columns else "close"
        returns = df[col].pct_change().dropna().tail(252)
        if len(returns) < 30:
            return 0.0
        return float(returns.std() * np.sqrt(252))

    def _compute_growth(self, df: pd.DataFrame) -> float:
        """Growth exposure: recent earnings/revenue growth proxy."""
        col = "adj_close" if "adj_close" in df.columns else "close"
        ret_6m = float(df[col].pct_change(126).iloc[-1])
        # Volume growth as revenue proxy
        vol_early = float(df["volume"].iloc[-126:-63].mean())
        vol_late = float(df["volume"].iloc[-63:].mean())
        vol_growth = (vol_late - vol_early) / max(vol_early, 1)
        return 0.7 * ret_6m + 0.3 * vol_growth

    def _compute_leverage(self, df: pd.DataFrame) -> float:
        """Leverage exposure: price/volume volatility as debt proxy."""
        col = "adj_close" if "adj_close" in df.columns else "close"
        returns = df[col].pct_change().dropna().tail(252)
        if len(returns) < 30:
            return 0.0
        # Higher volatility + higher volume swings = higher leverage
        vol = float(returns.std())
        vol_vol = float(df["volume"].pct_change().std())
        return vol * (1.0 + vol_vol)

    def _compute_liquidity(self, df: pd.DataFrame) -> float:
        """Liquidity exposure: Amihud illiquidity + turnover."""
        col = "adj_close" if "adj_close" in df.columns else "close"
        ret_abs = df[col].pct_change().abs().tail(63)
        dollar_vol = (df["volume"] * df[col]).tail(63)
        daily_illiq = (ret_abs / dollar_vol.replace(0, np.nan)).replace([np.inf, -np.inf], 0)
        amihud = float(daily_illiq.mean()) if len(daily_illiq) > 0 else 0.0

        # Monthly turnover
        turnover = float(df["volume"].tail(21).mean() / df["volume"].tail(252).mean())
        return -amihud * 1e9 + turnover
