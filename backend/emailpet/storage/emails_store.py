"""SQLite-backed emails metadata + behavior store.

See docs/modules/backend/emailpet/storage/emails_store.md for full module doc.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from emailpet.mail.models import Email, Summary


class EmailsStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS emails (
                uid INTEGER PRIMARY KEY,
                sender_address TEXT NOT NULL,
                sender_name TEXT,
                subject TEXT,
                body_text TEXT,
                summary TEXT,
                category TEXT,
                is_important BOOLEAN,
                needs_reply BOOLEAN,
                received_at TEXT,
                user_action TEXT DEFAULT 'pending',
                replied_body TEXT,
                indexed_at TEXT
            )
            """
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_sender ON emails(sender_address)"
        )
        self._conn.commit()

    def upsert(self, email: Email, summary: Summary) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO emails
                (uid, sender_address, sender_name, subject, body_text, summary,
                 category, is_important, needs_reply, received_at, user_action,
                 replied_body, indexed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                email.uid,
                email.from_address,
                email.from_name,
                email.subject,
                email.body_text,
                summary.text,
                summary.category,
                summary.is_important,
                summary.needs_reply,
                email.received_at.isoformat(),
                "pending",
                None,
                None,
            ),
        )
        self._conn.commit()

    def _row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        d["is_important"] = bool(d["is_important"]) if d["is_important"] is not None else None
        d["needs_reply"] = bool(d["needs_reply"]) if d["needs_reply"] is not None else None
        return d

    def get_by_uid(self, uid: int) -> Optional[dict[str, Any]]:
        cur = self._conn.execute("SELECT * FROM emails WHERE uid = ?", (uid,))
        row = cur.fetchone()
        return self._row_to_dict(row) if row else None

    def get_by_sender(self, sender_address: str) -> list[dict[str, Any]]:
        cur = self._conn.execute(
            "SELECT * FROM emails WHERE sender_address = ? ORDER BY received_at DESC",
            (sender_address,),
        )
        return [self._row_to_dict(r) for r in cur.fetchall()]

    def update_action(
        self, uid: int, action: str, replied_body: Optional[str] = None
    ) -> None:
        if replied_body is not None:
            self._conn.execute(
                "UPDATE emails SET user_action = ?, replied_body = ? WHERE uid = ?",
                (action, replied_body, uid),
            )
        else:
            self._conn.execute(
                "UPDATE emails SET user_action = ? WHERE uid = ?",
                (action, uid),
            )
        self._conn.commit()

    def mark_indexed(self, uid: int) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            "UPDATE emails SET indexed_at = ? WHERE uid = ?", (now, uid)
        )
        self._conn.commit()

    def query_unindexed(self) -> list[dict[str, Any]]:
        cur = self._conn.execute(
            "SELECT * FROM emails WHERE indexed_at IS NULL AND is_important = 1"
        )
        return [self._row_to_dict(r) for r in cur.fetchall()]

    def close(self) -> None:
        self._conn.close()
