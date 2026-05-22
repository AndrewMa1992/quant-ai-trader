"""
交易接口路由
"""
from typing import Optional
from datetime import datetime
import numpy as np
from fastapi import APIRouter, Query

router = APIRouter(prefix="/api/trade", tags=["trading"])

# 这些会在 main.py 中注入
executor = None
portfolio = None
risk_manager = None
store = None


def init(
    exec_ref, port_ref, risk_ref, store_ref
):
    """注入依赖"""
    global executor, portfolio, risk_manager, store
    executor = exec_ref
    portfolio = port_ref
    risk_manager = risk_ref
    store = store_ref


@router.get("/portfolio")
async def get_portfolio():
    """获取组合状态"""
    if portfolio is None:
        return {"error": "组合管理器未初始化"}
    # 从 realtime 获取价格
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
    }


@router.get("/positions")
async def get_positions():
    """获取持仓详情"""
    if portfolio is None:
        return {"error": "组合管理器未初始化"}
    # 简化返回，前端会自行计算
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
    """获取交易历史"""
    if store is None:
        return {"error": "存储未初始化"}
    trades = store.get_trades(ticker, limit, since)
    if trades.empty:
        return {"trades": []}
    return {"trades": trades.to_dict(orient="records")}


@router.get("/execution-summary")
async def get_execution_summary():
    """获取执行摘要"""
    if executor is None:
        return {"error": "执行器未初始化"}
    return executor.get_execution_summary()


@router.get("/risk-status")
async def get_risk_status():
    """获取风控状态"""
    if risk_manager is None:
        return {"error": "风控未初始化"}
    return risk_manager.get_status()


# ============================================================
# 仪表盘增强: Sharpe / 最大回撤 / 胜率
# ============================================================
@router.get("/dashboard")
async def get_dashboard_metrics():
    """获取实时仪表盘指标"""
    if portfolio is None:
        return {"error": "组合管理器未初始化"}

    metrics = portfolio.get_metrics()
    value_history = getattr(portfolio, 'value_history', [])

    # 计算 Sharpe Ratio
    sharpe = _compute_sharpe(value_history)

    # 计算最大回撤
    max_dd, max_dd_pct = _compute_max_drawdown(value_history)

    # 计算胜率
    win_rate, profit_factor = _compute_wr_pf()

    # 计算 Calmar Ratio
    calmar = _compute_calmar(value_history, max_dd_pct)

    return {
        **metrics,
        "sharpe_ratio": round(sharpe, 4),
        "max_drawdown": round(max_dd, 2),
        "max_drawdown_pct": round(max_dd_pct, 4),
        "win_rate": round(win_rate, 4),
        "profit_factor": round(profit_factor, 4),
        "calmar_ratio": round(calmar, 4),
        "snapshot_count": len(value_history),
        "timestamp": datetime.now().isoformat(),
    }


def _compute_sharpe(value_history, risk_free_rate=0.05):
    """计算年化 Sharpe Ratio"""
    if len(value_history) < 3:
        return 0.0
    values = [v for _, v in value_history]
    returns = np.diff(values) / (np.array(values[:-1]) + 1e-8)
    if len(returns) < 2 or returns.std() == 0:
        return 0.0
    excess = returns.mean() - risk_free_rate / 252
    return float(excess / (returns.std() + 1e-8) * np.sqrt(252))


def _compute_max_drawdown(value_history):
    """计算最大回撤"""
    if len(value_history) < 2:
        return 0.0, 0.0
    values = np.array([v for _, v in value_history])
    peak = np.maximum.accumulate(values)
    drawdowns = (values - peak) / (peak + 1e-8)
    max_dd_idx = drawdowns.argmin()
    return float(values[max_dd_idx] - peak[max_dd_idx]), float(drawdowns.min())


def _compute_wr_pf():
    """计算胜率和盈利因子"""
    if store is None:
        return 0.0, 0.0
    try:
        trades = store.get_trades(ticker=None, limit=500)
        if trades.empty or len(trades) < 2:
            return 0.0, 0.0

        # 按股票分组计算 P&L
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
    """计算 Calmar Ratio"""
    if len(value_history) < 3 or max_dd_pct == 0:
        return 0.0
    values = [v for _, v in value_history]
    total_return = (values[-1] - values[0]) / (values[0] + 1e-8)
    days = len(values)
    annual_return = (1 + total_return) ** (252 / max(days, 1)) - 1
    return float(annual_return / abs(max_dd_pct + 1e-8))


# ============================================================
# 老虎实盘账户
# ============================================================
@router.get("/tiger-account")
async def get_tiger_account():
    """查询老虎实盘/模拟账号状态"""
    from backend.data_engine.tiger_client import tiger_client
    result = {
        "connected": tiger_client.is_connected(),
        "simulation_account": tiger_client._simulation_account,
        "real_account": tiger_client._real_account,
        "status": {},
        "timestamp": datetime.now().isoformat(),
    }
    if tiger_client.is_connected():
        try:
            status = tiger_client.get_status()
            result["status"] = status
        except Exception as e:
            result["status"] = {"error": str(e)}
    return result
