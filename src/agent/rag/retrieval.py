"""Semantic vector retrieval service for DATT RAG knowledge base."""

from dataclasses import dataclass, field
import logging
from typing import Any
from uuid import UUID

import numpy as np
from sqlalchemy import select

from src.agent.config import agent_config
from src.agent.rag.embeddings import BaseEmbeddingService, get_embedding_service
from src.db.database import Database
from src.db.models import KnowledgeChunk, KnowledgeDocument

logger = logging.getLogger("datt.agent.retrieval")


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
    """Retrieves relevant documentation passages via vector similarity search."""

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

    def retrieve(
        self,
        query: str,
        top_k: int | None = None,
        document_type: str | None = None,
        score_threshold: float | None = None,
    ) -> dict[str, Any]:
        """Retrieve relevant knowledge chunks for a user query.

        Args:
            query: User search or question string.
            top_k: Number of chunks to return (default from config).
            document_type: Optional filter (e.g. 'markdown', 'pdf', 'troubleshooting').
            score_threshold: Minimum cosine similarity score (default from config).

        Returns:
            Dictionary matching the required RAG tool output schema.
        """
        k = top_k or agent_config.rag_top_k
        threshold = score_threshold if score_threshold is not None else agent_config.rag_score_threshold

        clean_query = (query or "").strip()
        if not clean_query:
            return {
                "status": "insufficient_context",
                "message": "Empty query provided.",
                "results": [],
            }

        # Embed query
        query_vec = self.embedder.embed_query(clean_query)
        if len(query_vec) != agent_config.embedding_dim:
            raise ValueError(
                f"Incompatible query vector dimension: got {len(query_vec)}, "
                f"expected {agent_config.embedding_dim} for model {agent_config.embedding_model}"
            )

        candidates: list[RetrievedChunk] = []
        for attempt in range(2):
            try:
                with self.db.transaction() as session:
                    is_postgres = session.bind.dialect.name == "postgresql"

                    if is_postgres:
                        # Use native pgvector cosine distance: distance_col = chunk.embedding <=> query_vec
                        # Cosine similarity = 1.0 - distance
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

                        stmt = stmt.order_by(dist_col.asc()).limit(k * 2)
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
                        # SQLite fallback: load chunks and compute cosine similarity in memory
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
                        candidates = []
                        q_arr = np.array(query_vec, dtype=np.float32)
                        q_norm = np.linalg.norm(q_arr) or 1.0

                        for chunk_row, doc_title, doc_type in rows:
                            emb = chunk_row.embedding
                            if not emb:
                                continue
                            c_arr = np.array(emb, dtype=np.float32)
                            c_norm = np.linalg.norm(c_arr) or 1.0
                            sim = float(np.dot(q_arr, c_arr) / (q_norm * c_norm))
                            if sim >= threshold:
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
                    break
            except Exception as exc:
                if attempt == 0 and ("connection" in str(exc).lower() or "closed" in str(exc).lower()):
                    logger.warning("Database connection dropped during retrieval; reconnecting: %s", exc)
                    continue
                raise

        selected = candidates[:k]
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
