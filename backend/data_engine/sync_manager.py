"""
Sync-status manager.
Tracks incremental sync progress via the sync_status table.
Supports paging cursors, resume-from-checkpoint, and full-sync decisions.
"""
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional
from loguru import logger

from configs.settings import settings


class SyncManager:
    """
    Sync-status manager.

    Tracks progress for every data type:
    - last sync time per sync_type
    - paging cursor for resume-from-checkpoint
    - whether a full sync is required

    Usage:
        mgr = SyncManager(store.historical_store)
        last = mgr.get_last_sync("orders")
        mgr.update_sync("orders", cursor="page_3", records=50)
        if mgr.needs_full_sync("orders", max_age_hours=24):
            run_full_sync()
    """

    # Default max interval between full syncs (hours)
    DEFAULT_FULL_SYNC_INTERVAL = 24
    # Recommended full-sync interval by type
    SYNC_INTERVALS = {
        "orders": 24,
        "transactions": 24,
        "fundamentals": 24,
        "assets": 1,
        "calendar": 168,        # weekly
        "capital_flow": 24,
        "corporate_events": 24,
        "positions": 0.05,       # 3 minutes (always incremental)
    }

    def __init__(self, db_path: Optional[Path] = None):
        """
        Args:
            db_path: database file path; defaults to the global config
        """
        self.db_path = str(db_path or DB_PATH)
        self._ensure_table()

    def _get_conn(self) -> sqlite3.Connection:
        """Return a database connection."""
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def _ensure_table(self):
        """Ensure the sync_status table exists."""
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
        logger.debug("sync_status table ready")

    # ================================================================
    # Reads
    # ================================================================

    def get_last_sync(self, sync_type: str) -> Dict:
        """
        Return last-sync info for a given type.

        Args:
            sync_type: sync type (orders/transactions/fundamentals/etc)

        Returns:
            { sync_type, last_sync_time, last_success_time, last_cursor,
              records_synced, status, error_message, next_scheduled_time }
            Default values if this type has never synced
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
        """Return status for every sync type."""
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
    # Writes
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
        Update sync status.

        Args:
            sync_type: sync type
            cursor: paging cursor (for resume-from-checkpoint)
            records: records synced this run
            status: status (idle/running/success/error)
            error_message: error details
            next_scheduled_time: next scheduled run time
        """
        now = datetime.now().isoformat()

        conn = self._get_conn()
        cursor_exec = conn.cursor()

        # Read existing row first
        cursor_exec.execute(
            "SELECT last_cursor, records_synced FROM sync_status WHERE sync_type = ?",
            (sync_type,)
        )
        existing = cursor_exec.fetchone()

        existing_cursor = existing[0] if existing else None
        existing_records = existing[1] if existing else 0

        # Time fields
        last_sync_time = now
        last_success_time = now if status in ("success", "idle") else None

        # Merge cursor and record counts
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
        """Mark a sync as running."""
        self._set_status(sync_type, "running")

    def mark_error(self, sync_type: str, error_message: str):
        """Mark a sync error."""
        self.update_sync(sync_type, status="error", error_message=error_message)

    def mark_success(self, sync_type: str, records: int = 0, cursor: Optional[str] = None):
        """Mark a successful sync."""
        self.update_sync(sync_type, status="success", records=records, cursor=cursor)

    # ================================================================
    # Decisions
    # ================================================================

    def needs_full_sync(self, sync_type: str, max_age_hours: Optional[float] = None) -> bool:
        """
        Check whether a full sync is required.

        Args:
            sync_type: sync type
            max_age_hours: max interval in hours; None uses the default

        Returns:
            True if never synced or last success is older than the interval
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
        """Return whether a sync is currently running."""
        status = self.get_last_sync(sync_type)
        return status["status"] == "running"

    def is_error(self, sync_type: str) -> bool:
        """Return whether the last sync ended in error."""
        status = self.get_last_sync(sync_type)
        return status["status"] == "error"

    # ================================================================
    # Internals
    # ================================================================

    def _set_status(self, sync_type: str, status: str):
        """Update only the status field."""
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
        """Reset one type's sync status (used to force a full sync)."""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM sync_status WHERE sync_type = ?", (sync_type,))
        conn.commit()
        conn.close()
        logger.info(f"🔄 Reset sync status: {sync_type}")

    def reset_all(self):
        """Reset all sync status rows."""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM sync_status")
        conn.commit()
        conn.close()
        logger.info("🔄 Reset all sync status")
