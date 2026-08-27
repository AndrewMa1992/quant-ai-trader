"""
Macro market-data engine — multi-dimensional features.

Data dimensions:
- VIX fear index (^VIX)
- Sector ETF flows (SPY/QQQ/IWM/DIA/XLF/XLE/XLK/XLV/XLI/XLY)
- US Dollar Index (DX-Y.NYB)
- US Treasury yield (^TNX)

Uses:
- Broad-market regime features for models
- Risk-on / risk-off detection
- Sector-rotation signals
"""
import time
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
from pathlib import Path
from datetime import datetime, timedelta
from loguru import logger


# Macro data symbols
MACRO_SYMBOLS = {
    "vix": "^VIX",           # CBOE Volatility Index
    "spy": "SPY",             # S&P 500 ETF
    "qqq": "QQQ",             # Nasdaq 100 ETF
    "iwm": "IWM",             # Russell 2000 ETF
    "dia": "DIA",             # Dow Jones ETF
    "tlt": "TLT",             # 20+ year Treasury ETF (rates proxy)
    "gld": "GLD",             # Gold ETF (safe-haven proxy)
    "uso": "USO",             # Crude oil ETF
    "xlv": "XLV",             # Healthcare sector
    "xlf": "XLF",             # Financials sector
    "xlk": "XLK",             # Technology sector
    "xle": "XLE",             # Energy sector
    "xli": "XLI",             # Industrials sector
    "xly": "XLY",             # Consumer discretionary sector
}

# Sector ETF map (used to build sector features)
SECTOR_ETFS = {
    "Tech": "XLK",
    "Finance": "XLF",
    "Healthcare": "XLV",
    "Energy": "XLE",
    "Industrial": "XLI",
    "Consumer": "XLY",
}


class MacroDataEngine:
    """Macro market-data engine."""

    def __init__(self, use_cache: bool = True, cache_ttl: int = 3600):
        self.use_cache = use_cache
        self.cache_ttl = cache_ttl
        self._cache: Dict[str, Tuple[float, pd.DataFrame]] = {}  # {symbol: (timestamp, df)}
        self._sector_flows: Dict[str, Dict] = {}

    def fetch_macro_data(self, period: str = "3mo") -> pd.DataFrame:
        """
        Fetch macro market data and merge into a single DataFrame.

        Returns:
            DataFrame with columns: vix, spy_return, qqq_return, sector_spread, ...
        """
        df_list = []
        failed = []

        for name, symbol in MACRO_SYMBOLS.items():
            try:
                df = self._fetch_single(symbol, period)
                if df is not None and not df.empty:
                    df = df[["close"]].rename(columns={"close": name})
                    df_list.append(df)
                else:
                    failed.append(name)
            except Exception as e:
                failed.append(name)
                logger.debug(f"Macro data {name} ({symbol}) fetch failed: {e}")

        if not df_list:
            logger.warning("⚠️ All macro data fetches failed")
            return pd.DataFrame()

        # Merge all macro series
        macro_df = pd.concat(df_list, axis=1, join="outer")
        macro_df = macro_df.ffill().dropna(how="all")

        if failed:
            logger.debug(f"Some macro series unavailable: {failed}")

        return macro_df

    def _fetch_single(self, symbol: str, period: str) -> Optional[pd.DataFrame]:
        """Fetch historical data for a single symbol."""
        cache_key = f"{symbol}_{period}"

        # Cache check
        if self.use_cache and cache_key in self._cache:
            ts, df = self._cache[cache_key]
            if time.time() - ts < self.cache_ttl:
                return df.copy()

        try:
            import yfinance as yf
            ticker = yf.Ticker(symbol)
            df = ticker.history(period=period)
            if df is not None and not df.empty:
                df.index = pd.to_datetime(df.index).tz_localize(None)
                self._cache[cache_key] = (time.time(), df.copy())
                return df
        except Exception:
            pass

        return None

    def compute_macro_features(self, macro_df: pd.DataFrame) -> Dict[str, np.ndarray]:
        """
        Compute feature vectors from macro data.

        Returns:
            {
                "vix_level": float,        # current VIX level
                "vix_change_5d": float,    # 5-day VIX change
                "market_regime": str,      # market regime: risk_on/risk_off/normal
                "sector_momentum": dict,   # sector momentum
                "sector_rotation": str,    # sector-rotation direction
                "rates_trend": float,      # rates trend
                "gold_signal": str,        # safe-haven signal
            }
        """
        features = {
            "vix_level": 15.0,
            "vix_change_5d": 0.0,
            "market_regime": "normal",
            "sector_momentum": {},
            "sector_rotation": "neutral",
            "rates_trend": 0.0,
            "gold_signal": "neutral",
        }

        if macro_df.empty:
            return features

        try:
            # VIX features
            if "vix" in macro_df.columns:
                vix_series = macro_df["vix"].dropna()
                if len(vix_series) >= 5:
                    features["vix_level"] = float(vix_series.iloc[-1])
                    features["vix_change_5d"] = float(
                        (vix_series.iloc[-1] - vix_series.iloc[-5]) / (vix_series.iloc[-5] + 1e-8)
                    )

                    # Market-regime classification
                    vix = features["vix_level"]
                    if vix > 30:
                        features["market_regime"] = "risk_off"
                    elif vix < 15:
                        features["market_regime"] = "risk_on"
                    else:
                        features["market_regime"] = "normal"

            # Rates trend (TLT price moves inversely to yields)
            if "tlt" in macro_df.columns:
                tlt = macro_df["tlt"].dropna()
                if len(tlt) >= 20:
                    features["rates_trend"] = float(
                        (tlt.iloc[-1] - tlt.iloc[-20]) / (tlt.iloc[-20] + 1e-8)
                    )

            # Gold safe-haven signal
            if "gld" in macro_df.columns:
                gld = macro_df["gld"].dropna()
                if len(gld) >= 5:
                    gld_return = float((gld.iloc[-1] - gld.iloc[-5]) / (gld.iloc[-5] + 1e-8))
                    if gld_return > 0.03 and features["market_regime"] == "risk_off":
                        features["gold_signal"] = "safe_haven_demand_rising"
                    elif gld_return < -0.02:
                        features["gold_signal"] = "risk_appetite_returning"
                    else:
                        features["gold_signal"] = "neutral"

            # Sector momentum
            sector_momentum = {}
            for sector_name, etf_symbol in SECTOR_ETFS.items():
                col = etf_symbol.lower()
                if col in macro_df.columns:
                    series = macro_df[col].dropna()
                    if len(series) >= 20:
                        momentum = (series.iloc[-1] - series.iloc[-20]) / (series.iloc[-20] + 1e-8)
                        sector_momentum[sector_name] = float(momentum)

            features["sector_momentum"] = sector_momentum

            # Sector rotation
            if sector_momentum:
                top_sector = max(sector_momentum, key=sector_momentum.get)
                bottom_sector = min(sector_momentum, key=sector_momentum.get)
                spread = sector_momentum[top_sector] - sector_momentum[bottom_sector]

                if spread > 0.05:
                    features["sector_rotation"] = f"inflows to {top_sector}, outflows from {bottom_sector}"
                else:
                    features["sector_rotation"] = "limited sector divergence"

            # Benchmark returns
            for bench in ["spy", "qqq", "iwm"]:
                if bench in macro_df.columns:
                    series = macro_df[bench].dropna()
                    if len(series) >= 5:
                        features[f"{bench}_return_5d"] = float(
                            (series.iloc[-1] - series.iloc[-5]) / (series.iloc[-5] + 1e-8)
                        )
                    if len(series) >= 20:
                        features[f"{bench}_return_20d"] = float(
                            (series.iloc[-1] - series.iloc[-20]) / (series.iloc[-20] + 1e-8)
                        )

        except Exception as e:
            logger.warning(f"Macro feature computation failed: {e}")

        return features

    def get_sector_allocation_hint(self, macro_features: Dict) -> Dict[str, float]:
        """
        Suggest sector weights from macro features.
        Risk-on → overweight tech and consumer discretionary
        Risk-off → overweight healthcare and utilities
        """
        regime = macro_features.get("market_regime", "normal")
        sector_momentum = macro_features.get("sector_momentum", {})

        base_allocation = {
            "Tech": 0.20, "Finance": 0.15, "Healthcare": 0.15,
            "Consumer": 0.15, "Industrial": 0.15, "Energy": 0.10,
            "Other": 0.10,
        }

        if regime == "risk_on":
            base_allocation["Tech"] += 0.10
            base_allocation["Consumer"] += 0.05
            base_allocation["Healthcare"] -= 0.05
            base_allocation["Energy"] -= 0.05
        elif regime == "risk_off":
            base_allocation["Healthcare"] += 0.10
            base_allocation["Consumer"] += 0.05
            base_allocation["Tech"] -= 0.05
            base_allocation["Energy"] -= 0.05
            base_allocation["Finance"] -= 0.05

        # Momentum overlay
        for sector, momentum in sector_momentum.items():
            if sector in base_allocation:
                base_allocation[sector] += max(0, momentum * 0.5)

        # Normalize
        total = sum(base_allocation.values())
        if total > 0:
            for k in base_allocation:
                base_allocation[k] /= total

        return base_allocation

    def get_market_regime_signal(self, macro_features: Dict) -> Dict:
        """
        Produce a market-regime trading signal.
        Used to scale system-wide risk exposure.
        """
        regime = macro_features.get("market_regime", "normal")
        vix = macro_features.get("vix_level", 15.0)
        rates_trend = macro_features.get("rates_trend", 0.0)

        if regime == "risk_off":
            risk_multiplier = 0.5
            signal = "hold_cash_defensive"
        elif regime == "risk_on":
            risk_multiplier = 1.2
            signal = "aggressive_allocation"
        else:
            risk_multiplier = 1.0
            signal = "normal_trading"

        # Rates impact: rising yields pressure growth stocks
        if rates_trend < -0.05:  # TLT down = yields up
            rate_bias = "value_over_growth"
        elif rates_trend > 0.05:
            rate_bias = "growth_over_value"
        else:
            rate_bias = "neutral"

        return {
            "regime": regime,
            "risk_multiplier": risk_multiplier,
            "signal": signal,
            "vix": vix,
            "rate_bias": rate_bias,
        }


# Global singleton
macro_engine = MacroDataEngine()
