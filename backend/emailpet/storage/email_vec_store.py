"""sqlite-vec backed vector index for email RAG.

See docs/modules/backend/emailpet/storage/email_vec_store.md for full module doc.
"""
from __future__ import annotations

import sqlite3
import struct
from pathlib import Path

import sqlite_vec


class EmailVecStore:
    def __init__(self, db_path: str | Path, dimensions: int) -> None:
        self.db_path = str(db_path)
        self.dimensions = dimensions
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.enable_load_extension(True)
        self._conn.load_extension(sqlite_vec.loadable_path())
        self._conn.enable_load_extension(False)
        self._conn.execute(
            f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS email_vec USING vec0(
                uid INTEGER PRIMARY KEY,
                embedding FLOAT[{dimensions}]
            )
            """
        )
        self._conn.commit()

    def index(self, uid: int, embedding: list[float]) -> None:
        embedding_bytes = struct.pack(f"{len(embedding)}f", *embedding)
        # vec0 doesn't support INSERT OR REPLACE, so delete first then insert
        self._conn.execute("DELETE FROM email_vec WHERE uid = ?", (uid,))
        self._conn.execute(
            "INSERT INTO email_vec(uid, embedding) VALUES (?, ?)",
            (uid, embedding_bytes),
        )
        self._conn.commit()

    def query(self, embedding: list[float], k: int = 5) -> list[int]:
        embedding_bytes = struct.pack(f"{len(embedding)}f", *embedding)
        cur = self._conn.execute(
            "SELECT uid FROM email_vec "
            "WHERE embedding MATCH ? AND k = ? "
            "ORDER BY distance",
            (embedding_bytes, k),
        )
        return [row[0] for row in cur.fetchall()]

    def close(self) -> None:
        self._conn.close()
