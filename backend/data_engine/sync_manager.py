"""
同步状态管理器
管理增量同步状态，通过 sync_status 表读取/写入同步进度。
支持分页游标、断点续传和全量同步判断。
"""
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional
from loguru import logger

from configs.settings import settings


class SyncManager:
    """
    同步状态管理器

    管理所有数据类型的同步进度：
    - 记录每种 sync_type 的上次同步时间
    - 保存分页游标以支持断点续传
    - 判断是否需要全量同步

    用法:
        mgr = SyncManager(store.historical_store)
        last = mgr.get_last_sync("orders")
        mgr.update_sync("orders", cursor="page_3", records=50)
        if mgr.needs_full_sync("orders", max_age_hours=24):
            run_full_sync()
    """

    # 默认全量同步的最长间隔（小时）
    DEFAULT_FULL_SYNC_INTERVAL = 24
    # 各类型推荐的全量同步间隔
    SYNC_INTERVALS = {
        "orders": 24,
        "transactions": 24,
        "fundamentals": 24,
        "assets": 1,
        "calendar": 168,        # 每周
        "capital_flow": 24,
        "corporate_events": 24,
        "positions": 0.05,       # 3 分钟（总是增量）
    }

    def __init__(self, db_path: Optional[Path] = None):
        """
        Args:
            db_path: 数据库文件路径，默认使用全局配置
        """
        self.db_path = str(db_path or DB_PATH)
        self._ensure_table()

    def _get_conn(self) -> sqlite3.Connection:
        """获取数据库连接"""
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def _ensure_table(self):
        """确保 sync_status 表存在"""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sync_status (
                sync_type TEXT PRIMARY KEY,
                last_sync_time TEXT,
                last_success_time TEXT,
                last_cursor TEXT,
                records_synced INTEGER DEFAULT 0,
                status TEXT DEFAULT 'idle',
                error_message TEXT,
                next_scheduled_time TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.commit()
        conn.close()
        logger.debug("sync_status 表已就绪")

    # ================================================================
    # 读取
    # ================================================================

    def get_last_sync(self, sync_type: str) -> Dict:
        """
        获取指定类型的上次同步信息

        Args:
            sync_type: 同步类型 (orders/transactions/fundamentals/etc)

        Returns:
            { sync_type, last_sync_time, last_success_time, last_cursor,
              records_synced, status, error_message, next_scheduled_time }
            如果从未同步过，返回默认值
        """
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM sync_status WHERE sync_type = ?",
            (sync_type,)
        )
        row = cursor.fetchone()
        conn.close()

        if row is None:
            return {
                "sync_type": sync_type,
                "last_sync_time": None,
                "last_success_time": None,
                "last_cursor": None,
                "records_synced": 0,
                "status": "idle",
                "error_message": None,
                "next_scheduled_time": None,
            }

        return {
            "sync_type": row[0],
            "last_sync_time": row[1],
            "last_success_time": row[2],
            "last_cursor": row[3],
            "records_synced": row[4],
            "status": row[5],
            "error_message": row[6],
            "next_scheduled_time": row[7],
        }

    def get_all_sync_status(self) -> Dict[str, Dict]:
        """获取所有同步类型的状态"""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT sync_type, last_sync_time, last_success_time, "
                       "last_cursor, records_synced, status FROM sync_status")
        rows = cursor.fetchall()
        conn.close()

        result = {}
        for row in rows:
            result[row[0]] = {
                "last_sync_time": row[1],
                "last_success_time": row[2],
                "last_cursor": row[3],
                "records_synced": row[4],
                "status": row[5],
            }
        return result

    # ================================================================
    # 写入
    # ================================================================

    def update_sync(
        self,
        sync_type: str,
        cursor: Optional[str] = None,
        records: Optional[int] = None,
        status: str = "success",
        error_message: Optional[str] = None,
        next_scheduled_time: Optional[str] = None,
    ):
        """
        更新同步状态

        Args:
            sync_type: 同步类型
            cursor: 分页游标（用于断点续传）
            records: 本次同步的记录数
            status: 状态 (idle/running/success/error)
            error_message: 错误信息
            next_scheduled_time: 下次计划执行时间
        """
        now = datetime.now().isoformat()

        conn = self._get_conn()
        cursor_exec = conn.cursor()

        # 先读取现有记录
        cursor_exec.execute(
            "SELECT last_cursor, records_synced FROM sync_status WHERE sync_type = ?",
            (sync_type,)
        )
        existing = cursor_exec.fetchone()

        existing_cursor = existing[0] if existing else None
        existing_records = existing[1] if existing else 0

        # 更新时间字段
        last_sync_time = now
        last_success_time = now if status in ("success", "idle") else None

        # 合并游标和记录数
        final_cursor = cursor or existing_cursor
        add_records = records or 0
        total_records = existing_records + add_records if existing else add_records

        cursor_exec.execute("""
            INSERT OR REPLACE INTO sync_status
                (sync_type, last_sync_time, last_success_time, last_cursor,
                 records_synced, status, error_message, next_scheduled_time)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            sync_type,
            last_sync_time,
            last_success_time,
            final_cursor,
            total_records,
            status,
            error_message,
            next_scheduled_time,
        ))
        conn.commit()
        conn.close()

        if status == "error":
            logger.warning(f"sync_status[{sync_type}]: {status} - {error_message}")
        else:
            logger.debug(
                f"sync_status[{sync_type}]: {status} "
                f"(+{add_records} records, cursor={final_cursor})"
            )

    def start_sync(self, sync_type: str):
        """标记同步为运行中"""
        self._set_status(sync_type, "running")

    def mark_error(self, sync_type: str, error_message: str):
        """标记同步错误"""
        self.update_sync(sync_type, status="error", error_message=error_message)

    def mark_success(self, sync_type: str, records: int = 0, cursor: Optional[str] = None):
        """标记同步成功"""
        self.update_sync(sync_type, status="success", records=records, cursor=cursor)

    # ================================================================
    # 判断
    # ================================================================

    def needs_full_sync(self, sync_type: str, max_age_hours: Optional[float] = None) -> bool:
        """
        检查是否需要全量同步

        Args:
            sync_type: 同步类型
            max_age_hours: 最大同步间隔（小时），None 使用默认值

        Returns:
            True 如果从未同步或上次同步超过指定间隔
        """
        status = self.get_last_sync(sync_type)

        if status["last_success_time"] is None:
            return True

        max_hours = max_age_hours or self.SYNC_INTERVALS.get(
            sync_type, self.DEFAULT_FULL_SYNC_INTERVAL
        )

        try:
            last_sync = datetime.fromisoformat(status["last_success_time"])
            age = datetime.now() - last_sync
            return age > timedelta(hours=max_hours)
        except (ValueError, TypeError):
            return True

    def is_syncing(self, sync_type: str) -> bool:
        """检查是否正在同步中"""
        status = self.get_last_sync(sync_type)
        return status["status"] == "running"

    def is_error(self, sync_type: str) -> bool:
        """检查是否出错"""
        status = self.get_last_sync(sync_type)
        return status["status"] == "error"

    # ================================================================
    # 内部方法
    # ================================================================

    def _set_status(self, sync_type: str, status: str):
        """仅更新状态字段"""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO sync_status
                (sync_type, last_sync_time, status)
            VALUES (?, ?, ?)
        """, (
            sync_type,
            datetime.now().isoformat(),
            status,
        ))
        conn.commit()
        conn.close()

    def reset(self, sync_type: str):
        """重置某类型的同步状态（用于强制全量同步）"""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM sync_status WHERE sync_type = ?", (sync_type,))
        conn.commit()
        conn.close()
        logger.info(f"🔄 重置同步状态: {sync_type}")

    def reset_all(self):
        """重置所有同步状态"""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM sync_status")
        conn.commit()
        conn.close()
        logger.info("🔄 重置所有同步状态")
