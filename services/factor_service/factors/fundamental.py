"""services/factor_service/factors/fundamental.py – Fundamental factors (30 factors).

Value, quality, growth, and financial health factors.
Most require quarterly financial data merged into the price DataFrame.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from services.factor_service.engine.factor_base import FactorBase


# ── Value Factors ────────────────────────────────────────────
class PERatio(FactorBase):
    factor_id = "F100"
    name = "pe_ratio"
    category = "fundamental"
    subcategory = "value"
    description = "Price-to-Earnings ratio (trailing 12m)"
    lookback_default = 252
    frequency = "monthly"
    direction = -1

    def compute(self, df: pd.DataFrame) -> pd.Series:
        if "eps" in df.columns:
            return df["close"] / df["eps"].clip(lower=1e-8)
        if "pe_ratio" in df.columns:
            return df["pe_ratio"]
        return pd.Series(np.nan, index=df.index)


class PBRatio(FactorBase):
    factor_id = "F101"
    name = "pb_ratio"
    category = "fundamental"
    subcategory = "value"
    description = "Price-to-Book ratio"
    lookback_default = 252
    frequency = "monthly"
    direction = -1

    def compute(self, df: pd.DataFrame) -> pd.Series:
        if "book_value_per_share" in df.columns:
            return df["close"] / df["book_value_per_share"].clip(lower=1e-8)
        if "pb_ratio" in df.columns:
            return df["pb_ratio"]
        return pd.Series(np.nan, index=df.index)


class PSRatio(FactorBase):
    factor_id = "F102"
    name = "ps_ratio"
    category = "fundamental"
    subcategory = "value"
    description = "Price-to-Sales ratio"
    lookback_default = 252
    frequency = "monthly"
    direction = -1

    def compute(self, df: pd.DataFrame) -> pd.Series:
        if "revenue_per_share" in df.columns:
            return df["close"] / df["revenue_per_share"].clip(lower=1e-8)
        if "ps_ratio" in df.columns:
            return df["ps_ratio"]
        return pd.Series(np.nan, index=df.index)


class FCFYield(FactorBase):
    factor_id = "F104"
    name = "fcf_yield"
    category = "fundamental"
    subcategory = "value"
    description = "Free Cash Flow / Market Cap"
    lookback_default = 252
    frequency = "monthly"
    direction = 1

    def compute(self, df: pd.DataFrame) -> pd.Series:
        if "fcf_per_share" in df.columns:
            return df["fcf_per_share"] / df["close"].clip(lower=1e-8)
        if "fcf_yield" in df.columns:
            return df["fcf_yield"]
        return pd.Series(np.nan, index=df.index)


class EarningsYield(FactorBase):
    factor_id = "F105"
    name = "earnings_yield"
    category = "fundamental"
    subcategory = "value"
    description = "E/P ratio (1/PE)"
    lookback_default = 252
    frequency = "monthly"
    direction = 1

    def compute(self, df: pd.DataFrame) -> pd.Series:
        if "eps" in df.columns:
            return df["eps"] / df["close"].clip(lower=1e-8)
        if "pe_ratio" in df.columns:
            return 1.0 / df["pe_ratio"].clip(lower=1e-8)
        return pd.Series(np.nan, index=df.index)


class DividendYield(FactorBase):
    factor_id = "F106"
    name = "dividend_yield"
    category = "fundamental"
    subcategory = "value"
    description = "Trailing 12-month dividend yield"
    lookback_default = 252
    frequency = "monthly"
    direction = 1

    def compute(self, df: pd.DataFrame) -> pd.Series:
        if "dividend_per_share" in df.columns:
            return df["dividend_per_share"].rolling(252).sum() / df["close"]
        if "dividend_yield" in df.columns:
            return df["dividend_yield"]
        return pd.Series(np.nan, index=df.index)


# ── Quality / Profitability ──────────────────────────────────
class ROE(FactorBase):
    factor_id = "F108"
    name = "roe"
    category = "fundamental"
    subcategory = "quality"
    description = "Return on Equity (trailing 12m)"
    lookback_default = 252
    frequency = "monthly"
    direction = 1

    def compute(self, df: pd.DataFrame) -> pd.Series:
        if "roe" in df.columns:
            return df["roe"]
        if "net_income" in df.columns and "equity" in df.columns:
            return df["net_income"].rolling(4).sum() / df["equity"].clip(lower=1e-8)
        return pd.Series(np.nan, index=df.index)


class ROA(FactorBase):
    factor_id = "F109"
    name = "roa"
    category = "fundamental"
    subcategory = "quality"
    description = "Return on Assets (trailing 12m)"
    lookback_default = 252
    frequency = "monthly"
    direction = 1

    def compute(self, df: pd.DataFrame) -> pd.Series:
        if "roa" in df.columns:
            return df["roa"]
        if "net_income" in df.columns and "total_assets" in df.columns:
            return df["net_income"].rolling(4).sum() / df["total_assets"].clip(lower=1e-8)
        return pd.Series(np.nan, index=df.index)


class ROIC(FactorBase):
    factor_id = "F110"
    name = "roic"
    category = "fundamental"
    subcategory = "quality"
    description = "Return on Invested Capital"
    lookback_default = 252
    frequency = "monthly"
    direction = 1

    def compute(self, df: pd.DataFrame) -> pd.Series:
        if "roic" in df.columns:
            return df["roic"]
        if "ebit" in df.columns and "invested_capital" in df.columns:
            tax_rate = 0.21
            nopat = df["ebit"] * (1 - tax_rate)
            return nopat.rolling(4).sum() / df["invested_capital"].clip(lower=1e-8)
        return pd.Series(np.nan, index=df.index)


class GrossMargin(FactorBase):
    factor_id = "F111"
    name = "gross_margin"
    category = "fundamental"
    subcategory = "quality"
    description = "Gross profit margin"
    lookback_default = 252
    frequency = "quarterly"
    direction = 1

    def compute(self, df: pd.DataFrame) -> pd.Series:
        if "gross_margin" in df.columns:
            return df["gross_margin"]
        if "gross_profit" in df.columns and "revenue" in df.columns:
            return df["gross_profit"] / df["revenue"].clip(lower=1e-8)
        return pd.Series(np.nan, index=df.index)


class OperatingMargin(FactorBase):
    factor_id = "F113"
    name = "operating_margin"
    category = "fundamental"
    subcategory = "quality"
    description = "Operating income margin"
    lookback_default = 252
    frequency = "quarterly"
    direction = 1

    def compute(self, df: pd.DataFrame) -> pd.Series:
        if "operating_margin" in df.columns:
            return df["operating_margin"]
        if "operating_income" in df.columns and "revenue" in df.columns:
            return df["operating_income"] / df["revenue"].clip(lower=1e-8)
        return pd.Series(np.nan, index=df.index)


class NetMargin(FactorBase):
    factor_id = "F114"
    name = "net_margin"
    category = "fundamental"
    subcategory = "quality"
    description = "Net profit margin"
    lookback_default = 252
    frequency = "quarterly"
    direction = 1

    def compute(self, df: pd.DataFrame) -> pd.Series:
        if "net_margin" in df.columns:
            return df["net_margin"]
        if "net_income" in df.columns and "revenue" in df.columns:
            return df["net_income"] / df["revenue"].clip(lower=1e-8)
        return pd.Series(np.nan, index=df.index)


class AssetTurnover(FactorBase):
    factor_id = "F115"
    name = "asset_turnover"
    category = "fundamental"
    subcategory = "quality"
    description = "Revenue / Total Assets"
    lookback_default = 252
    frequency = "quarterly"
    direction = 1

    def compute(self, df: pd.DataFrame) -> pd.Series:
        if "asset_turnover" in df.columns:
            return df["asset_turnover"]
        if "revenue" in df.columns and "total_assets" in df.columns:
            return df["revenue"] / df["total_assets"].clip(lower=1e-8)
        return pd.Series(np.nan, index=df.index)


# ── Growth Factors ───────────────────────────────────────────
class RevenueGrowthYoY(FactorBase):
    factor_id = "F117"
    name = "revenue_growth_yoy"
    category = "fundamental"
    subcategory = "growth"
    description = "YoY revenue growth rate"
    lookback_default = 252
    frequency = "quarterly"
    direction = 1

    def compute(self, df: pd.DataFrame) -> pd.Series:
        if "revenue" in df.columns:
            return df["revenue"].pct_change(periods=4)
        if "revenue_growth" in df.columns:
            return df["revenue_growth"]
        return pd.Series(np.nan, index=df.index)


class EarningsGrowthYoY(FactorBase):
    factor_id = "F118"
    name = "earnings_growth_yoy"
    category = "fundamental"
    subcategory = "growth"
    description = "YoY EPS growth rate"
    lookback_default = 252
    frequency = "quarterly"
    direction = 1

    def compute(self, df: pd.DataFrame) -> pd.Series:
        if "eps" in df.columns:
            return df["eps"].pct_change(periods=4)
        if "earnings_growth" in df.columns:
            return df["earnings_growth"]
        return pd.Series(np.nan, index=df.index)


class EarningsSurprise(FactorBase):
    factor_id = "F120"
    name = "earnings_surprise"
    category = "fundamental"
    subcategory = "growth"
    description = "Latest earnings surprise vs consensus"
    lookback_default = 90
    frequency = "quarterly"
    direction = 1

    def compute(self, df: pd.DataFrame) -> pd.Series:
        if "eps_actual" in df.columns and "eps_estimate" in df.columns:
            return (df["eps_actual"] - df["eps_estimate"]) / df["eps_estimate"].abs().clip(lower=1e-8)
        if "earnings_surprise" in df.columns:
            return df["earnings_surprise"]
        return pd.Series(np.nan, index=df.index)


# ── Financial Health ─────────────────────────────────────────
class DebtToEquity(FactorBase):
    factor_id = "F123"
    name = "debt_to_equity"
    category = "fundamental"
    subcategory = "health"
    description = "Total Debt / Total Equity"
    lookback_default = 252
    frequency = "quarterly"
    direction = -1

    def compute(self, df: pd.DataFrame) -> pd.Series:
        if "debt_to_equity" in df.columns:
            return df["debt_to_equity"]
        if "total_debt" in df.columns and "total_equity" in df.columns:
            return df["total_debt"] / df["total_equity"].clip(lower=1e-8)
        return pd.Series(np.nan, index=df.index)


class CurrentRatio(FactorBase):
    factor_id = "F124"
    name = "current_ratio"
    category = "fundamental"
    subcategory = "health"
    description = "Current Assets / Current Liabilities"
    lookback_default = 252
    frequency = "quarterly"
    direction = 1

    def compute(self, df: pd.DataFrame) -> pd.Series:
        if "current_ratio" in df.columns:
            return df["current_ratio"]
        if "current_assets" in df.columns and "current_liabilities" in df.columns:
            return df["current_assets"] / df["current_liabilities"].clip(lower=1e-8)
        return pd.Series(np.nan, index=df.index)


class InterestCoverage(FactorBase):
    factor_id = "F125"
    name = "interest_coverage"
    category = "fundamental"
    subcategory = "health"
    description = "EBIT / Interest Expense"
    lookback_default = 252
    frequency = "quarterly"
    direction = 1

    def compute(self, df: pd.DataFrame) -> pd.Series:
        if "interest_coverage" in df.columns:
            return df["interest_coverage"]
        if "ebit" in df.columns and "interest_expense" in df.columns:
            return df["ebit"] / df["interest_expense"].abs().clip(lower=1e-8) * (-1)
        return pd.Series(np.nan, index=df.index)


class AltmanZScore(FactorBase):
    factor_id = "F126"
    name = "altman_z"
    category = "fundamental"
    subcategory = "health"
    description = "Altman Z-score"
    lookback_default = 252
    frequency = "quarterly"
    direction = 1

    def compute(self, df: pd.DataFrame) -> pd.Series:
        if "altman_z" in df.columns:
            return df["altman_z"]
        # Approximate with available data
        result = pd.Series(0.0, index=df.index)
        if "working_capital" in df.columns and "total_assets" in df.columns:
            result += 1.2 * (df["working_capital"] / df["total_assets"].clip(lower=1e-8))
        if "retained_earnings" in df.columns and "total_assets" in df.columns:
            result += 1.4 * (df["retained_earnings"] / df["total_assets"].clip(lower=1e-8))
        if "ebit" in df.columns and "total_assets" in df.columns:
            result += 3.3 * (df["ebit"] / df["total_assets"].clip(lower=1e-8))
        if "market_cap" in df.columns and "total_liabilities" in df.columns:
            result += 0.6 * (df["market_cap"] / df["total_liabilities"].clip(lower=1e-8))
        if "revenue" in df.columns and "total_assets" in df.columns:
            result += 1.0 * (df["revenue"] / df["total_assets"].clip(lower=1e-8))
        return result


# ── Aggregate list ───────────────────────────────────────────
FUNDAMENTAL_FACTORS: list[FactorBase] = [
    PERatio(), PBRatio(), PSRatio(), FCFYield(), EarningsYield(), DividendYield(),
    ROE(), ROA(), ROIC(),
    GrossMargin(), OperatingMargin(), NetMargin(), AssetTurnover(),
    RevenueGrowthYoY(), EarningsGrowthYoY(), EarningsSurprise(),
    DebtToEquity(), CurrentRatio(), InterestCoverage(), AltmanZScore(),
]
