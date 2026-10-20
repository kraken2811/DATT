"""Knowledge retrieval tool (RAG) for DATT AI Agent."""

import logging
import threading
import time
from typing import Any
from langchain_core.tools import tool

from src.agent.config import agent_config
from src.agent.rag.retrieval import KnowledgeRetriever

logger = logging.getLogger("datt.agent.tools.knowledge")


class KnowledgeCache:
    """Thread-safe, TTL-bounded in-memory cache for RAG knowledge retrieval."""

    def __init__(self, ttl_seconds: float | None = None, max_size: int | None = None) -> None:
        self.ttl = ttl_seconds if ttl_seconds is not None else agent_config.rag_cache_ttl_seconds
        self.max_size = max_size if max_size is not None else agent_config.rag_cache_max_size
        self._cache: dict[tuple[str, int, str | None], dict[str, Any]] = {}
        self._lock = threading.RLock()

    def get(self, key: tuple[str, int, str | None]) -> dict[str, Any] | None:
        now = time.monotonic()
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            if now - entry["created_at"] > self.ttl:
                del self._cache[key]
                return None
            return entry["result"]

    def set(self, key: tuple[str, int, str | None], result: dict[str, Any]) -> None:
        now = time.monotonic()
        with self._lock:
            if len(self._cache) >= self.max_size and key not in self._cache:
                # Evict oldest entry (by creation time)
                oldest_key = min(self._cache.keys(), key=lambda k: self._cache[k]["created_at"])
                del self._cache[oldest_key]
            self._cache[key] = {
                "created_at": now,
                "result": result,
            }

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()

    def size(self) -> int:
        with self._lock:
            return len(self._cache)


_knowledge_cache = KnowledgeCache()


def invalidate_knowledge_cache() -> None:
    """Invalidate all cached RAG knowledge entries after documentation ingestion."""
    _knowledge_cache.clear()
    logger.info("Knowledge retrieval cache invalidated.")


# Backwards compatibility alias
clear_knowledge_cache = invalidate_knowledge_cache


@tool
def get_knowledge(
    query: str | None = None,
    question: str | None = None,
    search_query: str | None = None,
    top_k: int = 4,
    document_type: str | None = None,
) -> dict[str, Any]:
    """Retrieve relevant operational guides, troubleshooting manuals, and system documentation.

    Use this tool when answering questions about:
    - How to fix or troubleshoot cameras, offline streams, or detection issues.
    - System configuration, installation, deployment, and architecture.
    - Operating procedures, alert policies, watchlist rules, and best practices.

    DO NOT call this tool for simple queries about live camera status or recent events.

    Args:
        query: Specific semantic search query describing the problem or topic.
        question: Optional alias for query.
        search_query: Optional alias for query.
        top_k: Number of most relevant passages to return (1-10, default: 4).
        document_type: Optional filter (e.g. 'markdown', 'pdf', 'txt', 'troubleshooting').

    Returns:
        Structured collection of relevant passages with scores, document titles, and section headers.
    """
    clean_q = (query or question or search_query or "").strip()
    if not clean_q:
        return {
            "status": "insufficient_context",
            "message": "Query must not be empty.",
            "results": [],
        }

    bounded_k = max(1, min(10, top_k))
    cache_key = (clean_q.lower(), bounded_k, document_type)
    cached = _knowledge_cache.get(cache_key)
    if cached is not None:
        return cached

    with KnowledgeRetriever() as retriever:
        res = retriever.retrieve(
            query=clean_q,
            top_k=bounded_k,
            document_type=document_type,
        )
        if isinstance(res, dict) and res.get("status") == "success":
            _knowledge_cache.set(cache_key, res)
        return res
