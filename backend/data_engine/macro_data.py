"""
宏观市场数据引擎 — 拓展多维度特征

数据维度:
- VIX 恐慌指数 (^VIX)
- 板块 ETF 资金流向 (SPY/QQQ/IWM/DIA/XLF/XLE/XLK/XLV/XLI/XLY)
- 美元指数 (DX-Y.NYB)
- 美债收益率 (^TNX)

用途:
- 作为大盘环境特征输入到模型
- 识别风险偏好/避险模式
- 板块轮动信号
"""
import time
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
from pathlib import Path
from datetime import datetime, timedelta
from loguru import logger


# 宏观数据标的
MACRO_SYMBOLS = {
    "vix": "^VIX",           # CBOE 波动率指数
    "spy": "SPY",             # S&P 500 ETF
    "qqq": "QQQ",             # Nasdaq 100 ETF
    "iwm": "IWM",             # Russell 2000 ETF
    "dia": "DIA",             # Dow Jones ETF
    "tlt": "TLT",             # 20+年美债 ETF (利率代理)
    "gld": "GLD",             # 黄金 ETF (避险代理)
    "uso": "USO",             # 原油 ETF
    "xlv": "XLV",             # 医疗板块
    "xlf": "XLF",             # 金融板块
    "xlk": "XLK",             # 科技板块
    "xle": "XLE",             # 能源板块
    "xli": "XLI",             # 工业板块
    "xly": "XLY",             # 可选消费板块
}

# 板块 ETF 对照（用于生成板块特征）
SECTOR_ETFS = {
    "Tech": "XLK",
    "Finance": "XLF",
    "Healthcare": "XLV",
    "Energy": "XLE",
    "Industrial": "XLI",
    "Consumer": "XLY",
}


class MacroDataEngine:
    """宏观市场数据引擎"""

    def __init__(self, use_cache: bool = True, cache_ttl: int = 3600):
        self.use_cache = use_cache
        self.cache_ttl = cache_ttl
        self._cache: Dict[str, Tuple[float, pd.DataFrame]] = {}  # {symbol: (timestamp, df)}
        self._sector_flows: Dict[str, Dict] = {}

    def fetch_macro_data(self, period: str = "3mo") -> pd.DataFrame:
        """
        获取宏观市场数据，合并为统一 DataFrame。

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
                logger.debug(f"宏观数据 {name} ({symbol}) 获取失败: {e}")

        if not df_list:
            logger.warning("⚠️ 所有宏观数据获取失败")
            return pd.DataFrame()

        # 合并所有宏观数据
        macro_df = pd.concat(df_list, axis=1, join="outer")
        macro_df = macro_df.ffill().dropna(how="all")

        if failed:
            logger.debug(f"部分宏观数据不可用: {failed}")

        return macro_df

    def _fetch_single(self, symbol: str, period: str) -> Optional[pd.DataFrame]:
        """获取单个标的的历史数据"""
        cache_key = f"{symbol}_{period}"

        # 缓存检查
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
        从宏观数据计算特征向量。

        Returns:
            {
                "vix_level": float,        # VIX 当前水平
                "vix_change_5d": float,    # VIX 5日变化
                "market_regime": str,      # 市场状态: risk_on/risk_off/normal
                "sector_momentum": dict,   # 各板块动量
                "sector_rotation": str,    # 板块轮动方向
                "rates_trend": float,      # 利率趋势
                "gold_signal": str,        # 避险信号
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
            # VIX 特征
            if "vix" in macro_df.columns:
                vix_series = macro_df["vix"].dropna()
                if len(vix_series) >= 5:
                    features["vix_level"] = float(vix_series.iloc[-1])
                    features["vix_change_5d"] = float(
                        (vix_series.iloc[-1] - vix_series.iloc[-5]) / (vix_series.iloc[-5] + 1e-8)
                    )

                    # 市场状态判断
                    vix = features["vix_level"]
                    if vix > 30:
                        features["market_regime"] = "risk_off"
                    elif vix < 15:
                        features["market_regime"] = "risk_on"
                    else:
                        features["market_regime"] = "normal"

            # 利率趋势（TLT 价格与利率反向）
            if "tlt" in macro_df.columns:
                tlt = macro_df["tlt"].dropna()
                if len(tlt) >= 20:
                    features["rates_trend"] = float(
                        (tlt.iloc[-1] - tlt.iloc[-20]) / (tlt.iloc[-20] + 1e-8)
                    )

            # 黄金避险信号
            if "gld" in macro_df.columns:
                gld = macro_df["gld"].dropna()
                if len(gld) >= 5:
                    gld_return = float((gld.iloc[-1] - gld.iloc[-5]) / (gld.iloc[-5] + 1e-8))
                    if gld_return > 0.03 and features["market_regime"] == "risk_off":
                        features["gold_signal"] = "避险情绪升温"
                    elif gld_return < -0.02:
                        features["gold_signal"] = "风险偏好回升"
                    else:
                        features["gold_signal"] = "neutral"

            # 板块动量计算
            sector_momentum = {}
            for sector_name, etf_symbol in SECTOR_ETFS.items():
                col = etf_symbol.lower()
                if col in macro_df.columns:
                    series = macro_df[col].dropna()
                    if len(series) >= 20:
                        momentum = (series.iloc[-1] - series.iloc[-20]) / (series.iloc[-20] + 1e-8)
                        sector_momentum[sector_name] = float(momentum)

            features["sector_momentum"] = sector_momentum

            # 板块轮动判断
            if sector_momentum:
                top_sector = max(sector_momentum, key=sector_momentum.get)
                bottom_sector = min(sector_momentum, key=sector_momentum.get)
                spread = sector_momentum[top_sector] - sector_momentum[bottom_sector]

                if spread > 0.05:
                    features["sector_rotation"] = f"资金流入 {top_sector}，流出 {bottom_sector}"
                else:
                    features["sector_rotation"] = "板块分化不明显"

            # 大盘基准收益率
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
            logger.warning(f"宏观特征计算异常: {e}")

        return features

    def get_sector_allocation_hint(self, macro_features: Dict) -> Dict[str, float]:
        """
        基于宏观特征给出板块配置建议。
        风险偏好高 → 超配科技、可选消费
        风险规避 → 超配医疗、公用事业
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

        # 动量加成
        for sector, momentum in sector_momentum.items():
            if sector in base_allocation:
                base_allocation[sector] += max(0, momentum * 0.5)

        # 归一化
        total = sum(base_allocation.values())
        if total > 0:
            for k in base_allocation:
                base_allocation[k] /= total

        return base_allocation

    def get_market_regime_signal(self, macro_features: Dict) -> Dict:
        """
        生成市场状态交易信号。
        用于调整系统整体的风险敞口。
        """
        regime = macro_features.get("market_regime", "normal")
        vix = macro_features.get("vix_level", 15.0)
        rates_trend = macro_features.get("rates_trend", 0.0)

        if regime == "risk_off":
            risk_multiplier = 0.5
            signal = "持有现金避险"
        elif regime == "risk_on":
            risk_multiplier = 1.2
            signal = "积极配置"
        else:
            risk_multiplier = 1.0
            signal = "正常交易"

        # 利率影响：利率升 → 成长股承压
        if rates_trend < -0.05:  # TLT跌 = 利率升
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


# 全局单例
macro_engine = MacroDataEngine()
