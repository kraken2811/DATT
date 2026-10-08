"""Unit and integration tests for DATT Agent RAG subsystem."""

from pathlib import Path
import pytest

from src.agent.rag.chunking import chunk_document
from src.agent.rag.embeddings import FastEmbedService, MockEmbeddingService, get_embedding_service
from src.agent.rag.ingestion import IngestionService
from src.agent.rag.retrieval import KnowledgeRetriever
from src.db.database import Database
from src.db.models import KnowledgeChunk, KnowledgeDocument


@pytest.fixture
def mock_embedder():
    return MockEmbeddingService(dimension=384)


@pytest.fixture
def fast_embedder():
    return FastEmbedService(dimension=384)


@pytest.fixture
def test_db():
    db = Database()
    yield db
    db.dispose()


def test_chunking_with_markdown_headers():
    doc_text = """# DATT Overview
The DATT system monitors computer vision streams and vehicle tracking.

## Camera Configuration
Cameras are configured in YAML or PostgreSQL registry.
Each camera has an ID and RTSP/HLS stream URL.

### Troubleshooting Camera Offline
When a camera is offline, verify network reachability and RTSP credentials.
Check error logs for HTTP 404 or connection refused.
"""
    chunks = chunk_document(doc_text, doc_metadata={"source": "docs/test.md"}, chunk_size=200, chunk_overlap=30)
    assert len(chunks) >= 2
    # Verify section titles extracted
    sections = [c.metadata.get("section") for c in chunks]
    assert any("Camera Configuration" in s or "Troubleshooting" in s or "Overview" in s for s in sections)


def test_mock_embedding_determinism(mock_embedder):
    vec1 = mock_embedder.embed_query("CAM01 connection timeout")
    vec2 = mock_embedder.embed_query("CAM01 connection timeout")
    assert len(vec1) == 384
    assert vec1 == vec2
    # Different text produces different embedding
    vec3 = mock_embedder.embed_query("Vehicle watchlist registration")
    assert vec1 != vec3


def test_ingestion_and_retrieval_flow(test_db, fast_embedder):
    service = IngestionService(db=test_db, embedding_service=fast_embedder)
    retriever = KnowledgeRetriever(db=test_db, embedding_service=fast_embedder)

    doc_content = """# Camera Troubleshooting Manual
Section 1: Offline Cameras
If CAM03 is offline, follow these steps:
1. Check the network cable and power supply.
2. Verify if the RTSP or YouTube stream is reachable.
3. Restart the camera stream reader in the Camera Management panel.
"""
    unique_title = "Unit Test Camera Troubleshooting Manual"
    unique_source = "tests/fixtures/test_cam_manual.md"

    # 1. Ingest text
    res = service.ingest_text(
        title=unique_title,
        text=doc_content,
        source=unique_source,
        document_type="markdown",
        force_update=True,
    )
    assert res.status in ("created", "updated")
    assert res.chunks_created >= 1

    # 2. Duplicate ingestion should be skipped
    res_dup = service.ingest_text(
        title=unique_title,
        text=doc_content,
        source=unique_source,
        document_type="markdown",
        force_update=False,
    )
    assert res_dup.status == "skipped"

    # 3. Retrieve knowledge
    search_res = retriever.retrieve(
        query="If CAM03 is offline, follow these steps:",
        top_k=3,
        score_threshold=0.50,
    )
    assert search_res["status"] == "success"
    assert len(search_res["results"]) > 0
    first_result = search_res["results"][0]
    assert "content" in first_result
    assert "document_name" in first_result
    assert first_result["document_name"] == unique_title
    assert "score" in first_result

    # 4. Insufficient context test
    empty_res = retriever.retrieve(
        query="completely unrelated astronomical quantum query xyz987654",
        score_threshold=0.999,
    )
    assert empty_res["status"] == "insufficient_context"
    assert len(empty_res["results"]) == 0

    # Cleanup test document
    with test_db.transaction() as session:
        doc = session.query(KnowledgeDocument).filter(KnowledgeDocument.source == unique_source).first()
        if doc:
            session.delete(doc)


def test_dimension_mismatch_protection(test_db):
    """Verify that incompatible embedding dimension is rejected."""
    wrong_dim_embedder = MockEmbeddingService(dimension=512)
    service = IngestionService(db=test_db, embedding_service=wrong_dim_embedder)

    with pytest.raises(ValueError, match="Incompatible embedding dimension"):
        service.ingest_text(
            title="Dimension Test",
            text="This should fail due to dimension mismatch.",
            source="tests/fixtures/wrong_dim.md",
            force_update=True,
        )

    retriever = KnowledgeRetriever(db=test_db, embedding_service=wrong_dim_embedder)
    with pytest.raises(ValueError, match="Incompatible query vector dimension"):
        retriever.retrieve(query="Test query with wrong dimension")
