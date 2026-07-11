"""SQLite-backed store of processed IMAP UIDs.

See docs/modules/backend/emailpet/storage/uid_store.md for full module doc.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class UIDStore:
    """已处理邮件 UID 记录。

    职责：避免重复处理同一封邮件。
    用法：mark_processed() 标记已处理，is_processed() 检查状态。
    """
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        # processed_uids 表：记录所有已处理过的邮件 UID
        # uid: IMAP UID（主键）
        # processed_at: 处理时间
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS processed_uids (
                uid INTEGER PRIMARY KEY,
                processed_at TEXT NOT NULL
            )
            """
        )
        self._conn.commit()

    def mark_processed(self, uid: int) -> None:
        """标记邮件已处理。

        使用 INSERT OR IGNORE：重复标记不会报错，保证幂等。
        """
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            "INSERT OR IGNORE INTO processed_uids (uid, processed_at) VALUES (?, ?)",
            (uid, now),
        )
        self._conn.commit()

    def is_processed(self, uid: int) -> bool:
        """检查邮件是否已处理。"""
        cur = self._conn.execute(
            "SELECT 1 FROM processed_uids WHERE uid = ?", (uid,)
        )
        return cur.fetchone() is not None

    def processed_uids(self) -> set[int]:
        """获取所有已处理的 UID 集合（用于启动时去重）。"""
        cur = self._conn.execute("SELECT uid FROM processed_uids")
        return {row[0] for row in cur.fetchall()}

    def close(self) -> None:
        """关闭数据库连接。"""
        self._conn.close()
