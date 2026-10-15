"""
Market data API routes.
"""
from typing import List
from fastapi import APIRouter, Query
from pydantic import BaseModel

from backend.data_engine import MarketDataEngine, DataPipeline
from backend.data_engine.historical_store import HistoricalStore

router = APIRouter(prefix="/api/data", tags=["market-data"])
market_data = MarketDataEngine()
data_pipeline = DataPipeline()
store = HistoricalStore()


class MarketDataResponse(BaseModel):
    ticker: str
    period: str
    interval: str
    rows: int
    columns: List[str]
    start_date: str
    end_date: str
    sample: dict


@router.get("/history/{ticker}")
async def get_history(
    ticker: str,
    period: str = Query("1y", description="1d/5d/1mo/3mo/6mo/1y/2y/5y/10y"),
    interval: str = Query("1d", description="1m/5m/15m/30m/1h/1d/1wk/1mo"),
    include_features: bool = Query(False, description="Include engineered features"),
):
    """Return historical OHLCV data."""
    df = market_data.get_historical_data(ticker, period, interval)

    if df.empty:
        return {"error": f"Unable to fetch data for {ticker}"}

    if include_features:
        df = data_pipeline.process(df)

    # Frontend-friendly records
    records = df.reset_index().to_dict(orient="records")

    # Format timestamps
    for r in records:
        ts = r.get("timestamp")
        if hasattr(ts, "isoformat"):
            r["timestamp"] = ts.isoformat()
        elif hasattr(ts, "strftime"):
            r["timestamp"] = str(ts)

    return {
        "ticker": ticker,
        "period": period,
        "interval": interval,
        "rows": len(records),
        "columns": [c for c in df.columns if c != "ticker"],
        "data": records,
        "features_included": include_features,
    }


@router.get("/quote/{ticker}")
async def get_quote(ticker: str):
    """Return a live quote."""
    quote = market_data.get_realtime_quote(ticker)
    if quote is None:
        return {"error": f"Unable to fetch quote for {ticker}"}
    return quote


@router.get("/tickers")
async def get_tickers():
    """Return the full ticker universe (5 markets)."""
    import json
    from pathlib import Path

    # Read cache file directly to avoid singleton-init timing issues
    cache_file = Path(__file__).parent.parent.parent / "backend" / "data" / "stock_universe.json"

    us, hk, sg, au, nz = [], [], [], [], []
    all_info = []

    if cache_file.exists():
        try:
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            stocks = data.get("stocks", [])
            for s in stocks:
                if not isinstance(s, dict):
                    continue
                t = s.get("ticker", "")
                info = {
                    "symbol": t,
                    "name": s.get("name", ""),
                    "market": s.get("sector", "US"),
                    "currency": "USD",
                }
                all_info.append(info)

                if t.endswith(".HK"):
                    hk.append(t.replace(".HK", ""))
                elif t.endswith(".SI"):
                    sg.append(t)
                elif t.endswith(".AX"):
                    au.append(t)
                elif t.endswith(".NZ"):
                    nz.append(t)
                else:
                    us.append(t)

        except Exception as e:
            pass

    # Fallback
    if not us:
        from configs.settings import settings
        us = settings.data_us_tickers_list
        hk = settings.data_hk_tickers_list

    return {
        "all": all_info,
        "us_tickers": us,
        "hk_tickers": hk,
        "sg_tickers": sg,
        "au_tickers": au,
        "nz_tickers": nz,
        "count": len(all_info),
    }


@router.get("/market-status")
async def get_market_status():
    """Return market status."""
    return market_data.get_market_status()


@router.get("/stored-tickers")
async def get_stored_tickers():
    """Return tickers already stored locally."""
    return {"tickers": store.get_all_tickers()}


@router.get("/storage-stats")
async def get_storage_stats():
    """Return storage statistics."""
    return store.get_storage_stats()
