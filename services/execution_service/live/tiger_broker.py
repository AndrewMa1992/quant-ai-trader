"""services/execution_service/live/tiger_broker.py – Live Tiger Broker integration.

Account: 20874631.
Supports: market/limit orders, cancel, position/order/account queries.
Optional confirmation gate before live order submission.
"""

from __future__ import annotations

import asyncio
from typing import Any

from loguru import logger

from configs.settings import settings
from services.execution_service.config import exec_config


class TigerBroker:
    """Live Tiger Broker API wrapper for order execution.

    Places real orders via Tiger Open API.
    Account: 20874631 (configurable).

    Attributes:
        account: Tiger account number.
        require_confirm: Whether to require secondary confirmation.
    """

    def __init__(
        self,
        account: str = "",
        require_confirm: bool | None = None,
    ) -> None:
        self.account = account or exec_config.TIGER_ACCOUNT
        self.require_confirm = require_confirm if require_confirm is not None else exec_config.LIVE_TRADING_REQUIRE_CONFIRM
        self._client: Any = None
        self._initialized = False

    def _ensure_client(self) -> None:
        """Lazy-initialize Tiger client."""
        if self._initialized:
            return

        try:
            from tigeropen.tiger_open_config import TigerOpenClientConfig
            from tigeropen.trade.trade_client import TradeClient

            client_config = TigerOpenClientConfig()
            client_config.private_key = self._load_key()
            client_config.tiger_id = settings.TIGER_ID
            client_config.account = self.account
            client_config.license = settings.TIGER_LICENSE

            self._client = TradeClient(client_config)
            self._initialized = True
            logger.info(f"Tiger broker initialized (account={self.account})")

        except ImportError:
            logger.warning("tigeropen SDK not available — using paper broker")
        except Exception as e:
            logger.error(f"Tiger broker init failed: {e}")

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
            positions = await asyncio.to_thread(self._client.get_positions)
            result: list[dict[str, Any]] = []
            for p in (positions or []):
                # Tiger SDK: symbol lives under contract.symbol, not position.symbol
                ticker = ""
                if hasattr(p, "contract") and p.contract is not None:
                    ticker = getattr(p.contract, "symbol", "") or ""
                if not ticker:
                    ticker = getattr(p, "symbol", "")
                result.append({
                    "ticker": ticker,
                    "quantity": getattr(p, "quantity", 0),
                    "avg_cost": getattr(p, "average_cost", 0.0),
                    "market_value": getattr(p, "market_value", 0.0),
                })
            return result
        except Exception as e:
            logger.error(f"Failed to get positions: {e}")
            return []

    async def get_account_summary(self) -> dict[str, Any]:
        """Get account summary via Tiger SDK ``get_assets()``.

        The Tiger ``TradeClient.get_assets()`` method returns a list of
        ``PortfolioAccount`` objects whose ``.summary`` attribute holds
        ``Account`` fields like ``net_liquidation``, ``cash``, ``buying_power``.
        Some summary fields may be ``inf`` (e.g. ``accrued_cash``); a safe-float
        helper filters those out.

        Returns:
            Account info dict with keys: account, nav, cash, buying_power,
            currency.
        """
        self._ensure_client()
        if not self._initialized:
            return {"account": self.account, "nav": 0, "cash": 0}

        try:
            assets = await asyncio.to_thread(self._client.get_assets)
            if assets and len(assets) > 0:
                acc = assets[0]
                summary = getattr(acc, "summary", acc)

                def _safe_float(val: Any) -> float:
                    """Convert value to float, returning 0.0 for inf/nan/errors."""
                    try:
                        v = float(val)
                        if v == float("inf") or v == float("-inf") or v != v:  # inf or nan
                            return 0.0
                        return v
                    except (TypeError, ValueError):
                        return 0.0

                return {
                    "account": self.account,
                    "nav": _safe_float(getattr(summary, "net_liquidation", 0.0)),
                    "cash": _safe_float(getattr(summary, "cash", 0.0)),
                    "buying_power": _safe_float(getattr(summary, "buying_power", 0.0)),
                    "currency": getattr(summary, "currency", "USD"),
                }
        except Exception as e:
            logger.error(f"Failed to get account: {e}")

        return {"account": self.account, "nav": 0, "cash": 0}
