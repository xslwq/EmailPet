"""Tests for emailpet.agent.llm — LLM wrapper with structured output parsing."""
import pytest
from unittest.mock import AsyncMock, MagicMock
from emailpet.agent.llm import LLMClient, LLMError, _extract_json, _truncate, MAX_BODY_CHARS_FOR_LLM
from emailpet.mail.models import Summary, Draft


@pytest.fixture
def patched_llm(monkeypatch):
    """Returns (client, mock_create) where mock_create is the AsyncMock for chat.completions.create."""
    def make(responses: list[str]):
        async def fake_create(*args, **kwargs):
            content = responses.pop(0)
            choice = MagicMock()
            choice.message = MagicMock()
            choice.message.content = content
            comp = MagicMock()
            comp.choices = [choice]
            return comp
        client = LLMClient(base_url="http://x", api_key="k", model="m")
        mock_create = AsyncMock(side_effect=fake_create)
        client.client.chat.completions.create = mock_create
        return client, mock_create
    return make


async def test_summarize_important(patched_llm):
    client, _ = patched_llm([
        '{"summary": "老板让你周三交方案", "is_important": true, "category": "work", "needs_reply": true, "suggested_action": "reply"}'
    ])
    s = await client.summarize("hi")
    assert isinstance(s, Summary)
    assert s.is_important is True
    assert s.category == "work"
    assert s.suggested_action == "reply"
    assert s.needs_reply is True
    assert "周三" in s.text


async def test_summarize_not_important(patched_llm):
    client, _ = patched_llm([
        '{"summary": "推广", "is_important": false, "category": "promo", "needs_reply": false, "suggested_action": "archive"}'
    ])
    s = await client.summarize("hi")
    assert s.is_important is False
    assert s.category == "promo"
    assert s.needs_reply is False


async def test_summarize_bad_json_retry_then_succeed(patched_llm):
    client, mock = patched_llm([
        "not json at all",
        '{"summary": "ok", "is_important": true, "category": "work", "needs_reply": true, "suggested_action": "reply"}',
    ])
    s = await client.summarize("hi")
    assert s.text == "ok"
    assert s.needs_reply is True
    assert mock.await_count == 2


async def test_summarize_retry_exhausted_falls_back_important(patched_llm):
    """When both calls fail to parse, summarize returns is_important=True fallback."""
    client, mock = patched_llm(["garbage", "still garbage"])
    s = await client.summarize("hi")
    assert s.is_important is True
    assert "(LLM" in s.text or "未能" in s.text
    assert mock.await_count == 2


async def test_summarize_invalid_category_falls_back(patched_llm):
    client, _ = patched_llm([
        '{"summary": "x", "is_important": true, "category": "invalid_cat", "needs_reply": true, "suggested_action": "reply"}',
        '{"summary": "x", "is_important": true, "category": "still_bad", "needs_reply": true, "suggested_action": "reply"}',
    ])
    s = await client.summarize("hi")
    assert s.is_important is True  # fallback
    assert s.needs_reply is True


async def test_draft_reply_success(patched_llm):
    client, _ = patched_llm([
        '{"body": "好的，我会按时提交。", "reason": "明确确认收到任务"}'
    ])
    d = await client.draft_reply("老板邮件原文")
    assert isinstance(d, Draft)
    assert "按时提交" in d.body
    assert d.reason


async def test_draft_reply_with_feedback(patched_llm):
    client, mock = patched_llm([
        '{"body": "好的", "reason": "简短确认"}'
    ])
    await client.draft_reply("原文", feedback="语气客气一点")
    # Inspect the call args — the user prompt should contain the feedback string
    call = mock.await_args_list[0]
    user_msg = call.kwargs["messages"][1]["content"]
    assert "语气客气一点" in user_msg
    assert "上次草稿" in user_msg or "反馈" in user_msg


async def test_draft_reply_retry_exhausted_raises(patched_llm):
    """When parse fails twice, draft_reply raises LLMError (no fallback)."""
    client, _ = patched_llm(["bad", "still bad"])
    with pytest.raises(LLMError):
        await client.draft_reply("原文")


async def test_extract_json_handles_markdown_fence():
    """LLMs often wrap JSON in ```json ... ```."""
    text = '```json\n{"summary": "x", "is_important": true, "category": "work", "needs_reply": true, "suggested_action": "reply"}\n```'
    data = _extract_json(text)
    assert data["category"] == "work"
    assert data["needs_reply"] is True


async def test_extract_json_handles_plain_fence():
    text = '```\n{"a": 1}\n```'
    data = _extract_json(text)
    assert data == {"a": 1}


async def test_truncate_under_limit():
    body = "x" * (MAX_BODY_CHARS_FOR_LLM - 1)
    assert _truncate(body) == body


async def test_truncate_over_limit():
    body = "x" * (MAX_BODY_CHARS_FOR_LLM + 100)
    out = _truncate(body)
    assert len(out) <= MAX_BODY_CHARS_FOR_LLM + 50
    assert "已截断" in out


async def test_summarize_truncates_long_body(patched_llm):
    client, mock = patched_llm([
        '{"summary": "x", "is_important": false, "category": "promo", "needs_reply": false, "suggested_action": "archive"}'
    ])
    big_body = "x" * (MAX_BODY_CHARS_FOR_LLM + 5_000)
    await client.summarize(big_body)
    user_msg = mock.await_args_list[0].kwargs["messages"][1]["content"]
    # truncation marker should be present
    assert "已截断" in user_msg
