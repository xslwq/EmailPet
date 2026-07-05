"""Tests for EmbeddingClient."""
from unittest.mock import AsyncMock, MagicMock

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
