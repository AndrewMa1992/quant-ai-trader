"""
历史数据存储层 - SQLite + Parquet 混合存储
支持增量更新、高效查询
"""
import sqlite3
from datetime import datetime, date
from pathlib import Path
from typing import Dict, List, Optional
import pandas as pd
from loguru import logger

from backend.config import DB_PATH, DATA_DIR


class HistoricalStore:
    """
    本地数据持久化
    - SQLite 存储元数据与交易记录
    - Parquet 存储历史行情数据（高效压缩）
    - 增量更新策略
    """

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or DB_PATH
        self.parquet_dir = DATA_DIR / "parquet"
        self.parquet_dir.mkdir(parents=True, exist_ok=True)
        self._init_db()

    # ================================================================
    # 数据库初始化
    # ================================================================

    def _init_db(self):
        """初始化数据库表"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        # 行情元数据表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS market_metadata (
                ticker TEXT PRIMARY KEY,
                last_updated TEXT,
                data_start TEXT,
                data_end TEXT,
                total_rows INTEGER,
                interval TEXT DEFAULT '1d'
            )
        """)

        # 交易记录表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL,
                side TEXT NOT NULL,  -- buy / sell
                quantity REAL NOT NULL,
                price REAL NOT NULL,
                value REAL NOT NULL,
                commission REAL DEFAULT 0,
                timestamp TEXT NOT NULL,
                signal_strength REAL,
                strategy TEXT,
                status TEXT DEFAULT 'filled',
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)

        # 组合快照表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS portfolio_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                total_value REAL NOT NULL,
                cash REAL NOT NULL,
                positions_value REAL NOT NULL,
                daily_pnl REAL,
                total_pnl REAL,
                drawdown REAL,
                sharpe_ratio REAL
            )
        """)

        # 信号记录表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                signal_type TEXT NOT NULL,
                signal_value REAL,
                confidence REAL,
                model_name TEXT,
                details TEXT
            )
        """)
        # 实时价格缓存表（对冲基金级性能）
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS price_ticks (
                ticker TEXT NOT NULL,
                price REAL NOT NULL,
                volume REAL,
                timestamp TEXT NOT NULL,
                market TEXT DEFAULT 'US',
                PRIMARY KEY (ticker, timestamp)
            )
        """)

        # 创建索引加速查询
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_ticker ON trades(ticker)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_time ON trades(timestamp)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_signals_time ON signals(timestamp)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_signals_ticker ON signals(ticker)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_time ON portfolio_snapshots(timestamp)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_price_ticks_ticker ON price_ticks(ticker)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_price_ticks_time ON price_ticks(timestamp)")

        # WAL 模式：写入性能提升 10x，支持并发读写
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA cache_size=-64000")  # 64MB 缓存
        cursor.execute("PRAGMA temp_store=MEMORY")
        cursor.execute("PRAGMA mmap_size=268435456")  # 256MB 内存映射

        conn.commit()
        conn.close()
        logger.info(f"数据库初始化完成: {self.db_path} (WAL模式, 64MB缓存)")

    # ================================================================
    # 行情数据读写
    # ================================================================

    def save_ohlcv(self, df: pd.DataFrame, ticker: str, interval: str = "1d"):
        """
        保存OHLCV数据到Parquet

        Args:
            df: OHLCV DataFrame（含技术指标）
            ticker: 股票代码
            interval: 数据周期
        """
        if df.empty:
            return

        file_path = self.parquet_dir / f"{ticker}_{interval}.parquet"

        # 检查已有数据，进行增量合并
        if file_path.exists():
            existing = pd.read_parquet(file_path)
            combined = pd.concat([existing, df])
            combined = combined[~combined.index.duplicated(keep="last")]
            combined = combined.sort_index()
            combined.to_parquet(file_path)
            logger.info(f"📝 {ticker} 增量更新: {len(df)} 新行 → 共 {len(combined)} 行")
        else:
            df.to_parquet(file_path)
            logger.info(f"📝 {ticker} 新建存储: {len(df)} 行")

        # 更新元数据
        self._update_metadata(ticker, interval, df)

    def load_ohlcv(self, ticker: str, interval: str = "1d") -> pd.DataFrame:
        """加载OHLCV数据"""
        file_path = self.parquet_dir / f"{ticker}_{interval}.parquet"
        if file_path.exists():
            return pd.read_parquet(file_path)
        return pd.DataFrame()

    def get_latest_date(self, ticker: str, interval: str = "1d") -> Optional[date]:
        """获取最新数据日期"""
        df = self.load_ohlcv(ticker, interval)
        if not df.empty:
            return df.index[-1].date() if hasattr(df.index[-1], "date") else df.index[-1]
        return None

    # ================================================================
    # 交易记录
    # ================================================================

    def save_trade(self, trade_data: Dict):
        """保存交易记录"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO trades (ticker, side, quantity, price, value, commission,
                                timestamp, signal_strength, strategy, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            trade_data["ticker"],
            trade_data["side"],
            trade_data["quantity"],
            trade_data["price"],
            trade_data["value"],
            trade_data.get("commission", 0),
            trade_data.get("timestamp", datetime.now().isoformat()),
            trade_data.get("signal_strength"),
            trade_data.get("strategy"),
            trade_data.get("status", "filled"),
        ))
        conn.commit()
        trade_id = cursor.lastrowid
        conn.close()
        return trade_id

    def get_trades(
        self,
        ticker: Optional[str] = None,
        limit: int = 100,
        since: Optional[str] = None
    ) -> pd.DataFrame:
        """获取历史交易记录"""
        conn = sqlite3.connect(str(self.db_path))
        query = "SELECT * FROM trades"
        conditions = []
        params = []

        if ticker:
            conditions.append("ticker = ?")
            params.append(ticker)
        if since:
            conditions.append("timestamp >= ?")
            params.append(since)

        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        df = pd.read_sql_query(query, conn, params=params)
        conn.close()
        return df

    # ================================================================
    # 组合快照
    # ================================================================

    def save_snapshot(self, snapshot: Dict):
        """保存组合快照"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO portfolio_snapshots
                (timestamp, total_value, cash, positions_value,
                 daily_pnl, total_pnl, drawdown, sharpe_ratio)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            snapshot.get("timestamp", datetime.now().isoformat()),
            snapshot["total_value"],
            snapshot["cash"],
            snapshot["positions_value"],
            snapshot.get("daily_pnl"),
            snapshot.get("total_pnl"),
            snapshot.get("drawdown"),
            snapshot.get("sharpe_ratio"),
        ))
        conn.commit()
        conn.close()

    def get_portfolio_history(self, limit: int = 500) -> pd.DataFrame:
        """获取组合历史数据"""
        conn = sqlite3.connect(str(self.db_path))
        df = pd.read_sql_query(
            "SELECT * FROM portfolio_snapshots ORDER BY timestamp DESC LIMIT ?",
            conn, params=(limit,)
        )
        conn.close()
        return df

    # ================================================================
    # 信号记录
    # ================================================================

    def save_signal(self, signal: Dict):
        """保存交易信号"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO signals (ticker, timestamp, signal_type, signal_value,
                                 confidence, model_name, details)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            signal["ticker"],
            signal.get("timestamp", datetime.now().isoformat()),
            signal["signal_type"],
            signal.get("signal_value"),
            signal.get("confidence"),
            signal.get("model_name"),
            signal.get("details"),
        ))
        conn.commit()
        conn.close()

    # ================================================================
    # 实时数据方法（对冲基金级批量写入）
    # ================================================================

    def save_price_ticks_batch(self, prices: Dict[str, float]):
        """批量保存实时价格（单事务，高性能）"""
        now = datetime.now().isoformat()
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        cursor.execute("BEGIN")
        for ticker, price in prices.items():
            market = "HK" if ".HK" in ticker else ("SG" if ".SI" in ticker else "US")
            cursor.execute(
                "INSERT OR REPLACE INTO price_ticks (ticker, price, timestamp, market) VALUES (?, ?, ?, ?)",
                (ticker, round(price, 4), now, market)
            )
        conn.commit()
        conn.close()

    def save_signals_batch(self, signals: Dict[str, Dict]):
        """批量保存信号（单事务）"""
        now = datetime.now().isoformat()
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        cursor.execute("BEGIN")
        for ticker, sig in signals.items():
            cursor.execute(
                "INSERT INTO signals (ticker, timestamp, signal_type, signal_value, confidence, model_name) VALUES (?, ?, ?, ?, ?, ?)",
                (ticker, now, sig.get("decision", "hold"),
                 sig.get("strength", 0), sig.get("confidence", 0),
                 sig.get("strategy", "ensemble"))
            )
        conn.commit()
        conn.close()

    def save_trades_batch(self, trades: List[Dict]):
        """批量保存交易"""
        if not trades:
            return
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        cursor.execute("BEGIN")
        for t in trades:
            cursor.execute(
                "INSERT INTO trades (ticker, side, quantity, price, value, timestamp, signal_strength, strategy) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (t["ticker"], t["side"], t["quantity"], t.get("price", 0),
                 t.get("value", 0), t.get("timestamp", datetime.now().isoformat()),
                 t.get("signal_strength", 0), t.get("strategy", "ensemble"))
            )
        conn.commit()
        conn.close()
        logger.debug(f"已保存 {len(trades)} 笔交易")

    def get_latest_prices(self) -> Dict[str, float]:
        """获取最新价格快照"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        cursor.execute("""
            SELECT ticker, price FROM price_ticks
            WHERE timestamp = (SELECT MAX(timestamp) FROM price_ticks)
        """)
        result = {row[0]: row[1] for row in cursor.fetchall()}
        conn.close()
        return result

    # ================================================================
    # 内部方法
    # ================================================================

    def _update_metadata(self, ticker: str, interval: str, df: pd.DataFrame):
        """更新数据元数据"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        dates = df.index.tolist()
        data_start = str(dates[0]) if hasattr(dates[0], "date") else str(dates[0])
        data_end = str(dates[-1]) if hasattr(dates[-1], "date") else str(dates[-1])

        cursor.execute("""
            INSERT OR REPLACE INTO market_metadata
                (ticker, last_updated, data_start, data_end, total_rows, interval)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            f"{ticker}_{interval}",
            datetime.now().isoformat(),
            data_start,
            data_end,
            len(df),
            interval,
        ))
        conn.commit()
        conn.close()

    def get_all_tickers(self) -> List[str]:
        """获取所有已存储 ticker 列表"""
        conn = sqlite3.connect(str(self.db_path))
        df = pd.read_sql_query(
            "SELECT DISTINCT ticker FROM market_metadata ORDER BY ticker", conn
        )
        conn.close()
        return df["ticker"].tolist() if not df.empty else []

    def get_storage_stats(self) -> Dict:
        """获取存储统计"""
        conn = sqlite3.connect(str(self.db_path))

        total_trades = pd.read_sql_query(
            "SELECT COUNT(*) as cnt FROM trades", conn
        ).iloc[0]["cnt"]

        total_signals = pd.read_sql_query(
            "SELECT COUNT(*) as cnt FROM signals", conn
        ).iloc[0]["cnt"]

        tickers_count = len(self.get_all_tickers())

        # Parquet 文件大小
        parquet_size = sum(f.stat().st_size for f in self.parquet_dir.glob("*.parquet"))

        conn.close()

        return {
            "tickers": tickers_count,
            "total_trades": total_trades,
            "total_signals": total_signals,
            "parquet_size_mb": round(parquet_size / 1024 / 1024, 2),
        }
