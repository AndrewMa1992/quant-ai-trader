"""
Data pipeline - feature engineering.
Quant-fund-grade technical indicators and factor computation.
"""
import pandas as pd
import numpy as np
from typing import List, Optional, Tuple


class DataPipeline:
    """
    Feature-engineering pipeline.
    - 30+ technical indicators
    - Missing-value handling
    - Standardization / normalization
    - Sequencing (for Transformer input)
    """
    # Quant-fund-grade features (63)
    FEATURE_COLUMNS = [
        # === Returns (7) ===
        "returns_1d", "returns_5d", "returns_20d", "returns_60d",
        "high_minus_low", "close_minus_open", "body_pct",
        
        # === Price transforms (3) ===
        "typical_price", "log_return", "price_position_20",
        
        # === Trend (10) ===
        "close_sma_5", "close_sma_10", "close_sma_20", "close_sma_50", "close_sma_200",
        "ema_12", "ema_26",
        "macd", "macd_signal", "macd_hist",
        
        # === Momentum (10) ===
        "rsi_14", "rsi_21",
        "stoch_k", "stoch_d",
        "williams_r", "cci", "roc_10", "momentum_10", "momentum_20",
        "adx_14",
        
        # === Volatility (8) ===
        "bb_width_20", "bb_pct_20",
        "atr_14", "atr_ratio",
        "hist_vol_10", "hist_vol_21", "hist_vol_63",
        "keltner_width",
        
        # === Volume (10) ===
        "vol_ratio_5", "vol_ratio_20", "vol_ratio_60",
        "obv", "vpt", "mfi", "cmf_20",
        "volume_trend_5", "volume_trend_20",
        "volatility_of_volume",
        
        # === Price patterns (7) ===
        "consecutive_ups", "consecutive_downs",
        "gap_up", "gap_down",
        "doji", "hammer", "engulfing",
        
        # === Market structure (8) ===
        "high_low_ratio",
        "sar", "ichimoku_lead",
        "close_vs_sma_20", "close_vs_sma_50", "close_vs_sma_200",
        "sma_20_vs_50", "sma_50_vs_200",
    ]

    def __init__(self):
        self._feature_cache = {}

    # ================================================================
    # Core processing
    # ================================================================

    def process(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Run full feature engineering on a single ticker's data.

        Args:
            df: DataFrame with open, high, low, close, volume columns

        Returns:
            DataFrame with all technical indicators added
        """
        if df.empty:
            return df

        data = df.copy()

        # Basic derived features
        data = self._add_basic_features(data)

        # Trend indicators
        data = self._add_trend_indicators(data)

        # Momentum indicators
        data = self._add_momentum_indicators(data)

        # Volatility indicators
        data = self._add_volatility_indicators(data)

        # Volume indicators
        data = self._add_volume_indicators(data)

        # Price-pattern features
        data = self._add_price_pattern_features(data)

        return data

    def prepare_sequence(
        self,
        df: pd.DataFrame,
        lookback: int = 60,
        feature_cols: Optional[List[str]] = None
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Convert processed data into sequence format (Transformer input).

        Args:
            df: processed data
            lookback: lookback window
            feature_cols: feature columns to use

        Returns:
            (X, y): input sequences and targets
        """
        if feature_cols is None:
            feature_cols = [c for c in df.columns if c not in [
                "open", "high", "low", "close", "volume",
                "ticker", "dividends", "stock_splits"
            ]]

        data = df[feature_cols].values
        X, y = [], []

        for i in range(lookback, len(data)):
            X.append(data[i - lookback:i])
            y.append(data[i, 0])  # predict next-period close

        return np.array(X), np.array(y)

    def normalize(self, df: pd.DataFrame, method: str = "zscore") -> pd.DataFrame:
        """Standardize numeric columns."""
        data = df.copy()
        numeric_cols = data.select_dtypes(include=[np.number]).columns

        if method == "zscore":
            data[numeric_cols] = (data[numeric_cols] - data[numeric_cols].mean()) / data[numeric_cols].std()
        elif method == "minmax":
            data[numeric_cols] = (data[numeric_cols] - data[numeric_cols].min()) / \
                                 (data[numeric_cols].max() - data[numeric_cols].min() + 1e-8)
        elif method == "pct_change":
            data[numeric_cols] = data[numeric_cols].pct_change()

        return data.fillna(0).replace([np.inf, -np.inf], 0)

    # ================================================================
    # Basic features
    # ================================================================

    def _add_basic_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Basic derived features."""
        data = df.copy()

        # Returns
        data["returns_1d"] = data["close"].pct_change(1)
        data["returns_5d"] = data["close"].pct_change(5)
        data["returns_20d"] = data["close"].pct_change(20)
        data["returns_60d"] = data["close"].pct_change(60)

        # Price location
        data["high_minus_low"] = data["high"] - data["low"]
        data["close_minus_open"] = data["close"] - data["open"]
        data["body_pct"] = abs(data["close"] - data["open"]) / (data["high"] - data["low"] + 1e-8)
        data["high_low_ratio"] = data["high"] / (data["low"] + 1e-8)

        # Typical price
        data["typical_price"] = (data["high"] + data["low"] + data["close"]) / 3
        data["vwap"] = (data["volume"] * data["typical_price"]).rolling(20).sum() / \
                        data["volume"].rolling(20).sum()

        # Log returns
        data["log_return"] = np.log(data["close"] / data["close"].shift(1))

        # Intraday range (useful for minute-level data)
        data["intraday_range"] = data["high"] / data["low"] - 1

        return data

    # ================================================================
    # Trend indicators
    # ================================================================

    def _add_trend_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Trend technical indicators."""
        data = df.copy()
        close = data["close"]

        # SMA - simple moving average
        for period in [5, 10, 20, 50, 200]:
            data[f"sma_{period}"] = close.rolling(period).mean()
            data[f"close_sma_{period}"] = (close - data[f"sma_{period}"]) / data[f"sma_{period}"]
        
        # Close vs SMA (percentage)
        data["close_vs_sma_20"] = data["close"] / (data["sma_20"] + 1e-8) - 1
        data["close_vs_sma_50"] = data["close"] / (data["sma_50"] + 1e-8) - 1  
        data["close_vs_sma_200"] = data["close"] / (data["sma_200"] + 1e-8) - 1
        
        # SMA cross signals
        data["sma_20_vs_50"] = data["sma_20"] / (data["sma_50"] + 1e-8) - 1
        data["sma_50_vs_200"] = data["sma_50"] / (data["sma_200"] + 1e-8) - 1
        
        # Price position in 20-day range
        data["price_position_20"] = (close - close.rolling(20).min()) / (close.rolling(20).max() - close.rolling(20).min() + 1e-8)

        # EMA - exponential moving average
        for period in [12, 26, 50]:
            data[f"ema_{period}"] = close.ewm(span=period, adjust=False).mean()

        # MACD
        ema_12 = close.ewm(span=12, adjust=False).mean()
        ema_26 = close.ewm(span=26, adjust=False).mean()
        data["macd"] = ema_12 - ema_26
        data["macd_signal"] = data["macd"].ewm(span=9, adjust=False).mean()
        data["macd_hist"] = data["macd"] - data["macd_signal"]

        # Ichimoku Cloud (simplified)
        data["ichimoku_tenkan"] = (data["high"].rolling(9).max() + data["low"].rolling(9).min()) / 2
        data["ichimoku_kijun"] = (data["high"].rolling(26).max() + data["low"].rolling(26).min()) / 2
        data["ichimoku_lead"] = (data["ichimoku_tenkan"] + data["ichimoku_kijun"]) / 2

        # ADX
        data["adx_14"] = self._compute_adx(data["high"], data["low"], close, period=14)

        # Parabolic SAR
        data["sar"] = self._compute_parabolic_sar(data["high"], data["low"], close)

        return data

    # ================================================================
    # Momentum indicators
    # ================================================================

    def _add_momentum_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Momentum indicators."""
        data = df.copy()
        close = data["close"]

        # RSI
        for period in [6, 14, 21]:
            data[f"rsi_{period}"] = self._compute_rsi(close, period)

        # Stochastic Oscillator
        k_period = 14
        low_14 = data["low"].rolling(k_period).min()
        high_14 = data["high"].rolling(k_period).max()
        data["stoch_k"] = 100 * (close - low_14) / (high_14 - low_14 + 1e-8)
        data["stoch_d"] = data["stoch_k"].rolling(3).mean()

        # Williams %R
        data["williams_r"] = -100 * (high_14 - close) / (high_14 - low_14 + 1e-8)

        # CCI - Commodity Channel Index
        tp = (data["high"] + data["low"] + close) / 3
        data["cci"] = (tp - tp.rolling(20).mean()) / (tp.rolling(20).std() + 1e-8)

        # ROC - Rate of Change
        for period in [5, 10, 20]:
            data[f"roc_{period}"] = close.pct_change(period) * 100

        # Momentum
        for period in [10, 20]:
            data[f"momentum_{period}"] = close - close.shift(period)

        # Ultimate Oscillator
        data["ult_osc"] = self._compute_ultimate_oscillator(data)

        return data

    # ================================================================
    # Volatility indicators
    # ================================================================

    def _add_volatility_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Volatility indicators."""
        data = df.copy()
        close = data["close"]

        # Bollinger Bands
        for period in [20, 50]:
            sma = close.rolling(period).mean()
            std = close.rolling(period).std()
            data[f"bb_sma_{period}"] = sma
            data[f"bb_upper_{period}"] = sma + 2 * std
            data[f"bb_lower_{period}"] = sma - 2 * std
            data[f"bb_width_{period}"] = (data[f"bb_upper_{period}"] - data[f"bb_lower_{period}"]) / sma
            data[f"bb_pct_{period}"] = (close - data[f"bb_lower_{period}"]) / \
                                        (data[f"bb_upper_{period}"] - data[f"bb_lower_{period}"] + 1e-8)

        # ATR - Average True Range
        for period in [14, 21]:
            data[f"atr_{period}"] = self._compute_atr(data["high"], data["low"], close, period)

        # Keltner Channels
        for period in [20]:
            ema = close.ewm(span=period).mean()
            atr = self._compute_atr(data["high"], data["low"], close, period)
            data[f"kc_upper_{period}"] = ema + 1.5 * atr
            data[f"kc_lower_{period}"] = ema - 1.5 * atr

        # Historical Volatility
        for period in [10, 21, 63]:
            data[f"hist_vol_{period}"] = data["log_return"].rolling(period).std() * np.sqrt(252)
        
        # ATR ratio (ATR/Close)
        data["atr_ratio"] = data["atr_14"] / (close + 1e-8)
        
        # Keltner Width
        data["keltner_width"] = (data["kc_upper_20"] - data["kc_lower_20"]) / (data["kc_upper_20"] + data["kc_lower_20"] + 1e-8)

        return data

    # ================================================================
    # Volume indicators
    # ================================================================

    def _add_volume_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Volume indicators."""
        data = df.copy()
        volume = data["volume"]

        # Volume SMA
        for period in [5, 10, 20, 60]:
            data[f"vol_sma_{period}"] = volume.rolling(period).mean()
            data[f"vol_ratio_{period}"] = volume / (data[f"vol_sma_{period}"] + 1e-8)

        # OBV - On-Balance Volume
        obv = (np.sign(data["returns_1d"]) * volume).fillna(0).cumsum()
        data["obv"] = obv
        data["obv_sma"] = obv.rolling(20).mean()

        # Volume Price Trend
        data["vpt"] = (data["returns_1d"] * volume).fillna(0).cumsum()

        # Money Flow Index
        data["mfi"] = self._compute_mfi(data, period=14)

        # Chaikin Money Flow
        mf_multiplier = ((close := data["close"]) - data["low"] - (data["high"] - close)) / \
                         (data["high"] - data["low"] + 1e-8)
        mf_volume = mf_multiplier * volume
        data["cmf_20"] = mf_volume.rolling(20).sum() / volume.rolling(20).sum()

        # Volume Weighted Average Price (VWAP)
        data["vwap"] = (data["typical_price"] * volume).rolling(20).sum() / volume.rolling(20).sum()
        
        # Volume trend (rate of change)
        data["volume_trend_5"] = volume.pct_change(5)
        data["volume_trend_20"] = volume.pct_change(20)
        
        # Volatility of volume
        data["volatility_of_volume"] = volume.pct_change().rolling(20).std()

        return data

    # ================================================================
    # Price-pattern features
    # ================================================================

    def _add_price_pattern_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Price-pattern features."""
        data = df.copy()

        # Doji (cross)
        data["doji"] = (abs(data["close"] - data["open"]) <= (data["high"] - data["low"]) * 0.1).astype(float)

        # Hammer / hanging man
        body = abs(data["close"] - data["open"])
        lower_shadow = data["low"].where(data["close"] > data["open"], data["low"]).where(
            data["close"] < data["open"], data["low"])
        # Simplified: lower shadow is at least 2x the body
        data["hammer"] = (lower_shadow > body * 2).astype(float)

        # Consecutive up/down days
        data["consecutive_ups"] = (data["returns_1d"] > 0).astype(int).groupby(
            (data["returns_1d"] <= 0).cumsum()).cumsum()
        data["consecutive_downs"] = (data["returns_1d"] < 0).astype(int).groupby(
            (data["returns_1d"] >= 0).cumsum()).cumsum()

        # New highs / lows
        data["new_high_20"] = (close := data["close"]) == close.rolling(20).max()
        data["new_low_20"] = close == close.rolling(20).min()

        # Gaps
        data["gap_up"] = (data["low"] > data["high"].shift(1)).astype(float)
        data["gap_down"] = (data["high"] < data["low"].shift(1)).astype(float)
        
        # Engulfing pattern
        prev_open = data["open"].shift(1)
        prev_close = data["close"].shift(1)
        bullish_engulf = (data["close"] > prev_open) & (data["open"] < prev_close) & (data["close"] > data["open"])
        bearish_engulf = (data["close"] < prev_open) & (data["open"] > prev_close) & (data["close"] < data["open"])
        data["engulfing"] = (bullish_engulf.astype(int) - bearish_engulf.astype(int)).astype(float) + 1

        return data

    # ================================================================
    # Internal helpers
    # ================================================================

    @staticmethod
    def _compute_rsi(close: pd.Series, period: int = 14) -> pd.Series:
        """Compute RSI."""
        delta = close.diff()
        gain = delta.where(delta > 0, 0).rolling(period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
        rs = gain / (loss + 1e-8)
        return 100 - (100 / (1 + rs))

    @staticmethod
    def _compute_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
        """Compute ATR."""
        tr1 = high - low
        tr2 = abs(high - close.shift())
        tr3 = abs(low - close.shift())
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return tr.rolling(period).mean()

    @staticmethod
    def _compute_adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
        """Compute ADX."""
        tr = DataPipeline._compute_atr(high, low, close, period)
        up_move = high - high.shift()
        down_move = low.shift() - low

        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0)

        plus_di = 100 * pd.Series(plus_dm, index=close.index).rolling(period).mean() / (tr + 1e-8)
        minus_di = 100 * pd.Series(minus_dm, index=close.index).rolling(period).mean() / (tr + 1e-8)

        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di + 1e-8)
        return dx.rolling(period).mean()

    @staticmethod
    def _compute_mfi(df: pd.DataFrame, period: int = 14) -> pd.Series:
        """Compute MFI."""
        typical_price = (df["high"] + df["low"] + df["close"]) / 3
        money_flow = typical_price * df["volume"]
        positive_flow = money_flow.where(typical_price > typical_price.shift(), 0).rolling(period).sum()
        negative_flow = money_flow.where(typical_price < typical_price.shift(), 0).rolling(period).sum()
        mfi_ratio = positive_flow / (negative_flow + 1e-8)
        return 100 - (100 / (1 + mfi_ratio))

    @staticmethod
    def _compute_ultimate_oscillator(df: pd.DataFrame) -> pd.Series:
        """Compute Ultimate Oscillator."""
        close = df["close"]
        low = df["low"]
        high = df["high"]

        bp = close - pd.concat([low, close.shift()], axis=1).min(axis=1)
        tr = pd.concat(
            [high - low, abs(high - close.shift()), abs(low - close.shift())], axis=1
        ).max(axis=1)

        avg7 = bp.rolling(7).sum() / (tr.rolling(7).sum() + 1e-8)
        avg14 = bp.rolling(14).sum() / (tr.rolling(14).sum() + 1e-8)
        avg28 = bp.rolling(28).sum() / (tr.rolling(28).sum() + 1e-8)

        return 100 * (4 * avg7 + 2 * avg14 + avg28) / 7

    @staticmethod
    def _compute_parabolic_sar(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
        """Simplified Parabolic SAR."""
        # Simplified implementation; ta-lib is more accurate in production
        sar = close.copy()
        af = 0.02
        max_af = 0.2
        is_up = True

        for i in range(1, len(sar)):
            if is_up:
                sar.iloc[i] = sar.iloc[i - 1] + af * (high.iloc[i - 1] - sar.iloc[i - 1])
                if low.iloc[i] < sar.iloc[i]:
                    is_up = False
                    sar.iloc[i] = high.iloc[i - 1]
                    af = 0.02
            else:
                sar.iloc[i] = sar.iloc[i - 1] + af * (low.iloc[i - 1] - sar.iloc[i - 1])
                if high.iloc[i] > sar.iloc[i]:
                    is_up = True
                    sar.iloc[i] = low.iloc[i - 1]
                    af = 0.02
            af = min(af + 0.02, max_af) if is_up else max(af - 0.02, 0.02)

        return sar


# Global singleton
data_pipeline = DataPipeline()
