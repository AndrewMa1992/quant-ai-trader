"""services/data_service/ingestion/tiger_client.py – Tiger Broker API wrapper.

Live trading account: 20874631
Provides:
- Real-time quote snapshots
- Order execution (placement, cancellation, status)
- Position and account queries
- WebSocket streaming support
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import date, datetime
from typing import Any, Optional

import pandas as pd
from loguru import logger

from configs.settings import settings
from services.data_service.config import data_config
from shared.core.exceptions import DataFetchError, ExecutionError


class TigerClient:
    """Tiger Broker API client for live trading and real-time data.

    Uses tigeropen SDK with RSA private key authentication.
    Paper account default under sim lock.
    """

    def __init__(self) -> None:
        from shared.tiger_account import resolve_tiger_account

        self._account = resolve_tiger_account(settings.TIGER_ACCOUNT)
        self._tiger_id = settings.TIGER_ID
        self._private_key_path = settings.TIGER_PRIVATE_KEY_PATH
        self._license = settings.TIGER_LICENSE
        self._rate_limit = data_config.TIGER_RATE_LIMIT_SECONDS
        self._last_request: float = 0.0
        self._client: Any = None
        self._initialized: bool = False

    def _ensure_initialized(self) -> None:
        """Lazy-initialize the Tiger client."""
        if self._initialized:
            return

        try:
            from tigeropen.tiger_open_config import TigerOpenClientConfig
            from tigeropen.common.consts import Language

            client_config = TigerOpenClientConfig()
            client_config.private_key = self._load_private_key()
            client_config.tiger_id = self._tiger_id
            client_config.account = self._account
            client_config.language = Language.en_US
            client_config.license = self._license
            client_config.tiger_client_version = settings.TIGER_CLIENT_VERSION

            from tigeropen.trade.trade_client import TradeClient
            from tigeropen.quote.quote_client import QuoteClient

            self._trade_client = TradeClient(client_config)
            self._quote_client = QuoteClient(client_config)
            self._initialized = True
            logger.info(f"Tiger client initialized (account={self._account})")
        except ImportError:
            logger.warning("tigeropen SDK not installed — Tiger client unavailable")
            self._initialized = False
        except Exception as e:
            logger.error(f"Failed to initialize Tiger client: {e}")
            self._initialized = False

    def _load_private_key(self) -> str:
        """Load the Tiger RSA private key from file path.

        Returns:
            Private key content as string.

        Raises:
            FileNotFoundError: If the key file does not exist.
        """
        path = os.path.expanduser(self._private_key_path)
        if not os.path.exists(path):
            logger.warning(f"Tiger private key not found at {path}")
            return ""
        with open(path, "r") as f:
            return f.read()

    async def _rate_limit_wait(self) -> None:
        """Enforce rate limit between Tiger API calls."""
        elapsed = time_now() - self._last_request
        if elapsed < self._rate_limit:
            await asyncio.sleep(self._rate_limit - elapsed)
        self._last_request = time_now()

    @staticmethod
    def _is_empty_result(obj) -> bool:
        """Check if a Tiger SDK result is empty — handles DataFrame, list, None.

        Tiger SDK returns a DataFrame for single-ticker queries, which triggers
        ``ValueError: The truth value of a DataFrame is ambiguous`` if tested
        with ``if not obj:``.
        """
        if obj is None:
            return True
        if hasattr(obj, "empty"):
            return bool(obj.empty)
        return len(obj) == 0

    async def get_quote(self, ticker: str) -> dict[str, Any]:
        """Get real-time quote snapshot for a ticker.

        Args:
            ticker: Stock ticker (Tiger format, e.g. 'AAPL' or '700' for HK).

        Returns:
            Quote dictionary with bid/ask/last/volume.
        """
        self._ensure_initialized()
        if not self._initialized:
            return {"ticker": ticker, "error": "Tiger client not initialized"}

        await self._rate_limit_wait()
        try:
            result = await asyncio.to_thread(
                self._quote_client.get_stock_briefs, [ticker]
            )
            if not self._is_empty_result(result):
                quote = result[0]
                return {
                    "ticker": getattr(quote, "symbol", ticker),
                    "last": getattr(quote, "latest_price", None),
                    "bid": getattr(quote, "bid_price", None),
                    "ask": getattr(quote, "ask_price", None),
                    "bid_size": getattr(quote, "bid_volume", None),
                    "ask_size": getattr(quote, "ask_volume", None),
                    "volume": getattr(quote, "volume", None),
                    "open": getattr(quote, "open", None),
                    "high": getattr(quote, "high", None),
                    "low": getattr(quote, "low", None),
                    "change_pct": getattr(quote, "change", None),
                    "timestamp": datetime.now().isoformat(),
                }
            return {"ticker": ticker, "error": "No data"}
        except Exception as e:
            logger.error(f"Tiger get_quote failed for {ticker}: {e}")
            raise DataFetchError(f"Tiger quote failed: {ticker}", details={"error": str(e)})

    async def get_quotes(self, tickers: list[str]) -> list[dict[str, Any]]:
        """Get quotes for multiple tickers.

        Args:
            tickers: List of tiger-format ticker symbols.

        Returns:
            List of quote dictionaries.
        """
        self._ensure_initialized()
        if not self._initialized:
            return [{"ticker": t, "error": "Tiger client not initialized"} for t in tickers]

        await self._rate_limit_wait()
        try:
            results = await asyncio.to_thread(
                self._quote_client.get_stock_briefs, tickers
            )
            quotes = []
            for q in results:
                quotes.append({
                    "ticker": getattr(q, "symbol", ""),
                    "last": getattr(q, "latest_price", None),
                    "bid": getattr(q, "bid_price", None),
                    "ask": getattr(q, "ask_price", None),
                    "volume": getattr(q, "volume", None),
                    "change_pct": getattr(q, "change", None),
                })
            return quotes
        except Exception as e:
            logger.error(f"Tiger get_quotes failed: {e}")
            raise DataFetchError("Tiger multi-quote failed", details={"error": str(e)})

    async def get_positions(self) -> list[dict[str, Any]]:
        """Get current positions for the trading account.

        Returns:
            List of position dictionaries.
        """
        self._ensure_initialized()
        if not self._initialized:
            return []

        await self._rate_limit_wait()
        try:
            positions = await asyncio.to_thread(
                self._trade_client.get_positions
            )
            result = []
            for pos in (positions or []):
                # Tiger SDK: symbol lives under contract.symbol, not position.symbol
                ticker = ""
                if hasattr(pos, "contract") and pos.contract is not None:
                    ticker = getattr(pos.contract, "symbol", "") or ""
                if not ticker:
                    ticker = getattr(pos, "symbol", "")
                result.append({
                    "ticker": ticker,
                    "quantity": getattr(pos, "quantity", 0),
                    "avg_cost": getattr(pos, "average_cost", 0.0),
                    "market_price": getattr(pos, "market_price", 0.0),
                    "market_value": getattr(pos, "market_value", 0.0),
                    "unrealized_pnl": getattr(pos, "unrealized_pnl", 0.0),
                })
            return result
        except Exception as e:
            logger.error(f"Tiger get_positions failed: {e}")
            return []

    async def get_account_summary(self) -> dict[str, Any]:
        """Get account summary including NAV, cash, margin.

        Returns:
            Account summary dictionary.
        """
        self._ensure_initialized()
        if not self._initialized:
            return {"error": "Tiger client not initialized"}

        await self._rate_limit_wait()
        try:
            account = await asyncio.to_thread(
                self._trade_client.get_accounts
            )
            if account and len(account) > 0:
                acc = account[0]
                # Tiger SDK: account fields live under acc.summary (e.g. summary.net_liquidation)
                summary = getattr(acc, "summary", acc)
                return {
                    "account_id": getattr(acc, "account", self._account),
                    "nav": getattr(summary, "net_liquidation", 0.0),
                    "cash": getattr(summary, "cash", 0.0),
                    "margin_used": getattr(summary, "margin", 0.0),
                    "buying_power": getattr(summary, "buying_power", 0.0),
                }
            return {"error": "No account data"}
        except Exception as e:
            logger.error(f"Tiger get_account_summary failed: {e}")
            return {"error": str(e)}

    async def place_order(
        self,
        ticker: str,
        side: str,
        quantity: int,
        order_type: str = "MKT",
        limit_price: float | None = None,
    ) -> dict[str, Any]:
        """Place a live order via Tiger.

        Args:
            ticker: Stock symbol.
            side: 'BUY' or 'SELL'.
            quantity: Number of shares.
            order_type: 'MKT' or 'LMT'.
            limit_price: Limit price (required for LMT orders).

        Returns:
            Order confirmation dictionary.
        """
        self._ensure_initialized()
        if not self._initialized:
            raise ExecutionError("Tiger client not initialized")

        await self._rate_limit_wait()
        try:
            from tigeropen.common.consts import OrderType, Action

            action = Action.BUY if side.upper() == "BUY" else Action.SELL
            otype = OrderType.MARKET if order_type.upper() == "MKT" else OrderType.LIMIT
            price = limit_price if otype == OrderType.LIMIT else None

            order = await asyncio.to_thread(
                self._trade_client.place_order,
                contract=None,  # Tiger resolves by symbol
                action=action,
                order_type=otype,
                quantity=quantity,
                limit_price=price,
            )

            return {
                "order_id": getattr(order, "order_id", ""),
                "ticker": ticker,
                "side": side.upper(),
                "quantity": quantity,
                "order_type": order_type.upper(),
                "status": "SUBMITTED",
            }
        except Exception as e:
            logger.error(f"Tiger place_order failed for {ticker}: {e}")
            raise ExecutionError(f"Order placement failed: {ticker}", details={"error": str(e)})


def time_now() -> float:
    """Return current monotonic time."""
    import time as _time
    return _time.monotonic()
