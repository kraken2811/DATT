"""Comprehensive verification suite for context-guided hybrid search with progressive n-gram backoff.

Covers all 22 mandatory tests defined in the DATT implementation specification:
1. Context Search finds Long directly.
2. Keyword Search finds Long when contextual name extraction is wrong.
3. Full-phrase matching succeeds without fallback.
4. Full phrase fails but a shorter phrase succeeds.
5. Three-word scope falls back 3 -> 2 -> 1.
6. Four-word scope falls back 4 -> 3 -> 2 -> 1.
7. Keyword retrieval remains restricted to the contextual entity span.
8. Generic contextual words do not create false identity matches.
9. Unigram and bigram results are deduplicated by UUID.
10. Context and keyword searches return the same identity.
11. Context and keyword searches return conflicting identities.
12. Multiple people share one surname.
13. Vietnamese diacritics and case normalization.
14. Multiple-word Vietnamese full names.
15. Exact UUID bypasses unnecessary fallback.
16. No matching identity.
17. Database and authentication failures.
18. Existing Face History workflow.
19. Existing Vehicle Watchlist workflows.
20. Existing Notification queries.
21. Existing RAG documentation workflow.
22. No unnecessary extra tool calls after reliable resolution.
"""

from datetime import datetime, timezone
import json
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.exc import OperationalError

from src.agent import graph, nodes
from src.agent.config import agent_config
from src.agent.identity_resolution import (
    GENERIC_PERSON_WORDS,
    calculate_match_score,
    extract_context_scope,
    generate_ngrams,
    is_pure_generic,
    normalize_vietnamese,
    resolve_identity,
)
from src.agent.tools.events import search_events
from src.agent.tools.watchlist import search_watchlist
from src.db.database import Database
from src.db.models import Base, Camera, FaceEvent, Target, VehicleWatchlist

UUID_LONG = UUID("11111111-1111-4111-8111-111111111111")
UUID_NV_LONG = UUID("22222222-2222-4222-8222-222222222222")
UUID_NT_MAI = UUID("33333333-3333-4333-8333-333333333333")
UUID_NH_NAM = UUID("44444444-4444-4444-8444-444444444444")
UUID_TUAN = UUID("55555555-5555-4555-8555-555555555555")
UUID_DANG_LONG = UUID("66666666-6666-4666-8666-666666666666")
UUID_BICH_NGOC = UUID("77777777-7777-4777-8777-777777777777")
UUID_CAM = UUID("88888888-8888-4888-8888-888888888888")

RECOGNIZED = datetime(2026, 10, 8, 8, 9, 10, tzinfo=timezone.utc)
REGISTERED = datetime(2025, 1, 1, tzinfo=timezone.utc)


@pytest.fixture
def hybrid_db(tmp_path, monkeypatch):
    """Setup isolated SQLite database with monitored watchlist entities and recognition events."""
    url = "sqlite:///" + (tmp_path / "hybrid_search.db").as_posix()
    db = Database(url)
    Base.metadata.create_all(db.engine)
    with db.transaction() as session:
        session.add_all([
            Target(id=UUID_LONG, name="Long", target_type="face", active=True, created_at=REGISTERED),
            Target(id=UUID_NV_LONG, name="Nguyễn Văn Long", target_type="face", active=True, created_at=REGISTERED),
            Target(id=UUID_NT_MAI, name="Nguyễn Thị Mai", target_type="face", active=True, created_at=REGISTERED),
            Target(id=UUID_NH_NAM, name="Nguyễn Hoàng Nam", target_type="face", active=True, created_at=REGISTERED),
            Target(id=UUID_TUAN, name="Tuấn", target_type="face", active=True, created_at=REGISTERED),
            Target(id=UUID_DANG_LONG, name="Nguyễn Đăng Long", target_type="face", active=True, created_at=REGISTERED),
            Target(id=UUID_BICH_NGOC, name="Trần Thị Bích Ngọc", target_type="face", active=True, created_at=REGISTERED),
            Camera(id=UUID_CAM, registry_key="CAM_GATE", name="Cổng chính", location="Cổng A, tầng 1", source_type="local", source="fixture.mp4"),
            VehicleWatchlist(plate_number="29A-12345", display_name="Xe Camry đen", owner_info="Nguyễn Văn A"),
        ])
        session.flush()
        session.add_all([
            FaceEvent(camera_id="CAM_GATE", target_id=UUID_LONG, decision="FACE_MATCH", similarity=0.9234, created_at=RECOGNIZED),
            FaceEvent(camera_id="CAM_GATE", target_id=UUID_LONG, decision="FACE_MATCH", similarity=0.8541, created_at=RECOGNIZED.replace(hour=9)),
        ])

    monkeypatch.setattr(agent_config, "get_database", lambda: Database(url))
    monkeypatch.setattr(nodes, "get_llm", lambda: nodes.MockChatModel())
    monkeypatch.setenv("DATT_STRICT_AUTH", "0")
    monkeypatch.setenv("DATT_REQUIRE_OPERATIONAL_AUTH", "0")
    saver = InMemorySaver()

    def ask(question, thread="hybrid-test", user="fixture-operator", authenticated=True):
        return graph.run_agent_message(question, thread, user, authenticated, saver)

    yield db, ask, saver
    db.dispose()


# ---------------------------------------------------------------------------
# TEST 1: Context Search finds Long directly.
# ---------------------------------------------------------------------------
def test_1_context_search_finds_long_directly(hybrid_db):
    db, _, _ = hybrid_db
    q = "Tìm thông tin về sự kiện người tên Long đã từng xuất hiện ở đâu và khoảng thời gian nào?"
    scope = extract_context_scope(q)
    assert scope["candidate_name"] == "Long"
    assert scope["entity_span"] == "người tên Long"

    res = resolve_identity(
        original_question=q,
        contextual_scope=scope,
        candidate_name=scope["candidate_name"],
        db=db,
    )
    assert res["status"] == "resolved"
    assert res["target_id"] == str(UUID_LONG)
    assert res["name"] == "Long"
    assert res["resolution_source"] in ("context_search", "full_phrase")
    assert "initial_search" in res["metrics"]["stages_executed"]
    assert "1_gram_backoff" not in res["metrics"]["stages_executed"]


# ---------------------------------------------------------------------------
# TEST 2: Keyword Search finds Long when contextual name extraction is wrong.
# ---------------------------------------------------------------------------
def test_2_keyword_search_recovers_when_candidate_name_is_wrong(hybrid_db):
    db, _, _ = hybrid_db
    q = "Tìm thông tin về sự kiện người tên Long đã từng xuất hiện ở đâu và khoảng thời gian nào?"
    # Simulate failed/incorrect LLM name extraction
    wrong_candidate = "người tên"  # purely generic prefix mistakenly extracted as name
    scope = {"entity_span": "người tên Long", "candidate_name": wrong_candidate}

    res = resolve_identity(
        original_question=q,
        contextual_scope=scope,
        candidate_name=wrong_candidate,
        db=db,
    )
    assert res["status"] == "resolved"
    assert res["target_id"] == str(UUID_LONG)
    assert res["name"] == "Long"
    assert res["resolution_source"] == "progressive_ngram"
    assert "long" in [t.lower() for t in res["matched_terms"]]


# ---------------------------------------------------------------------------
# TEST 3: Full-phrase matching succeeds without fallback.
# ---------------------------------------------------------------------------
def test_3_full_phrase_matching_succeeds_without_fallback(hybrid_db):
    db, _, _ = hybrid_db
    q = "Thời gian xuất hiện của Trần Thị Bích Ngọc"
    scope = {"entity_span": "Trần Thị Bích Ngọc", "candidate_name": "Trần Thị Bích Ngọc"}

    res = resolve_identity(
        original_question=q,
        contextual_scope=scope,
        candidate_name=scope["candidate_name"],
        db=db,
    )
    assert res["status"] == "resolved"
    assert res["target_id"] == str(UUID_BICH_NGOC)
    assert res["name"] == "Trần Thị Bích Ngọc"
    assert res["metrics"]["stages_executed"] == ["initial_search"]
    assert "3_gram_backoff" not in res["metrics"]["stages_executed"]
    assert "2_gram_backoff" not in res["metrics"]["stages_executed"]


# ---------------------------------------------------------------------------
# TEST 4: Full phrase fails but a shorter phrase succeeds.
# ---------------------------------------------------------------------------
def test_4_full_phrase_fails_but_shorter_phrase_succeeds(hybrid_db):
    db, _, _ = hybrid_db
    q = "Lịch sử nhân sự Nguyễn Văn Long"
    # Scope includes 4 tokens: "nhân sự Nguyễn Văn Long" (no target has this exact name)
    scope = {"entity_span": "nhân sự Nguyễn Văn Long", "candidate_name": None}

    res = resolve_identity(
        original_question=q,
        contextual_scope=scope,
        candidate_name=None,
        db=db,
    )
    assert res["status"] == "resolved"
    assert res["target_id"] == str(UUID_NV_LONG)
    assert res["name"] == "Nguyễn Văn Long"
    # Succeeded at 3-gram ("Nguyễn Văn Long"), stopped before 2-gram or 1-gram
    assert res["matching_stage"] == "3-gram"
    assert "2_gram_backoff" not in res["metrics"]["stages_executed"]


# ---------------------------------------------------------------------------
# TEST 5: Three-word scope falls back 3 -> 2 -> 1.
# ---------------------------------------------------------------------------
def test_5_three_word_scope_falls_back_3_2_1(hybrid_db):
    db, _, _ = hybrid_db
    # Target in DB is simply "Long". Scope is 3 tokens: "người", "tên", "Long"
    q = "Tìm người tên Long"
    scope = {"entity_span": "người tên Long", "candidate_name": None}

    res = resolve_identity(
        original_question=q,
        contextual_scope=scope,
        candidate_name=None,
        db=db,
    )
    assert res["status"] == "resolved"
    assert res["target_id"] == str(UUID_LONG)
    # Executed initial search (3-gram), 2-gram backoff, and 1-gram backoff
    stages = res["metrics"]["stages_executed"]
    assert "initial_search" in stages
    assert "2_gram_backoff" in stages
    assert "1_gram_backoff" in stages


# ---------------------------------------------------------------------------
# TEST 6: Four-word scope falls back 4 -> 3 -> 2 -> 1.
# ---------------------------------------------------------------------------
def test_6_four_word_scope_falls_back_4_3_2_1(hybrid_db):
    db, _, _ = hybrid_db
    # Target in DB is "Tuấn". Scope is 4 tokens: "đối tượng người Tuấn"
    q = "Kiểm tra đối tượng người Tuấn"
    scope = {"entity_span": "đối tượng người Tuấn", "candidate_name": None}

    res = resolve_identity(
        original_question=q,
        contextual_scope=scope,
        candidate_name=None,
        db=db,
    )
    assert res["status"] == "resolved"
    assert res["target_id"] == str(UUID_TUAN)
    stages = res["metrics"]["stages_executed"]
    assert "initial_search" in stages
    assert "3_gram_backoff" in stages
    assert "2_gram_backoff" in stages
    assert "1_gram_backoff" in stages


# ---------------------------------------------------------------------------
# TEST 7: Keyword retrieval remains restricted to the contextual entity span.
# ---------------------------------------------------------------------------
def test_7_keyword_retrieval_restricted_to_contextual_span(hybrid_db):
    q = "Tìm thông tin về sự kiện người tên Long đã từng xuất hiện ở đâu và khoảng thời gian nào?"
    scope = extract_context_scope(q)
    assert scope["entity_span"] == "người tên Long"

    tokens = scope["entity_span"].split()
    all_ngrams = []
    for k in range(len(tokens), 0, -1):
        all_ngrams.extend(generate_ngrams(tokens, k))

    # Terms outside the entity_span must never be in generated lookup phrases
    forbidden_terms = ["thông tin", "sự kiện", "xuất hiện", "ở đâu", "thời gian", "khoảng"]
    for phrase in all_ngrams:
        for forbidden in forbidden_terms:
            assert forbidden not in phrase.lower()


# ---------------------------------------------------------------------------
# TEST 8: Generic contextual words do not create false identity matches.
# ---------------------------------------------------------------------------
def test_8_generic_words_do_not_create_false_identity_matches(hybrid_db):
    db, _, _ = hybrid_db
    # Query composed exclusively of generic role words
    q = "Tìm thông tin về người đối tượng nhân viên"
    scope = {"entity_span": "người đối tượng nhân viên", "candidate_name": None}

    res = resolve_identity(
        original_question=q,
        contextual_scope=scope,
        candidate_name=None,
        db=db,
    )
    assert res["status"] == "not_found"
    assert res["target_id"] is None
    assert res["candidate_count"] == 0


# ---------------------------------------------------------------------------
# TEST 9: Unigram and bigram results are deduplicated by UUID.
# ---------------------------------------------------------------------------
def test_9_candidates_deduplicated_by_target_uuid(hybrid_db):
    db, _, _ = hybrid_db
    q = "người tên Long"
    res = resolve_identity(
        original_question=q,
        contextual_scope="người tên Long",
        candidate_name="Long",
        db=db,
    )
    seen_ids = set()
    for c in res.get("candidates", []):
        assert c["id"] not in seen_ids, f"Duplicate UUID found: {c['id']}"
        seen_ids.add(c["id"])


# ---------------------------------------------------------------------------
# TEST 10: Context and keyword searches return the same identity.
# ---------------------------------------------------------------------------
def test_10_context_and_keyword_searches_agree(hybrid_db):
    db, _, _ = hybrid_db
    q = "Khuôn mặt Long xuất hiện ở đâu"
    res = resolve_identity(
        original_question=q,
        contextual_scope="Long",
        candidate_name="Long",
        db=db,
    )
    assert res["status"] == "resolved"
    assert res["target_id"] == str(UUID_LONG)
    assert res["confidence"] >= 0.95


# ---------------------------------------------------------------------------
# TEST 11: Context and keyword searches return conflicting identities.
# ---------------------------------------------------------------------------
def test_11_conflicting_identities_yield_ambiguity_or_clarification(hybrid_db):
    db, _, _ = hybrid_db
    # Simulated conflicting extraction: candidate_name points to Long, scope points to Tuấn
    q = "Khuôn mặt Tuấn"
    res = resolve_identity(
        original_question=q,
        contextual_scope="Tuấn",
        candidate_name="Long",
        db=db,
    )
    # Both are valid targets in DB with identical match scores, leading to ambiguity
    assert res["status"] == "ambiguous"
    assert res["candidate_count"] >= 2
    cand_names = [c["name"] for c in res["candidates"]]
    assert "Long" in cand_names and "Tuấn" in cand_names


# ---------------------------------------------------------------------------
# TEST 12: Multiple people share one surname.
# ---------------------------------------------------------------------------
def test_12_multiple_people_sharing_surname_yields_ambiguity(hybrid_db):
    db, _, _ = hybrid_db
    # Three targets share surname "Nguyễn": Nguyễn Văn Long, Nguyễn Thị Mai, Nguyễn Hoàng Nam
    q = "Tra cứu người họ Nguyễn"
    res = resolve_identity(
        original_question=q,
        contextual_scope="người họ Nguyễn",
        candidate_name="Nguyễn",
        db=db,
    )
    assert res["status"] == "ambiguous"
    assert res["candidate_count"] >= 3
    cand_ids = {c["id"] for c in res["candidates"]}
    assert str(UUID_NV_LONG) in cand_ids
    assert str(UUID_NT_MAI) in cand_ids
    assert str(UUID_NH_NAM) in cand_ids


# ---------------------------------------------------------------------------
# TEST 13: Vietnamese diacritics and case normalization.
# ---------------------------------------------------------------------------
def test_13_vietnamese_diacritics_and_case_normalization(hybrid_db):
    db, _, _ = hybrid_db
    # Target in DB: "Nguyễn Đăng Long"
    # Query without diacritics and mixed case: "nguyen dang long"
    q = "tim nguoi nguyen dang long"
    res = resolve_identity(
        original_question=q,
        contextual_scope="nguyen dang long",
        candidate_name="nguyen dang long",
        db=db,
    )
    assert res["status"] == "resolved"
    assert res["target_id"] == str(UUID_DANG_LONG)
    assert res["name"] == "Nguyễn Đăng Long"


# ---------------------------------------------------------------------------
# TEST 14: Multiple-word Vietnamese full names.
# ---------------------------------------------------------------------------
def test_14_multiple_word_vietnamese_full_names(hybrid_db):
    db, _, _ = hybrid_db
    # Target: "Trần Thị Bích Ngọc" (4 words)
    q = "Sự kiện của Trần Thị Bích Ngọc"
    res = resolve_identity(
        original_question=q,
        contextual_scope="Trần Thị Bích Ngọc",
        candidate_name="Trần Thị Bích Ngọc",
        db=db,
    )
    assert res["status"] == "resolved"
    assert res["target_id"] == str(UUID_BICH_NGOC)
    assert res["confidence"] >= 0.95


# ---------------------------------------------------------------------------
# TEST 15: Exact UUID bypasses unnecessary fallback.
# ---------------------------------------------------------------------------
def test_15_exact_uuid_bypasses_fallback(hybrid_db):
    db, _, _ = hybrid_db
    uuid_str = str(UUID_LONG)
    q = f"Lịch sử của đối tượng {uuid_str}"
    res = resolve_identity(
        original_question=q,
        contextual_scope=uuid_str,
        candidate_name=uuid_str,
        db=db,
    )
    assert res["status"] == "resolved"
    assert res["target_id"] == uuid_str
    assert res["resolution_source"] == "exact_uuid"
    assert res["matching_stage"] == "uuid"
    assert res["metrics"]["stages_executed"] == ["exact_uuid"]


# ---------------------------------------------------------------------------
# TEST 16: No matching identity.
# ---------------------------------------------------------------------------
def test_16_no_matching_identity(hybrid_db):
    db, _, _ = hybrid_db
    q = "Người tên KhôngCóTrongWatchlist xuất hiện khi nào"
    res = resolve_identity(
        original_question=q,
        contextual_scope="người tên KhôngCóTrongWatchlist",
        candidate_name="KhôngCóTrongWatchlist",
        db=db,
    )
    assert res["status"] == "not_found"
    assert res["target_id"] is None
    assert res["candidate_count"] == 0


# ---------------------------------------------------------------------------
# TEST 17: Database and authentication failures.
# ---------------------------------------------------------------------------
def test_17_database_and_auth_failures(hybrid_db, monkeypatch):
    db, _, _ = hybrid_db
    # A. Auth failure
    monkeypatch.setenv("DATT_REQUIRE_OPERATIONAL_AUTH", "1")
    res_auth = resolve_identity(
        original_question="Tìm Long",
        contextual_scope="Long",
        candidate_name="Long",
        db=db,
        is_authenticated=False,
    )
    assert res_auth["status"] == "authentication_error"
    assert "Truy cập bị từ chối" in res_auth["message"]

    # B. Database error
    monkeypatch.setenv("DATT_REQUIRE_OPERATIONAL_AUTH", "0")
    bad_db = MagicMock()
    bad_db.transaction.side_effect = OperationalError("connection refused", {}, None)
    res_db = resolve_identity(
        original_question="Tìm Long",
        contextual_scope="Long",
        candidate_name="Long",
        db=bad_db,
    )
    assert res_db["status"] == "database_error"
    assert "Database error" in res_db["message"]


# ---------------------------------------------------------------------------
# TEST 18: Existing Face History workflow with the exact specified question.
# ---------------------------------------------------------------------------
def test_18_existing_face_history_workflow(hybrid_db):
    _, ask, saver = hybrid_db
    q = "Tìm thông tin về sự kiện người tên Long đã từng xuất hiện ở đâu và khoảng thời gian nào?"
    result = ask(q)

    # 1. Tool execution sequence: search_watchlist -> search_events
    assert result["tools_called"] == ["search_watchlist", "search_events"]

    # 2. State inspection: verify search_events uses resolved UUID
    state = graph.build_agent_graph(saver).get_state(graph.make_thread_config("hybrid-test", user_id="fixture-operator"))
    calls = [call for m in state.values["messages"] if isinstance(m, AIMessage) for call in m.tool_calls]
    assert calls[0]["name"] == "search_watchlist"
    assert calls[0]["args"]["watchlist_type"] == "face"
    assert calls[1]["name"] == "search_events"
    assert calls[1]["args"]["target_id"] == str(UUID_LONG)
    assert calls[1]["args"]["event_type"] == "face"
    assert calls[1]["args"]["watchlist_match"] is True

    # 3. Final Vietnamese response
    reply = result["reply"]
    assert "Long" in reply and str(UUID_LONG) in reply
    assert "CAM_GATE" in reply and "Cổng chính" in reply
    assert RECOGNIZED.isoformat() in reply
    assert "Tổng số kết quả phù hợp: 2" in reply


# ---------------------------------------------------------------------------
# TEST 19: Existing Vehicle Watchlist workflows.
# ---------------------------------------------------------------------------
def test_19_existing_vehicle_watchlist_workflow(hybrid_db):
    _, ask, _ = hybrid_db
    result = ask("Kiểm tra danh sách theo dõi xe 29A-12345")
    assert "search_watchlist" in result["tools_called"]
    assert "29A-12345" in result["reply"]


# ---------------------------------------------------------------------------
# TEST 20: Existing Notification queries.
# ---------------------------------------------------------------------------
def test_20_existing_notification_queries(hybrid_db):
    _, ask, _ = hybrid_db
    q = "Khuôn mặt Long đã nhận diện ở đâu và đã gửi email cảnh báo chưa?"
    result = ask(q)
    # Expected sequence: search_watchlist -> search_events -> get_notifications_status
    assert result["tools_called"] == ["search_watchlist", "search_events", "get_notifications_status"]
    assert "email cảnh báo" in result["reply"]


# ---------------------------------------------------------------------------
# TEST 21: Existing RAG documentation workflow.
# ---------------------------------------------------------------------------
def test_21_existing_rag_documentation_workflow(hybrid_db):
    _, ask, _ = hybrid_db
    result = ask("Hướng dẫn cấu hình camera Bytetrack trong hệ thống")
    assert result["tools_called"] == ["get_knowledge"]


# ---------------------------------------------------------------------------
# TEST 22: No unnecessary extra tool calls after reliable resolution.
# ---------------------------------------------------------------------------
def test_22_no_unnecessary_extra_tool_calls_after_resolution(hybrid_db):
    _, ask, saver = hybrid_db
    q = "Tìm thông tin về sự kiện người tên Long đã từng xuất hiện ở đâu và khoảng thời gian nào?"
    result = ask(q)
    # Once Long is resolved and historical events are retrieved, graph finishes cleanly
    assert len(result["tools_called"]) == 2
    assert result["tools_called"] == ["search_watchlist", "search_events"]
