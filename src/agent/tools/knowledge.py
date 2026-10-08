"""Knowledge retrieval tool (RAG) for DATT AI Agent."""

from typing import Any
from langchain_core.tools import tool

from src.agent.rag.retrieval import KnowledgeRetriever


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
    with KnowledgeRetriever() as retriever:
        return retriever.retrieve(
            query=clean_q,
            top_k=bounded_k,
            document_type=document_type,
        )
