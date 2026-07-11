"""SQLite-backed log of silently-archived emails.

See docs/modules/backend/emailpet/storage/archive_log.md for full module doc.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from emailpet.mail.models import Email


class ArchiveLog:
    """静默归档日志。

    职责：记录被自动归档的邮件，供用户查看历史。
    用法：log() 记录归档，query_recent() 查询最近记录。
    """
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        # silent_archives 表：静默归档记录
        # uid: 邮件 UID
        # from_address: 发件人
        # subject: 主题
        # category: 分类
        # archived_at: 归档时间
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS silent_archives (
                uid INTEGER NOT NULL,
                from_address TEXT NOT NULL,
                subject TEXT NOT NULL,
                category TEXT NOT NULL,
                archived_at TEXT NOT NULL
            )
            """
        )
        # 按时间倒序查询优化
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_archived_at ON silent_archives(archived_at DESC)"
        )
        self._conn.commit()

    def log(self, email: Email, category: str) -> None:
        """记录一封被静默归档的邮件。"""
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            """
            INSERT INTO silent_archives
                (uid, from_address, subject, category, archived_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (email.uid, email.from_address, email.subject, category, now),
        )
        self._conn.commit()

    def query_recent(self, limit: int = 50) -> list[dict]:
        """查询最近的静默归档记录（按时间倒序）。"""
        cur = self._conn.execute(
            """
            SELECT uid, from_address, subject, category, archived_at
            FROM silent_archives
            ORDER BY archived_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [
            {
                "uid": row[0],
                "from_address": row[1],
                "subject": row[2],
                "category": row[3],
                "archived_at": row[4],
            }
            for row in cur.fetchall()
        ]

    def close(self) -> None:
        """关闭数据库连接。"""
        self._conn.close()
