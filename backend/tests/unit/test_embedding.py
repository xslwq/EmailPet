"""Tests for EmbeddingClient."""
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from emailpet.agent.embedding import EmbeddingClient, EmbeddingError


@pytest.fixture
def client():
    return EmbeddingClient(
        base_url="https://api.example.com/v1",
        api_key="sk-test",
        model="text-embedding-3-small",
    )


async def test_embed_returns_vector(client):
    client.client = MagicMock()
    mock_response = MagicMock()
    mock_response.data = [MagicMock(embedding=[0.1, 0.2, 0.3])]
    client.client.embeddings = MagicMock()
    client.client.embeddings.create = AsyncMock(return_value=mock_response)
    vec = await client.embed("hello")
    assert vec == [0.1, 0.2, 0.3]


async def test_embed_api_failure_raises(client):
    client.client = MagicMock()
    client.client.embeddings = MagicMock()
    client.client.embeddings.create = AsyncMock(side_effect=RuntimeError("api dead"))
    with pytest.raises(EmbeddingError):
        await client.embed("hello")


async def test_embed_records_input_chars():
    """embed() 调用 token_store.record() 并传入 input_chars."""
    token_store = Mock()
    client = EmbeddingClient(
        base_url="https://api.example.com/v1",
        api_key="sk-test",
        model="text-embedding-3-small",
        token_store=token_store,
    )

    mock_response = MagicMock()
    mock_response.data = [MagicMock(embedding=[0.1, 0.2, 0.3])]
    client.client = MagicMock()
    client.client.embeddings = MagicMock()
    client.client.embeddings.create = AsyncMock(return_value=mock_response)

    await client.embed("hello world")  # len=11

    assert token_store.record.called
    call_args = token_store.record.call_args
    assert call_args.kwargs["call_type"] == "embedding"
    assert call_args.kwargs["model"] == "text-embedding-3-small"
    assert call_args.kwargs["input_chars"] == 11


async def test_embed_without_token_store():
    """token_store 为 None 时不报错."""
    client = EmbeddingClient(
        base_url="https://api.example.com/v1",
        api_key="sk-test",
        model="text-embedding-3-small",
        token_store=None,
    )

    mock_response = MagicMock()
    mock_response.data = [MagicMock(embedding=[0.1, 0.2, 0.3])]
    client.client = MagicMock()
    client.client.embeddings = MagicMock()
    client.client.embeddings.create = AsyncMock(return_value=mock_response)

    # 不应抛异常
    result = await client.embed("hello")
    assert result == [0.1, 0.2, 0.3]
