"""services/execution_service/live/tiger_broker.py – Live Tiger Broker integration.

Paper account default: 21837535188693626 (sim lock).
Live account: 20874631 when simulation is off.
"""

from __future__ import annotations

import asyncio
from typing import Any

from loguru import logger

from configs.settings import settings
from services.execution_service.config import exec_config
from shared.tiger_account import resolve_tiger_account, should_use_paper_account
from shared.tiger_assets import merge_orders, parse_account_summary, parse_order, parse_position


class TigerBroker:
    """Tiger Broker API wrapper for order execution.

    Places orders via Tiger Open API. Account resolves from paper/live policy.

    Attributes:
        account: Tiger account number.
        require_confirm: Whether to require secondary confirmation.
    """

    def __init__(
        self,
        account: str = "",
        require_confirm: bool | None = None,
    ) -> None:
        self.account = resolve_tiger_account(account or exec_config.TIGER_ACCOUNT or settings.TIGER_ACCOUNT)
        self.require_confirm = require_confirm if require_confirm is not None else exec_config.LIVE_TRADING_REQUIRE_CONFIRM
        self._client: Any = None
        self._quote_client: Any = None
        self._initialized = False
        self._paper = should_use_paper_account(self.account)
        self._sandbox_enabled: bool = False
        self._init_error: str | None = None

    def _ensure_client(self, sandbox: bool | None = None) -> None:
        """Lazy-initialize TradeClient + QuoteClient via shared.tiger_sdk.

        Paper/demo trading uses the **production** OpenAPI with the paper
        account id. Sandbox is a separate environment (QAT_TIGER_SANDBOX).
        The ``sandbox`` argument is kept for call-site compatibility and ignored.
        """
        from shared.tiger_sdk import connect, is_sandbox_requested, last_error

        want_sandbox = is_sandbox_requested()
        if self._initialized and self._client is not None and self._sandbox_enabled == want_sandbox:
            return

        try:
            trade, quote = connect(account=self.account)
            self._client = trade
            self._quote_client = quote
            self._initialized = True
            self._sandbox_enabled = want_sandbox
            self._init_error = None
            logger.info(
                f"Tiger broker initialized (account={self.account} sandbox={want_sandbox} paper={self._paper})"
            )
        except ImportError as e:
            self._init_error = f"tigeropen not installed: {e}"
            logger.warning("tigeropen SDK not available — using paper broker")
            self._initialized = False
            self._client = None
            self._quote_client = None
        except Exception as e:
            self._init_error = last_error() or str(e)
            logger.error(f"Tiger broker init failed: {self._init_error}")
            self._initialized = False
            self._client = None
            self._quote_client = None

    def _load_key(self) -> str:
        """Load RSA private key for callers that still use this helper."""
        try:
            from shared.tiger_sdk import load_private_key

            return load_private_key()
        except Exception as exc:
            logger.warning("Tiger private key load failed: %s", exc)
            return ""

    async def place_order(
        self,
        ticker: str,
        side: str,
        quantity: int,
        order_type: str = "MKT",
        limit_price: float | None = None,
        algo: str = "direct",
    ) -> dict[str, Any]:
        """Place a live (or paper) order.

        Args:
            ticker: Stock ticker.
            side: 'BUY' or 'SELL'.
            quantity: Number of shares.
            order_type: 'MKT' or 'LMT'.
            limit_price: Required for LMT orders.
            algo: 'direct' / 'twap' / 'vwap' / 'pov'.

        Returns:
            Order confirmation dict.
        """
        self._ensure_client()

        # Human confirm is live-money only. Paper/demo must reach the Tiger app.
        if self.require_confirm and not self._paper and settings.is_production:
            logger.warning(f"CONFIRMATION REQUIRED: {side} {quantity} {ticker} "
                           f"({order_type}) on account {self.account}")
            return {
                "status": "PENDING_CONFIRMATION",
                "ticker": ticker,
                "side": side,
                "quantity": quantity,
                "message": "Awaiting human confirmation",
            }

        if not self._initialized or self._client is None:
            import uuid
            import time
            logger.warning(
                "Tiger SDK unavailable — local PAPER_SUBMITTED only, not visible in the Tiger app"
            )
            return {
                "order_id": str(uuid.uuid4())[:12],
                "ticker": ticker,
                "side": side.upper(),
                "quantity": quantity,
                "order_type": order_type.upper(),
                "algo": algo,
                "status": "PAPER_SUBMITTED",
                "account": self.account,
                "timestamp": time.time(),
                "message": "Paper order (Tiger SDK not available)",
            }

        try:
            from shared.tiger_orders import submit_stock_order

            result = await asyncio.to_thread(
                submit_stock_order,
                self._client,
                account=self.account,
                ticker=ticker,
                side=side,
                quantity=int(quantity),
                order_type=order_type,
                limit_price=limit_price,
                quote_client=self._quote_client,
                paper=self._paper,
            )
            result["algo"] = algo
            if not result.get("order_id"):
                result["status"] = "FAILED"
                result.setdefault("error", "Tiger place_order returned no order id")
            return result
        except Exception as e:
            logger.error(f"Tiger order failed: {e}")
            return {
                "ticker": ticker,
                "side": side.upper() if side else "",
                "quantity": quantity,
                "status": "FAILED",
                "account": self.account,
                "error": str(e),
            }

    async def cancel_order(self, order_id: str) -> dict[str, Any]:
        """Cancel a pending order.

        Args:
            order_id: Order identifier.

        Returns:
            Cancellation result.
        """
        self._ensure_client()
        if not self._initialized:
            return {"order_id": order_id, "status": "PAPER_CANCELLED"}

        try:
            await asyncio.to_thread(self._client.cancel_order, order_id)
            return {"order_id": order_id, "status": "CANCELLED"}
        except Exception as e:
            return {"order_id": order_id, "status": "FAILED", "error": str(e)}

    async def get_positions(self) -> list[dict[str, Any]]:
        """Get current positions.

        Returns:
            List of position dicts.
        """
        self._ensure_client()
        if not self._initialized:
            return []

        try:
            positions = await asyncio.to_thread(self._fetch_positions)
            return positions
        except Exception as e:
            logger.error(f"Failed to get positions: {e}")
            return []

    def _fetch_positions(self) -> list[dict[str, Any]]:
        if not self._client:
            return []
        raw = None
        for kwargs in ({"account": self.account}, {}):
            try:
                raw = self._client.get_positions(**kwargs) if kwargs else self._client.get_positions()
                break
            except TypeError:
                try:
                    raw = self._client.get_positions()
                    break
                except Exception as exc:
                    logger.debug("get_positions: %s", exc)
            except Exception as exc:
                logger.debug("get_positions(%s): %s", kwargs, exc)
        result: list[dict[str, Any]] = []
        for p in (raw or []):
            parsed = parse_position(p)
            if parsed.get("ticker"):
                result.append(parsed)
        return result

    def _call_with_account(self, method: str, **extra: Any) -> Any:
        fn = getattr(self._client, method, None) if self._client else None
        if not callable(fn):
            return None
        kwargs: dict[str, Any] = dict(extra)
        if self.account:
            kwargs["account"] = self.account
        try:
            return fn(**kwargs)
        except TypeError:
            try:
                return fn()
            except Exception as exc:
                logger.debug("%s() failed: %s", method, exc)
                return None
        except Exception as exc:
            logger.debug("%s(%s) failed: %s", method, kwargs, exc)
            return None

    def _list_orders_sync(self, *methods: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for method in methods:
            raw = self._call_with_account(method)
            if not raw:
                continue
            try:
                iterable = list(raw)
            except TypeError:
                continue
            for o in iterable:
                parsed = parse_order(o)
                if parsed.get("id") or parsed.get("ticker"):
                    rows.append(parsed)
            if rows:
                break
        return rows

    async def get_open_orders(self) -> list[dict[str, Any]]:
        self._ensure_client()
        if not self._initialized:
            return []
        return await asyncio.to_thread(
            self._list_orders_sync, "get_open_orders", "get_active_orders", "get_orders"
        )

    async def get_filled_orders(self) -> list[dict[str, Any]]:
        self._ensure_client()
        if not self._initialized:
            return []
        return await asyncio.to_thread(
            self._list_orders_sync, "get_filled_orders", "get_executed_orders"
        )

    async def get_order_history(self) -> list[dict[str, Any]]:
        open_rows = await self.get_open_orders()
        filled = await self.get_filled_orders()
        return merge_orders(open_rows, filled)

    async def get_transactions(self) -> list[dict[str, Any]]:
        self._ensure_client()
        if not self._initialized:
            return []
        return await asyncio.to_thread(self._fetch_transactions)

    def _fetch_transactions(self) -> list[dict[str, Any]]:
        raw = self._call_with_account("get_transactions")
        if raw is None:
            raw = self._call_with_account("get_trade_fills")
        out: list[dict[str, Any]] = []
        for t in (raw or []):
            parsed = parse_order(t)
            parsed["source"] = "tiger_tx"
            if parsed.get("id") or parsed.get("ticker"):
                out.append(parsed)
        return out

    def _fetch_assets_raw(self) -> Any:
        if not self._client:
            return None
        attempts: list[tuple[str, dict[str, Any]]] = [
            ("get_assets", {"account": self.account, "segment": True}),
            ("get_assets", {"account": self.account}),
            ("get_prime_assets", {"account": self.account}),
            ("get_assets", {}),
        ]
        for method, kwargs in attempts:
            fn = getattr(self._client, method, None)
            if not callable(fn):
                continue
            try:
                raw = fn(**kwargs) if kwargs else fn()
                if raw:
                    return raw
            except TypeError:
                try:
                    raw = fn()
                    if raw:
                        return raw
                except Exception as exc:
                    logger.debug("%s() failed: %s", method, exc)
            except Exception as exc:
                logger.debug("%s(%s) failed: %s", method, kwargs, exc)
        return None

    def _get_account_summary_sync(self) -> dict[str, Any]:
        raw = self._fetch_assets_raw()
        parsed = parse_account_summary(raw, account=self.account)
        parsed["account"] = parsed.get("account") or self.account
        parsed["sandbox"] = bool(self._sandbox_enabled)
        parsed["paper"] = self._paper
        parsed["source"] = "tiger_sdk"
        return parsed

    async def get_account_summary(self) -> dict[str, Any]:
        """Get account summary via Tiger SDK ``get_assets(account=...)``.

        Paper virtual funds are on the production OpenAPI paper book, often
        under ``segments`` rather than ``summary.cash``.
        """
        from shared.tiger_sdk import last_error

        self._ensure_client()
        if not self._initialized:
            return {
                "account": self.account,
                "nav": 0,
                "cash": 0,
                "buying_power": 0,
                "paper": self._paper,
                "sandbox": bool(self._sandbox_enabled),
                "error": "sdk_unavailable",
                "detail": self._init_error or last_error(),
            }

        try:
            parsed = await asyncio.to_thread(self._get_account_summary_sync)
            logger.info(
                "tiger_broker account=%s sandbox=%s cash=%.2f nav=%.2f bp=%.2f segs=%d",
                parsed.get("account"),
                parsed.get("sandbox"),
                float(parsed.get("cash") or 0),
                float(parsed.get("nav") or 0),
                float(parsed.get("buying_power") or 0),
                len(parsed.get("segments") or []),
            )
            return parsed
        except Exception as e:
            logger.error(f"Failed to get account: {e}")
            return {
                "account": self.account,
                "nav": 0,
                "cash": 0,
                "buying_power": 0,
                "paper": self._paper,
                "sandbox": bool(self._sandbox_enabled),
                "error": str(e),
            }
