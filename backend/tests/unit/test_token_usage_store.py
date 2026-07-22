"""Tests for TokenUsageStore — SQLite-backed token usage tracking."""
import tempfile
from pathlib import Path

from emailpet.storage.token_usage_store import TokenUsageStore


def test_record_and_summary():
    """record() 写入数据，summary() 按 call_type 聚合."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "tokens.db"
        store = TokenUsageStore(db_path)

        # 记录几次调用
        store.record("summarize", model="gpt-4", prompt_tokens=100, completion_tokens=50, total_tokens=150)
        store.record("summarize", model="gpt-4", prompt_tokens=200, completion_tokens=100, total_tokens=300)
        store.record("draft_reply", model="gpt-4", prompt_tokens=300, completion_tokens=150, total_tokens=450)
        store.record("embedding", model="text-embedding-3-small", input_chars=1000)
        store.record("embedding", model="text-embedding-3-small", input_chars=2000)

        summary = store.summary()

        assert "summarize" in summary
        assert summary["summarize"]["count"] == 2
        assert summary["summarize"]["total_tokens"] == 450
        assert summary["summarize"]["avg_tokens"] == 225.0

        assert "draft_reply" in summary
        assert summary["draft_reply"]["count"] == 1
        assert summary["draft_reply"]["total_tokens"] == 450

        assert "embedding" in summary
        assert summary["embedding"]["count"] == 2
        assert summary["embedding"]["total_tokens"] == 0
        assert summary["embedding"]["input_chars"] == 3000

        store.close()


def test_summary_empty():
    """空数据库返回空 dict."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = TokenUsageStore(Path(tmpdir) / "tokens.db")
        assert store.summary() == {}
        store.close()


def test_summary_avg_calculation():
    """avg_tokens 计算正确：total_tokens / count."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = TokenUsageStore(Path(tmpdir) / "tokens.db")

        # total_tokens=100+200+300=600, count=3 → avg=200
        store.record("free_chat", total_tokens=100)
        store.record("free_chat", total_tokens=200)
        store.record("free_chat", total_tokens=300)

        summary = store.summary()
        assert summary["free_chat"]["avg_tokens"] == 200.0

        store.close()


def test_record_optional_fields():
    """只传 call_type，其他字段为 None 时正常工作."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = TokenUsageStore(Path(tmpdir) / "tokens.db")
        store.record("test_type")  # 只传 call_type
        summary = store.summary()
        assert summary["test_type"]["count"] == 1
        assert summary["test_type"]["total_tokens"] == 0
        store.close()


def test_record_with_thread_id():
    """thread_id 可选参数正常写入."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = TokenUsageStore(Path(tmpdir) / "tokens.db")
        store.record("summarize", thread_id="email_123", total_tokens=100)
        # summary 不聚合 thread_id，但 record 不应报错
        summary = store.summary()
        assert summary["summarize"]["count"] == 1
        store.close()


def test_close_multiple_times_safe():
    """多次 close 不会报错."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = TokenUsageStore(Path(tmpdir) / "tokens.db")
        store.close()
        store.close()  # 第二次 close 应安全


def test_record_failure_does_not_raise():
    """record() 异常时只打 warning，不抛异常."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = TokenUsageStore(Path(tmpdir) / "tokens.db")
        store.close()  # 先关闭连接
        # 对已关闭的连接调用 record 不应抛异常
        store.record("summarize", total_tokens=100)
