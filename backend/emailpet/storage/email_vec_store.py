"""sqlite-vec backed vector index for email RAG.
"""
from __future__ import annotations

import sqlite3
import struct
from pathlib import Path

import sqlite_vec


class EmailVecStore:
    """邮件向量索引（基于 sqlite-vec）。

    职责：为重要邮件建立向量索引，支持 KNN 相似度检索。
    用法：index() 存入向量，query() 检索最相似的邮件 UID。
    """
    def __init__(self, db_path: str | Path, dimensions: int) -> None:
        self.db_path = str(db_path)
        self.dimensions = dimensions
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        # 加载 sqlite-vec 扩展
        self._conn.enable_load_extension(True)
        self._conn.load_extension(sqlite_vec.loadable_path())
        self._conn.enable_load_extension(False)
        # vec0 虚拟表：存储邮件向量
        # uid: 邮件 UID（主键）
        # embedding: 浮点向量（维度固定）
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
        """存入邮件向量。

        vec0 不支持 INSERT OR REPLACE，所以用 DELETE + INSERT 替代。

        参数：
            uid: 邮件 UID
            embedding: 浮点向量列表
        """
        # struct.pack 将 float 列表转为二进制 bytes（sqlite-vec 要求）
        embedding_bytes = struct.pack(f"{len(embedding)}f", *embedding)
        # vec0 虚拟表限制：不支持 INSERT OR REPLACE，先删后插实现幂等
        self._conn.execute("DELETE FROM email_vec WHERE uid = ?", (uid,))
        self._conn.execute(
            "INSERT INTO email_vec(uid, embedding) VALUES (?, ?)",
            (uid, embedding_bytes),
        )
        self._conn.commit()

    def query(self, embedding: list[float], k: int = 5) -> list[int]:
        """KNN 检索：返回最相似的 k 个邮件 UID。

        参数：
            embedding: 查询向量
            k: 返回结果数量

        返回：按相似度排序的邮件 UID 列表
        """
        embedding_bytes = struct.pack(f"{len(embedding)}f", *embedding)
        cur = self._conn.execute(
            "SELECT uid FROM email_vec "
            "WHERE embedding MATCH ? AND k = ? "
            "ORDER BY distance",
            (embedding_bytes, k),
        )
        return [row[0] for row in cur.fetchall()]

    def close(self) -> None:
        """关闭数据库连接。"""
        self._conn.close()
