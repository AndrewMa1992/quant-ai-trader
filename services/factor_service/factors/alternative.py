"""services/factor_service/factors/alternative.py – Alternative factors (20 factors).

Sentiment, macro, ESG, supply chain, and alternative data factors.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from services.factor_service.engine.factor_base import FactorBase


# ── Sentiment Factors ────────────────────────────────────────
class ShortInterestRatio(FactorBase):
    factor_id = "F200"
    name = "short_interest_ratio"
    category = "alternative"
    subcategory = "sentiment"
    description = "Days to cover (short interest / avg volume)"
    lookback_default = 21
    frequency = "biweekly"
    direction = 1

    def compute(self, df: pd.DataFrame) -> pd.Series:
        if "short_interest" in df.columns:
            avg_vol = df["volume"].rolling(21).mean()
            return df["short_interest"] / avg_vol.clip(lower=1e-8)
        return pd.Series(np.nan, index=df.index)


class PutCallRatio(FactorBase):
    factor_id = "F201"
    name = "put_call_ratio"
    category = "alternative"
    subcategory = "sentiment"
    description = "Equity put/call volume ratio (z-score)"
    lookback_default = 21
    neutralizable = False
    direction = -1

    def compute(self, df: pd.DataFrame) -> pd.Series:
        if "put_call_ratio" in df.columns:
            pcr = df["put_call_ratio"]
            mean = pcr.rolling(63).mean()
            std = pcr.rolling(63).std().clip(lower=1e-8)
            return (pcr - mean) / std
        return pd.Series(np.nan, index=df.index)


class NewsSentiment(FactorBase):
    factor_id = "F202"
    name = "news_sentiment"
    category = "alternative"
    subcategory = "sentiment"
    description = "NLP news sentiment score"
    lookback_default = 5
    frequency = "daily"
    direction = 1

    def compute(self, df: pd.DataFrame) -> pd.Series:
        if "news_sentiment" in df.columns:
            return df["news_sentiment"].rolling(5).mean()
        return pd.Series(np.nan, index=df.index)


class AnalystRecommendation(FactorBase):
    factor_id = "F204"
    name = "analyst_recommendation"
    category = "alternative"
    subcategory = "sentiment"
    description = "Consensus analyst rating (1=Strong Buy, 5=Strong Sell)"
    lookback_default = 90
    frequency = "monthly"
    direction = -1

    def compute(self, df: pd.DataFrame) -> pd.Series:
        if "analyst_rating" in df.columns:
            return df["analyst_rating"]
        if "recommendation_mean" in df.columns:
            return df["recommendation_mean"]
        return pd.Series(np.nan, index=df.index)


class InsiderTrading(FactorBase):
    factor_id = "F205"
    name = "insider_trading"
    category = "alternative"
    subcategory = "sentiment"
    description = "Net insider buy/sell ratio (3m)"
    lookback_default = 63
    frequency = "monthly"
    direction = 1

    def compute(self, df: pd.DataFrame) -> pd.Series:
        if "insider_buy_volume" in df.columns and "insider_sell_volume" in df.columns:
            net = df["insider_buy_volume"] - df["insider_sell_volume"]
            total = df["insider_buy_volume"] + df["insider_sell_volume"]
            return net / total.clip(lower=1e-8)
        return pd.Series(np.nan, index=df.index)


# ── Macro / Cross-Asset Factors ──────────────────────────────
class BetaToVIX(FactorBase):
    factor_id = "F207"
    name = "beta_to_vix"
    category = "alternative"
    subcategory = "macro"
    description = "Sensitivity to VIX changes (63d)"
    lookback_default = 63
    neutralizable = False
    direction = -1

    def compute(self, df: pd.DataFrame) -> pd.Series:
        if "vix" in df.columns:
            col = "adj_close" if "adj_close" in df.columns else "close"
            stock_ret = df[col].pct_change()
            vix_ret = df["vix"].pct_change()

            cov = stock_ret.rolling(63).cov(vix_ret)
            var = vix_ret.rolling(63).var().clip(lower=1e-8)
            return cov / var
        return pd.Series(np.nan, index=df.index)


class USDSensitivity(FactorBase):
    factor_id = "F208"
    name = "usd_sensitivity"
    category = "alternative"
    subcategory = "macro"
    description = "Sensitivity to DXY index (63d)"
    lookback_default = 63
    neutralizable = False
    direction = 0

    def compute(self, df: pd.DataFrame) -> pd.Series:
        if "dxy" in df.columns:
            col = "adj_close" if "adj_close" in df.columns else "close"
            stock_ret = df[col].pct_change()
            dxy_ret = df["dxy"].pct_change()

            cov = stock_ret.rolling(63).cov(dxy_ret)
            var = dxy_ret.rolling(63).var().clip(lower=1e-8)
            return cov / var
        return pd.Series(np.nan, index=df.index)


class RateSensitivity(FactorBase):
    factor_id = "F210"
    name = "rate_sensitivity"
    category = "alternative"
    subcategory = "macro"
    description = "Sensitivity to 10Y Treasury yield changes"
    lookback_default = 63
    neutralizable = False
    direction = 0

    def compute(self, df: pd.DataFrame) -> pd.Series:
        if "treasury_10y" in df.columns:
            col = "adj_close" if "adj_close" in df.columns else "close"
            stock_ret = df[col].pct_change()
            rate_chg = df["treasury_10y"].diff()

            cov = stock_ret.rolling(63).cov(rate_chg)
            var = rate_chg.rolling(63).var().clip(lower=1e-8)
            return cov / var
        return pd.Series(np.nan, index=df.index)


# ── ESG Factors ──────────────────────────────────────────────
class ESGScore(FactorBase):
    factor_id = "F212"
    name = "esg_score"
    category = "alternative"
    subcategory = "esg"
    description = "Aggregate ESG score"
    lookback_default = 252
    frequency = "annually"
    direction = 1

    def compute(self, df: pd.DataFrame) -> pd.Series:
        if "esg_score" in df.columns:
            return df["esg_score"]
        return pd.Series(np.nan, index=df.index)


class CarbonIntensity(FactorBase):
    factor_id = "F213"
    name = "carbon_intensity"
    category = "alternative"
    subcategory = "esg"
    description = "Scope 1+2 emissions / Revenue"
    lookback_default = 252
    frequency = "annually"
    direction = -1

    def compute(self, df: pd.DataFrame) -> pd.Series:
        if "carbon_intensity" in df.columns:
            return df["carbon_intensity"]
        if "emissions" in df.columns and "revenue" in df.columns:
            return df["emissions"] / df["revenue"].clip(lower=1e-8)
        return pd.Series(np.nan, index=df.index)


# ── Supply Chain / Alt Data ──────────────────────────────────
class AppDownloads(FactorBase):
    factor_id = "F218"
    name = "app_downloads"
    category = "alternative"
    subcategory = "alt_data"
    description = "Mobile app download growth rate"
    lookback_default = 21
    frequency = "weekly"
    direction = 1

    def compute(self, df: pd.DataFrame) -> pd.Series:
        if "app_downloads" in df.columns:
            return df["app_downloads"].pct_change(periods=21)
        return pd.Series(np.nan, index=df.index)


class WebsiteTraffic(FactorBase):
    factor_id = "F219"
    name = "website_traffic"
    category = "alternative"
    subcategory = "alt_data"
    description = "Web traffic growth (SimilarWeb)"
    lookback_default = 21
    frequency = "weekly"
    direction = 1

    def compute(self, df: pd.DataFrame) -> pd.Series:
        if "website_traffic" in df.columns:
            return df["website_traffic"].pct_change(periods=21)
        return pd.Series(np.nan, index=df.index)


# ── Aggregate list ───────────────────────────────────────────
ALTERNATIVE_FACTORS: list[FactorBase] = [
    ShortInterestRatio(), PutCallRatio(), NewsSentiment(),
    AnalystRecommendation(), InsiderTrading(),
    BetaToVIX(), USDSensitivity(), RateSensitivity(),
    ESGScore(), CarbonIntensity(),
    AppDownloads(), WebsiteTraffic(),
]
