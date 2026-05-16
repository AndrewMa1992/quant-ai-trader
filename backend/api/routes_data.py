"""
数据接口路由
"""
from typing import List, Optional
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
    include_features: bool = Query(False, description="是否包含特征工程"),
):
    """获取历史K线数据"""
    df = market_data.get_historical_data(ticker, period, interval)

    if df.empty:
        return {"error": f"无法获取 {ticker} 的数据"}

    if include_features:
        df = data_pipeline.process(df)

    # 转前端友好格式
    records = df.reset_index().to_dict(orient="records")

    # 日期格式化
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
    """获取实时报价"""
    quote = market_data.get_realtime_quote(ticker)
    if quote is None:
        return {"error": f"无法获取 {ticker} 报价"}
    return quote


@router.get("/tickers")
async def get_tickers():
    """获取关注的所有股票列表（美股 + 港股）"""
    from backend.config import data_config
    info = data_config.TICKER_INFO
    us = data_config.US_TICKERS
    hk = [t.replace(".HK", "") for t in data_config.ALL_TICKERS if ".HK" in t]
    return {
        "all": info,
        "us_tickers": us,
        "hk_tickers": hk,
        "count": len(info),
    }


@router.get("/market-status")
async def get_market_status():
    """获取市场状态"""
    return market_data.get_market_status()


@router.get("/stored-tickers")
async def get_stored_tickers():
    """获取已存储的 ticker"""
    return {"tickers": store.get_all_tickers()}


@router.get("/storage-stats")
async def get_storage_stats():
    """获取存储统计"""
    return store.get_storage_stats()
