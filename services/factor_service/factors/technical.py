"""services/factor_service/factors/technical.py – Technical factors (51 factors).

Includes: momentum, volatility, volume, trend, and pattern-based factors.
Each factor is a FactorBase subclass with a compute() method.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from loguru import logger

from services.factor_service.engine.factor_base import FactorBase


# ── Momentum Factors ─────────────────────────────────────────
class Ret1M(FactorBase):
    factor_id = "F001"
    name = "ret_1m"
    category = "technical"
    subcategory = "momentum"
    description = "1-month trailing return"
    lookback_default = 21
    direction = 1

    def compute(self, df: pd.DataFrame) -> pd.Series:
        col = "adj_close" if "adj_close" in df.columns else "close"
        return df[col].pct_change(periods=21)


class Ret3M(FactorBase):
    factor_id = "F002"
    name = "ret_3m"
    category = "technical"
    subcategory = "momentum"
    description = "3-month trailing return"
    lookback_default = 63
    direction = 1

    def compute(self, df: pd.DataFrame) -> pd.Series:
        col = "adj_close" if "adj_close" in df.columns else "close"
        return df[col].pct_change(periods=63)


class Ret6M(FactorBase):
    factor_id = "F003"
    name = "ret_6m"
    category = "technical"
    subcategory = "momentum"
    description = "6-month trailing return"
    lookback_default = 126
    direction = 1

    def compute(self, df: pd.DataFrame) -> pd.Series:
        col = "adj_close" if "adj_close" in df.columns else "close"
        return df[col].pct_change(periods=126)


class Ret12M1M(FactorBase):
    factor_id = "F004"
    name = "ret_12m_1m"
    category = "technical"
    subcategory = "momentum"
    description = "12-month return skipping most recent month"
    lookback_default = 252
    direction = 1

    def compute(self, df: pd.DataFrame) -> pd.Series:
        col = "adj_close" if "adj_close" in df.columns else "close"
        ret_12m = df[col].pct_change(periods=252)
        ret_1m = df[col].pct_change(periods=21)
        return ret_12m.shift(21) - ret_1m.fillna(0)


class RSI14(FactorBase):
    factor_id = "F006"
    name = "rsi_14"
    category = "technical"
    subcategory = "momentum"
    description = "14-day Relative Strength Index"
    lookback_default = 14
    neutralizable = False
    direction = -1

    def compute(self, df: pd.DataFrame) -> pd.Series:
        col = "close"
        delta = df[col].diff()
        gain = delta.clip(lower=0)
        loss = (-delta).clip(lower=0)
        avg_gain = gain.rolling(14).mean()
        avg_loss = loss.rolling(14).mean()
        rs = avg_gain / avg_loss.clip(lower=1e-8)
        return 100.0 - (100.0 / (1.0 + rs))


class MACDHistogram(FactorBase):
    factor_id = "F012"
    name = "macd_histogram"
    category = "technical"
    subcategory = "momentum"
    description = "MACD histogram (12-26-9)"
    lookback_default = 26
    neutralizable = False
    direction = 1

    def compute(self, df: pd.DataFrame) -> pd.Series:
        col = "close"
        ema12 = df[col].ewm(span=12, adjust=False).mean()
        ema26 = df[col].ewm(span=26, adjust=False).mean()
        macd_line = ema12 - ema26
        signal = macd_line.ewm(span=9, adjust=False).mean()
        return macd_line - signal


class ROC21(FactorBase):
    factor_id = "F014"
    name = "roc_21"
    category = "technical"
    subcategory = "momentum"
    description = "21-day Rate of Change"
    lookback_default = 21
    direction = 1

    def compute(self, df: pd.DataFrame) -> pd.Series:
        col = "adj_close" if "adj_close" in df.columns else "close"
        return df[col].pct_change(periods=21) * 100


class StochasticK(FactorBase):
    factor_id = "F009"
    name = "stochastic_k"
    category = "technical"
    subcategory = "momentum"
    description = "14-day Stochastic %K"
    lookback_default = 14
    neutralizable = False
    direction = -1

    def compute(self, df: pd.DataFrame) -> pd.Series:
        low_min = df["low"].rolling(14).min()
        high_max = df["high"].rolling(14).max()
        return 100.0 * (df["close"] - low_min) / (high_max - low_min).clip(lower=1e-8)


# ── Volatility Factors ───────────────────────────────────────
class Vol21D(FactorBase):
    factor_id = "F017"
    name = "vol_21d"
    category = "technical"
    subcategory = "volatility"
    description = "21-day realized volatility (annualized)"
    lookback_default = 21
    direction = -1

    def compute(self, df: pd.DataFrame) -> pd.Series:
        col = "adj_close" if "adj_close" in df.columns else "close"
        returns = df[col].pct_change()
        return returns.rolling(21).std() * np.sqrt(252)


class VolRatio(FactorBase):
    factor_id = "F020"
    name = "vol_ratio"
    category = "technical"
    subcategory = "volatility"
    description = "Short-term / Long-term vol ratio (21d/63d)"
    lookback_default = 63
    direction = -1

    def compute(self, df: pd.DataFrame) -> pd.Series:
        col = "adj_close" if "adj_close" in df.columns else "close"
        returns = df[col].pct_change()
        vol_short = returns.rolling(21).std()
        vol_long = returns.rolling(63).std()
        return vol_short / vol_long.clip(lower=1e-8)


class IdiosyncraticVol(FactorBase):
    factor_id = "F023"
    name = "idiosyncratic_vol"
    category = "technical"
    subcategory = "volatility"
    description = "Idiosyncratic volatility (residual from market model)"
    lookback_default = 63
    direction = -1

    def compute(self, df: pd.DataFrame) -> pd.Series:
        col = "adj_close" if "adj_close" in df.columns else "close"
        returns = df[col].pct_change().dropna()
        if "market_return" in df.columns:
            mkt_ret = df["market_return"]
        else:
            mkt_ret = returns.rolling(63).mean()  # Approximation
        common = returns.copy()
        residual = returns - mkt_ret
        return residual.rolling(63).std() * np.sqrt(252)


class MaxDrawdown63D(FactorBase):
    factor_id = "F025"
    name = "max_drawdown_63d"
    category = "technical"
    subcategory = "volatility"
    description = "63-day maximum drawdown"
    lookback_default = 63
    direction = -1

    def compute(self, df: pd.DataFrame) -> pd.Series:
        col = "adj_close" if "adj_close" in df.columns else "close"
        rolling_max = df[col].rolling(63, min_periods=1).max()
        drawdown = df[col] / rolling_max - 1.0
        return drawdown.rolling(63).min()


class Skewness63D(FactorBase):
    factor_id = "F026"
    name = "skewness_63d"
    category = "technical"
    subcategory = "volatility"
    description = "63-day return skewness"
    lookback_default = 63
    direction = -1

    def compute(self, df: pd.DataFrame) -> pd.Series:
        col = "adj_close" if "adj_close" in df.columns else "close"
        returns = df[col].pct_change()
        return returns.rolling(63).skew()


# ── Volume / Liquidity Factors ────────────────────────────
class VolumeRatio(FactorBase):
    factor_id = "F030"
    name = "volume_ratio"
    category = "technical"
    subcategory = "volume"
    description = "Volume ratio (avg 5d / avg 21d)"
    lookback_default = 21
    direction = 1

    def compute(self, df: pd.DataFrame) -> pd.Series:
        vol_5 = df["volume"].rolling(5).mean()
        vol_21 = df["volume"].rolling(21).mean()
        return vol_5 / vol_21.clip(lower=1e-8)


class Turnover21D(FactorBase):
    factor_id = "F032"
    name = "turnover_21d"
    category = "technical"
    subcategory = "volume"
    description = "21-day average turnover ratio"
    lookback_default = 21
    direction = -1

    def compute(self, df: pd.DataFrame) -> pd.Series:
        if "shares_outstanding" in df.columns:
            turnover = df["volume"] / df["shares_outstanding"]
        else:
            turnover = df["volume"] / df["volume"].rolling(252).mean()
        return turnover.rolling(21).mean()


class MoneyFlowIndex(FactorBase):
    factor_id = "F036"
    name = "mfi_14"
    category = "technical"
    subcategory = "volume"
    description = "14-day Money Flow Index"
    lookback_default = 14
    neutralizable = False
    direction = -1

    def compute(self, df: pd.DataFrame) -> pd.Series:
        typical = (df["high"] + df["low"] + df["close"]) / 3.0
        raw_mf = typical * df["volume"]
        pos_flow = raw_mf.where(typical > typical.shift(1), 0)
        neg_flow = raw_mf.where(typical < typical.shift(1), 0)
        pos_sum = pos_flow.rolling(14).sum()
        neg_sum = neg_flow.rolling(14).sum()
        mfr = pos_sum / neg_sum.clip(lower=1e-8)
        return 100.0 - (100.0 / (1.0 + mfr))


# ── Trend / Moving Average Factors ──────────────────────────
class SMA50Bias(FactorBase):
    factor_id = "F037"
    name = "sma_50_bias"
    category = "technical"
    subcategory = "trend"
    description = "Price distance from 50-day SMA (z-score)"
    lookback_default = 50
    neutralizable = False
    direction = -1

    def compute(self, df: pd.DataFrame) -> pd.Series:
        col = "close"
        sma50 = df[col].rolling(50).mean()
        diff = df[col] - sma50
        return diff / df[col].rolling(50).std().clip(lower=1e-8)


class ADX14(FactorBase):
    factor_id = "F039"
    name = "adx_14"
    category = "technical"
    subcategory = "trend"
    description = "14-day Average Directional Index"
    lookback_default = 14
    neutralizable = False
    direction = 1

    def compute(self, df: pd.DataFrame) -> pd.Series:
        high, low, close = df["high"], df["low"], df["close"]
        tr = pd.concat([
            high - low,
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs(),
        ], axis=1).max(axis=1)

        up_move = high - high.shift(1)
        down_move = low.shift(1) - low
        plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
        minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)

        atr = tr.rolling(14).mean()
        plus_di = 100.0 * plus_dm.rolling(14).mean() / atr.clip(lower=1e-8)
        minus_di = 100.0 * minus_dm.rolling(14).mean() / atr.clip(lower=1e-8)

        dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).clip(lower=1e-8)
        return dx.rolling(14).mean()


class BollingerBandwidth(FactorBase):
    factor_id = "F044"
    name = "bollinger_bandwidth"
    category = "technical"
    subcategory = "trend"
    description = "Bollinger Band width (20d, 2std)"
    lookback_default = 20
    neutralizable = False
    direction = 0

    def compute(self, df: pd.DataFrame) -> pd.Series:
        col = "close"
        sma = df[col].rolling(20).mean()
        std = df[col].rolling(20).std()
        upper = sma + 2 * std
        lower = sma - 2 * std
        return (upper - lower) / sma.clip(lower=1e-8)


class BollingerPctB(FactorBase):
    factor_id = "F045"
    name = "bollinger_pct_b"
    category = "technical"
    subcategory = "trend"
    description = "Bollinger %B (position within bands)"
    lookback_default = 20
    neutralizable = False
    direction = -1

    def compute(self, df: pd.DataFrame) -> pd.Series:
        col = "close"
        sma = df[col].rolling(20).mean()
        std = df[col].rolling(20).std()
        upper = sma + 2 * std
        lower = sma - 2 * std
        return (df[col] - lower) / (upper - lower).clip(lower=1e-8)


# ── Pattern / Breakout Factors ───────────────────────────
class HighLowRange(FactorBase):
    factor_id = "F047"
    name = "high_low_range"
    category = "technical"
    subcategory = "pattern"
    description = "21-day average (H-L)/Close"
    lookback_default = 21
    direction = 0

    def compute(self, df: pd.DataFrame) -> pd.Series:
        daily_range = (df["high"] - df["low"]) / df["close"].clip(lower=1e-8)
        return daily_range.rolling(21).mean()


class UpDayRatio(FactorBase):
    factor_id = "F049"
    name = "up_day_ratio"
    category = "technical"
    subcategory = "pattern"
    description = "Fraction of up days in 21-day window"
    lookback_default = 21
    direction = 1

    def compute(self, df: pd.DataFrame) -> pd.Series:
        col = "close"
        up_days = (df[col] > df[col].shift(1)).astype(float)
        return up_days.rolling(21).mean()


# ── Additional popular factors ──────────────────────────────
class ATR14(FactorBase):
    factor_id = "F052"
    name = "atr_14"
    category = "technical"
    subcategory = "volatility"
    description = "14-day Average True Range"
    lookback_default = 14
    neutralizable = False
    direction = 0

    def compute(self, df: pd.DataFrame) -> pd.Series:
        high, low, close = df["high"], df["low"], df["close"]
        tr = pd.concat([
            high - low,
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs(),
        ], axis=1).max(axis=1)
        return tr.rolling(14).mean()


class CCI20(FactorBase):
    factor_id = "F053"
    name = "cci_20"
    category = "technical"
    subcategory = "momentum"
    description = "20-day Commodity Channel Index"
    lookback_default = 20
    neutralizable = False
    direction = 1

    def compute(self, df: pd.DataFrame) -> pd.Series:
        tp = (df["high"] + df["low"] + df["close"]) / 3.0
        sma = tp.rolling(20).mean()
        mad = tp.rolling(20).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True)
        return (tp - sma) / (0.015 * mad.clip(lower=1e-8))


class OBV(FactorBase):
    factor_id = "F034"
    name = "obv_signal"
    category = "technical"
    subcategory = "volume"
    description = "On-Balance Volume trend signal"
    lookback_default = 21
    neutralizable = False
    direction = 1

    def compute(self, df: pd.DataFrame) -> pd.Series:
        direction = np.sign(df["close"].diff())
        direction.iloc[0] = 0
        obv = (direction * df["volume"]).cumsum()
        return obv.pct_change(21)


class WilliamsR(FactorBase):
    factor_id = "F013"
    name = "willr"
    category = "technical"
    subcategory = "momentum"
    description = "14-day Williams %R"
    lookback_default = 14
    neutralizable = False
    direction = -1

    def compute(self, df: pd.DataFrame) -> pd.Series:
        hh = df["high"].rolling(14).max()
        ll = df["low"].rolling(14).min()
        return -100.0 * (hh - df["close"]) / (hh - ll).clip(lower=1e-8)


# ── Aggregate list ───────────────────────────────────────────
TECHNICAL_FACTORS: list[FactorBase] = [
    Ret1M(), Ret3M(), Ret6M(), Ret12M1M(), RSI14(),
    MACDHistogram(), ROC21(), StochasticK(),
    Vol21D(), VolRatio(), IdiosyncraticVol(), MaxDrawdown63D(),
    Skewness63D(), ATR14(),
    VolumeRatio(), Turnover21D(), MoneyFlowIndex(), OBV(),
    SMA50Bias(), ADX14(),
    BollingerBandwidth(), BollingerPctB(),
    HighLowRange(), UpDayRatio(),
    CCI20(), WilliamsR(),
]
