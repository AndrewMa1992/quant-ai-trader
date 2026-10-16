"""services/data_service/api/routes.py – REST API routes for the data service.

Endpoints:
- GET /bars – Daily OHLCV bars for a ticker/date range
- GET /minute_bars – Intraday minute bars
- GET /ticker_info – Ticker reference data
- GET /universe – Market universe listing
- GET /market_status – Current market open/close status
- POST /ingest – Trigger data ingestion for ticker(s)
- GET /quote/{ticker} – Real-time quote from latest bar
- GET /stored-tickers – List all tickers with cached data
- GET /storage-stats – Parquet storage statistics
"""

from __future__ import annotations

from datetime import date, timedelta, datetime
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from loguru import logger
from pydantic import BaseModel, Field

from configs.market_universe import MARKET_UNIVERSE, get_all_tickers, get_stocks_by_sector
from configs.settings import settings
from services.data_service.ingestion.yfinance_client import YFinanceClient
from services.data_service.ingestion.china_adapter import ChinaDataAdapter
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
    start_date: str | None = Query(default=None, description="Start date (YYYY-MM-DD)"),
    end_date: str | None = Query(default=None, description="End date (YYYY-MM-DD)"),
) -> APIResponse:
    """Retrieve daily OHLCV bars for a ticker.

    Returns cached data from Parquet store. Falls back to yfinance if not cached.
    When start_date is omitted, the last two years are returned.
    """
    log = get_logger(__name__)
    try:
        if not start_date:
            start_date = (date.today() - timedelta(days=730)).isoformat()
        s_date = date.fromisoformat(start_date)
        e_date = date.fromisoformat(end_date) if end_date else date.today()

        # Try Parquet store first
        df = store.read_daily(ticker, s_date, e_date)

        if df is None or df.empty:
            log.info(f"No cached data for {ticker}, fetching from yfinance")
            df = await yf_client.fetch_daily(ticker, s_date, e_date)

            # China A-share fallback: if yfinance returns nothing and ticker
            # looks like a Chinese stock, try Eastmoney → Tencent chain
            if (df is None or df.empty) and ChinaDataAdapter.is_china_ticker(ticker):
                log.info(f"yfinance returned no data for {ticker}, trying China adapters")
                adapter = ChinaDataAdapter()
                df = await adapter.fetch_history_async(ticker, s_date, e_date)

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


# ── P2-1: Real-time Quote ────────────────────────────────────
@router.get("/quote/{ticker}")
async def get_quote(ticker: str) -> APIResponse:
    """Retrieve the latest bar as a real-time quote for a ticker.

    Reads the most recent daily bar from the Parquet store and returns
    close price, change percentage, volume, and timestamp.
    """
    log = get_logger(__name__)
    try:
        df = store.read_daily(ticker)
        if df is None or df.empty:
            return APIResponse(
                success=True,
                message=f"No data available for {ticker}",
                data={"ticker": ticker, "available": False},
            )

        latest = df.iloc[-1]
        close_val = float(latest.get("close", 0))
        open_val = float(latest.get("open", close_val))
        change_pct = ((close_val - open_val) / open_val * 100) if open_val > 0 else 0.0
        vol = float(latest.get("volume", 0))

        # Determine timestamp from index or column
        if isinstance(df.index[-1], (date, datetime)):
            ts = df.index[-1]
        else:
            ts = latest.get("date", latest.name)

        return APIResponse(
            success=True,
            message=f"Quote for {ticker}",
            data={
                "ticker": ticker,
                "close": round(close_val, 4),
                "change_pct": round(change_pct, 4),
                "volume": int(vol),
                "time": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
                "available": True,
            },
        )
    except Exception as e:
        log.exception(f"Failed to get quote for {ticker}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── P2-3: Stored Tickers ─────────────────────────────────────
@router.get("/stored-tickers")
async def stored_tickers() -> APIResponse:
    """List all tickers that have cached data in the Parquet store.

    Scans the ``data/parquet/daily/`` directory for .parquet files.
    """
    try:
        tickers = store.list_tickers()
        return APIResponse(
            success=True,
            message=f"{len(tickers)} tickers with stored data",
            data={"count": len(tickers), "tickers": tickers},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── P2-3: Storage Statistics ──────────────────────────────────
@router.get("/storage-stats")
async def storage_stats() -> APIResponse:
    """Return storage statistics for the Parquet data store.

    Includes total ticker count, date range coverage, file counts, and disk usage.
    """
    try:
        stats = store.get_storage_stats()
        tickers = store.list_tickers()

        # Compute overall date range across all tickers
        oldest: date | None = None
        newest: date | None = None
        for t in tickers:
            dr = store.get_date_range(t)
            if dr is None:
                continue
            if oldest is None or dr[0] < oldest:
                oldest = dr[0]
            if newest is None or dr[1] > newest:
                newest = dr[1]

        return APIResponse(
            success=True,
            message="Storage statistics",
            data={
                "total_tickers": len(tickers),
                "oldest_date": oldest.isoformat() if oldest else None,
                "newest_date": newest.isoformat() if newest else None,
                "total_files": stats["daily_files"] + stats["minute_files"],
                "size_mb": stats["total_size_mb"],
                "daily_files": stats["daily_files"],
                "minute_files": stats["minute_files"],
            },
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
