"""services/data_service/api/routes.py – REST API routes for the data service.

Endpoints:
- GET /bars – Daily OHLCV bars for a ticker/date range
- GET /minute_bars – Intraday minute bars
- GET /ticker_info – Ticker reference data
- GET /universe – Market universe listing
- GET /market_status – Current market open/close status
- POST /ingest – Trigger data ingestion for ticker(s)
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from loguru import logger
from pydantic import BaseModel, Field

from configs.market_universe import MARKET_UNIVERSE, get_all_tickers, get_stocks_by_sector
from configs.settings import settings
from services.data_service.ingestion.yfinance_client import YFinanceClient
from services.data_service.storage.parquet_store import ParquetStore
from shared.core.exceptions import DataError, DataFetchError, DataValidationError
from shared.core.logger import get_logger
from shared.schema import APIResponse

router = APIRouter()
store = ParquetStore()
yf_client = YFinanceClient()


class IngestRequest(BaseModel):
    """Request body for triggering data ingestion."""
    tickers: list[str] = Field(..., description="List of ticker symbols to ingest")
    start_date: str | None = Field(default=None, description="Start date (YYYY-MM-DD)")
    end_date: str | None = Field(default=None, description="End date (YYYY-MM-DD)")
    interval: str = Field(default="1d", description="Interval: 1d, 1wk, 1mo")


class BarsQuery(BaseModel):
    """Query parameters for bar data retrieval."""
    ticker: str = Field(..., description="Ticker symbol")
    start_date: str = Field(..., description="Start date (YYYY-MM-DD)")
    end_date: str | None = Field(default=None, description="End date (YYYY-MM-DD)")


@router.get("/bars")
async def get_daily_bars(
    ticker: str = Query(..., description="Ticker symbol"),
    start_date: str = Query(..., description="Start date (YYYY-MM-DD)"),
    end_date: str | None = Query(default=None, description="End date (YYYY-MM-DD)"),
) -> APIResponse:
    """Retrieve daily OHLCV bars for a ticker.

    Returns cached data from Parquet store. Falls back to yfinance if not cached.
    """
    log = get_logger(__name__)
    try:
        s_date = date.fromisoformat(start_date)
        e_date = date.fromisoformat(end_date) if end_date else date.today()

        # Try Parquet store first
        df = store.read_daily(ticker, s_date, e_date)

        if df is None or df.empty:
            log.info(f"No cached data for {ticker}, fetching from yfinance")
            df = await yf_client.fetch_daily(ticker, s_date, e_date)
            if df is not None and not df.empty:
                store.write_daily(ticker, df)

        if df is None or df.empty:
            return APIResponse(
                success=True,
                message=f"No data available for {ticker}",
                data={"ticker": ticker, "bars": []},
            )

        bars = df.reset_index().to_dict(orient="records")
        # Convert timestamps to ISO strings
        for bar in bars:
            for k, v in bar.items():
                if isinstance(v, (date, datetime)):
                    bar[k] = v.isoformat()
                elif hasattr(v, "isoformat"):
                    bar[k] = str(v)

        return APIResponse(
            success=True,
            message=f"Retrieved {len(bars)} bars for {ticker}",
            data={"ticker": ticker, "count": len(bars), "bars": bars},
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except DataError as e:
        raise HTTPException(status_code=e.status_code, detail=e.to_dict())
    except Exception as e:
        log.exception(f"Failed to fetch bars for {ticker}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/minute_bars")
async def get_minute_bars(
    ticker: str = Query(..., description="Ticker symbol"),
    date_str: str = Query(..., description="Date (YYYY-MM-DD)"),
) -> APIResponse:
    """Retrieve intraday minute bars for a ticker on a specific date."""
    log = get_logger(__name__)
    try:
        q_date = date.fromisoformat(date_str)
        df = store.read_minute(ticker, q_date)

        if df is None or df.empty:
            return APIResponse(
                success=True,
                message=f"No minute data for {ticker} on {date_str}",
                data={"ticker": ticker, "date": date_str, "bars": []},
            )

        bars = df.reset_index().to_dict(orient="records")
        for bar in bars:
            for k, v in bar.items():
                if isinstance(v, (date, datetime)):
                    bar[k] = v.isoformat()
                elif hasattr(v, "isoformat"):
                    bar[k] = str(v)

        return APIResponse(
            success=True,
            message=f"Retrieved {len(bars)} minute bars for {ticker}",
            data={"ticker": ticker, "date": date_str, "count": len(bars), "bars": bars},
        )
    except DataError as e:
        raise HTTPException(status_code=e.status_code, detail=e.to_dict())
    except Exception as e:
        log.exception(f"Failed to fetch minute bars: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ticker_info")
async def get_ticker_info(
    ticker: str = Query(..., description="Ticker symbol"),
) -> APIResponse:
    """Retrieve reference information for a ticker."""
    try:
        all_stocks = MARKET_UNIVERSE
        for market, stocks in all_stocks.items():
            for stock in stocks:
                if stock["ticker"].upper() == ticker.upper():
                    return APIResponse(
                        success=True,
                        message=f"Found {ticker}",
                        data=dict(stock),
                    )
        return APIResponse(
            success=True,
            message=f"Ticker {ticker} not found in universe",
            data=None,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/universe")
async def get_universe(
    market: str | None = Query(default=None, description="Filter by market (US/HK/SG/AU/NZ)"),
    sector: str | None = Query(default=None, description="Filter by sector"),
) -> APIResponse:
    """List the market universe."""
    try:
        if market or sector:
            stocks = get_stocks_by_sector(market=market, sector=sector)
        else:
            stocks = []
            for mkt_stocks in MARKET_UNIVERSE.values():
                stocks.extend(mkt_stocks)

        return APIResponse(
            success=True,
            message=f"Returned {len(stocks)} stocks",
            data={
                "count": len(stocks),
                "markets": {m: len(s) for m, s in MARKET_UNIVERSE.items()},
                "stocks": stocks,
            },
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/market_status")
async def get_market_status() -> APIResponse:
    """Return current market open/close status for all markets."""
    from shared.core.datetime_utils import MarketTimeHelper, MARKET_TIMEZONES

    statuses = {}
    for market in ["US", "HK", "SG", "AU", "NZ"]:
        try:
            helper = MarketTimeHelper(market)
            is_open = helper.is_market_open()
            seconds_to_open = helper.time_to_open() if not is_open else 0.0
            seconds_to_close = helper.time_to_close() if is_open else 0.0
            statuses[market] = {
                "is_open": is_open,
                "seconds_to_open": round(seconds_to_open, 0),
                "seconds_to_close": round(seconds_to_close, 0),
            }
        except Exception:
            statuses[market] = {"is_open": False, "error": "Timezone lookup failed"}

    return APIResponse(
        success=True,
        message="Market status retrieved",
        data=statuses,
    )


@router.post("/ingest")
async def ingest_data(
    req: IngestRequest,
    background_tasks: BackgroundTasks,
) -> APIResponse:
    """Trigger data ingestion for specified tickers.

    Processing runs in the background via BackgroundTasks.
    """
    log = get_logger(__name__)
    tickers = req.tickers or get_all_tickers()

    async def _ingest():
        success_count = 0
        fail_count = 0
        for i, ticker in enumerate(tickers):
            try:
                s = date.fromisoformat(req.start_date) if req.start_date else None
                e = date.fromisoformat(req.end_date) if req.end_date else None

                df = await yf_client.fetch_daily(ticker, s, e)
                if df is not None and not df.empty:
                    store.write_daily(ticker, df)
                    success_count += 1
                    log.info(f"[{i+1}/{len(tickers)}] Ingested {ticker}: {len(df)} bars")
                else:
                    fail_count += 1
                    log.warning(f"[{i+1}/{len(tickers)}] No data for {ticker}")
            except Exception as e:
                fail_count += 1
                log.error(f"[{i+1}/{len(tickers)}] Failed {ticker}: {e}")

        log.info(f"Ingestion complete: {success_count} succeeded, {fail_count} failed")

    background_tasks.add_task(_ingest)

    return APIResponse(
        success=True,
        message=f"Ingestion started for {len(tickers)} tickers",
        data={"ticker_count": len(tickers)},
    )
