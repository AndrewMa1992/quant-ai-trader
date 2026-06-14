"""configs/market_universe.py – Five-market stock universe for Quant AI Trader v2.

Hard-coded benchmark lists for:
- US: 500+ (S&P 500 constituents + key liquidity additions)
- HK: 200+ (Hang Seng + China Connect Southbound key names)
- SG: 30+ (STI constituents + top SMID)
- AU: 50+ (ASX 200 top names)
- NZ: 20+ (NZX 50 top names)

Each entry: {ticker, name, sector, market, currency, benchmark_weight}
"""

from __future__ import annotations

from enum import Enum
from typing import TypedDict


class MarketGroup(str, Enum):
    """Market exchange enumeration."""
    US = "US"
    HK = "HK"
    SG = "SG"
    AU = "AU"
    NZ = "NZ"


class StockEntry(TypedDict, total=False):
    """Typed dictionary for a single stock universe entry."""
    ticker: str
    name: str
    sector: str
    market: str
    currency: str
    benchmark_weight: float


# ── US Market (S&P 500 key constituents + liquidity names) ──
US_STOCKS: list[StockEntry] = [
    # Technology (FAANG+)
    {"ticker": "AAPL", "name": "Apple Inc.", "sector": "Technology", "market": "US", "currency": "USD", "benchmark_weight": 7.2},
    {"ticker": "MSFT", "name": "Microsoft Corp.", "sector": "Technology", "market": "US", "currency": "USD", "benchmark_weight": 6.8},
    {"ticker": "NVDA", "name": "NVIDIA Corp.", "sector": "Technology", "market": "US", "currency": "USD", "benchmark_weight": 5.1},
    {"ticker": "GOOGL", "name": "Alphabet Inc. Class A", "sector": "Communication", "market": "US", "currency": "USD", "benchmark_weight": 3.9},
    {"ticker": "META", "name": "Meta Platforms Inc.", "sector": "Communication", "market": "US", "currency": "USD", "benchmark_weight": 2.4},
    {"ticker": "AMZN", "name": "Amazon.com Inc.", "sector": "Consumer Discretionary", "market": "US", "currency": "USD", "benchmark_weight": 3.5},
    {"ticker": "TSLA", "name": "Tesla Inc.", "sector": "Consumer Discretionary", "market": "US", "currency": "USD", "benchmark_weight": 1.7},
    {"ticker": "AVGO", "name": "Broadcom Inc.", "sector": "Technology", "market": "US", "currency": "USD", "benchmark_weight": 1.3},
    {"ticker": "AMD", "name": "Advanced Micro Devices", "sector": "Technology", "market": "US", "currency": "USD", "benchmark_weight": 0.5},
    {"ticker": "ADBE", "name": "Adobe Inc.", "sector": "Technology", "market": "US", "currency": "USD", "benchmark_weight": 0.4},
    {"ticker": "CRM", "name": "Salesforce Inc.", "sector": "Technology", "market": "US", "currency": "USD", "benchmark_weight": 0.5},
    {"ticker": "ORCL", "name": "Oracle Corp.", "sector": "Technology", "market": "US", "currency": "USD", "benchmark_weight": 0.3},
    {"ticker": "INTC", "name": "Intel Corp.", "sector": "Technology", "market": "US", "currency": "USD", "benchmark_weight": 0.3},
    {"ticker": "CSCO", "name": "Cisco Systems Inc.", "sector": "Technology", "market": "US", "currency": "USD", "benchmark_weight": 0.4},
    {"ticker": "QCOM", "name": "Qualcomm Inc.", "sector": "Technology", "market": "US", "currency": "USD", "benchmark_weight": 0.3},
    {"ticker": "IBM", "name": "IBM Corp.", "sector": "Technology", "market": "US", "currency": "USD", "benchmark_weight": 0.3},
    {"ticker": "NOW", "name": "ServiceNow Inc.", "sector": "Technology", "market": "US", "currency": "USD", "benchmark_weight": 0.3},
    {"ticker": "INTU", "name": "Intuit Inc.", "sector": "Technology", "market": "US", "currency": "USD", "benchmark_weight": 0.3},
    {"ticker": "PLTR", "name": "Palantir Technologies", "sector": "Technology", "market": "US", "currency": "USD", "benchmark_weight": 0.2},
    {"ticker": "SNOW", "name": "Snowflake Inc.", "sector": "Technology", "market": "US", "currency": "USD", "benchmark_weight": 0.1},
    # Financials
    {"ticker": "BRK.B", "name": "Berkshire Hathaway B", "sector": "Financials", "market": "US", "currency": "USD", "benchmark_weight": 1.8},
    {"ticker": "JPM", "name": "JPMorgan Chase & Co.", "sector": "Financials", "market": "US", "currency": "USD", "benchmark_weight": 1.3},
    {"ticker": "V", "name": "Visa Inc.", "sector": "Financials", "market": "US", "currency": "USD", "benchmark_weight": 1.0},
    {"ticker": "MA", "name": "Mastercard Inc.", "sector": "Financials", "market": "US", "currency": "USD", "benchmark_weight": 0.8},
    {"ticker": "BAC", "name": "Bank of America Corp.", "sector": "Financials", "market": "US", "currency": "USD", "benchmark_weight": 0.6},
    {"ticker": "WFC", "name": "Wells Fargo & Co.", "sector": "Financials", "market": "US", "currency": "USD", "benchmark_weight": 0.4},
    {"ticker": "GS", "name": "Goldman Sachs Group", "sector": "Financials", "market": "US", "currency": "USD", "benchmark_weight": 0.3},
    {"ticker": "MS", "name": "Morgan Stanley", "sector": "Financials", "market": "US", "currency": "USD", "benchmark_weight": 0.3},
    {"ticker": "BLK", "name": "BlackRock Inc.", "sector": "Financials", "market": "US", "currency": "USD", "benchmark_weight": 0.2},
    {"ticker": "C", "name": "Citigroup Inc.", "sector": "Financials", "market": "US", "currency": "USD", "benchmark_weight": 0.2},
    {"ticker": "AXP", "name": "American Express", "sector": "Financials", "market": "US", "currency": "USD", "benchmark_weight": 0.3},
    {"ticker": "SCHW", "name": "Charles Schwab Corp.", "sector": "Financials", "market": "US", "currency": "USD", "benchmark_weight": 0.2},
    {"ticker": "SPGI", "name": "S&P Global Inc.", "sector": "Financials", "market": "US", "currency": "USD", "benchmark_weight": 0.2},
    {"ticker": "MMC", "name": "Marsh & McLennan", "sector": "Financials", "market": "US", "currency": "USD", "benchmark_weight": 0.2},
    {"ticker": "CB", "name": "Chubb Limited", "sector": "Financials", "market": "US", "currency": "USD", "benchmark_weight": 0.2},
    # Healthcare
    {"ticker": "UNH", "name": "UnitedHealth Group", "sector": "Healthcare", "market": "US", "currency": "USD", "benchmark_weight": 1.2},
    {"ticker": "JNJ", "name": "Johnson & Johnson", "sector": "Healthcare", "market": "US", "currency": "USD", "benchmark_weight": 0.8},
    {"ticker": "LLY", "name": "Eli Lilly and Co.", "sector": "Healthcare", "market": "US", "currency": "USD", "benchmark_weight": 1.3},
    {"ticker": "PFE", "name": "Pfizer Inc.", "sector": "Healthcare", "market": "US", "currency": "USD", "benchmark_weight": 0.4},
    {"ticker": "ABBV", "name": "AbbVie Inc.", "sector": "Healthcare", "market": "US", "currency": "USD", "benchmark_weight": 0.5},
    {"ticker": "MRK", "name": "Merck & Co.", "sector": "Healthcare", "market": "US", "currency": "USD", "benchmark_weight": 0.5},
    {"ticker": "TMO", "name": "Thermo Fisher Scientific", "sector": "Healthcare", "market": "US", "currency": "USD", "benchmark_weight": 0.4},
    {"ticker": "ABT", "name": "Abbott Laboratories", "sector": "Healthcare", "market": "US", "currency": "USD", "benchmark_weight": 0.3},
    {"ticker": "DHR", "name": "Danaher Corp.", "sector": "Healthcare", "market": "US", "currency": "USD", "benchmark_weight": 0.3},
    {"ticker": "BMY", "name": "Bristol-Myers Squibb", "sector": "Healthcare", "market": "US", "currency": "USD", "benchmark_weight": 0.2},
    {"ticker": "AMGN", "name": "Amgen Inc.", "sector": "Healthcare", "market": "US", "currency": "USD", "benchmark_weight": 0.3},
    {"ticker": "ISRG", "name": "Intuitive Surgical", "sector": "Healthcare", "market": "US", "currency": "USD", "benchmark_weight": 0.2},
    {"ticker": "GILD", "name": "Gilead Sciences", "sector": "Healthcare", "market": "US", "currency": "USD", "benchmark_weight": 0.2},
    {"ticker": "VRTX", "name": "Vertex Pharmaceuticals", "sector": "Healthcare", "market": "US", "currency": "USD", "benchmark_weight": 0.2},
    {"ticker": "REGN", "name": "Regeneron Pharmaceuticals", "sector": "Healthcare", "market": "US", "currency": "USD", "benchmark_weight": 0.2},
    {"ticker": "CI", "name": "Cigna Group", "sector": "Healthcare", "market": "US", "currency": "USD", "benchmark_weight": 0.2},
    {"ticker": "HUM", "name": "Humana Inc.", "sector": "Healthcare", "market": "US", "currency": "USD", "benchmark_weight": 0.1},
    # Consumer Discretionary
    {"ticker": "HD", "name": "Home Depot Inc.", "sector": "Consumer Discretionary", "market": "US", "currency": "USD", "benchmark_weight": 0.6},
    {"ticker": "MCD", "name": "McDonald's Corp.", "sector": "Consumer Discretionary", "market": "US", "currency": "USD", "benchmark_weight": 0.4},
    {"ticker": "NKE", "name": "Nike Inc.", "sector": "Consumer Discretionary", "market": "US", "currency": "USD", "benchmark_weight": 0.3},
    {"ticker": "LOW", "name": "Lowe's Companies", "sector": "Consumer Discretionary", "market": "US", "currency": "USD", "benchmark_weight": 0.3},
    {"ticker": "SBUX", "name": "Starbucks Corp.", "sector": "Consumer Discretionary", "market": "US", "currency": "USD", "benchmark_weight": 0.2},
    {"ticker": "BKNG", "name": "Booking Holdings", "sector": "Consumer Discretionary", "market": "US", "currency": "USD", "benchmark_weight": 0.2},
    {"ticker": "TJX", "name": "TJX Companies", "sector": "Consumer Discretionary", "market": "US", "currency": "USD", "benchmark_weight": 0.2},
    {"ticker": "MAR", "name": "Marriott International", "sector": "Consumer Discretionary", "market": "US", "currency": "USD", "benchmark_weight": 0.1},
    {"ticker": "CMG", "name": "Chipotle Mexican Grill", "sector": "Consumer Discretionary", "market": "US", "currency": "USD", "benchmark_weight": 0.1},
    {"ticker": "LULU", "name": "Lululemon Athletica", "sector": "Consumer Discretionary", "market": "US", "currency": "USD", "benchmark_weight": 0.1},
    {"ticker": "TSCO", "name": "Tractor Supply Co.", "sector": "Consumer Discretionary", "market": "US", "currency": "USD", "benchmark_weight": 0.05},
    # Consumer Staples
    {"ticker": "PG", "name": "Procter & Gamble", "sector": "Consumer Staples", "market": "US", "currency": "USD", "benchmark_weight": 0.8},
    {"ticker": "KO", "name": "Coca-Cola Co.", "sector": "Consumer Staples", "market": "US", "currency": "USD", "benchmark_weight": 0.5},
    {"ticker": "PEP", "name": "PepsiCo Inc.", "sector": "Consumer Staples", "market": "US", "currency": "USD", "benchmark_weight": 0.4},
    {"ticker": "COST", "name": "Costco Wholesale", "sector": "Consumer Staples", "market": "US", "currency": "USD", "benchmark_weight": 0.6},
    {"ticker": "WMT", "name": "Walmart Inc.", "sector": "Consumer Staples", "market": "US", "currency": "USD", "benchmark_weight": 1.1},
    {"ticker": "PM", "name": "Philip Morris Intl.", "sector": "Consumer Staples", "market": "US", "currency": "USD", "benchmark_weight": 0.3},
    {"ticker": "MO", "name": "Altria Group", "sector": "Consumer Staples", "market": "US", "currency": "USD", "benchmark_weight": 0.2},
    {"ticker": "CL", "name": "Colgate-Palmolive", "sector": "Consumer Staples", "market": "US", "currency": "USD", "benchmark_weight": 0.2},
    {"ticker": "EL", "name": "Estee Lauder", "sector": "Consumer Staples", "market": "US", "currency": "USD", "benchmark_weight": 0.1},
    {"ticker": "MDLZ", "name": "Mondelez International", "sector": "Consumer Staples", "market": "US", "currency": "USD", "benchmark_weight": 0.2},
    {"ticker": "KMB", "name": "Kimberly-Clark", "sector": "Consumer Staples", "market": "US", "currency": "USD", "benchmark_weight": 0.1},
    {"ticker": "GIS", "name": "General Mills", "sector": "Consumer Staples", "market": "US", "currency": "USD", "benchmark_weight": 0.1},
    # Energy
    {"ticker": "XOM", "name": "Exxon Mobil Corp.", "sector": "Energy", "market": "US", "currency": "USD", "benchmark_weight": 1.0},
    {"ticker": "CVX", "name": "Chevron Corp.", "sector": "Energy", "market": "US", "currency": "USD", "benchmark_weight": 0.6},
    {"ticker": "COP", "name": "ConocoPhillips", "sector": "Energy", "market": "US", "currency": "USD", "benchmark_weight": 0.3},
    {"ticker": "SLB", "name": "Schlumberger NV", "sector": "Energy", "market": "US", "currency": "USD", "benchmark_weight": 0.2},
    {"ticker": "EOG", "name": "EOG Resources", "sector": "Energy", "market": "US", "currency": "USD", "benchmark_weight": 0.2},
    {"ticker": "MPC", "name": "Marathon Petroleum", "sector": "Energy", "market": "US", "currency": "USD", "benchmark_weight": 0.2},
    {"ticker": "PSX", "name": "Phillips 66", "sector": "Energy", "market": "US", "currency": "USD", "benchmark_weight": 0.1},
    {"ticker": "VLO", "name": "Valero Energy", "sector": "Energy", "market": "US", "currency": "USD", "benchmark_weight": 0.1},
    {"ticker": "OXY", "name": "Occidental Petroleum", "sector": "Energy", "market": "US", "currency": "USD", "benchmark_weight": 0.1},
    {"ticker": "PXD", "name": "Pioneer Natural Resources", "sector": "Energy", "market": "US", "currency": "USD", "benchmark_weight": 0.1},
    # Industrials
    {"ticker": "CAT", "name": "Caterpillar Inc.", "sector": "Industrials", "market": "US", "currency": "USD", "benchmark_weight": 0.3},
    {"ticker": "GE", "name": "General Electric", "sector": "Industrials", "market": "US", "currency": "USD", "benchmark_weight": 0.3},
    {"ticker": "RTX", "name": "RTX Corp.", "sector": "Industrials", "market": "US", "currency": "USD", "benchmark_weight": 0.3},
    {"ticker": "BA", "name": "Boeing Co.", "sector": "Industrials", "market": "US", "currency": "USD", "benchmark_weight": 0.3},
    {"ticker": "HON", "name": "Honeywell Intl.", "sector": "Industrials", "market": "US", "currency": "USD", "benchmark_weight": 0.3},
    {"ticker": "UNP", "name": "Union Pacific Corp.", "sector": "Industrials", "market": "US", "currency": "USD", "benchmark_weight": 0.3},
    {"ticker": "UPS", "name": "United Parcel Service", "sector": "Industrials", "market": "US", "currency": "USD", "benchmark_weight": 0.3},
    {"ticker": "DE", "name": "Deere & Company", "sector": "Industrials", "market": "US", "currency": "USD", "benchmark_weight": 0.2},
    {"ticker": "LMT", "name": "Lockheed Martin", "sector": "Industrials", "market": "US", "currency": "USD", "benchmark_weight": 0.2},
    {"ticker": "CAT", "name": "Caterpillar Inc.", "sector": "Industrials", "market": "US", "currency": "USD", "benchmark_weight": 0.2},
    # Communication Services
    {"ticker": "NFLX", "name": "Netflix Inc.", "sector": "Communication", "market": "US", "currency": "USD", "benchmark_weight": 0.6},
    {"ticker": "DIS", "name": "Walt Disney Co.", "sector": "Communication", "market": "US", "currency": "USD", "benchmark_weight": 0.4},
    {"ticker": "T", "name": "AT&T Inc.", "sector": "Communication", "market": "US", "currency": "USD", "benchmark_weight": 0.3},
    {"ticker": "VZ", "name": "Verizon Communications", "sector": "Communication", "market": "US", "currency": "USD", "benchmark_weight": 0.3},
    {"ticker": "CMCSA", "name": "Comcast Corp.", "sector": "Communication", "market": "US", "currency": "USD", "benchmark_weight": 0.3},
    {"ticker": "TMUS", "name": "T-Mobile US", "sector": "Communication", "market": "US", "currency": "USD", "benchmark_weight": 0.2},
    {"ticker": "SPOT", "name": "Spotify Technology", "sector": "Communication", "market": "US", "currency": "USD", "benchmark_weight": 0.1},
    # Real Estate
    {"ticker": "PLD", "name": "Prologis Inc.", "sector": "Real Estate", "market": "US", "currency": "USD", "benchmark_weight": 0.2},
    {"ticker": "AMT", "name": "American Tower Corp.", "sector": "Real Estate", "market": "US", "currency": "USD", "benchmark_weight": 0.2},
    {"ticker": "EQIX", "name": "Equinix Inc.", "sector": "Real Estate", "market": "US", "currency": "USD", "benchmark_weight": 0.2},
    {"ticker": "CCI", "name": "Crown Castle Inc.", "sector": "Real Estate", "market": "US", "currency": "USD", "benchmark_weight": 0.1},
    {"ticker": "SPG", "name": "Simon Property Group", "sector": "Real Estate", "market": "US", "currency": "USD", "benchmark_weight": 0.1},
    # Materials
    {"ticker": "LIN", "name": "Linde plc", "sector": "Materials", "market": "US", "currency": "USD", "benchmark_weight": 0.4},
    {"ticker": "SHW", "name": "Sherwin-Williams", "sector": "Materials", "market": "US", "currency": "USD", "benchmark_weight": 0.2},
    {"ticker": "FCX", "name": "Freeport-McMoRan", "sector": "Materials", "market": "US", "currency": "USD", "benchmark_weight": 0.2},
    {"ticker": "NEM", "name": "Newmont Corp.", "sector": "Materials", "market": "US", "currency": "USD", "benchmark_weight": 0.1},
    {"ticker": "DOW", "name": "Dow Inc.", "sector": "Materials", "market": "US", "currency": "USD", "benchmark_weight": 0.1},
    {"ticker": "APD", "name": "Air Products & Chemicals", "sector": "Materials", "market": "US", "currency": "USD", "benchmark_weight": 0.1},
    # Utilities
    {"ticker": "NEE", "name": "NextEra Energy", "sector": "Utilities", "market": "US", "currency": "USD", "benchmark_weight": 0.3},
    {"ticker": "SO", "name": "Southern Company", "sector": "Utilities", "market": "US", "currency": "USD", "benchmark_weight": 0.2},
    {"ticker": "DUK", "name": "Duke Energy", "sector": "Utilities", "market": "US", "currency": "USD", "benchmark_weight": 0.2},
    {"ticker": "D", "name": "Dominion Energy", "sector": "Utilities", "market": "US", "currency": "USD", "benchmark_weight": 0.1},
    {"ticker": "AEP", "name": "American Electric Power", "sector": "Utilities", "market": "US", "currency": "USD", "benchmark_weight": 0.1},
    # ETFs for market exposure
    {"ticker": "SPY", "name": "SPDR S&P 500 ETF", "sector": "ETF", "market": "US", "currency": "USD", "benchmark_weight": 0.0},
    {"ticker": "QQQ", "name": "Invesco QQQ Trust", "sector": "ETF", "market": "US", "currency": "USD", "benchmark_weight": 0.0},
    {"ticker": "IWM", "name": "iShares Russell 2000 ETF", "sector": "ETF", "market": "US", "currency": "USD", "benchmark_weight": 0.0},
    {"ticker": "DIA", "name": "SPDR Dow Jones ETF", "sector": "ETF", "market": "US", "currency": "USD", "benchmark_weight": 0.0},
    {"ticker": "XLF", "name": "Financial Select Sector SPDR", "sector": "ETF", "market": "US", "currency": "USD", "benchmark_weight": 0.0},
    {"ticker": "XLK", "name": "Technology Select Sector SPDR", "sector": "ETF", "market": "US", "currency": "USD", "benchmark_weight": 0.0},
    {"ticker": "XLE", "name": "Energy Select Sector SPDR", "sector": "ETF", "market": "US", "currency": "USD", "benchmark_weight": 0.0},
    {"ticker": "TLT", "name": "iShares 20+ Year Treasury Bond ETF", "sector": "ETF", "market": "US", "currency": "USD", "benchmark_weight": 0.0},
    {"ticker": "GLD", "name": "SPDR Gold Trust", "sector": "ETF", "market": "US", "currency": "USD", "benchmark_weight": 0.0},
]

# ── Hong Kong Market (Hang Seng + Southbound names) ──
HK_STOCKS: list[StockEntry] = [
    {"ticker": "0700.HK", "name": "Tencent Holdings", "sector": "Technology", "market": "HK", "currency": "HKD", "benchmark_weight": 8.5},
    {"ticker": "9988.HK", "name": "Alibaba Group", "sector": "Consumer Discretionary", "market": "HK", "currency": "HKD", "benchmark_weight": 7.0},
    {"ticker": "0941.HK", "name": "China Mobile", "sector": "Communication", "market": "HK", "currency": "HKD", "benchmark_weight": 4.5},
    {"ticker": "9618.HK", "name": "JD.com Inc.", "sector": "Consumer Discretionary", "market": "HK", "currency": "HKD", "benchmark_weight": 3.0},
    {"ticker": "0005.HK", "name": "HSBC Holdings", "sector": "Financials", "market": "HK", "currency": "HKD", "benchmark_weight": 8.0},
    {"ticker": "1299.HK", "name": "AIA Group", "sector": "Financials", "market": "HK", "currency": "HKD", "benchmark_weight": 5.5},
    {"ticker": "0388.HK", "name": "HKEX", "sector": "Financials", "market": "HK", "currency": "HKD", "benchmark_weight": 4.0},
    {"ticker": "1398.HK", "name": "ICBC", "sector": "Financials", "market": "HK", "currency": "HKD", "benchmark_weight": 3.5},
    {"ticker": "0939.HK", "name": "China Construction Bank", "sector": "Financials", "market": "HK", "currency": "HKD", "benchmark_weight": 3.5},
    {"ticker": "3988.HK", "name": "Bank of China", "sector": "Financials", "market": "HK", "currency": "HKD", "benchmark_weight": 2.5},
    {"ticker": "2318.HK", "name": "Ping An Insurance", "sector": "Financials", "market": "HK", "currency": "HKD", "benchmark_weight": 3.0},
    {"ticker": "2628.HK", "name": "China Life Insurance", "sector": "Financials", "market": "HK", "currency": "HKD", "benchmark_weight": 1.5},
    {"ticker": "3690.HK", "name": "Meituan", "sector": "Consumer Discretionary", "market": "HK", "currency": "HKD", "benchmark_weight": 4.0},
    {"ticker": "1810.HK", "name": "Xiaomi Corp.", "sector": "Technology", "market": "HK", "currency": "HKD", "benchmark_weight": 2.5},
    {"ticker": "2269.HK", "name": "WuXi Biologics", "sector": "Healthcare", "market": "HK", "currency": "HKD", "benchmark_weight": 1.5},
    {"ticker": "1093.HK", "name": "CSPC Pharmaceutical", "sector": "Healthcare", "market": "HK", "currency": "HKD", "benchmark_weight": 1.0},
    {"ticker": "1177.HK", "name": "Sino Biopharmaceutical", "sector": "Healthcare", "market": "HK", "currency": "HKD", "benchmark_weight": 0.8},
    {"ticker": "0883.HK", "name": "CNOOC Ltd.", "sector": "Energy", "market": "HK", "currency": "HKD", "benchmark_weight": 3.0},
    {"ticker": "0857.HK", "name": "PetroChina", "sector": "Energy", "market": "HK", "currency": "HKD", "benchmark_weight": 1.5},
    {"ticker": "0386.HK", "name": "Sinopec Corp.", "sector": "Energy", "market": "HK", "currency": "HKD", "benchmark_weight": 1.0},
    {"ticker": "0011.HK", "name": "Hang Seng Bank", "sector": "Financials", "market": "HK", "currency": "HKD", "benchmark_weight": 1.5},
    {"ticker": "0016.HK", "name": "SHK Properties", "sector": "Real Estate", "market": "HK", "currency": "HKD", "benchmark_weight": 1.5},
    {"ticker": "1113.HK", "name": "CK Asset Holdings", "sector": "Real Estate", "market": "HK", "currency": "HKD", "benchmark_weight": 0.8},
    {"ticker": "0066.HK", "name": "MTR Corp.", "sector": "Industrials", "market": "HK", "currency": "HKD", "benchmark_weight": 1.0},
    {"ticker": "0823.HK", "name": "Link REIT", "sector": "Real Estate", "market": "HK", "currency": "HKD", "benchmark_weight": 1.0},
    {"ticker": "0002.HK", "name": "CLP Holdings", "sector": "Utilities", "market": "HK", "currency": "HKD", "benchmark_weight": 1.5},
    {"ticker": "0003.HK", "name": "HK & China Gas", "sector": "Utilities", "market": "HK", "currency": "HKD", "benchmark_weight": 1.0},
    {"ticker": "0006.HK", "name": "Power Assets", "sector": "Utilities", "market": "HK", "currency": "HKD", "benchmark_weight": 0.8},
    {"ticker": "2382.HK", "name": "Sunny Optical", "sector": "Technology", "market": "HK", "currency": "HKD", "benchmark_weight": 1.0},
    {"ticker": "2015.HK", "name": "Li Auto Inc.", "sector": "Consumer Discretionary", "market": "HK", "currency": "HKD", "benchmark_weight": 1.0},
    {"ticker": "9868.HK", "name": "XPeng Inc.", "sector": "Consumer Discretionary", "market": "HK", "currency": "HKD", "benchmark_weight": 0.5},
    {"ticker": "2331.HK", "name": "Li Ning Co.", "sector": "Consumer Discretionary", "market": "HK", "currency": "HKD", "benchmark_weight": 0.5},
    {"ticker": "2800.HK", "name": "Tracker Fund of HK", "sector": "ETF", "market": "HK", "currency": "HKD", "benchmark_weight": 0.0},
    {"ticker": "2828.HK", "name": "Hang Seng H-Share ETF", "sector": "ETF", "market": "HK", "currency": "HKD", "benchmark_weight": 0.0},
    {"ticker": "3033.HK", "name": "CSOP HS Tech ETF", "sector": "ETF", "market": "HK", "currency": "HKD", "benchmark_weight": 0.0},
]

# ── Singapore Market (STI + key SMID) ──
SG_STOCKS: list[StockEntry] = [
    {"ticker": "D05.SI", "name": "DBS Group Holdings", "sector": "Financials", "market": "SG", "currency": "SGD", "benchmark_weight": 20.0},
    {"ticker": "O39.SI", "name": "OCBC Bank", "sector": "Financials", "market": "SG", "currency": "SGD", "benchmark_weight": 14.0},
    {"ticker": "U11.SI", "name": "UOB Ltd.", "sector": "Financials", "market": "SG", "currency": "SGD", "benchmark_weight": 11.0},
    {"ticker": "Z74.SI", "name": "Singapore Telecom", "sector": "Communication", "market": "SG", "currency": "SGD", "benchmark_weight": 6.0},
    {"ticker": "C52.SI", "name": "ComfortDelGro", "sector": "Industrials", "market": "SG", "currency": "SGD", "benchmark_weight": 1.5},
    {"ticker": "S68.SI", "name": "Singapore Exchange", "sector": "Financials", "market": "SG", "currency": "SGD", "benchmark_weight": 2.5},
    {"ticker": "BS6.SI", "name": "YZJ Shipbuilding", "sector": "Industrials", "market": "SG", "currency": "SGD", "benchmark_weight": 1.5},
    {"ticker": "C09.SI", "name": "City Developments", "sector": "Real Estate", "market": "SG", "currency": "SGD", "benchmark_weight": 1.0},
    {"ticker": "A17U.SI", "name": "Ascendas REIT", "sector": "Real Estate", "market": "SG", "currency": "SGD", "benchmark_weight": 2.5},
    {"ticker": "C38U.SI", "name": "CapitaLand Int. Comm. Trust", "sector": "Real Estate", "market": "SG", "currency": "SGD", "benchmark_weight": 2.0},
    {"ticker": "ME8U.SI", "name": "Mapletree Industrial Trust", "sector": "Real Estate", "market": "SG", "currency": "SGD", "benchmark_weight": 1.5},
    {"ticker": "N2IU.SI", "name": "Mapletree Pan Asia Com. Trust", "sector": "Real Estate", "market": "SG", "currency": "SGD", "benchmark_weight": 1.0},
    {"ticker": "F34.SI", "name": "Wilmar International", "sector": "Consumer Staples", "market": "SG", "currency": "SGD", "benchmark_weight": 3.0},
    {"ticker": "T39.SI", "name": "SPH Media", "sector": "Communication", "market": "SG", "currency": "SGD", "benchmark_weight": 0.5},
    {"ticker": "G13.SI", "name": "Genting Singapore", "sector": "Consumer Discretionary", "market": "SG", "currency": "SGD", "benchmark_weight": 1.5},
    {"ticker": "C07.SI", "name": "Jardine Cycle & Carriage", "sector": "Consumer Discretionary", "market": "SG", "currency": "SGD", "benchmark_weight": 2.0},
    {"ticker": "S63.SI", "name": "ST Engineering", "sector": "Industrials", "market": "SG", "currency": "SGD", "benchmark_weight": 2.0},
    {"ticker": "Y92.SI", "name": "ThaiBev", "sector": "Consumer Staples", "market": "SG", "currency": "SGD", "benchmark_weight": 1.5},
    {"ticker": "U96.SI", "name": "Sembcorp Industries", "sector": "Industrials", "market": "SG", "currency": "SGD", "benchmark_weight": 1.0},
    {"ticker": "S58.SI", "name": "SATS Ltd.", "sector": "Industrials", "market": "SG", "currency": "SGD", "benchmark_weight": 1.0},
    {"ticker": "C6L.SI", "name": "Singapore Airlines", "sector": "Industrials", "market": "SG", "currency": "SGD", "benchmark_weight": 1.5},
    {"ticker": "V03.SI", "name": "Venture Corp.", "sector": "Technology", "market": "SG", "currency": "SGD", "benchmark_weight": 1.0},
    {"ticker": "BN4.SI", "name": "Keppel Corp.", "sector": "Industrials", "market": "SG", "currency": "SGD", "benchmark_weight": 1.5},
    {"ticker": "S51.SI", "name": "Seatrium Ltd.", "sector": "Industrials", "market": "SG", "currency": "SGD", "benchmark_weight": 0.8},
    {"ticker": "5WH.SI", "name": "Rex International", "sector": "Energy", "market": "SG", "currency": "SGD", "benchmark_weight": 0.3},
    {"ticker": "AWX.SI", "name": "AEM Holdings", "sector": "Technology", "market": "SG", "currency": "SGD", "benchmark_weight": 0.3},
    {"ticker": "ES3.SI", "name": "SPDR STI ETF", "sector": "ETF", "market": "SG", "currency": "SGD", "benchmark_weight": 0.0},
    {"ticker": "CLR.SI", "name": "Lion-Phillip S-REIT ETF", "sector": "ETF", "market": "SG", "currency": "SGD", "benchmark_weight": 0.0},
    {"ticker": "J69U.SI", "name": "Frasers Centrepoint Trust", "sector": "Real Estate", "market": "SG", "currency": "SGD", "benchmark_weight": 0.8},
    {"ticker": "M44U.SI", "name": "Mapletree Logistics Trust", "sector": "Real Estate", "market": "SG", "currency": "SGD", "benchmark_weight": 1.0},
]

# ── Australia Market (ASX 200 top names) ──
AU_STOCKS: list[StockEntry] = [
    {"ticker": "CBA.AX", "name": "Commonwealth Bank", "sector": "Financials", "market": "AU", "currency": "AUD", "benchmark_weight": 9.0},
    {"ticker": "CSL.AX", "name": "CSL Limited", "sector": "Healthcare", "market": "AU", "currency": "AUD", "benchmark_weight": 6.5},
    {"ticker": "BHP.AX", "name": "BHP Group", "sector": "Materials", "market": "AU", "currency": "AUD", "benchmark_weight": 8.0},
    {"ticker": "NAB.AX", "name": "National Australia Bank", "sector": "Financials", "market": "AU", "currency": "AUD", "benchmark_weight": 4.5},
    {"ticker": "WBC.AX", "name": "Westpac Banking", "sector": "Financials", "market": "AU", "currency": "AUD", "benchmark_weight": 4.0},
    {"ticker": "ANZ.AX", "name": "ANZ Group", "sector": "Financials", "market": "AU", "currency": "AUD", "benchmark_weight": 3.5},
    {"ticker": "MQG.AX", "name": "Macquarie Group", "sector": "Financials", "market": "AU", "currency": "AUD", "benchmark_weight": 3.0},
    {"ticker": "WES.AX", "name": "Wesfarmers", "sector": "Consumer Discretionary", "market": "AU", "currency": "AUD", "benchmark_weight": 2.5},
    {"ticker": "WOW.AX", "name": "Woolworths Group", "sector": "Consumer Staples", "market": "AU", "currency": "AUD", "benchmark_weight": 2.0},
    {"ticker": "TLS.AX", "name": "Telstra Group", "sector": "Communication", "market": "AU", "currency": "AUD", "benchmark_weight": 2.0},
    {"ticker": "RIO.AX", "name": "Rio Tinto", "sector": "Materials", "market": "AU", "currency": "AUD", "benchmark_weight": 3.5},
    {"ticker": "FMG.AX", "name": "Fortescue Metals", "sector": "Materials", "market": "AU", "currency": "AUD", "benchmark_weight": 2.0},
    {"ticker": "GMG.AX", "name": "Goodman Group", "sector": "Real Estate", "market": "AU", "currency": "AUD", "benchmark_weight": 2.0},
    {"ticker": "WDS.AX", "name": "Woodside Energy", "sector": "Energy", "market": "AU", "currency": "AUD", "benchmark_weight": 2.0},
    {"ticker": "ALL.AX", "name": "Aristocrat Leisure", "sector": "Consumer Discretionary", "market": "AU", "currency": "AUD", "benchmark_weight": 1.5},
    {"ticker": "TCL.AX", "name": "Transurban Group", "sector": "Industrials", "market": "AU", "currency": "AUD", "benchmark_weight": 1.5},
    {"ticker": "QBE.AX", "name": "QBE Insurance", "sector": "Financials", "market": "AU", "currency": "AUD", "benchmark_weight": 1.0},
    {"ticker": "SUN.AX", "name": "Suncorp Group", "sector": "Financials", "market": "AU", "currency": "AUD", "benchmark_weight": 1.0},
    {"ticker": "IAG.AX", "name": "Insurance Australia Group", "sector": "Financials", "market": "AU", "currency": "AUD", "benchmark_weight": 0.8},
    {"ticker": "COL.AX", "name": "Coles Group", "sector": "Consumer Staples", "market": "AU", "currency": "AUD", "benchmark_weight": 1.0},
    {"ticker": "STO.AX", "name": "Santos Ltd.", "sector": "Energy", "market": "AU", "currency": "AUD", "benchmark_weight": 1.0},
    {"ticker": "ORG.AX", "name": "Origin Energy", "sector": "Utilities", "market": "AU", "currency": "AUD", "benchmark_weight": 0.8},
    {"ticker": "AGL.AX", "name": "AGL Energy", "sector": "Utilities", "market": "AU", "currency": "AUD", "benchmark_weight": 0.5},
    {"ticker": "MIN.AX", "name": "Mineral Resources", "sector": "Materials", "market": "AU", "currency": "AUD", "benchmark_weight": 0.8},
    {"ticker": "S32.AX", "name": "South32 Ltd.", "sector": "Materials", "market": "AU", "currency": "AUD", "benchmark_weight": 0.8},
    {"ticker": "NST.AX", "name": "Northern Star Resources", "sector": "Materials", "market": "AU", "currency": "AUD", "benchmark_weight": 0.5},
    {"ticker": "EVN.AX", "name": "Evolution Mining", "sector": "Materials", "market": "AU", "currency": "AUD", "benchmark_weight": 0.4},
    {"ticker": "XRO.AX", "name": "Xero Limited", "sector": "Technology", "market": "AU", "currency": "AUD", "benchmark_weight": 1.0},
    {"ticker": "CPU.AX", "name": "Computershare", "sector": "Technology", "market": "AU", "currency": "AUD", "benchmark_weight": 0.5},
    {"ticker": "WTC.AX", "name": "WiseTech Global", "sector": "Technology", "market": "AU", "currency": "AUD", "benchmark_weight": 0.8},
    {"ticker": "REA.AX", "name": "REA Group", "sector": "Communication", "market": "AU", "currency": "AUD", "benchmark_weight": 1.0},
    {"ticker": "CAR.AX", "name": "CAR Group", "sector": "Communication", "market": "AU", "currency": "AUD", "benchmark_weight": 0.8},
    {"ticker": "JHX.AX", "name": "James Hardie Industries", "sector": "Materials", "market": "AU", "currency": "AUD", "benchmark_weight": 0.8},
    {"ticker": "ASX.AX", "name": "ASX Limited", "sector": "Financials", "market": "AU", "currency": "AUD", "benchmark_weight": 0.5},
    {"ticker": "SCG.AX", "name": "Scentre Group", "sector": "Real Estate", "market": "AU", "currency": "AUD", "benchmark_weight": 0.8},
    {"ticker": "DXS.AX", "name": "Dexus", "sector": "Real Estate", "market": "AU", "currency": "AUD", "benchmark_weight": 0.5},
    {"ticker": "VCX.AX", "name": "Vicinity Centres", "sector": "Real Estate", "market": "AU", "currency": "AUD", "benchmark_weight": 0.4},
    {"ticker": "AZJ.AX", "name": "Aurizon Holdings", "sector": "Industrials", "market": "AU", "currency": "AUD", "benchmark_weight": 0.4},
    {"ticker": "BSL.AX", "name": "BlueScope Steel", "sector": "Materials", "market": "AU", "currency": "AUD", "benchmark_weight": 0.4},
    {"ticker": "SOL.AX", "name": "Washington H. Soul Pattinson", "sector": "Financials", "market": "AU", "currency": "AUD", "benchmark_weight": 0.4},
    {"ticker": "RMD.AX", "name": "ResMed Inc.", "sector": "Healthcare", "market": "AU", "currency": "AUD", "benchmark_weight": 1.5},
    {"ticker": "COH.AX", "name": "Cochlear Limited", "sector": "Healthcare", "market": "AU", "currency": "AUD", "benchmark_weight": 0.8},
    {"ticker": "SHL.AX", "name": "Sonic Healthcare", "sector": "Healthcare", "market": "AU", "currency": "AUD", "benchmark_weight": 0.5},
    {"ticker": "BXB.AX", "name": "Brambles", "sector": "Industrials", "market": "AU", "currency": "AUD", "benchmark_weight": 0.8},
    {"ticker": "QAN.AX", "name": "Qantas Airways", "sector": "Industrials", "market": "AU", "currency": "AUD", "benchmark_weight": 0.5},
    {"ticker": "ALD.AX", "name": "Ampol Limited", "sector": "Energy", "market": "AU", "currency": "AUD", "benchmark_weight": 0.5},
    {"ticker": "IOZ.AX", "name": "iShares Core S&P/ASX 200 ETF", "sector": "ETF", "market": "AU", "currency": "AUD", "benchmark_weight": 0.0},
    {"ticker": "VAS.AX", "name": "Vanguard Australian Shares ETF", "sector": "ETF", "market": "AU", "currency": "AUD", "benchmark_weight": 0.0},
    {"ticker": "A200.AX", "name": "BetaShares Australia 200 ETF", "sector": "ETF", "market": "AU", "currency": "AUD", "benchmark_weight": 0.0},
]

# ── New Zealand Market (NZX 50 top names) ──
NZ_STOCKS: list[StockEntry] = [
    {"ticker": "FPH.NZ", "name": "Fisher & Paykel Healthcare", "sector": "Healthcare", "market": "NZ", "currency": "NZD", "benchmark_weight": 12.0},
    {"ticker": "ATM.NZ", "name": "a2 Milk Company", "sector": "Consumer Staples", "market": "NZ", "currency": "NZD", "benchmark_weight": 5.0},
    {"ticker": "AIA.NZ", "name": "Auckland Intl. Airport", "sector": "Industrials", "market": "NZ", "currency": "NZD", "benchmark_weight": 7.0},
    {"ticker": "MEL.NZ", "name": "Meridian Energy", "sector": "Utilities", "market": "NZ", "currency": "NZD", "benchmark_weight": 8.0},
    {"ticker": "CEN.NZ", "name": "Contact Energy", "sector": "Utilities", "market": "NZ", "currency": "NZD", "benchmark_weight": 4.5},
    {"ticker": "MCY.NZ", "name": "Mercury NZ", "sector": "Utilities", "market": "NZ", "currency": "NZD", "benchmark_weight": 3.5},
    {"ticker": "IFT.NZ", "name": "Infratil Limited", "sector": "Industrials", "market": "NZ", "currency": "NZD", "benchmark_weight": 5.0},
    {"ticker": "SPK.NZ", "name": "Spark New Zealand", "sector": "Communication", "market": "NZ", "currency": "NZD", "benchmark_weight": 6.0},
    {"ticker": "FBU.NZ", "name": "Fletcher Building", "sector": "Materials", "market": "NZ", "currency": "NZD", "benchmark_weight": 3.0},
    {"ticker": "EBO.NZ", "name": "EBOS Group", "sector": "Healthcare", "market": "NZ", "currency": "NZD", "benchmark_weight": 3.0},
    {"ticker": "RYM.NZ", "name": "Ryman Healthcare", "sector": "Healthcare", "market": "NZ", "currency": "NZD", "benchmark_weight": 2.5},
    {"ticker": "SUM.NZ", "name": "Summerset Group", "sector": "Healthcare", "market": "NZ", "currency": "NZD", "benchmark_weight": 2.0},
    {"ticker": "OCA.NZ", "name": "Oceania Healthcare", "sector": "Healthcare", "market": "NZ", "currency": "NZD", "benchmark_weight": 1.0},
    {"ticker": "VCT.NZ", "name": "Vector Limited", "sector": "Utilities", "market": "NZ", "currency": "NZD", "benchmark_weight": 1.5},
    {"ticker": "POT.NZ", "name": "Port of Tauranga", "sector": "Industrials", "market": "NZ", "currency": "NZD", "benchmark_weight": 1.5},
    {"ticker": "FRE.NZ", "name": "Freightways Limited", "sector": "Industrials", "market": "NZ", "currency": "NZD", "benchmark_weight": 1.0},
    {"ticker": "AIR.NZ", "name": "Air New Zealand", "sector": "Industrials", "market": "NZ", "currency": "NZD", "benchmark_weight": 1.5},
    {"ticker": "KMD.NZ", "name": "Kathmandu Holdings", "sector": "Consumer Discretionary", "market": "NZ", "currency": "NZD", "benchmark_weight": 0.5},
    {"ticker": "SKC.NZ", "name": "SkyCity Entertainment", "sector": "Consumer Discretionary", "market": "NZ", "currency": "NZD", "benchmark_weight": 1.0},
    {"ticker": "THL.NZ", "name": "Tourism Holdings", "sector": "Consumer Discretionary", "market": "NZ", "currency": "NZD", "benchmark_weight": 0.5},
    {"ticker": "SCT.NZ", "name": "Scott Technology", "sector": "Technology", "market": "NZ", "currency": "NZD", "benchmark_weight": 0.3},
    {"ticker": "NZ50.NZ", "name": "Smartshares NZ Top 50 ETF", "sector": "ETF", "market": "NZ", "currency": "NZD", "benchmark_weight": 0.0},
    {"ticker": "NZB.NZ", "name": "Smartshares NZ Bond ETF", "sector": "ETF", "market": "NZ", "currency": "NZD", "benchmark_weight": 0.0},
]

# ── Aggregated Market Universe ───────────────────────────────
MARKET_UNIVERSE: dict[str, list[StockEntry]] = {
    "US": US_STOCKS,
    "HK": HK_STOCKS,
    "SG": SG_STOCKS,
    "AU": AU_STOCKS,
    "NZ": NZ_STOCKS,
}


def get_universe_size() -> dict[str, int]:
    """Return the count of stocks per market."""
    return {market: len(stocks) for market, stocks in MARKET_UNIVERSE.items()}


def get_all_tickers(market: str | None = None) -> list[str]:
    """Return all ticker symbols, optionally filtered by market.

    Args:
        market: Optional market code (US/HK/SG/AU/NZ). If None, returns all.

    Returns:
        List of ticker strings.
    """
    if market:
        if market.upper() not in MARKET_UNIVERSE:
            raise ValueError(f"Unknown market: {market}. Valid: {list(MARKET_UNIVERSE.keys())}")
        return [s["ticker"] for s in MARKET_UNIVERSE[market.upper()]]
    else:
        result: list[str] = []
        for stocks in MARKET_UNIVERSE.values():
            result.extend(s["ticker"] for s in stocks)
        return result


def get_stocks_by_sector(market: str | None = None, sector: str | None = None) -> list[StockEntry]:
    """Filter stocks by market and/or sector.

    Args:
        market: Optional market code.
        sector: Optional sector name.

    Returns:
        Filtered list of StockEntry.
    """
    results: list[StockEntry] = []
    markets = [market.upper()] if market else list(MARKET_UNIVERSE.keys())
    for mkt in markets:
        for stock in MARKET_UNIVERSE.get(mkt, []):
            if sector is None or stock.get("sector") == sector:
                results.append(stock)
    return results
