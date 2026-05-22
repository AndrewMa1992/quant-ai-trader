"""
交易接口路由
"""
from typing import Optional
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
