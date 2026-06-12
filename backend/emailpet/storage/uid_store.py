"""SQLite-backed store of processed IMAP UIDs.

See docs/modules/backend/emailpet/storage/uid_store.md for full module doc.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class UIDStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
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
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            "INSERT OR IGNORE INTO processed_uids (uid, processed_at) VALUES (?, ?)",
            (uid, now),
        )
        self._conn.commit()

    def is_processed(self, uid: int) -> bool:
        cur = self._conn.execute(
            "SELECT 1 FROM processed_uids WHERE uid = ?", (uid,)
        )
        return cur.fetchone() is not None

    def processed_uids(self) -> set[int]:
        cur = self._conn.execute("SELECT uid FROM processed_uids")
        return {row[0] for row in cur.fetchall()}

    def close(self) -> None:
        self._conn.close()
