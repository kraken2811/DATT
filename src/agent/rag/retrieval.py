"""Semantic vector retrieval service for DATT RAG knowledge base."""

from dataclasses import dataclass, field
import logging
import math
import re
import unicodedata
from typing import Any

import numpy as np
from sqlalchemy import select

from src.agent.config import agent_config
from src.agent.rag.chunking import is_low_value_chunk
from src.agent.rag.embeddings import BaseEmbeddingService, get_embedding_service
from src.db.database import Database
from src.db.models import KnowledgeChunk, KnowledgeDocument

logger = logging.getLogger("datt.agent.retrieval")


def _normalize(text: str) -> str:
    raw = unicodedata.normalize("NFKD", text or "")
    ascii_text = "".join(ch for ch in raw if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", ascii_text.lower()).strip()


def _terms(text: str) -> set[str]:
    stop = {
        "va", "la", "cua", "cho", "mot", "nhung", "cac", "the", "nao", "gi", "ve", "trong", "khi",
        "and", "the", "of", "for", "to", "how", "what", "is", "are", "a", "an",
    }
    return {t for t in _normalize(text).split() if len(t) > 1 and t not in stop}


def _lexical_overlap(query: str, candidate: str) -> float:
    q = _terms(query)
    c = _terms(candidate)
    if not q or not c:
        return 0.0
    return len(q & c) / len(q)


@dataclass
class RetrievedChunk:
    """Individual retrieved knowledge chunk with relevance score and provenance."""
    chunk_id: str
    document_id: str
    document_name: str
    content: str
    score: float
    section: str = "General"
    page: int | None = None
    document_type: str = "markdown"
    metadata: dict[str, Any] = field(default_factory=dict)
    rerank_score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        res = {
            "content": self.content,
            "document_name": self.document_name,
            "section": self.section,
            "score": round(self.score, 4),
            "document_type": self.document_type,
        }
        if self.page is not None:
            res["page"] = self.page
        return res


class KnowledgeRetriever:
    """Retrieves relevant documentation passages via semantic search plus lightweight reranking."""

    def __init__(self, db: Database | None = None, embedding_service: BaseEmbeddingService | None = None) -> None:
        self.db = db or agent_config.get_database()
        self._owns_db = db is None
        self.embedder = embedding_service or get_embedding_service()

    def close(self) -> None:
        if self._owns_db:
            self.db.dispose()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    @staticmethod
    def _rerank(query: str, candidates: list[RetrievedChunk], top_k: int) -> list[RetrievedChunk]:
        """Blend semantic score with title/section/content lexical evidence and structural penalties."""
        for candidate in candidates:
            title_overlap = _lexical_overlap(query, candidate.document_name)
            section_overlap = _lexical_overlap(query, candidate.section)
            content_overlap = _lexical_overlap(query, candidate.content[:1600])

            low_value = is_low_value_chunk(candidate.section, candidate.content)
            penalty = 0.35 if low_value else 0.0

            # Vector similarity remains dominant, while heading/title matches improve precision
            # for broad operational queries such as "hướng dẫn sử dụng hệ thống".
            candidate.rerank_score = (
                0.72 * candidate.score
                + 0.12 * title_overlap
                + 0.10 * section_overlap
                + 0.06 * content_overlap
                - penalty
            )

        candidates.sort(key=lambda item: (item.rerank_score, item.score), reverse=True)

        # Avoid returning several adjacent/duplicative chunks from the same section when
        # diverse evidence is available.
        selected: list[RetrievedChunk] = []
        seen: set[tuple[str, str]] = set()
        deferred: list[RetrievedChunk] = []
        for candidate in candidates:
            key = (candidate.document_id, candidate.section)
            if key in seen:
                deferred.append(candidate)
                continue
            selected.append(candidate)
            seen.add(key)
            if len(selected) >= top_k:
                return selected

        for candidate in deferred:
            selected.append(candidate)
            if len(selected) >= top_k:
                break
        return selected

    def retrieve(
        self,
        query: str,
        top_k: int | None = None,
        document_type: str | None = None,
        score_threshold: float | None = None,
    ) -> dict[str, Any]:
        """Retrieve relevant knowledge chunks for a user query."""
        k = top_k or agent_config.rag_top_k
        threshold = score_threshold if score_threshold is not None else agent_config.rag_score_threshold

        clean_query = (query or "").strip()
        if not clean_query:
            return {
                "status": "insufficient_context",
                "message": "Empty query provided.",
                "results": [],
            }

        query_vec = self.embedder.embed_query(clean_query)
        if len(query_vec) != agent_config.embedding_dim:
            raise ValueError(
                f"Incompatible query vector dimension: got {len(query_vec)}, "
                f"expected {agent_config.embedding_dim} for model {agent_config.embedding_model}"
            )

        # Retrieve a wider semantic candidate pool, then rerank locally.
        candidate_limit = max(k * 4, 12)
        candidates: list[RetrievedChunk] = []
        for attempt in range(2):
            try:
                with self.db.transaction() as session:
                    is_postgres = session.bind.dialect.name == "postgresql"

                    if is_postgres:
                        dist_col = KnowledgeChunk.embedding.cosine_distance(query_vec).label("distance")
                        stmt = (
                            select(
                                KnowledgeChunk,
                                KnowledgeDocument.title,
                                KnowledgeDocument.document_type,
                                dist_col,
                            )
                            .join(KnowledgeDocument, KnowledgeChunk.document_id == KnowledgeDocument.id)
                            .where(KnowledgeChunk.embedding.is_not(None))
                        )
                        if document_type:
                            stmt = stmt.where(KnowledgeDocument.document_type == document_type)

                        stmt = stmt.order_by(dist_col.asc()).limit(candidate_limit)
                        rows = session.execute(stmt).all()

                        for chunk_row, doc_title, doc_type, dist in rows:
                            dist_val = float(dist) if dist is not None else 1.0
                            sim_val = max(0.0, 1.0 - dist_val)
                            if sim_val < threshold:
                                continue
                            meta = chunk_row.chunk_metadata or {}
                            candidates.append(
                                RetrievedChunk(
                                    chunk_id=str(chunk_row.id),
                                    document_id=str(chunk_row.document_id),
                                    document_name=doc_title,
                                    content=chunk_row.content,
                                    score=sim_val,
                                    section=meta.get("section", "General"),
                                    page=meta.get("page"),
                                    document_type=doc_type,
                                    metadata=meta,
                                )
                            )
                    else:
                        stmt = (
                            select(
                                KnowledgeChunk,
                                KnowledgeDocument.title,
                                KnowledgeDocument.document_type,
                            )
                            .join(KnowledgeDocument, KnowledgeChunk.document_id == KnowledgeDocument.id)
                            .where(KnowledgeChunk.embedding.is_not(None))
                        )
                        if document_type:
                            stmt = stmt.where(KnowledgeDocument.document_type == document_type)

                        rows = session.execute(stmt).all()
                        q_arr = np.array(query_vec, dtype=np.float32)
                        q_norm = np.linalg.norm(q_arr) or 1.0

                        for chunk_row, doc_title, doc_type in rows:
                            emb = chunk_row.embedding
                            if not emb:
                                continue
                            c_arr = np.array(emb, dtype=np.float32)
                            c_norm = np.linalg.norm(c_arr) or 1.0
                            sim = float(np.dot(q_arr, c_arr) / (q_norm * c_norm))
                            if sim < threshold:
                                continue
                            meta = chunk_row.chunk_metadata or {}
                            candidates.append(
                                RetrievedChunk(
                                    chunk_id=str(chunk_row.id),
                                    document_id=str(chunk_row.document_id),
                                    document_name=doc_title,
                                    content=chunk_row.content,
                                    score=sim,
                                    section=meta.get("section", "General"),
                                    page=meta.get("page"),
                                    document_type=doc_type,
                                    metadata=meta,
                                )
                            )
                        candidates.sort(key=lambda x: x.score, reverse=True)
                        candidates = candidates[:candidate_limit]
                    break
            except Exception as exc:
                if attempt == 0 and ("connection" in str(exc).lower() or "closed" in str(exc).lower()):
                    logger.warning("Database connection dropped during retrieval; reconnecting: %s", exc)
                    continue
                raise

        selected = self._rerank(clean_query, candidates, k)
        if not selected:
            return {
                "status": "insufficient_context",
                "message": f"No sufficiently relevant documentation found for '{query}' (threshold: {threshold}).",
                "results": [],
            }

        return {
            "status": "success",
            "query": clean_query,
            "results": [c.to_dict() for c in selected],
        }
