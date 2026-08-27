"""OpenAI-compatible embedding client.
"""
from __future__ import annotations

import logging

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)


class EmbeddingError(Exception):
    """Embedding API 请求失败。"""


class EmbeddingClient:
    """OpenAI 兼容的 embedding 客户端，用于生成文本向量。"""
    def __init__(self, base_url: str, api_key: str, model: str, token_store=None) -> None:
        self.client = AsyncOpenAI(base_url=base_url, api_key=api_key)
        self.model = model
        self.token_store = token_store

    async def embed(self, text: str) -> list[float]:
        """生成文本的 embedding 向量。

        Args:
            text: 输入文本

        Returns:
            embedding 向量列表

        Raises:
            EmbeddingError: API 请求失败
        """
        try:
            response = await self.client.embeddings.create(
                model=self.model,
                input=text,
            )
            # 记录输入字符数
            if self.token_store is not None:
                self.token_store.record(
                    call_type="embedding",
                    model=self.model,
                    input_chars=len(text),
                )
            return response.data[0].embedding
        except Exception as e:  # noqa: BLE001
            logger.warning("embedding API failed: %s", e)
            raise EmbeddingError(f"embedding failed: {e}") from e
