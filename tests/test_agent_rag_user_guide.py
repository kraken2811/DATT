"""Regression tests for DATT RAG User Guide and How-To Answer Synthesis.

Verifies:
1. General introduction queries.
2. User guide queries (reproducing query: "Tôi cần tra cứu hướng dẫn sử dụng hệ thống.").
3. Camera usage instructions.
4. Watchlist operation instructions.
5. Troubleshooting queries.
6. Insufficient documentation guard (reports absence of UI steps, no hallucination).
7. Citation correctness (clean references, no raw chunks or retrieval scores).
8. Mock and Gemini provider paths & runtime provider inspection.
"""

import json
from unittest.mock import patch

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import MemorySaver
import pytest

from src.agent.graph import build_agent_graph
from src.agent.knowledge_synthesis import (
    extract_references,
    has_operational_instructions,
    synthesize_knowledge_answer,
)
from src.agent.llm import LLMUnavailableException, create_raw_model, get_active_provider_info
from src.agent.nodes import MockChatModel
from src.agent.rag.intent import (
    DocIntent,
    calculate_adjusted_score,
    classify_doc_intent,
)
from src.agent.response_formatting import format_result, format_tool_messages


@pytest.fixture
def memory_app():
    """Compiled agent graph backed by MemorySaver."""
    mem = MemorySaver()
    return build_agent_graph(checkpointer=mem)


def test_rag_user_guide_query_reproduction(memory_app):
    """Reproduced query: 'Tôi cần tra cứu hướng dẫn sử dụng hệ thống.'

    Must call get_knowledge, prioritize operational guide over README,
    and synthesize the 5 required aspects without raw retrieval scores.
    """
    thread_config = {"configurable": {"thread_id": "test-user-guide-repro"}}
    res = memory_app.invoke(
        {"messages": [HumanMessage(content="Tôi cần tra cứu hướng dẫn sử dụng hệ thống.")]},
        config=thread_config,
    )

    messages = res["messages"]
    assert len(messages) >= 3

    # Check tool call
    ai_msg = messages[1]
    assert isinstance(ai_msg, AIMessage)
    assert ai_msg.tool_calls
    assert ai_msg.tool_calls[0]["name"] == "get_knowledge"

    # Check final answer
    final_reply = messages[-1].content
    assert isinstance(final_reply, str)

    # 1. No raw scores or raw embeddings
    assert "Điểm truy xuất:" not in final_reply
    assert "0.5756" not in final_reply
    assert "score" not in final_reply.lower() or "expected results" in final_reply.lower()

    # 2. Covers 5 required operational aspects
    assert "Mục đích & Chức năng" in final_reply
    assert "Vị trí điều hướng" in final_reply or "Sidebar" in final_reply
    assert "Các bước thao tác" in final_reply or "Bước 1" in final_reply
    assert "Kết quả kỳ vọng" in final_reply
    assert "Lưu ý & Giới hạn" in final_reply

    # 3. Clean document references at the bottom
    assert "Nguồn tài liệu tham khảo:" in final_reply
    assert "User Guide" in final_reply or "USER_GUIDE" in final_reply


def test_rag_general_introduction_query(memory_app):
    """General introduction query: 'Giới thiệu hệ thống DATT'."""
    thread_config = {"configurable": {"thread_id": "test-general-intro"}}
    res = memory_app.invoke(
        {"messages": [HumanMessage(content="Giới thiệu hệ thống DATT")]},
        config=thread_config,
    )
    final_reply = res["messages"][-1].content
    assert "DATT" in final_reply
    assert "giám sát" in final_reply.lower() or "theo dõi" in final_reply.lower()
    assert "Điểm truy xuất:" not in final_reply


def test_rag_camera_usage_instructions(memory_app):
    """Camera operational instructions: 'Cách xem camera trên hệ thống'."""
    thread_config = {"configurable": {"thread_id": "test-cam-usage"}}
    res = memory_app.invoke(
        {"messages": [HumanMessage(content="Cách xem camera trên hệ thống")]},
        config=thread_config,
    )
    final_reply = res["messages"][-1].content

    # Operational UI elements
    assert "Dashboard" in final_reply
    assert "Xem camera" in final_reply or "Monitor" in final_reply or "giám sát" in final_reply.lower()
    assert "Bước 1" in final_reply
    assert "Điểm truy xuất:" not in final_reply
    assert "Nguồn tài liệu tham khảo:" in final_reply


def test_rag_watchlist_operation_instructions(memory_app):
    """Watchlist operational instructions: 'Hướng dẫn thêm đối tượng vào watchlist'."""
    thread_config = {"configurable": {"thread_id": "test-watchlist-guide"}}
    res = memory_app.invoke(
        {"messages": [HumanMessage(content="Hướng dẫn thêm đối tượng vào watchlist")]},
        config=thread_config,
    )
    final_reply = res["messages"][-1].content

    assert "Watchlist" in final_reply
    assert "Thêm đối tượng" in final_reply or "chân dung" in final_reply or "biển số" in final_reply
    assert "Bước 1" in final_reply
    assert "Điểm truy xuất:" not in final_reply


def test_rag_troubleshooting_query(memory_app):
    """Troubleshooting query: 'Hướng dẫn khắc phục sự cố camera offline mất kết nối'."""
    thread_config = {"configurable": {"thread_id": "test-trouble-query"}}
    res = memory_app.invoke(
        {"messages": [HumanMessage(content="Hướng dẫn khắc phục sự cố camera offline mất kết nối")]},
        config=thread_config,
    )
    final_reply = res["messages"][-1].content

    assert "Khắc phục sự cố" in final_reply or "khắc phục" in final_reply.lower()
    assert "RTSP" in final_reply
    assert "worker" in final_reply.lower() or "554" in final_reply
    assert "Điểm truy xuất:" not in final_reply


def test_rag_insufficient_documentation_guard():
    """Requirement 9: When retrieved chunks contain only architectural descriptions

    and no operational steps for a user guide query, report insufficient evidence
    instead of inventing UI actions.
    """
    architectural_data = {
        "status": "success",
        "doc_intent": "user_guide",
        "feature_domain": "ALL",
        "results": [
            {
                "document_name": "TECHNICAL_GUIDE.md",
                "section": "System Architecture",
                "content": "Deep neural network pipeline architecture using ByteTrack and AdaFace embeddings.",
                "score": 0.82,
            },
            {
                "document_name": "DATABASE_SCHEMA.md",
                "section": "PostgreSQL pgvector",
                "content": "Table schema definition with 512-dimensional vector indexing.",
                "score": 0.80,
            },
        ],
    }

    assert not has_operational_instructions(architectural_data["results"])

    reply = synthesize_knowledge_answer("Cách cấu hình camera qua giao diện", architectural_data)
    assert "Thông báo tài liệu:" in reply
    assert "chưa có thông tin quy trình thao tác người dùng" in reply
    assert "không tự tạo ra các bước giao diện" in reply
    assert "TECHNICAL_GUIDE.md" in reply
    # Must not contain fabricated step 1
    assert "Bước 1 — Chọn và xem Camera" not in reply


def test_rag_citation_correctness_and_no_raw_scores():
    """Requirement 6: Citations must be cleanly extracted without retrieval scores."""
    chunks = [
        {"document_name": "USER_GUIDE.md", "section": "Camera Selection", "page": 4, "score": 0.8923},
        {"document_name": "USER_GUIDE.md", "section": "Camera Selection", "page": 4, "score": 0.8123},  # duplicate
        {"document_name": "ADMIN_GUIDE.md", "section": "Workers", "score": 0.7654},
    ]

    refs = extract_references(chunks)
    assert len(refs) == 2  # Deduplicated
    assert refs[0] == "Tài liệu: USER_GUIDE.md — Mục: Camera Selection — Trang: 4"
    assert refs[1] == "Tài liệu: ADMIN_GUIDE.md — Mục: Workers"

    for r in refs:
        assert "0.8923" not in r
        assert "score" not in r.lower()


def test_rag_intent_classification_and_score_adjustment():
    """Requirement 2 & 3: Documentation intents are distinguished and scores adjusted."""
    # Test intent classification
    assert classify_doc_intent("Tôi cần tra cứu hướng dẫn sử dụng hệ thống")["intent"] == DocIntent.USER_GUIDE.value
    assert classify_doc_intent("Kiến trúc hệ thống DATT và các mô hình AI")["intent"] == DocIntent.TECHNICAL_ARCHITECTURE.value
    assert classify_doc_intent("Khắc phục lỗi camera offline mất kết nối")["intent"] == DocIntent.TROUBLESHOOTING.value
    assert classify_doc_intent("Cài đặt và triển khai hệ thống với Docker")["intent"] == DocIntent.INSTALLATION_DEPLOYMENT.value
    assert classify_doc_intent("Giới thiệu hệ thống DATT là gì")["intent"] == DocIntent.GENERAL_INTRODUCTION.value

    # Test score adjustment for user guide
    ug_score = calculate_adjusted_score(
        doc_title="USER_GUIDE.md",
        section="Dashboard",
        content="Hướng dẫn chọn camera trên Dashboard",
        base_score=0.55,
        intent=DocIntent.USER_GUIDE.value,
        feature_domain="CAMERA",
    )
    readme_score = calculate_adjusted_score(
        doc_title="README.md",
        section="Overview",
        content="Tổng quan hệ thống",
        base_score=0.57,
        intent=DocIntent.USER_GUIDE.value,
        feature_domain="CAMERA",
    )
    # USER_GUIDE score should clearly surpass README score
    assert ug_score > readme_score
    assert ug_score >= 0.70
    assert readme_score <= 0.50


def test_rag_runtime_provider_info_and_fallback():
    """Requirement 8: Inspect active LLM provider without exposing keys.

    Do not claim Gemini is active when application uses mock mode.
    """
    info = get_active_provider_info()
    assert "configured_provider" in info
    assert "actual_runtime" in info
    assert "is_mock" in info
    assert "model_name" in info

    # Ensure no API keys are exposed
    for k, v in info.items():
        assert "sk-" not in str(v)
        assert "AIza" not in str(v)

    # Explicit credential requirement when provider is google_genai without key
    with patch("src.agent.config.agent_config.gemini_api_key", None):
        with pytest.raises(LLMUnavailableException):
            create_raw_model("google_genai", "gemini-2.5-flash", 0.1)

