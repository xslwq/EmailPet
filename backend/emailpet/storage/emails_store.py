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
    """邮件元数据 + 用户行为存储。

    职责：存储邮件原始数据、LLM 摘要、分类、用户操作状态。
    用法：upsert() 插入/更新邮件，get_by_uid() 查询单封，update_action() 记录用户操作。
    """
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        # emails 表：邮件完整记录
        # uid: IMAP UID（主键）
        # sender_address: 发件人邮箱
        # sender_name: 发件人显示名
        # subject: 主题
        # body_text: 邮件正文文本
        # summary: LLM 生成的摘要
        # category: 分类（work/personal/promo/notification）
        # is_important: 是否重要
        # needs_reply: 是否需要回复
        # received_at: 接收时间（ISO 格式）
        # user_action: 用户操作（pending/reply/archive/skip）
        # replied_body: 用户批准的回复正文
        # indexed_at: 向量索引创建时间
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
        # 按发件人查询优化
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_sender ON emails(sender_address)"
        )
        self._conn.commit()

    def upsert(self, email: Email, summary: Summary) -> None:
        """插入或更新邮件（含摘要）。

        使用 INSERT OR REPLACE：同一 uid 覆盖旧记录，保证数据最新。

        参数：
            email: 原始邮件对象
            summary: LLM 生成的摘要对象
        """
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
        """SQLite Row 转字典，处理布尔类型。"""
        d = dict(row)
        d["is_important"] = bool(d["is_important"]) if d["is_important"] is not None else None
        d["needs_reply"] = bool(d["needs_reply"]) if d["needs_reply"] is not None else None
        return d

    def get_by_uid(self, uid: int) -> Optional[dict[str, Any]]:
        """根据 UID 查询单封邮件。"""
        cur = self._conn.execute("SELECT * FROM emails WHERE uid = ?", (uid,))
        row = cur.fetchone()
        return self._row_to_dict(row) if row else None

    def get_by_sender(self, sender_address: str) -> list[dict[str, Any]]:
        """查询某发件人的所有邮件（按时间倒序）。"""
        cur = self._conn.execute(
            "SELECT * FROM emails WHERE sender_address = ? ORDER BY received_at DESC",
            (sender_address,),
        )
        return [self._row_to_dict(r) for r in cur.fetchall()]

    def update_action(
        self, uid: int, action: str, replied_body: Optional[str] = None
    ) -> None:
        """更新用户操作状态。

        参数：
            uid: 邮件 UID
            action: 用户操作（reply/archive/skip）
            replied_body: 回复正文（仅 action=reply 时提供）
        """
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
        """标记邮件已完成向量索引。"""
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            "UPDATE emails SET indexed_at = ? WHERE uid = ?", (now, uid)
        )
        self._conn.commit()

    def query_unindexed(self) -> list[dict[str, Any]]:
        """查询未建索引的重要邮件（用于 RAG 索引构建）。"""
        cur = self._conn.execute(
            "SELECT * FROM emails WHERE indexed_at IS NULL AND is_important = 1"
        )
        return [self._row_to_dict(r) for r in cur.fetchall()]

    def close(self) -> None:
        """关闭数据库连接。"""
        self._conn.close()
