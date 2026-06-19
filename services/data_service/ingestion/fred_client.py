"""services/data_service/ingestion/fred_client.py – FRED API macro data client.

Fetches macro-economic indicators:
- Interest rates (FEDFUNDS, DGS10, DGS2)
- CPI (CPIAUCSL)
- GDP (GDP)
- Unemployment (UNRATE)
- Industrial Production (INDPRO)
"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from typing import Optional

import pandas as pd
from loguru import logger

from configs.settings import settings
from shared.core.exceptions import DataFetchError

# Standard FRED series for macro factor construction
FRED_SERIES: dict[str, str] = {
    "fed_funds_rate": "FEDFUNDS",       # Federal Funds Rate
    "treasury_10y": "DGS10",            # 10-Year Treasury Yield
    "treasury_2y": "DGS2",              # 2-Year Treasury Yield
    "treasury_spread_10y2y": "T10Y2Y",  # 10Y-2Y Spread
    "cpi": "CPIAUCSL",                  # Consumer Price Index
    "core_cpi": "CPILFESL",             # Core CPI
    "gdp": "GDP",                       # Gross Domestic Product
    "unemployment": "UNRATE",           # Unemployment Rate
    "industrial_production": "INDPRO",  # Industrial Production Index
    "retail_sales": "RSXFS",            # Retail Sales
    "housing_starts": "HOUST",          # Housing Starts
    "vix": "VIXCLS",                    # VIX (CBOE)
    "m2_money_supply": "M2SL",          # M2 Money Supply
    "nonfarm_payrolls": "PAYEMS",       # Nonfarm Payrolls
}


class FREDClient:
    """FRED API client for macro-economic data.

    Rate-limited and cached. API key from settings.
    """

    def __init__(self, api_key: str = "") -> None:
        self._api_key = api_key or settings.WIND_API_KEY or ""
        self._base_url = "https://api.stlouisfed.org/fred/series/observations"
        self._cache: dict[str, pd.DataFrame] = {}

    @property
    def is_available(self) -> bool:
        """Check if FRED client has an API key."""
        return bool(self._api_key)

    async def fetch_series(
        self,
        series_id: str,
        start: date | None = None,
        end: date | None = None,
    ) -> Optional[pd.DataFrame]:
        """Fetch a single FRED series.

        Args:
            series_id: FRED series ID (e.g. 'DGS10').
            start: Start date.
            end: End date.

        Returns:
            DataFrame with 'date' and 'value' columns, or None.
        """
        if not self.is_available:
            logger.debug(f"FRED not configured — skipping {series_id}")
            return None

        cache_key = f"{series_id}:{start}:{end}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        start = start or date.today() - timedelta(days=365 * 10)
        end = end or date.today()

        params = {
            "series_id": series_id,
            "api_key": self._api_key,
            "file_type": "json",
            "observation_start": start.isoformat(),
            "observation_end": end.isoformat(),
        }

        try:
            import httpx

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(self._base_url, params=params)
                response.raise_for_status()
                data = response.json()

            observations = data.get("observations", [])
            if not observations:
                return None

            records = [
                {"date": obs["date"], "value": float(obs["value"]) if obs["value"] != "." else None}
                for obs in observations
            ]
            df = pd.DataFrame(records)
            df["date"] = pd.to_datetime(df["date"])
            df = df.set_index("date")
            df = df.rename(columns={"value": series_id.lower()})

            self._cache[cache_key] = df
            logger.info(f"FRED: fetched {len(df)} obs for {series_id}")
            return df

        except ImportError:
            logger.debug("httpx not available for FRED")
            return None
        except Exception as e:
            logger.warning(f"FRED fetch failed for {series_id}: {e}")
            return None

    async def fetch_macro_snapshot(self) -> dict[str, float]:
        """Fetch latest values for all key macro indicators.

        Returns:
            Dictionary mapping indicator name → latest value.
        """
        snapshot: dict[str, float] = {}
        for name, series_id in FRED_SERIES.items():
            df = await self.fetch_series(series_id, start=date.today() - timedelta(days=365))
            if df is not None and not df.empty:
                col = series_id.lower()
                latest = df[col].dropna()
                if not latest.empty:
                    snapshot[name] = float(latest.iloc[-1])
        return snapshot

    async def fetch_yield_curve(self) -> Optional[pd.DataFrame]:
        """Fetch yield curve data (2Y, 5Y, 10Y, 30Y).

        Returns:
            DataFrame with columns for each maturity.
        """
        maturities = {
            "2y": "DGS2",
            "5y": "DGS5",
            "10y": "DGS10",
            "30y": "DGS30",
        }
        dfs = {}
        for name, series_id in maturities.items():
            df = await self.fetch_series(series_id, start=date.today() - timedelta(days=365 * 2))
            if df is not None and not df.empty:
                dfs[name] = df

        if not dfs:
            return None

        combined = pd.concat(dfs.values(), axis=1)
        combined.columns = list(dfs.keys())
        return combined
