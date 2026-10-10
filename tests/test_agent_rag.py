"""Unit and integration tests for DATT Agent RAG subsystem."""

from pathlib import Path
import pytest

from src.agent.rag.chunking import chunk_document, embedding_text_for_chunk, is_low_value_chunk
from src.agent.rag.embeddings import FastEmbedService, MockEmbeddingService
from src.agent.rag.ingestion import IngestionService
from src.agent.rag.retrieval import KnowledgeRetriever, RetrievedChunk
from src.db.database import Database
from src.db.models import KnowledgeDocument


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
    sections = [c.metadata.get("section") for c in chunks]
    assert any("Camera Configuration" in s or "Troubleshooting" in s or "Overview" in s for s in sections)


def test_table_of_contents_is_filtered_from_chunks():
    doc_text = """# USER GUIDE

## MỤC LỤC
1. [Giới thiệu hệ thống](#1-gioi-thieu-he-thong)
2. [Các chức năng chính](#2-cac-chuc-nang-chinh)
3. [Quản lý Camera](#3-quan-ly-camera)
4. [Event Center](#4-event-center)

## Các chức năng chính
DATT cho phép quản lý camera, watchlist, sự kiện, cảnh báo và AI Assistant.
"""
    chunks = chunk_document(doc_text, doc_metadata={"title": "User Guide"}, chunk_size=250, chunk_overlap=20)
    assert chunks
    assert all("MỤC LỤC" not in c.metadata.get("section", "") for c in chunks)
    assert any("Các chức năng chính" in c.metadata.get("section", "") for c in chunks)
    assert is_low_value_chunk("MỤC LỤC", "1. [Giới thiệu](#gioi-thieu)\n2. [Camera](#camera)\n3. [Events](#events)")


def test_embedding_text_contains_document_and_section_context():
    chunks = chunk_document(
        "# Guide\n\n## Camera offline\nKiểm tra ingestion worker và nguồn video.",
        doc_metadata={"title": "DATT User Guide"},
        chunk_size=200,
        chunk_overlap=10,
    )
    target = next(c for c in chunks if "ingestion worker" in c.content)
    embedding_text = embedding_text_for_chunk(target, "DATT User Guide")
    assert "Document: DATT User Guide" in embedding_text
    assert "Section: Camera offline" in embedding_text
    assert "Kiểm tra ingestion worker" in embedding_text


def test_retrieval_reranker_penalizes_toc_and_rewards_section_match():
    candidates = [
        RetrievedChunk(
            chunk_id="toc", document_id="doc", document_name="User Guide", content="1. [Camera](#camera)\n2. [Watchlist](#watchlist)\n3. [Events](#events)",
            score=0.78, section="MỤC LỤC",
        ),
        RetrievedChunk(
            chunk_id="guide", document_id="doc", document_name="User Guide", content="Quản lý camera, watchlist, Event Center và Alert Center từ giao diện DATT.",
            score=0.74, section="Các chức năng chính",
        ),
    ]
    ranked = KnowledgeRetriever._rerank("hướng dẫn sử dụng hệ thống camera watchlist event", candidates, 2)
    assert ranked[0].chunk_id == "guide"
    assert ranked[-1].chunk_id == "toc"


def test_mock_embedding_determinism(mock_embedder):
    vec1 = mock_embedder.embed_query("CAM01 connection timeout")
    vec2 = mock_embedder.embed_query("CAM01 connection timeout")
    assert len(vec1) == 384
    assert vec1 == vec2
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

    res = service.ingest_text(
        title=unique_title,
        text=doc_content,
        source=unique_source,
        document_type="markdown",
        force_update=True,
    )
    assert res.status in ("created", "updated")
    assert res.chunks_created >= 1

    res_dup = service.ingest_text(
        title=unique_title,
        text=doc_content,
        source=unique_source,
        document_type="markdown",
        force_update=False,
    )
    assert res_dup.status == "skipped"

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

    empty_res = retriever.retrieve(
        query="completely unrelated astronomical quantum query xyz987654",
        score_threshold=0.999,
    )
    assert empty_res["status"] == "insufficient_context"
    assert len(empty_res["results"]) == 0

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
