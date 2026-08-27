"""SQLite-backed token usage tracking store.
"""
from __future__ import annotations
import sqlite3
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


class TokenUsageStore:
    """Token 用量统计存储。

    职责：记录每次 LLM/embedding 调用，按 call_type 聚合统计。
    用法：record() 记录单次调用，summary() 获取聚合统计。
    """
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        # 创建表和索引
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS token_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                call_type TEXT NOT NULL,
                model TEXT,
                prompt_tokens INTEGER,
                completion_tokens INTEGER,
                total_tokens INTEGER,
                input_chars INTEGER,
                thread_id TEXT
            )
            """
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_token_call_type ON token_usage(call_type)"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_token_timestamp ON token_usage(timestamp)"
        )
        self._conn.commit()

    def record(
        self,
        call_type: str,
        model: Optional[str] = None,
        prompt_tokens: Optional[int] = None,
        completion_tokens: Optional[int] = None,
        total_tokens: Optional[int] = None,
        input_chars: Optional[int] = None,
        thread_id: Optional[str] = None,
    ) -> None:
        """记录一次调用的 token 用量。

        参数：
            call_type: 调用类型（必需），如 "summarize"、"draft_reply"、"embedding"
            model: 模型名（可选）
            prompt_tokens: LLM prompt token 数（可选）
            completion_tokens: LLM completion token 数（可选）
            total_tokens: LLM total token 数（可选）
            input_chars: 输入字符数（可选，embedding 用）
            thread_id: 线程 ID（可选）
        """
        try:
            now = datetime.now(timezone.utc).isoformat()
            self._conn.execute(
                """
                INSERT INTO token_usage
                (timestamp, call_type, model, prompt_tokens, completion_tokens, total_tokens, input_chars, thread_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (now, call_type, model, prompt_tokens, completion_tokens, total_tokens, input_chars, thread_id),
            )
            self._conn.commit()
        except Exception as e:
            logger.warning("token_store.record failed: %s", e)

    def summary(self) -> dict[str, dict[str, Any]]:
        """按 call_type 聚合统计。

        返回：
            {call_type: {"count": int, "total_tokens": int, "avg_tokens": float, "input_chars": int}}
        """
        cur = self._conn.execute(
            """
            SELECT call_type,
                   COUNT(*) as count,
                   COALESCE(SUM(total_tokens), 0) as total_tokens,
                   COALESCE(SUM(input_chars), 0) as input_chars
            FROM token_usage
            GROUP BY call_type
            ORDER BY call_type
            """
        )
        result = {}
        for row in cur.fetchall():
            call_type, count, total_tokens, input_chars = row
            avg_tokens = total_tokens / count if count > 0 and total_tokens > 0 else 0.0
            result[call_type] = {
                "count": count,
                "total_tokens": total_tokens,
                "avg_tokens": round(avg_tokens, 1),
                "input_chars": input_chars,
            }
        return result

    def close(self) -> None:
        """关闭数据库连接。"""
        try:
            self._conn.close()
        except Exception as e:
            logger.warning("token_store.close failed: %s", e)
