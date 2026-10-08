"""Embedding service supporting FastEmbed (local ONNX), OpenAI, and Mock embeddings."""

from abc import ABC, abstractmethod
import hashlib
import logging
import math
from typing import Sequence

import numpy as np

from src.agent.config import agent_config

logger = logging.getLogger("datt.agent.embeddings")


class BaseEmbeddingService(ABC):
    """Abstract base class for text embedding generators."""

    @abstractmethod
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for a batch of texts."""
        pass

    @abstractmethod
    def embed_query(self, text: str) -> list[float]:
        """Generate embedding for a single query text."""
        pass

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Vector dimensionality."""
        pass


class MockEmbeddingService(BaseEmbeddingService):
    """Deterministic hash-based embedding service for unit tests and offline testing."""

    def __init__(self, dimension: int = 384) -> None:
        self._dim = dimension

    @property
    def dimension(self) -> int:
        return self._dim

    def _generate(self, text: str) -> list[float]:
        # Generate pseudo-deterministic float vector from MD5 hash seeds
        vec = []
        for i in range(self._dim):
            seed = f"{text}_{i}".encode("utf-8")
            h = int(hashlib.md5(seed).hexdigest()[:8], 16)
            val = (h / 0xFFFFFFFF) * 2.0 - 1.0
            vec.append(val)
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [float(x / norm) for x in vec]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._generate(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._generate(text)


class FastEmbedService(BaseEmbeddingService):
    """Fast local ONNX embeddings via fastembed library."""

    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5", dimension: int = 384) -> None:
        self._model_name = model_name
        self._dim = dimension
        self._model = None

    def _load_model(self):
        if self._model is None:
            try:
                from fastembed import TextEmbedding
                self._model = TextEmbedding(model_name=self._model_name)
                logger.info("FastEmbed model loaded: %s", self._model_name)
            except Exception as exc:
                logger.warning("Failed to initialize FastEmbed (%s); falling back to Mock: %s", self._model_name, exc)
                self._model = False

    @property
    def dimension(self) -> int:
        return self._dim

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self._load_model()
        if not texts:
            return []
        if self._model is False:
            return MockEmbeddingService(self._dim).embed_documents(texts)
        try:
            embeddings_generator = self._model.embed(texts)
            return [emb.tolist() if hasattr(emb, "tolist") else list(emb) for emb in embeddings_generator]
        except Exception as exc:
            logger.error("FastEmbed document batch generation error: %s; falling back to Mock", exc)
            return MockEmbeddingService(self._dim).embed_documents(texts)

    def embed_query(self, text: str) -> list[float]:
        results = self.embed_documents([text])
        return results[0] if results else [0.0] * self._dim


class OpenAIEmbeddingService(BaseEmbeddingService):
    """OpenAI embeddings via langchain_openai."""

    def __init__(self, api_key: str | None = None, model: str = "text-embedding-3-small", dimension: int = 1536) -> None:
        self._model = model
        self._dim = dimension
        self._client = None
        self._api_key = api_key or agent_config.openai_api_key

    def _load_client(self):
        if self._client is None and self._api_key:
            from langchain_openai import OpenAIEmbeddings
            self._client = OpenAIEmbeddings(
                model=self._model,
                api_key=self._api_key,
                dimensions=self._dim if self._dim == 1536 else None,
            )

    @property
    def dimension(self) -> int:
        return self._dim

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self._load_client()
        if not self._client:
            logger.warning("OpenAI API key missing; falling back to FastEmbed")
            return FastEmbedService(dimension=agent_config.embedding_dim).embed_documents(texts)
        return self._client.embed_documents(texts)

    def embed_query(self, text: str) -> list[float]:
        self._load_client()
        if not self._client:
            return FastEmbedService(dimension=agent_config.embedding_dim).embed_query(text)
        return self._client.embed_query(text)


_embedding_service_instance: BaseEmbeddingService | None = None


def get_embedding_service(provider: str | None = None) -> BaseEmbeddingService:
    """Singleton factory for embedding service."""
    global _embedding_service_instance
    if _embedding_service_instance is not None and provider is None:
        return _embedding_service_instance

    target_provider = provider or agent_config.embedding_provider
    if target_provider == "openai" and agent_config.openai_api_key:
        instance = OpenAIEmbeddingService(
            api_key=agent_config.openai_api_key,
            dimension=agent_config.embedding_dim,
        )
    elif target_provider == "mock":
        instance = MockEmbeddingService(dimension=agent_config.embedding_dim)
    else:
        # Default: FastEmbed (runs locally via ONNX without API keys)
        instance = FastEmbedService(
            model_name=agent_config.embedding_model,
            dimension=agent_config.embedding_dim,
        )

    if provider is None:
        _embedding_service_instance = instance
    return instance
