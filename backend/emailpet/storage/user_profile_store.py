"""SQLite-backed user profile store (style preferences).

See docs/modules/backend/emailpet/storage/user_profile_store.md for full module doc.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class UserProfileStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_profile (
                user_id INTEGER PRIMARY KEY DEFAULT 1,
                display_name TEXT,
                signature TEXT,
                tone TEXT CHECK(tone IN ('formal','casual','friendly')),
                honorific BOOLEAN DEFAULT 1,
                common_phrases TEXT,
                updated_at TEXT NOT NULL
            )
            """
        )
        self._conn.commit()
        self._conn.execute(
            "INSERT OR IGNORE INTO user_profile (user_id, updated_at) VALUES (1, ?)",
            (datetime.now(timezone.utc).isoformat(),),
        )
        self._conn.commit()

    def get(self) -> dict[str, Any]:
        cur = self._conn.execute(
            "SELECT display_name, signature, tone, honorific, common_phrases, updated_at "
            "FROM user_profile WHERE user_id = 1"
        )
        row = cur.fetchone()
        if row is None:
            return {}
        return {
            "display_name": row[0],
            "signature": row[1],
            "tone": row[2],
            "honorific": bool(row[3]) if row[3] is not None else None,
            "common_phrases": json.loads(row[4]) if row[4] else [],
            "updated_at": row[5],
        }

    def merge(self, patch: dict[str, Any]) -> dict[str, Any]:
        current = self.get()
        for field in ("display_name", "signature", "tone", "honorific"):
            if field in patch and patch[field] is not None:
                current[field] = patch[field]
        if "common_phrases" in patch and patch["common_phrases"]:
            existing = set(current.get("common_phrases") or [])
            existing.update(patch["common_phrases"])
            current["common_phrases"] = sorted(existing)
        current["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            """
            UPDATE user_profile
            SET display_name = ?, signature = ?, tone = ?, honorific = ?,
                common_phrases = ?, updated_at = ?
            WHERE user_id = 1
            """,
            (
                current.get("display_name"),
                current.get("signature"),
                current.get("tone"),
                current.get("honorific"),
                json.dumps(current.get("common_phrases") or [], ensure_ascii=False),
                current["updated_at"],
            ),
        )
        self._conn.commit()
        return current

    def close(self) -> None:
        self._conn.close()
