"""configs/factor_registry.py – 100+ factor registry for Quant AI Trader v2.

Organized into four categories:
- Technical (50+): momentum, volatility, volume, trend, pattern-based
- Fundamental (30+): value, quality, growth, profitability
- Alternative (20+): sentiment, ESG, supply-chain, macro
- Microstructure (10+): order-book, spread, liquidity, HFT

Each factor entry includes:
- id: unique factor identifier (e.g., 'F001')
- name: human-readable name
- category: FactorCategory enum
- description: brief explanation
- formula_ref: reference formula or paper
- lookback_default: default lookback window in days
- frequency: expected update frequency
- neutralizable: whether to neutralize (sector/market cap)
- direction: expected sign (1 = positive alpha, -1 = negative)
"""

from __future__ import annotations

from enum import Enum
from typing import TypedDict


class FactorCategory(str, Enum):
    """Factor category enumeration."""
    TECHNICAL = "technical"
    FUNDAMENTAL = "fundamental"
    ALTERNATIVE = "alternative"
    MICROSTRUCTURE = "microstructure"


class FactorEntry(TypedDict, total=False):
    """Typed dictionary for a single factor registry entry."""
    id: str
    name: str
    category: str
    subcategory: str
    description: str
    formula_ref: str
    lookback_default: int
    frequency: str
    neutralizable: bool
    direction: int


# ── Technical Factors (50+) ──────────────────────────────────
TECHNICAL_FACTORS: list[FactorEntry] = [
    # Momentum
    {"id": "F001", "name": "ret_1m", "category": "technical", "subcategory": "momentum",
     "description": "1-month trailing return", "formula_ref": "Jegadeesh-Titman 1993",
     "lookback_default": 21, "frequency": "daily", "neutralizable": True, "direction": 1},
    {"id": "F002", "name": "ret_3m", "category": "technical", "subcategory": "momentum",
     "description": "3-month trailing return", "formula_ref": "Jegadeesh-Titman 1993",
     "lookback_default": 63, "frequency": "daily", "neutralizable": True, "direction": 1},
    {"id": "F003", "name": "ret_6m", "category": "technical", "subcategory": "momentum",
     "description": "6-month trailing return (skip 1m)", "formula_ref": "Jegadeesh-Titman 1993",
     "lookback_default": 126, "frequency": "daily", "neutralizable": True, "direction": 1},
    {"id": "F004", "name": "ret_12m_1m", "category": "technical", "subcategory": "momentum",
     "description": "12-month return skipping most recent month", "formula_ref": "Fama-French MOM",
     "lookback_default": 252, "frequency": "daily", "neutralizable": True, "direction": 1},
    {"id": "F005", "name": "alpha_1m", "category": "technical", "subcategory": "momentum",
     "description": "1-month Jensen alpha vs market", "formula_ref": "CAPM alpha",
     "lookback_default": 21, "frequency": "daily", "neutralizable": True, "direction": 1},
    {"id": "F006", "name": "rsi_14", "category": "technical", "subcategory": "momentum",
     "description": "14-day Relative Strength Index", "formula_ref": "Wilder 1978",
     "lookback_default": 14, "frequency": "daily", "neutralizable": False, "direction": -1},
    {"id": "F007", "name": "mom_10_50", "category": "technical", "subcategory": "momentum",
     "description": "Price ratio MA(10)/MA(50) golden cross indicator", "formula_ref": "Moving average crossover",
     "lookback_default": 50, "frequency": "daily", "neutralizable": False, "direction": 1},
    {"id": "F008", "name": "mom_20_200", "category": "technical", "subcategory": "momentum",
     "description": "Price ratio MA(20)/MA(200)", "formula_ref": "Moving avg crossover",
     "lookback_default": 200, "frequency": "daily", "neutralizable": False, "direction": 1},
    {"id": "F009", "name": "stochastic_k", "category": "technical", "subcategory": "momentum",
     "description": "14-day Stochastic %K", "formula_ref": "Lane 1950s",
     "lookback_default": 14, "frequency": "daily", "neutralizable": False, "direction": -1},
    {"id": "F010", "name": "stochastic_d", "category": "technical", "subcategory": "momentum",
     "description": "3-day Stochastic %D (smooth)", "formula_ref": "Lane 1950s",
     "lookback_default": 14, "frequency": "daily", "neutralizable": False, "direction": -1},
    {"id": "F011", "name": "macd", "category": "technical", "subcategory": "momentum",
     "description": "MACD (12-26-9) signal line", "formula_ref": "Appel 1979",
     "lookback_default": 26, "frequency": "daily", "neutralizable": False, "direction": 1},
    {"id": "F012", "name": "macd_histogram", "category": "technical", "subcategory": "momentum",
     "description": "MACD histogram (MACD - signal)", "formula_ref": "Appel 1979",
     "lookback_default": 26, "frequency": "daily", "neutralizable": False, "direction": 1},
    {"id": "F013", "name": "willr", "category": "technical", "subcategory": "momentum",
     "description": "14-day Williams %R", "formula_ref": "Williams 1973",
     "lookback_default": 14, "frequency": "daily", "neutralizable": False, "direction": -1},
    {"id": "F014", "name": "roc_21", "category": "technical", "subcategory": "momentum",
     "description": "21-day Rate of Change", "formula_ref": "ROC indicator",
     "lookback_default": 21, "frequency": "daily", "neutralizable": True, "direction": 1},
    {"id": "F015", "name": "ts_mom_126", "category": "technical", "subcategory": "momentum",
     "description": "Time-series momentum (regression vs time)", "formula_ref": "Moskowitz 2012",
     "lookback_default": 126, "frequency": "daily", "neutralizable": True, "direction": 1},
    {"id": "F016", "name": "residual_mom", "category": "technical", "subcategory": "momentum",
     "description": "Residual momentum (orthogonal to Fama-French)", "formula_ref": "Blitz 2011",
     "lookback_default": 252, "frequency": "daily", "neutralizable": True, "direction": 1},

    # Volatility
    {"id": "F017", "name": "vol_21d", "category": "technical", "subcategory": "volatility",
     "description": "21-day realized volatility (annualized)", "formula_ref": "Standard volatility",
     "lookback_default": 21, "frequency": "daily", "neutralizable": True, "direction": -1},
    {"id": "F018", "name": "vol_63d", "category": "technical", "subcategory": "volatility",
     "description": "63-day realized volatility (annualized)", "formula_ref": "Standard volatility",
     "lookback_default": 63, "frequency": "daily", "neutralizable": True, "direction": -1},
    {"id": "F019", "name": "vol_252d", "category": "technical", "subcategory": "volatility",
     "description": "252-day realized volatility (annualized)", "formula_ref": "Standard volatility",
     "lookback_default": 252, "frequency": "daily", "neutralizable": True, "direction": -1},
    {"id": "F020", "name": "vol_ratio", "category": "technical", "subcategory": "volatility",
     "description": "Short-term / Long-term vol ratio (21d/63d)", "formula_ref": "Volatility regime",
     "lookback_default": 63, "frequency": "daily", "neutralizable": True, "direction": -1},
    {"id": "F021", "name": "beta_63d", "category": "technical", "subcategory": "volatility",
     "description": "63-day market beta", "formula_ref": "CAPM beta",
     "lookback_default": 63, "frequency": "daily", "neutralizable": False, "direction": 0},
    {"id": "F022", "name": "beta_252d", "category": "technical", "subcategory": "volatility",
     "description": "252-day market beta", "formula_ref": "CAPM beta",
     "lookback_default": 252, "frequency": "daily", "neutralizable": False, "direction": 0},
    {"id": "F023", "name": "idiosyncratic_vol", "category": "technical", "subcategory": "volatility",
     "description": "Idiosyncratic volatility (residual from market model)", "formula_ref": "Ang 2006 IVOL",
     "lookback_default": 63, "frequency": "daily", "neutralizable": True, "direction": -1},
    {"id": "F024", "name": "downside_vol", "category": "technical", "subcategory": "volatility",
     "description": "Downside deviation (semi-variance)", "formula_ref": "Sortino ratio component",
     "lookback_default": 63, "frequency": "daily", "neutralizable": True, "direction": -1},
    {"id": "F025", "name": "max_drawdown_63d", "category": "technical", "subcategory": "volatility",
     "description": "63-day maximum drawdown", "formula_ref": "Risk metric",
     "lookback_default": 63, "frequency": "daily", "neutralizable": True, "direction": -1},
    {"id": "F026", "name": "skewness_63d", "category": "technical", "subcategory": "volatility",
     "description": "63-day return skewness", "formula_ref": "Moment-based",
     "lookback_default": 63, "frequency": "daily", "neutralizable": True, "direction": -1},
    {"id": "F027", "name": "kurtosis_63d", "category": "technical", "subcategory": "volatility",
     "description": "63-day return kurtosis", "formula_ref": "Moment-based",
     "lookback_default": 63, "frequency": "daily", "neutralizable": True, "direction": -1},
    {"id": "F028", "name": "parkinson_vol", "category": "technical", "subcategory": "volatility",
     "description": "Parkinson (HL) volatility estimator", "formula_ref": "Parkinson 1980",
     "lookback_default": 21, "frequency": "daily", "neutralizable": True, "direction": -1},
    {"id": "F029", "name": "garman_klass_vol", "category": "technical", "subcategory": "volatility",
     "description": "Garman-Klass (OHLC) volatility estimator", "formula_ref": "Garman-Klass 1980",
     "lookback_default": 21, "frequency": "daily", "neutralizable": True, "direction": -1},

    # Volume / Liquidity
    {"id": "F030", "name": "volume_ratio", "category": "technical", "subcategory": "volume",
     "description": "Volume ratio (avg 5d / avg 21d)", "formula_ref": "Volume breakout",
     "lookback_default": 21, "frequency": "daily", "neutralizable": True, "direction": 1},
    {"id": "F031", "name": "dollar_volume_21d", "category": "technical", "subcategory": "volume",
     "description": "21-day average dollar volume (log)", "formula_ref": "Liquidity proxy",
     "lookback_default": 21, "frequency": "daily", "neutralizable": True, "direction": 0},
    {"id": "F032", "name": "turnover_21d", "category": "technical", "subcategory": "volume",
     "description": "21-day average turnover ratio", "formula_ref": "Datar 1998",
     "lookback_default": 21, "frequency": "daily", "neutralizable": True, "direction": -1},
    {"id": "F033", "name": "vwap_divergence", "category": "technical", "subcategory": "volume",
     "description": "Close/VWAP divergence (21d avg)", "formula_ref": "VWAP strategy",
     "lookback_default": 21, "frequency": "daily", "neutralizable": False, "direction": -1},
    {"id": "F034", "name": "obv_signal", "category": "technical", "subcategory": "volume",
     "description": "On-Balance Volume trend signal", "formula_ref": "Granville 1963",
     "lookback_default": 21, "frequency": "daily", "neutralizable": False, "direction": 1},
    {"id": "F035", "name": "avg_trade_size", "category": "technical", "subcategory": "volume",
     "description": "Average trade size trend", "formula_ref": "Institutional flow proxy",
     "lookback_default": 21, "frequency": "daily", "neutralizable": True, "direction": 1},
    {"id": "F036", "name": "mfi_14", "category": "technical", "subcategory": "volume",
     "description": "14-day Money Flow Index", "formula_ref": "Quong-Avram 1989",
     "lookback_default": 14, "frequency": "daily", "neutralizable": False, "direction": -1},

    # Trend / Moving Average
    {"id": "F037", "name": "sma_50_bias", "category": "technical", "subcategory": "trend",
     "description": "Price distance from 50-day SMA (z-score)", "formula_ref": "Mean reversion",
     "lookback_default": 50, "frequency": "daily", "neutralizable": False, "direction": -1},
    {"id": "F038", "name": "sma_200_bias", "category": "technical", "subcategory": "trend",
     "description": "Price distance from 200-day SMA (z-score)", "formula_ref": "Mean reversion",
     "lookback_default": 200, "frequency": "daily", "neutralizable": False, "direction": -1},
    {"id": "F039", "name": "adx_14", "category": "technical", "subcategory": "trend",
     "description": "14-day Average Directional Index", "formula_ref": "Wilder 1978",
     "lookback_default": 14, "frequency": "daily", "neutralizable": False, "direction": 1},
    {"id": "F040", "name": "aroon_up", "category": "technical", "subcategory": "trend",
     "description": "Aroon Up indicator (25-day)", "formula_ref": "Chande 1995",
     "lookback_default": 25, "frequency": "daily", "neutralizable": False, "direction": 1},
    {"id": "F041", "name": "aroon_down", "category": "technical", "subcategory": "trend",
     "description": "Aroon Down indicator (25-day)", "formula_ref": "Chande 1995",
     "lookback_default": 25, "frequency": "daily", "neutralizable": False, "direction": -1},
    {"id": "F042", "name": "ichimoku_span", "category": "technical", "subcategory": "trend",
     "description": "Ichimoku Cloud leading span B distance", "formula_ref": "Ichimoku Kinko Hyo",
     "lookback_default": 52, "frequency": "daily", "neutralizable": False, "direction": 1},
    {"id": "F043", "name": "donchian_channel", "category": "technical", "subcategory": "trend",
     "description": "Donchian Channel breakout (20-day)", "formula_ref": "Donchian 1960s",
     "lookback_default": 20, "frequency": "daily", "neutralizable": False, "direction": 1},
    {"id": "F044", "name": "bollinger_bandwidth", "category": "technical", "subcategory": "trend",
     "description": "Bollinger Band width (20d, 2std)", "formula_ref": "Bollinger 1980s",
     "lookback_default": 20, "frequency": "daily", "neutralizable": False, "direction": 0},
    {"id": "F045", "name": "bollinger_pct_b", "category": "technical", "subcategory": "trend",
     "description": "Bollinger %B (position within bands)", "formula_ref": "Bollinger 1980s",
     "lookback_default": 20, "frequency": "daily", "neutralizable": False, "direction": -1},
    {"id": "F046", "name": "kama", "category": "technical", "subcategory": "trend",
     "description": "Kaufman Adaptive Moving Average signal", "formula_ref": "Kaufman 1998",
     "lookback_default": 21, "frequency": "daily", "neutralizable": False, "direction": 1},

    # Pattern / Breakout
    {"id": "F047", "name": "high_low_range", "category": "technical", "subcategory": "pattern",
     "description": "21-day average (H-L)/Close", "formula_ref": "Range-based",
     "lookback_default": 21, "frequency": "daily", "neutralizable": True, "direction": 0},
    {"id": "F048", "name": "gap_ratio", "category": "technical", "subcategory": "pattern",
     "description": "Overnight gap ratio (Open/PrevClose-1)", "formula_ref": "Gap analysis",
     "lookback_default": 5, "frequency": "daily", "neutralizable": False, "direction": 1},
    {"id": "F049", "name": "up_day_ratio", "category": "technical", "subcategory": "pattern",
     "description": "Fraction of up days in 21-day window", "formula_ref": "Market breadth",
     "lookback_default": 21, "frequency": "daily", "neutralizable": True, "direction": 1},
    {"id": "F050", "name": "hammer_pattern", "category": "technical", "subcategory": "pattern",
     "description": "Hammer candlestick pattern score", "formula_ref": "Candlestick patterns",
     "lookback_default": 5, "frequency": "daily", "neutralizable": False, "direction": 1},
    {"id": "F051", "name": "engulfing_pattern", "category": "technical", "subcategory": "pattern",
     "description": "Bullish/Bearish engulfing pattern score", "formula_ref": "Candlestick patterns",
     "lookback_default": 5, "frequency": "daily", "neutralizable": False, "direction": 1},
]

# ── Fundamental Factors (30+) ────────────────────────────────
FUNDAMENTAL_FACTORS: list[FactorEntry] = [
    # Value
    {"id": "F100", "name": "pe_ratio", "category": "fundamental", "subcategory": "value",
     "description": "Price-to-Earnings ratio (trailing 12m)", "formula_ref": "Fama-French HML",
     "lookback_default": 252, "frequency": "monthly", "neutralizable": True, "direction": -1},
    {"id": "F101", "name": "pb_ratio", "category": "fundamental", "subcategory": "value",
     "description": "Price-to-Book ratio", "formula_ref": "Fama-French HML",
     "lookback_default": 252, "frequency": "monthly", "neutralizable": True, "direction": -1},
    {"id": "F102", "name": "ps_ratio", "category": "fundamental", "subcategory": "value",
     "description": "Price-to-Sales ratio (trailing 12m)", "formula_ref": "O'Shaughnessy 1996",
     "lookback_default": 252, "frequency": "monthly", "neutralizable": True, "direction": -1},
    {"id": "F103", "name": "ev_ebitda", "category": "fundamental", "subcategory": "value",
     "description": "EV/EBITDA ratio", "formula_ref": "Enterprise value multiple",
     "lookback_default": 252, "frequency": "monthly", "neutralizable": True, "direction": -1},
    {"id": "F104", "name": "fcf_yield", "category": "fundamental", "subcategory": "value",
     "description": "Free Cash Flow / Market Cap", "formula_ref": "Novy-Marx 2013",
     "lookback_default": 252, "frequency": "monthly", "neutralizable": True, "direction": 1},
    {"id": "F105", "name": "earnings_yield", "category": "fundamental", "subcategory": "value",
     "description": "E/P ratio (1/PE)", "formula_ref": "E/P anomaly",
     "lookback_default": 252, "frequency": "monthly", "neutralizable": True, "direction": 1},
    {"id": "F106", "name": "dividend_yield", "category": "fundamental", "subcategory": "value",
     "description": "Trailing 12-month dividend yield", "formula_ref": "Dividend premium",
     "lookback_default": 252, "frequency": "monthly", "neutralizable": True, "direction": 1},
    {"id": "F107", "name": "peg_ratio", "category": "fundamental", "subcategory": "value",
     "description": "PE / Earnings Growth rate", "formula_ref": "Lynch PEG",
     "lookback_default": 252, "frequency": "monthly", "neutralizable": True, "direction": -1},

    # Quality / Profitability
    {"id": "F108", "name": "roe", "category": "fundamental", "subcategory": "quality",
     "description": "Return on Equity (trailing 12m)", "formula_ref": "DuPont analysis",
     "lookback_default": 252, "frequency": "monthly", "neutralizable": True, "direction": 1},
    {"id": "F109", "name": "roa", "category": "fundamental", "subcategory": "quality",
     "description": "Return on Assets (trailing 12m)", "formula_ref": "Quality metric",
     "lookback_default": 252, "frequency": "monthly", "neutralizable": True, "direction": 1},
    {"id": "F110", "name": "roic", "category": "fundamental", "subcategory": "quality",
     "description": "Return on Invested Capital", "formula_ref": "Greenblatt Magic Formula",
     "lookback_default": 252, "frequency": "monthly", "neutralizable": True, "direction": 1},
    {"id": "F111", "name": "gross_margin", "category": "fundamental", "subcategory": "quality",
     "description": "Gross profit margin", "formula_ref": "Novy-Marx 2013",
     "lookback_default": 252, "frequency": "quarterly", "neutralizable": True, "direction": 1},
    {"id": "F112", "name": "gross_profitability", "category": "fundamental", "subcategory": "quality",
     "description": "Gross Profit / Total Assets", "formula_ref": "Novy-Marx 2013",
     "lookback_default": 252, "frequency": "quarterly", "neutralizable": True, "direction": 1},
    {"id": "F113", "name": "operating_margin", "category": "fundamental", "subcategory": "quality",
     "description": "Operating income margin", "formula_ref": "Quality factor",
     "lookback_default": 252, "frequency": "quarterly", "neutralizable": True, "direction": 1},
    {"id": "F114", "name": "net_margin", "category": "fundamental", "subcategory": "quality",
     "description": "Net profit margin", "formula_ref": "Quality factor",
     "lookback_default": 252, "frequency": "quarterly", "neutralizable": True, "direction": 1},
    {"id": "F115", "name": "asset_turnover", "category": "fundamental", "subcategory": "quality",
     "description": "Revenue / Total Assets", "formula_ref": "DuPont analysis",
     "lookback_default": 252, "frequency": "quarterly", "neutralizable": True, "direction": 1},
    {"id": "F116", "name": "accruals", "category": "fundamental", "subcategory": "quality",
     "description": "Balance-sheet accruals (ΔWC + ΔNCO)", "formula_ref": "Sloan 1996",
     "lookback_default": 252, "frequency": "quarterly", "neutralizable": True, "direction": -1},

    # Growth
    {"id": "F117", "name": "revenue_growth_yoy", "category": "fundamental", "subcategory": "growth",
     "description": "YoY revenue growth rate", "formula_ref": "Growth factor",
     "lookback_default": 252, "frequency": "quarterly", "neutralizable": True, "direction": 1},
    {"id": "F118", "name": "earnings_growth_yoy", "category": "fundamental", "subcategory": "growth",
     "description": "YoY EPS growth rate", "formula_ref": "Growth factor",
     "lookback_default": 252, "frequency": "quarterly", "neutralizable": True, "direction": 1},
    {"id": "F119", "name": "earnings_revision", "category": "fundamental", "subcategory": "growth",
     "description": "Analyst EPS estimate revision (3m change)", "formula_ref": "Post-earnings drift",
     "lookback_default": 63, "frequency": "monthly", "neutralizable": True, "direction": 1},
    {"id": "F120", "name": "earnings_surprise", "category": "fundamental", "subcategory": "growth",
     "description": "Latest earnings surprise vs consensus", "formula_ref": "SUE / PEAD",
     "lookback_default": 90, "frequency": "quarterly", "neutralizable": True, "direction": 1},
    {"id": "F121", "name": "capex_growth", "category": "fundamental", "subcategory": "growth",
     "description": "YoY CapEx growth rate", "formula_ref": "Abarbanell-Bushee 1998",
     "lookback_default": 252, "frequency": "quarterly", "neutralizable": True, "direction": 1},
    {"id": "F122", "name": "rd_to_sales", "category": "fundamental", "subcategory": "growth",
     "description": "R&D expense / Sales", "formula_ref": "Innovation proxy",
     "lookback_default": 252, "frequency": "quarterly", "neutralizable": True, "direction": 1},

    # Financial Health
    {"id": "F123", "name": "debt_to_equity", "category": "fundamental", "subcategory": "health",
     "description": "Total Debt / Total Equity", "formula_ref": "Leverage metric",
     "lookback_default": 252, "frequency": "quarterly", "neutralizable": True, "direction": -1},
    {"id": "F124", "name": "current_ratio", "category": "fundamental", "subcategory": "health",
     "description": "Current Assets / Current Liabilities", "formula_ref": "Liquidity metric",
     "lookback_default": 252, "frequency": "quarterly", "neutralizable": True, "direction": 1},
    {"id": "F125", "name": "interest_coverage", "category": "fundamental", "subcategory": "health",
     "description": "EBIT / Interest Expense", "formula_ref": "Altman Z-score component",
     "lookback_default": 252, "frequency": "quarterly", "neutralizable": True, "direction": 1},
    {"id": "F126", "name": "altman_z", "category": "fundamental", "subcategory": "health",
     "description": "Altman Z-score", "formula_ref": "Altman 1968",
     "lookback_default": 252, "frequency": "quarterly", "neutralizable": True, "direction": 1},
    {"id": "F127", "name": "piotroski_f", "category": "fundamental", "subcategory": "health",
     "description": "Piotroski F-score (0-9)", "formula_ref": "Piotroski 2000",
     "lookback_default": 252, "frequency": "quarterly", "neutralizable": True, "direction": 1},
    {"id": "F128", "name": "beneish_m", "category": "fundamental", "subcategory": "health",
     "description": "Beneish M-score (earnings manipulation)", "formula_ref": "Beneish 1999",
     "lookback_default": 252, "frequency": "quarterly", "neutralizable": True, "direction": -1},
    {"id": "F129", "name": "share_buyback", "category": "fundamental", "subcategory": "health",
     "description": "Net share repurchase / Market Cap", "formula_ref": "Payout yield",
     "lookback_default": 252, "frequency": "quarterly", "neutralizable": True, "direction": 1},
]

# ── Alternative Factors (20+) ────────────────────────────────
ALTERNATIVE_FACTORS: list[FactorEntry] = [
    # Sentiment
    {"id": "F200", "name": "short_interest_ratio", "category": "alternative", "subcategory": "sentiment",
     "description": "Days to cover (short interest / avg volume)", "formula_ref": "Short squeeze",
     "lookback_default": 21, "frequency": "biweekly", "neutralizable": True, "direction": 1},
    {"id": "F201", "name": "put_call_ratio", "category": "alternative", "subcategory": "sentiment",
     "description": "Equity put/call volume ratio (z-score)", "formula_ref": "Options sentiment",
     "lookback_default": 21, "frequency": "daily", "neutralizable": False, "direction": -1},
    {"id": "F202", "name": "news_sentiment", "category": "alternative", "subcategory": "sentiment",
     "description": "NLP news sentiment score (Bloomberg/Reuters)", "formula_ref": "NLP sentiment analysis",
     "lookback_default": 5, "frequency": "daily", "neutralizable": True, "direction": 1},
    {"id": "F203", "name": "social_buzz", "category": "alternative", "subcategory": "sentiment",
     "description": "Social media mention volume (z-score)", "formula_ref": "Social media analytics",
     "lookback_default": 5, "frequency": "daily", "neutralizable": True, "direction": 0},
    {"id": "F204", "name": "analyst_recommendation", "category": "alternative", "subcategory": "sentiment",
     "description": "Consensus analyst rating (1=Strong Buy, 5=Strong Sell)", "formula_ref": "Analyst consensus",
     "lookback_default": 90, "frequency": "monthly", "neutralizable": True, "direction": -1},
    {"id": "F205", "name": "insider_trading", "category": "alternative", "subcategory": "sentiment",
     "description": "Net insider buy/sell ratio (3m)", "formula_ref": "Insider trading signal",
     "lookback_default": 63, "frequency": "monthly", "neutralizable": True, "direction": 1},
    {"id": "F206", "name": "earnings_call_tone", "category": "alternative", "subcategory": "sentiment",
     "description": "Earnings call NLP tone (positive vs negative)", "formula_ref": "Loughran-McDonald 2011",
     "lookback_default": 90, "frequency": "quarterly", "neutralizable": True, "direction": 1},

    # Macro / Cross-Asset
    {"id": "F207", "name": "beta_to_vix", "category": "alternative", "subcategory": "macro",
     "description": "Sensitivity to VIX changes (63d)", "formula_ref": "Volatility beta",
     "lookback_default": 63, "frequency": "daily", "neutralizable": False, "direction": -1},
    {"id": "F208", "name": "usd_sensitivity", "category": "alternative", "subcategory": "macro",
     "description": "Sensitivity to DXY index (63d)", "formula_ref": "FX beta",
     "lookback_default": 63, "frequency": "daily", "neutralizable": False, "direction": 0},
    {"id": "F209", "name": "commodity_beta", "category": "alternative", "subcategory": "macro",
     "description": "Sensitivity to CRB commodity index", "formula_ref": "Cross-asset",
     "lookback_default": 63, "frequency": "daily", "neutralizable": False, "direction": 0},
    {"id": "F210", "name": "rate_sensitivity", "category": "alternative", "subcategory": "macro",
     "description": "Sensitivity to 10Y Treasury yield changes", "formula_ref": "Duration proxy",
     "lookback_default": 63, "frequency": "daily", "neutralizable": False, "direction": 0},
    {"id": "F211", "name": "country_rotation", "category": "alternative", "subcategory": "macro",
     "description": "Country ETF relative momentum rank", "formula_ref": "Country rotation",
     "lookback_default": 63, "frequency": "monthly", "neutralizable": False, "direction": 1},

    # ESG
    {"id": "F212", "name": "esg_score", "category": "alternative", "subcategory": "esg",
     "description": "Aggregate ESG score (MSCI/Sustainalytics)", "formula_ref": "ESG integration",
     "lookback_default": 252, "frequency": "annually", "neutralizable": True, "direction": 1},
    {"id": "F213", "name": "carbon_intensity", "category": "alternative", "subcategory": "esg",
     "description": "Scope 1+2 emissions / Revenue", "formula_ref": "Carbon metrics",
     "lookback_default": 252, "frequency": "annually", "neutralizable": True, "direction": -1},

    # Supply Chain
    {"id": "F214", "name": "supplier_momentum", "category": "alternative", "subcategory": "supply_chain",
     "description": "Key supplier stock return lead-lag", "formula_ref": "Supply chain alpha",
     "lookback_default": 21, "frequency": "monthly", "neutralizable": True, "direction": 1},
    {"id": "F215", "name": "customer_momentum", "category": "alternative", "subcategory": "supply_chain",
     "description": "Key customer stock return lead-lag", "formula_ref": "Supply chain alpha",
     "lookback_default": 21, "frequency": "monthly", "neutralizable": True, "direction": 1},

    # Alternative Data
    {"id": "F216", "name": "satellite_parking", "category": "alternative", "subcategory": "alt_data",
     "description": "Satellite-based retail parking lot fill rate", "formula_ref": "Alt data",
     "lookback_default": 21, "frequency": "weekly", "neutralizable": True, "direction": 1},
    {"id": "F217", "name": "credit_card_spend", "category": "alternative", "subcategory": "alt_data",
     "description": "Aggregated credit card spending growth", "formula_ref": "Alt data",
     "lookback_default": 21, "frequency": "weekly", "neutralizable": True, "direction": 1},
    {"id": "F218", "name": "app_downloads", "category": "alternative", "subcategory": "alt_data",
     "description": "Mobile app download growth rate", "formula_ref": "Alt data",
     "lookback_default": 21, "frequency": "weekly", "neutralizable": True, "direction": 1},
    {"id": "F219", "name": "website_traffic", "category": "alternative", "subcategory": "alt_data",
     "description": "Web traffic growth (SimilarWeb)", "formula_ref": "Alt data",
     "lookback_default": 21, "frequency": "weekly", "neutralizable": True, "direction": 1},
]

# ── Microstructure Factors (10+) ─────────────────────────────
MICROSTRUCTURE_FACTORS: list[FactorEntry] = [
    {"id": "F300", "name": "bid_ask_spread", "category": "microstructure", "subcategory": "spread",
     "description": "Time-weighted quoted spread (%)", "formula_ref": "Roll 1984",
     "lookback_default": 5, "frequency": "daily", "neutralizable": True, "direction": -1},
    {"id": "F301", "name": "effective_spread", "category": "microstructure", "subcategory": "spread",
     "description": "2 * |Price - Midpoint| at trade", "formula_ref": "Effective spread",
     "lookback_default": 5, "frequency": "daily", "neutralizable": True, "direction": -1},
    {"id": "F302", "name": "realized_spread", "category": "microstructure", "subcategory": "spread",
     "description": "Temporary price impact reversal", "formula_ref": "Huang-Stoll 1996",
     "lookback_default": 5, "frequency": "daily", "neutralizable": True, "direction": -1},
    {"id": "F303", "name": "price_impact", "category": "microstructure", "subcategory": "liquidity",
     "description": "Amihud illiquidity (|ret|/volume)", "formula_ref": "Amihud 2002",
     "lookback_default": 21, "frequency": "daily", "neutralizable": True, "direction": -1},
    {"id": "F304", "name": "order_imbalance", "category": "microstructure", "subcategory": "flow",
     "description": "Signed order flow imbalance (buy-sell)/(buy+sell)", "formula_ref": "Order flow",
     "lookback_default": 5, "frequency": "daily", "neutralizable": True, "direction": 1},
    {"id": "F305", "name": "depth_imbalance", "category": "microstructure", "subcategory": "flow",
     "description": "Bid depth / (Bid+Ask depth) at top of book", "formula_ref": "LOB imbalance",
     "lookback_default": 5, "frequency": "daily", "neutralizable": True, "direction": 1},
    {"id": "F306", "name": "trade_size_skew", "category": "microstructure", "subcategory": "flow",
     "description": "Ratio of large-trade volume to total volume", "formula_ref": "Institutional flow",
     "lookback_default": 5, "frequency": "daily", "neutralizable": True, "direction": 1},
    {"id": "F307", "name": "intraday_reversal", "category": "microstructure", "subcategory": "reversal",
     "description": "Intraday return reversal (open-close vs close-next_open)", "formula_ref": "HFT reversal",
     "lookback_default": 5, "frequency": "intraday", "neutralizable": True, "direction": -1},
    {"id": "F308", "name": "trade_signing_ratio", "category": "microstructure", "subcategory": "flow",
     "description": "Lee-Ready trade classification buy ratio", "formula_ref": "Lee-Ready 1991",
     "lookback_default": 5, "frequency": "intraday", "neutralizable": True, "direction": 1},
    {"id": "F309", "name": "market_impact_model", "category": "microstructure", "subcategory": "impact",
     "description": "Almgren-Chriss temporary impact coefficient", "formula_ref": "Almgren-Chriss 2000",
     "lookback_default": 21, "frequency": "daily", "neutralizable": True, "direction": -1},
    {"id": "F310", "name": "volume_synchronized_prob", "category": "microstructure", "subcategory": "correlation",
     "description": "VPIN (Volume-synchronized PIN)", "formula_ref": "Easley 2012 VPIN",
     "lookback_default": 21, "frequency": "daily", "neutralizable": True, "direction": -1},
    {"id": "F311", "name": "high_freq_mom", "category": "microstructure", "subcategory": "momentum",
     "description": "Intraday momentum (10-30min horizon)", "formula_ref": "HFT alpha",
     "lookback_default": 1, "frequency": "intraday", "neutralizable": False, "direction": 1},
]

# ── Aggregated Factor Registry ───────────────────────────────
FACTOR_REGISTRY: dict[str, list[FactorEntry]] = {
    "technical": TECHNICAL_FACTORS,
    "fundamental": FUNDAMENTAL_FACTORS,
    "alternative": ALTERNATIVE_FACTORS,
    "microstructure": MICROSTRUCTURE_FACTORS,
}


def get_factor_count() -> dict[str, int]:
    """Return the count of factors per category."""
    return {cat: len(factors) for cat, factors in FACTOR_REGISTRY.items()}


def get_total_factor_count() -> int:
    """Return total number of registered factors."""
    return sum(len(f) for f in FACTOR_REGISTRY.values())


def get_factor_by_id(factor_id: str) -> FactorEntry | None:
    """Look up a factor by its ID.

    Args:
        factor_id: Factor identifier string (e.g. 'F001').

    Returns:
        FactorEntry if found, None otherwise.
    """
    for category_factors in FACTOR_REGISTRY.values():
        for entry in category_factors:
            if entry["id"] == factor_id:
                return entry
    return None


def get_factors_by_subcategory(category: str, subcategory: str) -> list[FactorEntry]:
    """Filter factors by category and subcategory.

    Args:
        category: Factor category (technical/fundamental/alternative/microstructure).
        subcategory: Subcategory name to filter by.

    Returns:
        List of matching FactorEntry objects.
    """
    results: list[FactorEntry] = []
    for entry in FACTOR_REGISTRY.get(category, []):
        if entry.get("subcategory") == subcategory:
            results.append(entry)
    return results


def get_all_factor_ids() -> list[str]:
    """Return all factor IDs sorted."""
    ids: list[str] = []
    for category_factors in FACTOR_REGISTRY.values():
        ids.extend(e["id"] for e in category_factors)
    return sorted(ids)
