"""
Trading API routes.
"""
from typing import Optional
from datetime import datetime
import numpy as np
from fastapi import APIRouter, Query
from pydantic import BaseModel

router = APIRouter(prefix="/api/trade", tags=["trading"])

# P0-3: v2 risk router for circuit breaker management
risk_v2_router = APIRouter(prefix="/api/v2/risk", tags=["risk-v2"])

# Injected from main.py
executor = None
portfolio = None
risk_manager = None
store = None


def init(
    exec_ref, port_ref, risk_ref, store_ref
):
    """Inject dependencies."""
    global executor, portfolio, risk_manager, store
    executor = exec_ref
    portfolio = port_ref
    risk_manager = risk_ref
    store = store_ref


@router.get("/portfolio")
async def get_portfolio():
    """Return portfolio state (Tiger live data preferred)."""
    if portfolio is None:
        return {"error": "Portfolio manager is not initialized"}
    
    from backend.data_engine.tiger_client import tiger_client
    
    # On each dashboard query, align initial_capital with Tiger
    from backend.data_engine.tiger_client import tiger_client
    tiger_synced = tiger_client.is_connected()
    tiger_data = tiger_client.get_status() if tiger_synced else None
    
    if tiger_synced:
        try:
            tiger_acct = tiger_client.get_account_info()
            if tiger_acct and tiger_acct.get("total_value", 0) > 0:
                tiger_total = tiger_acct["total_value"]
                gap = abs(tiger_total - portfolio.initial_capital) / max(portfolio.initial_capital, 1)
                # Gap > 1% → auto-correct initial_capital
                if gap > 0.01:
                    portfolio.initial_capital = tiger_total
        except Exception:
            pass

    # Prices from the realtime engine
    from backend.data_engine.realtime import RealtimeEngine
    prices = {}
    try:
        rt = RealtimeEngine.__dict__.get('_instance')
    except:
        pass

    positions_list = []
    for t, s in portfolio.positions.items():
        pos = {
            "ticker": t,
            "shares": round(s, 4),
            "avg_cost": round(portfolio.avg_costs.get(t, 0), 2),
            "current_price": 0,
            "current_price_usd": 0,
            "currency": "USD",
            "market_value": 0,
            "unrealized_pnl": 0,
            "unrealized_pnl_pct": 0,
            "allocation": 0,
        }
        positions_list.append(pos)

    return {
        "metrics": portfolio.get_metrics(),
        "positions": positions_list,
        "value_history": [
            {"time": t.isoformat(), "value": v}
            for t, v in portfolio.value_history[-100:]
        ] if hasattr(portfolio, 'value_history') else [],
        "tiger_synced": tiger_synced,
        "tiger_data": tiger_data,
    }


@router.get("/positions")
async def get_positions():
    """Return position details."""
    if portfolio is None:
        return {"error": "Portfolio manager is not initialized"}
    # Simplified payload; the frontend computes derived fields
    return {
        "positions": [
            {"ticker": t, "shares": round(s, 4)}
            for t, s in portfolio.positions.items()
        ],
        "cash": round(portfolio.cash, 2),
    }


@router.get("/history")
async def get_trade_history(
    ticker: Optional[str] = None,
    limit: int = Query(100, le=500),
    since: Optional[str] = None,
):
    """Return trade history."""
    if store is None:
        return {"error": "Store is not initialized"}
    trades = store.get_trades(ticker, limit, since)
    if trades.empty:
        return {"trades": []}
    return {"trades": trades.to_dict(orient="records")}


@router.get("/execution-summary")
async def get_execution_summary():
    """Return execution summary."""
    if executor is None:
        return {"error": "Executor is not initialized"}
    return executor.get_execution_summary()


@router.get("/risk-status")
async def get_risk_status():
    """Return risk-control status."""
    if risk_manager is None:
        return {"error": "Risk manager is not initialized"}
    return risk_manager.get_status()


# ============================================================
# Dashboard extras: Sharpe / max drawdown / win rate
# ============================================================
@router.get("/dashboard")
async def get_dashboard_metrics():
    """Return live dashboard metrics (including DB-backed figures)."""
    if portfolio is None:
        return {"error": "Portfolio manager is not initialized"}

    metrics = portfolio.get_metrics()
    value_history = getattr(portfolio, 'value_history', [])

    # Sharpe Ratio
    sharpe = _compute_sharpe(value_history)

    # Max drawdown
    max_dd, max_dd_pct = _compute_max_drawdown(value_history)

    # Win rate from the trades table
    win_rate, profit_factor = _compute_wr_pf()

    # Calmar Ratio
    calmar = _compute_calmar(value_history, max_dd_pct)

    # Snapshot count from portfolio_snapshots
    snapshot_count = _get_snapshot_count()

    return {
        **metrics,
        "sharpe_ratio": round(sharpe, 4),
        "max_drawdown": round(max_dd, 2),
        "max_drawdown_pct": round(max_dd_pct, 4),
        "win_rate": round(win_rate, 4),
        "profit_factor": round(profit_factor, 4),
        "calmar_ratio": round(calmar, 4),
        "snapshot_count": snapshot_count,
        "timestamp": datetime.now().isoformat(),
    }


def _compute_sharpe(value_history, risk_free_rate=0.05):
    """Compute annualized Sharpe Ratio."""
    if len(value_history) < 3:
        return 0.0
    values = [v for _, v in value_history]
    returns = np.diff(values) / (np.array(values[:-1]) + 1e-8)
    if len(returns) < 2 or returns.std() == 0:
        return 0.0
    excess = returns.mean() - risk_free_rate / 252
    return float(excess / (returns.std() + 1e-8) * np.sqrt(252))


def _compute_max_drawdown(value_history):
    """Compute maximum drawdown."""
    if len(value_history) < 2:
        return 0.0, 0.0
    values = np.array([v for _, v in value_history])
    peak = np.maximum.accumulate(values)
    drawdowns = (values - peak) / (peak + 1e-8)
    max_dd_idx = drawdowns.argmin()
    return float(values[max_dd_idx] - peak[max_dd_idx]), float(drawdowns.min())


def _compute_wr_pf():
    """Compute win rate and profit factor."""
    if store is None:
        return 0.0, 0.0
    try:
        trades = store.get_trades(ticker=None, limit=500)
        if trades.empty or len(trades) < 2:
            return 0.0, 0.0

        # P&L grouped by ticker
        wins, losses = 0, 0
        total_profit, total_loss = 0.0, 0.0
        for ticker, group in trades.groupby('ticker'):
            buys = group[group['side'] == 'buy']
            sells = group[group['side'] == 'sell']
            if buys.empty or sells.empty:
                continue
            avg_buy = buys['price'].mean()
            avg_sell = sells['price'].mean()
            pnl = (avg_sell - avg_buy) * sells['quantity'].sum()
            if pnl > 0:
                wins += 1
                total_profit += pnl
            else:
                losses += 1
                total_loss += abs(pnl)

        total_trades = wins + losses
        wr = wins / total_trades if total_trades > 0 else 0.0
        pf = total_profit / (total_loss + 1e-8)
        return float(wr), float(pf)
    except Exception:
        return 0.0, 0.0


def _compute_calmar(value_history, max_dd_pct):
    """Compute Calmar Ratio."""
    if len(value_history) < 3 or max_dd_pct == 0:
        return 0.0
    values = [v for _, v in value_history]
    total_return = (values[-1] - values[0]) / (values[0] + 1e-8)
    days = len(values)
    annual_return = (1 + total_return) ** (252 / max(days, 1)) - 1
    return float(annual_return / abs(max_dd_pct + 1e-8))


def _get_snapshot_count() -> int:
    """Read snapshot count from the portfolio_snapshots table."""
    try:
        import sqlite3
        from pathlib import Path
        db_path = Path(__file__).parent.parent / "data" / "quant_trader.db"
        if store is not None and hasattr(store, "db_path"):
            db_path = store.db_path
        conn = sqlite3.connect(str(db_path))
        count = conn.execute("SELECT COUNT(*) FROM portfolio_snapshots").fetchone()[0]
        conn.close()
        return count
    except Exception:
        return 0


# ============================================================
# Tiger live account
# ============================================================
@router.get("/tiger-account")
async def get_tiger_account():
    """Query Tiger live-account status (positions and account info)."""
    from backend.data_engine.tiger_client import tiger_client
    result = {
        "connected": tiger_client.is_connected(),
        "simulation_account": tiger_client._simulation_account,
        "real_account": tiger_client._real_account,
        "status": {},
        "account_info": None,
        "positions": [],
        "position_count": 0,
        "timestamp": datetime.now().isoformat(),
    }
    if tiger_client.is_connected():
        try:
            status = tiger_client.get_status()
            result["status"] = status
            
            # Use local state already synced at startup (avoid extra Tiger API calls)
            result["position_count"] = len(portfolio.positions)
            result["positions"] = [
                {
                    "ticker": t,
                    "shares": round(s, 4),
                    "avg_cost": round(portfolio.avg_costs.get(t, 0), 2),
                    "market_value": round(s * portfolio.avg_costs.get(t, 0), 2),
                    "unrealized_pnl": 0,
                    "realized_pnl": 0,
                }
                for t, s in portfolio.positions.items()
            ]
            result["account_info"] = {
                "cash": round(portfolio.cash, 2),
                "market_value": round(portfolio.total_value - portfolio.cash, 2),
                "total_value": round(portfolio.total_value, 2),
                "buying_power": round(portfolio.cash, 2),
            }
        except Exception as e:
            result["status"] = {"error": str(e)}
    return result


@router.post("/tiger-refresh")
async def refresh_from_tiger():
    """Force a live refresh from Tiger."""
    from backend.data_engine.tiger_client import tiger_client
    from configs.settings import settings
    
    if not tiger_client.is_connected():
        tiger_client.connect()
    if not tiger_client.is_connected():
        return {"refreshed": False, "error": "Tiger is not connected"}
    
    # Call the Tiger SDK directly against the live account
    tiger_client.connect()
    try:
        # Use the live account (20874631), not the paper account
        real_account = settings.TIGER_ACCOUNT  # 20874631
        assets = tiger_client._trade_client.get_assets(account=real_account)
        
        if assets and isinstance(assets, list) and len(assets) > 0:
            a = assets[0]
            summary = a.summary if hasattr(a, 'summary') and a.summary else None
            cash = summary.cash if summary and hasattr(summary, 'cash') else 0
            total = summary.net_liquidation if summary and hasattr(summary, 'net_liquidation') else 0
        else:
            # Fallback
            cash = 0
            total = 0
    except Exception:
        cash = 0
        total = 0
    
    # Get positions  
    positions = tiger_client.get_positions(force=True)
    mkt_value = sum(p.get("market_value", 0) for p in positions)
    
    # Compute correct total if Tiger API failed
    if total <= 0:
        total = cash + mkt_value
    
    if total < 10 or cash < 0:
        return {"refreshed": False, "error": f"Invalid data: cash={cash}, total={total}"}
    
    old_ic = portfolio.initial_capital
    portfolio.cash = cash
    portfolio.total_value = total
    portfolio.initial_capital = total
    portfolio.save_state()
    
    return {
        "refreshed": True,
        "cash": cash,
        "total_value": total,
        "market_value": mkt_value,
        "initial_capital": total,
        "initial_capital_was": old_ic,
        "positions": len(positions),
        "timestamp": datetime.now().isoformat(),
    }
    return result


@router.post("/tiger-reconcile")
async def reconcile_with_tiger():
    """Manually trigger a reconciliation against Tiger Brokers."""
    result = portfolio.reconcile_with_tiger()
    return result


@router.post("/tiger-fix-shorts")
async def fix_short_positions():
    """Cover all negative (short) positions on the Tiger account."""
    from backend.data_engine.tiger_client import tiger_client
    
    if not tiger_client.is_connected():
        tiger_client.connect()
    if not tiger_client.is_connected():
        return {"fixed": False, "error": "Tiger not connected"}
    
    # Force reconnect to fetch latest data
    tiger_client.connect()
    positions = tiger_client.get_positions()
    
    negatives = [p for p in positions if p["shares"] < 0]
    if not negatives:
        return {"fixed": True, "neg_count": 0, "message": "No negative positions"}
    
    results = []
    for p in negatives:
        ticker = p["ticker"]
        shares = int(abs(p["shares"]))
        try:
            order = tiger_client.place_order(
                ticker=ticker, action="BUY",
                quantity=shares, order_type="MKT"
            )
            results.append({
                "ticker": ticker, "shares": shares,
                "order_id": order.get("order_id") if order else None,
                "status": "SUBMITTED" if order else "FAILED"
            })
        except Exception as e:
            results.append({
                "ticker": ticker, "shares": shares,
                "error": str(e), "status": "ERROR"
            })
    
    # Re-sync local state
    portfolio.sync_from_tiger(force=True)
    
    return {
        "fixed": True,
        "neg_count": len(negatives),
        "orders": results,
        "message": f"Submitted {len(results)} buy orders to cover shorts"
    }


# ============================================================
# P0-3: v2 Risk API — Circuit Breaker Management
# ============================================================

class BreakerToggleRequest(BaseModel):
    """Circuit-breaker mode toggle request."""
    mode: str  # "hard" or "warn"


@risk_v2_router.get("/circuit_breaker")
async def get_circuit_breaker_status():
    """Return current circuit-breaker status (including breaker_mode)."""
    if risk_manager is None:
        return {"error": "Risk manager is not initialized"}
    status = risk_manager.get_status()
    return {
        "circuit_breaker_triggered": status.get("circuit_breaker_triggered", False),
        "breaker_mode": status.get("breaker_mode", "warn"),
        "daily_pnl": status.get("daily_pnl", 0),
        "daily_pnl_pct": status.get("daily_pnl_pct", 0),
        "max_drawdown": status.get("max_drawdown", 0),
        "peak_value": status.get("peak_value", 0),
        "timestamp": datetime.now().isoformat(),
    }


@risk_v2_router.post("/circuit_breaker/reset")
async def reset_circuit_breaker():
    """Force-reset the circuit breaker and recalibrate peak value."""
    if risk_manager is None:
        return {"error": "Risk manager is not initialized"}
    try:
        risk_manager.force_reset_circuit()
        return {
            "reset": True,
            "breaker_mode": risk_manager.breaker_mode,
            "circuit_breaker_triggered": risk_manager.circuit_breaker_triggered,
            "peak_value": round(risk_manager.peak_value, 2),
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        return {"reset": False, "error": str(e)}


@risk_v2_router.post("/circuit_breaker/toggle")
async def toggle_circuit_breaker(req: BreakerToggleRequest):
    """Toggle circuit-breaker mode: hard / warn."""
    if risk_manager is None:
        return {"error": "Risk manager is not initialized"}
    if req.mode not in ("hard", "warn"):
        return {"error": f"Invalid mode: {req.mode}; only 'hard' or 'warn' is supported"}
    try:
        risk_manager.toggle_breaker_mode(req.mode)
        return {
            "toggled": True,
            "breaker_mode": risk_manager.breaker_mode,
            "circuit_breaker_triggered": risk_manager.circuit_breaker_triggered,
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        return {"toggled": False, "error": str(e)}
