"""services/factor_service/factors/microstructure.py – Microstructure factors (12 factors).

Spread, liquidity, order flow, and high-frequency factors.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from services.factor_service.engine.factor_base import FactorBase


class BidAskSpread(FactorBase):
    factor_id = "F300"
    name = "bid_ask_spread"
    category = "microstructure"
    subcategory = "spread"
    description = "Time-weighted quoted spread (%)"
    lookback_default = 5
    frequency = "daily"
    direction = -1

    def compute(self, df: pd.DataFrame) -> pd.Series:
        if "bid" in df.columns and "ask" in df.columns:
            midpoint = (df["bid"] + df["ask"]) / 2.0
            spread = df["ask"] - df["bid"]
            return spread / midpoint.clip(lower=1e-8) * 100.0
        # Approximate from HL range
        return (df["high"] - df["low"]) / df["close"].clip(lower=1e-8) * 100.0


class AmihudIlliquidity(FactorBase):
    factor_id = "F303"
    name = "price_impact"
    category = "microstructure"
    subcategory = "liquidity"
    description = "Amihud illiquidity (|ret|/volume)"
    lookback_default = 21
    frequency = "daily"
    direction = -1

    def compute(self, df: pd.DataFrame) -> pd.Series:
        col = "adj_close" if "adj_close" in df.columns else "close"
        ret = df[col].pct_change().abs()
        # Scale to avoid tiny numbers
        dollar_volume = df["volume"] * df[col] / 1_000_000
        daily_illiq = ret / dollar_volume.clip(lower=1e-8)
        return daily_illiq.rolling(21).mean()


class OrderImbalance(FactorBase):
    factor_id = "F304"
    name = "order_imbalance"
    category = "microstructure"
    subcategory = "flow"
    description = "Signed order flow imbalance"
    lookback_default = 5
    frequency = "daily"
    direction = 1

    def compute(self, df: pd.DataFrame) -> pd.Series:
        col = "close"
        # Approximate: price change direction × volume ratio
        direction = np.sign(df[col].diff())
        vol_ratio = df["volume"] / df["volume"].rolling(21).mean()
        imbalance = direction * vol_ratio
        return imbalance.rolling(5).mean()


class DepthImbalance(FactorBase):
    factor_id = "F305"
    name = "depth_imbalance"
    category = "microstructure"
    subcategory = "flow"
    description = "Bid depth / (Bid+Ask depth) at top of book"
    lookback_default = 5
    frequency = "daily"
    direction = 1

    def compute(self, df: pd.DataFrame) -> pd.Series:
        if "bid_size" in df.columns and "ask_size" in df.columns:
            return df["bid_size"] / (df["bid_size"] + df["ask_size"]).clip(lower=1e-8)
        # Fallback: use volume-weighted close deviation
        col = "close"
        typical = (df["high"] + df["low"] + df["close"]) / 3.0
        return 0.5 + 0.5 * (df[col] - typical) / typical.clip(lower=1e-8)


class TradeSizeSkew(FactorBase):
    factor_id = "F306"
    name = "trade_size_skew"
    category = "microstructure"
    subcategory = "flow"
    description = "Ratio of large-trade volume to total volume"
    lookback_default = 5
    frequency = "daily"
    direction = 1

    def compute(self, df: pd.DataFrame) -> pd.Series:
        # Approximate large trades by volume spikes
        avg_vol = df["volume"].rolling(21).mean()
        large_trade_vol = df["volume"].where(df["volume"] > avg_vol * 1.5, 0.0)
        cum_large = large_trade_vol.rolling(5).sum()
        cum_total = df["volume"].rolling(5).sum()
        return cum_large / cum_total.clip(lower=1e-8)


class IntradayReversal(FactorBase):
    factor_id = "F307"
    name = "intraday_reversal"
    category = "microstructure"
    subcategory = "reversal"
    description = "Intraday return reversal (open-close vs close-next_open)"
    lookback_default = 5
    frequency = "intraday"
    direction = -1

    def compute(self, df: pd.DataFrame) -> pd.Series:
        # Daily approximation: overnight vs intraday return
        daily_ret = df["close"].pct_change()
        overnight_ret = df["open"] / df["close"].shift(1) - 1.0
        intraday_ret = df["close"] / df["open"] - 1.0
        # Reversal: intraday move reversed overnight
        return -intraday_ret.rolling(5).mean()


class TradeSigningRatio(FactorBase):
    factor_id = "F308"
    name = "trade_signing_ratio"
    category = "microstructure"
    subcategory = "flow"
    description = "Lee-Ready trade classification buy ratio"
    lookback_default = 5
    frequency = "intraday"
    direction = 1

    def compute(self, df: pd.DataFrame) -> pd.Series:
        col = "close"
        # Approximate buy/sell ratio from price vs midpoint
        midpoint = (df["high"] + df["low"]) / 2.0
        buy_signal = (df[col] > midpoint).astype(float)
        return buy_signal.rolling(5).mean()


class MarketImpactModel(FactorBase):
    factor_id = "F309"
    name = "market_impact_model"
    category = "microstructure"
    subcategory = "impact"
    description = "Almgren-Chriss temporary impact coefficient"
    lookback_default = 21
    frequency = "daily"
    direction = -1

    def compute(self, df: pd.DataFrame) -> pd.Series:
        col = "close"
        ret = df[col].pct_change().abs()
        dollar_volume = df["volume"] * df[col]
        # Square-root impact model
        impact = ret / (dollar_volume ** 0.5).clip(lower=1e-8)
        return impact.rolling(21).mean()


class HighFreqMomentum(FactorBase):
    factor_id = "F311"
    name = "high_freq_mom"
    category = "microstructure"
    subcategory = "momentum"
    description = "Intraday momentum (short horizon)"
    lookback_default = 1
    frequency = "intraday"
    neutralizable = False
    direction = 1

    def compute(self, df: pd.DataFrame) -> pd.Series:
        col = "close"
        # Short-term return acceleration
        ret_1d = df[col].pct_change(1)
        ret_5d = df[col].pct_change(5)
        return ret_1d - ret_5d / 5.0


class VolumeSynchronizedProb(FactorBase):
    factor_id = "F310"
    name = "volume_synchronized_prob"
    category = "microstructure"
    subcategory = "correlation"
    description = "VPIN (Volume-synchronized PIN)"
    lookback_default = 21
    frequency = "daily"
    direction = -1

    def compute(self, df: pd.DataFrame) -> pd.Series:
        col = "close"
        # Simplified VPIN: volume imbalance over rolling window
        direction = np.sign(df[col].diff())
        vol_by_direction_up = (direction * df["volume"]).where(direction > 0, 0)
        vol_by_direction_down = (-direction * df["volume"]).where(direction < 0, 0)
        total_vol = df["volume"].rolling(21).sum()
        vpin = (vol_by_direction_up.rolling(21).sum() - vol_by_direction_down.rolling(21).sum()).abs()
        return vpin / total_vol.clip(lower=1e-8)


# ── Aggregate list ───────────────────────────────────────────
MICROSTRUCTURE_FACTORS: list[FactorBase] = [
    BidAskSpread(), AmihudIlliquidity(),
    OrderImbalance(), DepthImbalance(), TradeSizeSkew(),
    IntradayReversal(), TradeSigningRatio(),
    MarketImpactModel(), HighFreqMomentum(), VolumeSynchronizedProb(),
]
