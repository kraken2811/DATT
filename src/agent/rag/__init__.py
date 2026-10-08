"""RAG (Retrieval-Augmented Generation) subsystem for DATT AI Agent."""

from .embeddings import get_embedding_service
from .chunking import chunk_document
from .ingestion import IngestionService
from .retrieval import KnowledgeRetriever

__all__ = [
    "get_embedding_service",
    "chunk_document",
    "IngestionService",
    "KnowledgeRetriever",
]
