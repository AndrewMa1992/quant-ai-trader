"""
分析接口路由
"""
from fastapi import APIRouter

router = APIRouter(prefix="/api/analysis", tags=["analysis"])

strategy = None
ensemble = None
backtester = None


def init(strat_ref, ensemble_ref, bt_ref):
    global strategy, ensemble, backtester
    strategy = strat_ref
    ensemble = ensemble_ref
    backtester = bt_ref


@router.get("/latest-signals")
async def get_latest_signals():
    """获取最新信号"""
    if strategy is None:
        return {"error": "策略未初始化"}
    return {
        "signals": {
            ticker: signal
            for ticker, signal in strategy.last_signals.items()
        },
        "cycle": strategy._total_cycles,
    }


@router.get("/ensemble-status")
async def get_ensemble_status():
    """获取融合引擎状态"""
    if ensemble is None:
        return {"error": "融合引擎未初始化"}
    return ensemble.get_status()


@router.get("/strategy-status")
async def get_strategy_status():
    """获取策略状态"""
    if strategy is None:
        return {"error": "策略未初始化"}
    return strategy.get_status()


@router.get("/backtest-results")
async def get_backtest_results():
    """获取回测结果"""
    if backtester is None:
        return {"error": "回测引擎未初始化"}
    return {
        name: {k: v for k, v in result.items() if k != "value_history"}
        for name, result in backtester.results.items()
    }


@router.post("/run-backtest")
async def run_backtest():
    """运行回测"""
    # 简化版：实际会异步运行
    return {"message": "回测已排队", "status": "pending"}
