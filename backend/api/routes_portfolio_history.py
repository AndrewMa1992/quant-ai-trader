"""
组合历史数据接口路由 - NAV历史、年度收益、回撤时间线
从 portfolio_snapshots 表读取真实数据
"""
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Query
import sqlite3

router = APIRouter()

store = None

# Operational DB with real portfolio_snapshots data
_OP_DB = Path(__file__).parent.parent / "data" / "quant_trader.db"


def init(store_ref=None):
    """注入HistoricalStore依赖"""
    global store
    store = store_ref


def _get_conn() -> sqlite3.Connection:
    """
    获取数据库连接。
    优先使用 store 的 db_path，fallback 到 _OP_DB。
    """
    db_path = _OP_DB
    if store is not None and hasattr(store, "db_path"):
        db_path = store.db_path
    if not db_path.exists():
        # 最终 fallback：尝试项目根级的 data/ 目录
        db_path = Path(__file__).parent.parent.parent / "data" / "quant_trader.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


# ================================================================
# GET /analysis/portfolio-history — NAV 历史（最近90天）
# ================================================================

@router.get("/analysis/portfolio-history")
async def get_portfolio_history(days: int = Query(90, ge=1, le=365)):
    """获取组合NAV历史，含累计收益和回撤"""
    try:
        conn = _get_conn()
        cursor = conn.cursor()

        # 按日采样：每天取一条记录（最早的那条，或 AVG）
        cursor.execute("""
            SELECT 
                SUBSTR(timestamp, 1, 10) as snapshot_date,
                AVG(total_value) as nav
            FROM portfolio_snapshots 
            GROUP BY snapshot_date
            ORDER BY snapshot_date DESC
            LIMIT ?
        """, (days,))

        raw_rows = cursor.fetchall()
        conn.close()

        if not raw_rows:
            return {"history": []}

        # 按日期升序排列以便计算累计收益和回撤
        rows = list(reversed(raw_rows))

        if not rows:
            return {"history": []}

        first_value = rows[0]["nav"]
        peak = 0.0
        history = []

        for row in rows:
            nav = row["nav"]
            date_str = row["snapshot_date"]

            if first_value and first_value != 0:
                cumulative_return = (nav - first_value) / first_value
            else:
                cumulative_return = 0.0

            if nav > peak:
                peak = nav

            drawdown_from_peak = (nav - peak) / peak if peak > 0 else 0.0

            history.append({
                "date": date_str,
                "nav": round(nav, 2),
                "cumulative_return": round(cumulative_return, 4),
                "drawdown_from_peak": round(drawdown_from_peak, 4),
            })

        return {"history": history}

    except Exception as e:
        return {"history": [], "error": str(e)}


# ================================================================
# GET /analysis/yearly-returns — 年度收益聚合
# ================================================================

@router.get("/analysis/yearly-returns")
async def get_yearly_returns():
    """从 portfolio_snapshots 聚合计算年度收益"""
    try:
        conn = _get_conn()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT 
                CAST(SUBSTR(timestamp, 1, 4) AS INTEGER) as year,
                AVG(total_value) as avg_value
            FROM portfolio_snapshots 
            GROUP BY year 
            ORDER BY year
        """)

        yearly_snapshots = cursor.fetchall()

        if not yearly_snapshots:
            conn.close()
            return {"yearly_returns": []}

        # 按年计算收益：取每年的首尾快照
        yearly_returns = []
        for row in yearly_snapshots:
            year = row["year"]
            cursor.execute("""
                SELECT total_value 
                FROM portfolio_snapshots 
                WHERE SUBSTR(timestamp, 1, 4) = ?
                ORDER BY timestamp ASC LIMIT 1
            """, (str(year),))
            first_row = cursor.fetchone()

            cursor.execute("""
                SELECT total_value 
                FROM portfolio_snapshots 
                WHERE SUBSTR(timestamp, 1, 4) = ?
                ORDER BY timestamp DESC LIMIT 1
            """, (str(year),))
            last_row = cursor.fetchone()

            if first_row and last_row:
                first_val = first_row["total_value"]
                last_val = last_row["total_value"]
                if first_val and first_val != 0:
                    return_pct = round((last_val - first_val) / first_val * 100, 2)
                else:
                    return_pct = 0.0
            else:
                return_pct = 0.0

            yearly_returns.append({
                "year": year,
                "return_pct": return_pct,
            })

        conn.close()
        return {"yearly_returns": yearly_returns}

    except Exception as e:
        return {"yearly_returns": [], "error": str(e)}


# ================================================================
# GET /risk/drawdown-history — 回撤时间线
# ================================================================

@router.get("/risk/drawdown-history")
async def get_drawdown_history():
    """获取完整的回撤时间线"""
    try:
        conn = _get_conn()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT 
                SUBSTR(timestamp, 1, 10) as snapshot_date,
                AVG(total_value) as nav
            FROM portfolio_snapshots 
            GROUP BY snapshot_date
            ORDER BY snapshot_date
        """)

        rows = cursor.fetchall()
        conn.close()

        if not rows:
            return {"drawdown_history": []}

        # 计算回撤时间线
        peak = 0.0
        drawdown_history = []
        for row in rows:
            nav = row["nav"]
            date_str = row["snapshot_date"]
            if nav > peak:
                peak = nav
            dd = (nav - peak) / peak if peak > 0 else 0.0

            drawdown_history.append({
                "date": date_str,
                "drawdown": round(dd, 4),
            })

        return {"drawdown_history": drawdown_history}

    except Exception as e:
        return {"drawdown_history": [], "error": str(e)}
