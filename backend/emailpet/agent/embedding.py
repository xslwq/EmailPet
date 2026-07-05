"""OpenAI-compatible embedding client.

See docs/modules/backend/emailpet/agent/embedding.md for full module doc.
"""
from __future__ import annotations

import logging

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)


class EmbeddingError(Exception):
    """Embedding API request failed."""


class EmbeddingClient:
    def __init__(self, base_url: str, api_key: str, model: str) -> None:
        self.client = AsyncOpenAI(base_url=base_url, api_key=api_key)
        self.model = model

    async def embed(self, text: str) -> list[float]:
        try:
            response = await self.client.embeddings.create(
                model=self.model,
                input=text,
            )
            return response.data[0].embedding
        except Exception as e:  # noqa: BLE001
            logger.warning("embedding API failed: %s", e)
            raise EmbeddingError(f"embedding failed: {e}") from e
