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
        self._initialized = False
        self._paper = should_use_paper_account(self.account)
        self._sandbox_enabled: bool | None = None

    def _ensure_client(self, sandbox: bool | None = None) -> None:
        """Lazy-initialize Tiger client.

        Paper/sim uses ``sandbox_debug=True`` so virtual funds are read from
        the sandbox book (the live book for a paper id often reports zeros).
        """
        want_sandbox = self._paper if sandbox is None else bool(sandbox)
        if self._initialized and self._client is not None and self._sandbox_enabled == want_sandbox:
            return

        try:
            from tigeropen.tiger_open_config import TigerOpenClientConfig
            from tigeropen.trade.trade_client import TradeClient

            try:
                client_config = TigerOpenClientConfig(sandbox_debug=want_sandbox)
            except TypeError:
                client_config = TigerOpenClientConfig()
            if hasattr(client_config, "sandbox_debug"):
                try:
                    client_config.sandbox_debug = want_sandbox
                except Exception:
                    pass
            client_config.private_key = self._load_key()
            client_config.tiger_id = settings.TIGER_ID
            client_config.account = self.account
            client_config.license = settings.TIGER_LICENSE

            self._client = TradeClient(client_config)
            self._initialized = True
            self._sandbox_enabled = want_sandbox
            logger.info(
                f"Tiger broker initialized (account={self.account} sandbox={want_sandbox} paper={self._paper})"
            )

        except ImportError:
            logger.warning("tigeropen SDK not available — using paper broker")
            self._initialized = False
            self._client = None
        except Exception as e:
            logger.error(f"Tiger broker init failed: {e}")
            self._initialized = False
            self._client = None

    def _load_key(self) -> str:
        """Load RSA private key, stripped of PEM headers for Tiger SDK.

        Tiger SDK's ``load_private_key()`` expects raw base64 content, not PEM
        format. If the key file has ``-----BEGIN …-----`` / ``-----END …-----``
        wrapper lines, they are stripped before returning.

        Returns:
            Base64-encoded private key string, or empty string if file missing.
        """
        import os

        path = os.path.expanduser(settings.TIGER_PRIVATE_KEY_PATH)
        if os.path.exists(path):
            with open(path) as f:
                key = f.read().strip()
            # Tiger SDK expects raw base64, not PEM format.
            # Strip PEM header/footer lines if present.
            if "BEGIN" in key:
                lines = key.split("\n")
                key = "".join(line.strip() for line in lines if not line.startswith("-----"))
            return key
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

        # Confirmation gate
        if self.require_confirm:
            logger.warning(f"CONFIRMATION REQUIRED: {side} {quantity} {ticker} "
                           f"({order_type}) on account {self.account}")
            # In production, this would trigger a Slack/WeChat confirmation flow
            # For now, auto-confirm in paper/dev mode
            if settings.is_production:
                return {
                    "status": "PENDING_CONFIRMATION",
                    "ticker": ticker,
                    "side": side,
                    "quantity": quantity,
                    "message": "Awaiting human confirmation",
                }

        if not self._initialized:
            # Paper broker mode
            import uuid
            import time
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

        # Live order via Tiger
        try:
            from tigeropen.common.consts import Action, OrderType

            action = Action.BUY if side.upper() == "BUY" else Action.SELL
            otype = OrderType.MARKET if order_type.upper() == "MKT" else OrderType.LIMIT

            order = await asyncio.to_thread(
                self._client.place_order,
                contract=None,
                action=action,
                order_type=otype,
                quantity=quantity,
                limit_price=limit_price,
            )

            return {
                "order_id": str(getattr(order, "order_id", ""))[:12],
                "ticker": ticker,
                "side": side.upper(),
                "quantity": quantity,
                "order_type": order_type.upper(),
                "status": "LIVE_SUBMITTED",
                "account": self.account,
            }

        except Exception as e:
            logger.error(f"Tiger order failed: {e}")
            return {
                "ticker": ticker,
                "status": "FAILED",
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
        parsed["sandbox"] = self._sandbox_enabled
        parsed["paper"] = self._paper
        return parsed

    def _account_looks_empty(self, parsed: dict[str, Any]) -> bool:
        cash = float(parsed.get("cash") or 0)
        nav = float(parsed.get("nav") or parsed.get("net_liquidation") or 0)
        bp = float(parsed.get("buying_power") or 0)
        return cash <= 0 and nav <= 0 and bp <= 0

    async def get_account_summary(self) -> dict[str, Any]:
        """Get account summary via Tiger SDK ``get_assets(account=...)``.

        Paper virtual funds often live on the sandbox book and/or in
        ``segments`` rather than ``summary.cash``.  We parse every alias,
        then retry the opposite sandbox flag if the preferred book is empty.
        """
        self._ensure_client()
        if not self._initialized:
            return {
                "account": self.account,
                "nav": 0,
                "cash": 0,
                "buying_power": 0,
                "paper": self._paper,
                "error": "sdk_unavailable",
            }

        try:
            parsed = await asyncio.to_thread(self._get_account_summary_sync)
            if self._account_looks_empty(parsed) and self._sandbox_enabled is not None:
                flipped = not bool(self._sandbox_enabled)
                logger.info(
                    "tiger_broker: empty book on sandbox=%s — retrying sandbox=%s",
                    self._sandbox_enabled,
                    flipped,
                )
                self._ensure_client(sandbox=flipped)
                if self._initialized:
                    parsed = await asyncio.to_thread(self._get_account_summary_sync)
                    if self._account_looks_empty(parsed) and self._paper:
                        # Restore sandbox so later paper orders still hit the sim book.
                        self._ensure_client(sandbox=True)
                        parsed["sandbox"] = self._sandbox_enabled
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

        return {"account": self.account, "nav": 0, "cash": 0, "buying_power": 0}
