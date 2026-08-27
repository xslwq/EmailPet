"""SQLite-backed user profile store (style preferences).
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class UserProfileStore:
    """用户配置存储（风格偏好）。

    职责：管理用户的显示名、签名、语气、敬语、常用短语等配置。
    用法：get() 获取当前配置，merge() 增量更新配置。
    """
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        # user_profile 表：单例配置（user_id=1）
        # display_name: 用户显示名
        # signature: 邮件签名
        # tone: 语气（formal/casual/friendly）
        # honorific: 是否使用敬语
        # common_phrases: JSON 数组，常用短语
        # updated_at: 最后更新时间
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
        # 确保存在单例记录（仅初始化时插入一次）
        self._conn.execute(
            "INSERT OR IGNORE INTO user_profile (user_id, updated_at) VALUES (1, ?)",
            (datetime.now(timezone.utc).isoformat(),),
        )
        self._conn.commit()

    def get(self) -> dict[str, Any]:
        """获取当前用户配置。

        返回：包含所有配置字段的字典，字段为 None 表示未设置。
        """
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
        """增量更新用户配置。

        合并规则：
        - 标量字段（display_name/signature/tone/honorific）：非 None 值覆盖
        - common_phrases：合并并去重，按字母排序
        - updated_at：总是更新为当前时间

        参数：
            patch: 包含要更新字段的字典

        返回：合并后的完整配置
        """
        current = self.get()
        # 标量字段：非 None 值覆盖，跳过 null
        for field in ("display_name", "signature", "tone", "honorific"):
            if field in patch and patch[field] is not None:
                current[field] = patch[field]
        # common_phrases：合并并去重
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
        """关闭数据库连接。"""
        self._conn.close()
