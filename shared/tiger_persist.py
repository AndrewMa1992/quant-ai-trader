"""Persist Tiger (paper/live) account state into local SQLite and build WS payloads.

Writes: positions, portfolios, orders, executions, trades.
Works without Postgres — uses data/quant_trader.db (Lightsail default).
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

DB_PATH = Path("data/quant_trader.db")


def _market_of(ticker: str) -> str:
    if ".HK" in ticker:
        return "HK"
    if ".SI" in ticker:
        return "SG"
    if ".AX" in ticker:
        return "AU"
    if ".NZ" in ticker:
        return "NZ"
    return "US"


def normalize_position(pos: Dict[str, Any]) -> Dict[str, Any]:
    """Map Tiger/v2 fields → canonical {ticker, shares, avg_cost, market_value}."""
    ticker = str(pos.get("ticker") or pos.get("symbol") or "").strip()
    shares = pos.get("shares")
    if shares is None:
        shares = pos.get("quantity", 0)
    avg = float(pos.get("avg_cost") or pos.get("average_cost") or 0.0)
    mv = float(pos.get("market_value") or 0.0)
    px = float(pos.get("market_price") or pos.get("price") or 0.0)
    if mv <= 0 and px > 0 and float(shares or 0) != 0:
        mv = abs(float(shares)) * px
    if px <= 0 and float(shares or 0) != 0 and mv > 0:
        px = mv / abs(float(shares))
    return {
        "ticker": ticker,
        "shares": float(shares or 0),
        "quantity": float(shares or 0),
        "avg_cost": avg,
        "market_value": mv,
        "market_price": px,
        "market": _market_of(ticker),
    }


def normalize_account(acct: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not acct:
        return {"nav": 0.0, "cash": 0.0, "total_value": 0.0}
    nav = float(acct.get("nav") or acct.get("total_value") or acct.get("net_liquidation") or 0.0)
    cash = float(acct.get("cash") or 0.0)
    return {
        **acct,
        "nav": nav,
        "cash": cash,
        "total_value": float(acct.get("total_value") or nav),
    }


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def ensure_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS portfolios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_date DATE UNIQUE,
            nav REAL, gross_exposure REAL, net_exposure REAL,
            long_exposure REAL, short_exposure REAL, cash REAL,
            daily_pnl REAL DEFAULT 0, daily_return REAL DEFAULT 0,
            cumulative_return REAL DEFAULT 0,
            var_95 REAL, cvar_95 REAL, sharpe_ratio REAL,
            max_drawdown REAL, drawdown_from_peak REAL,
            num_positions INTEGER DEFAULT 0, leverage REAL DEFAULT 1,
            created_at TEXT, updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT, position_date DATE, market TEXT,
            quantity INTEGER, avg_cost REAL, market_price REAL,
            market_value REAL, unrealized_pnl REAL DEFAULT 0,
            realized_pnl REAL DEFAULT 0, weight REAL DEFAULT 0,
            sector TEXT, currency TEXT DEFAULT 'USD', fx_rate REAL DEFAULT 1,
            created_at TEXT, updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT, trade_date DATE, trade_time TEXT,
            side TEXT, quantity INTEGER, price REAL,
            commission REAL DEFAULT 0, slippage_bps REAL DEFAULT 0,
            notional REAL, order_id TEXT, execution_id TEXT,
            signal_id TEXT, market TEXT, currency TEXT DEFAULT 'USD',
            strategy TEXT, notes TEXT,
            created_at TEXT, updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id TEXT UNIQUE, ticker TEXT, side TEXT, order_type TEXT,
            quantity INTEGER, filled_quantity INTEGER DEFAULT 0,
            limit_price REAL, stop_price REAL, avg_fill_price REAL,
            status TEXT, time_in_force TEXT DEFAULT 'DAY',
            submitted_at TEXT, filled_at TEXT, cancelled_at TEXT,
            reject_reason TEXT, market TEXT, strategy TEXT,
            signal_id TEXT, is_paper INTEGER DEFAULT 1,
            retry_count INTEGER DEFAULT 0, notes TEXT,
            created_at TEXT, updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS executions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            execution_id TEXT UNIQUE, order_id TEXT, ticker TEXT, side TEXT,
            quantity INTEGER, price REAL, notional REAL,
            commission REAL DEFAULT 0, executed_at TEXT,
            market TEXT, exchange TEXT, venue TEXT, is_paper INTEGER DEFAULT 1,
            created_at TEXT, updated_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_pos_ticker_date ON positions(ticker, position_date);
        CREATE INDEX IF NOT EXISTS idx_trades_ticker_date ON trades(ticker, trade_date);
        CREATE INDEX IF NOT EXISTS idx_orders_order_id ON orders(order_id);
        """
    )
    conn.commit()


def persist_tiger_snapshot(
    positions: List[Dict[str, Any]],
    account: Optional[Dict[str, Any]] = None,
    orders: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Upsert Tiger snapshot into SQLite. Returns summary for WS."""
    now = datetime.now(timezone.utc).isoformat()
    today = date.today().isoformat()
    norm_pos = [normalize_position(p) for p in (positions or [])]
    norm_pos = [p for p in norm_pos if p["ticker"] and p["shares"] != 0]
    acct = normalize_account(account)

    conn = _connect()
    ensure_tables(conn)
    try:
        # Replace today's positions
        conn.execute("DELETE FROM positions WHERE position_date = ?", (today,))
        nav = float(acct.get("nav") or 0.0) or sum(abs(p["market_value"]) for p in norm_pos)
        cash = float(acct.get("cash") or 0.0)
        long_exp = sum(p["market_value"] for p in norm_pos if p["shares"] > 0)
        short_exp = sum(abs(p["market_value"]) for p in norm_pos if p["shares"] < 0)

        for p in norm_pos:
            qty = int(p["shares"])
            px = float(p["market_price"] or (p["market_value"] / abs(p["shares"]) if p["shares"] else 0))
            weight = (abs(p["market_value"]) / nav) if nav > 0 else 0.0
            unreal = (px - p["avg_cost"]) * qty if p["avg_cost"] else 0.0
            conn.execute(
                """INSERT INTO positions
                   (ticker, position_date, market, quantity, avg_cost, market_price,
                    market_value, unrealized_pnl, realized_pnl, weight, currency, fx_rate,
                    created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, 'USD', 1, ?, ?)""",
                (
                    p["ticker"], today, p["market"], qty, p["avg_cost"], px,
                    p["market_value"], unreal, weight, now, now,
                ),
            )

        conn.execute(
            """INSERT INTO portfolios
               (snapshot_date, nav, gross_exposure, net_exposure, long_exposure, short_exposure,
                cash, daily_pnl, daily_return, cumulative_return, num_positions, leverage,
                created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, 0, ?, 1, ?, ?)
               ON CONFLICT(snapshot_date) DO UPDATE SET
                 nav=excluded.nav, cash=excluded.cash,
                 gross_exposure=excluded.gross_exposure,
                 net_exposure=excluded.net_exposure,
                 long_exposure=excluded.long_exposure,
                 short_exposure=excluded.short_exposure,
                 num_positions=excluded.num_positions,
                 updated_at=excluded.updated_at
            """,
            (
                today, nav, long_exp + short_exp, long_exp - short_exp,
                long_exp, short_exp, cash, len(norm_pos), now, now,
            ),
        )

        orders_written = 0
        for o in orders or []:
            oid = str(o.get("order_id") or o.get("id") or uuid.uuid4())
            ticker = str(o.get("ticker") or "")
            if not ticker:
                continue
            side = str(o.get("side") or o.get("action") or "").upper()
            qty = int(float(o.get("quantity") or o.get("qty") or 0))
            status = str(o.get("status") or "SUBMITTED")
            conn.execute(
                """INSERT INTO orders
                   (order_id, ticker, side, order_type, quantity, filled_quantity,
                    avg_fill_price, status, market, is_paper, submitted_at, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
                   ON CONFLICT(order_id) DO UPDATE SET
                     status=excluded.status,
                     filled_quantity=excluded.filled_quantity,
                     avg_fill_price=excluded.avg_fill_price,
                     updated_at=excluded.updated_at
                """,
                (
                    oid, ticker, side, str(o.get("order_type") or "MKT"),
                    qty, int(float(o.get("filled_quantity") or qty if status == "FILLED" else 0)),
                    float(o.get("avg_fill_price") or o.get("price") or 0),
                    status, _market_of(ticker), now, now, now,
                ),
            )
            orders_written += 1

        conn.commit()
        snapshot = {
            "type": "tiger_snapshot",
            "source": "tiger",
            "timestamp": now,
            "account": acct,
            "nav": nav,
            "cash": cash,
            "positions": [
                {
                    "ticker": p["ticker"],
                    "quantity": p["shares"],
                    "shares": p["shares"],
                    "avg_cost": p["avg_cost"],
                    "market_value": p["market_value"],
                    "market_price": p["market_price"],
                    "unrealized_pnl": (p["market_price"] - p["avg_cost"]) * p["shares"]
                    if p["avg_cost"] else 0,
                }
                for p in norm_pos
            ],
            "positions_synced": len(norm_pos),
            "orders_synced": orders_written,
            "account_updated": True,
        }
        # Redis mirror
        try:
            from shared.market_cache import sync_cache_portfolio

            sync_cache_portfolio({
                "cash": cash,
                "total_value": nav,
                "n_positions": len(norm_pos),
                "source": "tiger",
            })
        except Exception:
            pass
        logger.info(
            f"Tiger persist: {len(norm_pos)} positions, NAV=${nav:,.2f}, cash=${cash:,.2f}"
        )
        return snapshot
    except Exception as exc:
        logger.error(f"Tiger persist failed: {exc}")
        return {"error": str(exc), "positions_synced": 0, "account_updated": False}
    finally:
        conn.close()


def persist_fill(
    ticker: str,
    side: str,
    quantity: float,
    price: float,
    order_id: Optional[str] = None,
    strategy: str = "paper",
    is_paper: bool = True,
) -> Dict[str, Any]:
    """Write a single fill into orders + executions + trades."""
    now = datetime.now(timezone.utc)
    today = date.today().isoformat()
    oid = order_id or f"paper-{uuid.uuid4().hex[:12]}"
    eid = f"exec-{uuid.uuid4().hex[:12]}"
    qty = int(abs(quantity))
    notional = abs(quantity) * price
    market = _market_of(ticker)
    conn = _connect()
    ensure_tables(conn)
    try:
        conn.execute(
            """INSERT INTO orders
               (order_id, ticker, side, order_type, quantity, filled_quantity,
                avg_fill_price, status, market, strategy, is_paper,
                submitted_at, filled_at, created_at, updated_at)
               VALUES (?, ?, ?, 'MKT', ?, ?, ?, 'FILLED', ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(order_id) DO UPDATE SET
                 status='FILLED', filled_quantity=excluded.filled_quantity,
                 avg_fill_price=excluded.avg_fill_price, filled_at=excluded.filled_at,
                 updated_at=excluded.updated_at
            """,
            (
                oid, ticker, side.upper(), qty, qty, price, market, strategy,
                1 if is_paper else 0, now.isoformat(), now.isoformat(),
                now.isoformat(), now.isoformat(),
            ),
        )
        conn.execute(
            """INSERT INTO executions
               (execution_id, order_id, ticker, side, quantity, price, notional,
                commission, executed_at, market, is_paper, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?)
            """,
            (
                eid, oid, ticker, side.upper(), qty, price, notional,
                now.isoformat(), market, 1 if is_paper else 0,
                now.isoformat(), now.isoformat(),
            ),
        )
        conn.execute(
            """INSERT INTO trades
               (ticker, trade_date, trade_time, side, quantity, price, commission,
                slippage_bps, notional, order_id, execution_id, market, currency,
                strategy, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, 0, 0, ?, ?, ?, ?, 'USD', ?, ?, ?)
            """,
            (
                ticker, today, now.isoformat(), side.upper(), qty, price,
                notional, oid, eid, market, strategy,
                now.isoformat(), now.isoformat(),
            ),
        )
        conn.commit()
        return {"order_id": oid, "execution_id": eid, "ticker": ticker, "quantity": qty}
    finally:
        conn.close()


def load_positions_for_api() -> Dict[str, Any]:
    """Load latest positions from DB for GET /positions."""
    today = date.today().isoformat()
    conn = _connect()
    ensure_tables(conn)
    try:
        rows = conn.execute(
            """SELECT ticker, quantity, avg_cost, market_price, market_value,
                      unrealized_pnl, weight, market
               FROM positions WHERE position_date = ?
               ORDER BY ABS(market_value) DESC""",
            (today,),
        ).fetchall()
        if not rows:
            rows = conn.execute(
                """SELECT ticker, quantity, avg_cost, market_price, market_value,
                          unrealized_pnl, weight, market
                   FROM positions
                   WHERE position_date = (SELECT MAX(position_date) FROM positions)
                   ORDER BY ABS(market_value) DESC"""
            ).fetchall()
        positions = []
        for r in rows:
            positions.append({
                "ticker": r[0],
                "quantity": r[1],
                "cost_basis": r[2],
                "market_price": r[3],
                "market_value": r[4],
                "unrealized_pnl": r[5],
                "weight": r[6],
                "market": r[7],
            })
        port = conn.execute(
            "SELECT nav, cash, num_positions FROM portfolios ORDER BY snapshot_date DESC LIMIT 1"
        ).fetchone()
        summary = {
            "total_market_value": float(port[0]) if port else 0.0,
            "cash": float(port[1]) if port else 0.0,
            "num_positions": int(port[2]) if port else len(positions),
            "position_count": int(port[2]) if port else len(positions),
            "total_pnl": sum(p["unrealized_pnl"] for p in positions),
            "unrealized_pnl": sum(p["unrealized_pnl"] for p in positions),
            "realized_pnl": 0.0,
            "source": "tiger_db",
        }
        return {"positions": positions, "summary": summary}
    finally:
        conn.close()


def load_orders_for_api(limit: int = 50, ticker: Optional[str] = None) -> List[Dict[str, Any]]:
    """Load recent orders from SQLite for GET /orders."""
    conn = _connect()
    ensure_tables(conn)
    try:
        if ticker:
            rows = conn.execute(
                """SELECT order_id, ticker, side, order_type, quantity, filled_quantity,
                          avg_fill_price, status, market, is_paper, submitted_at, filled_at, strategy
                   FROM orders WHERE UPPER(ticker) = UPPER(?)
                   ORDER BY COALESCE(filled_at, submitted_at, created_at) DESC LIMIT ?""",
                (ticker, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT order_id, ticker, side, order_type, quantity, filled_quantity,
                          avg_fill_price, status, market, is_paper, submitted_at, filled_at, strategy
                   FROM orders
                   ORDER BY COALESCE(filled_at, submitted_at, created_at) DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        out: List[Dict[str, Any]] = []
        for r in rows:
            out.append({
                "order_id": r[0],
                "ticker": r[1],
                "side": r[2],
                "order_type": r[3],
                "quantity": r[4],
                "filled_quantity": r[5],
                "avg_fill_price": r[6],
                "status": r[7],
                "market": r[8],
                "is_paper": bool(r[9]),
                "submitted_at": r[10],
                "filled_at": r[11],
                "strategy": r[12],
                "source": "tiger_db",
            })
        return out
    finally:
        conn.close()
