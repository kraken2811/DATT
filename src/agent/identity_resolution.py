"""Context-guided hybrid identity resolution with progressive n-gram backoff.

Coordinates contextual search and scoped keyword search for DATT Watchlist entities.
When initial matching fails, progressively reduces phrase length (N -> N-1 -> ... -> 1)
over the contextually identified entity span without expanding to the entire question.
"""

from __future__ import annotations

import logging
import re
import time
import unicodedata
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import defer

from src.agent.config import agent_config
from src.agent.security import operational_auth_required
from src.db.models import Target

logger = logging.getLogger("datt.agent.identity_resolution")

# Generic entity role and contextual prefix words in Vietnamese surveillance queries.
# These words must never independently establish a reliable identity match.
GENERIC_PERSON_WORDS = {
    "nguoi", "người",
    "ten", "tên",
    "doi tuong", "đối tượng", "doi", "đối", "tuong", "tượng",
    "khuon mat", "khuôn mặt", "khuon", "khuôn", "mat", "mặt",
    "nhan su", "nhân sự", "nhan", "nhân", "su", "sự",
    "nhan vien", "nhân viên", "vien", "viên",
    "ong", "ông", "ba", "bà",
    "anh", "chi", "chị", "em",
    "co", "cô", "chu", "chú", "bac", "bác",
    "ke", "kẻ", "ai",
}

UUID_PATTERN = re.compile(
    r"\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b", re.IGNORECASE
)


def normalize_vietnamese(value: str | None) -> str:
    """Normalize Vietnamese string: lowercase, strip accents, collapse spaces."""
    if not value:
        return ""
    text = value.lower().replace("đ", "d").replace("Đ", "d")
    nfkd = unicodedata.normalize("NFD", text)
    cleaned = "".join(c for c in nfkd if not unicodedata.combining(c))
    cleaned = re.sub(r"[^\w\s-]", " ", cleaned)
    return " ".join(cleaned.split())


def normalize_text_preserve_accents(value: str | None) -> str:
    """Normalize whitespace and punctuation while keeping Vietnamese diacritics."""
    if not value:
        return ""
    cleaned = re.sub(r"[^\w\s-]", " ", value)
    return " ".join(cleaned.split()).lower()


def is_pure_generic(phrase: str) -> bool:
    """Check if all tokens in phrase are generic entity role words."""
    norm = normalize_vietnamese(phrase)
    tokens = norm.split()
    if not tokens:
        return True
    return all(tok in GENERIC_PERSON_WORDS for tok in tokens)


def extract_context_scope(question: str) -> dict[str, Any]:
    """Identify intent, entity domain, scoped entity span, candidate name, and requested fields.

    Example:
        Question: 'Tìm thông tin về sự kiện người tên Long đã từng xuất hiện ở đâu và khoảng thời gian nào?'
        Result: {
            'intent': 'face_recognition_history',
            'entity_domain': 'face_watchlist',
            'entity_span': 'người tên Long',
            'candidate_name': 'Long',
            'requested_fields': ['recognition_time', 'camera', 'location']
        }
    """
    raw_q = question.strip()
    norm_q = normalize_vietnamese(raw_q)

    # 1. Intent & entity domain
    is_vehicle = any(w in norm_q for w in ("xe", "bien so", "phuong tien")) and not any(
        w in norm_q for w in ("khuon mat", "nguoi")
    )
    is_doc = any(w in norm_q for w in ("huong dan", "tai lieu", "cau hinh", "kien truc"))

    if is_doc:
        intent = "knowledge_inquiry"
        domain = "documentation"
    elif is_vehicle:
        intent = "vehicle_recognition_history"
        domain = "vehicle_watchlist"
    else:
        intent = "face_recognition_history"
        domain = "face_watchlist"

    # 2. Check for explicit UUID
    uuid_match = UUID_PATTERN.search(raw_q)
    if uuid_match:
        uuid_str = uuid_match.group()
        return {
            "intent": intent,
            "entity_domain": domain,
            "entity_span": uuid_str,
            "candidate_name": uuid_str,
            "requested_fields": ["recognition_time", "camera", "location"],
        }

    # 3. Extract entity_span and candidate_name
    entity_span = ""
    candidate_name = None

    # Pattern A: Leading phrase like 'người tên Long', 'khuôn mặt Long', 'đối tượng Nguyễn Văn A'
    # Match the prefix and everything up to action/time/location verbs
    prefix_match = re.search(
        r"(?:khuôn mặt|khuon mat|người tên|nguoi ten|đối tượng|doi tuong|nhân sự|nhan su|người|nguoi)\s+",
        raw_q,
        re.IGNORECASE,
    )
    if prefix_match:
        start_idx = prefix_match.start()
        span_sub = raw_q[start_idx:]
        # Find where the entity phrase ends (e.g. before 'đã', 'từng', 'xuất hiện', 'ở đâu', '?')
        boundary = re.search(
            r"\s+(?:đã|da|từng|tung|được|duoc|có|co|ở|o|tại|tai|lúc|luc|khi|trong|ngay|ngày|hôm nay|hom nay|hôm qua|hom qua|trước đây|truoc day|xuất hiện|xuat hien|nhận diện|nhan dien|khớp|khop|tìm thấy|tim thay|camera|thời gian|thoi gian|địa điểm|dia diem|lần nào|lan nao|là ai|la ai|và|va|trả về|tra ve)\b|\?|$",
            span_sub,
            re.IGNORECASE,
        )
        if boundary:
            entity_span = span_sub[: boundary.start()].strip()
        else:
            entity_span = span_sub.strip()

        # Derive candidate_name: strip the entity role prefix
        tail_after_prefix = raw_q[prefix_match.end() :]
        boundary_tail = re.search(
            r"\s+(?:đã|da|từng|tung|được|duoc|có|co|ở|o|tại|tai|lúc|luc|khi|trong|ngay|ngày|hôm nay|hom nay|hôm qua|hom qua|trước đây|truoc day|xuất hiện|xuat hien|nhận diện|nhan dien|khớp|khop|tìm thấy|tim thay|camera|thời gian|thoi gian|địa điểm|dia diem|lần nào|lan nao|là ai|la ai|và|va|trả về|tra ve)\b|\?|$",
            tail_after_prefix,
            re.IGNORECASE,
        )
        if boundary_tail:
            cand_raw = tail_after_prefix[: boundary_tail.start()].strip()
        else:
            cand_raw = tail_after_prefix.strip()

        # Strip quotes if present
        cand_raw = cand_raw.strip(' .,:;!?"\'“”')
        if cand_raw.startswith(('"“\'', '"', "“", "'")):
            cand_raw = cand_raw.strip('"“\'”')
        if cand_raw and not is_pure_generic(cand_raw):
            candidate_name = cand_raw

    # Pattern B: Personal name precedes verbs: 'Long đã từng xuất hiện ở đâu'
    if not entity_span:
        verb_match = re.search(
            r"\b(?:đã|da|từng|tung|được|duoc)\s+(?:được\s+|duoc\s+)?(?:nhận diện|nhan dien|xuất hiện|xuat hien|tìm thấy|tim thay)|xuất hiện|xuat hien|camera nào|camera nao",
            raw_q,
            re.IGNORECASE,
        )
        if verb_match:
            lead = raw_q[: verb_match.start()].strip()
            # Clean greeting / polite starters
            lead_norm = normalize_vietnamese(lead)
            if not lead_norm.startswith(
                ("hãy", "hay", "cho tôi", "cho toi", "tra cứu", "tra cuu", "thời gian", "thoi gian", "địa điểm", "dia diem", "sự kiện", "su kien")
            ):
                lead_clean = lead.strip(' .,:;!?"\'“”')
                if lead_clean and not is_pure_generic(lead_clean):
                    entity_span = lead_clean
                    candidate_name = lead_clean

    # Clean punctuation on entity span
    entity_span = entity_span.strip(' .,:;!?"\'“”')
    if not entity_span and candidate_name:
        entity_span = candidate_name

    # 4. Requested fields identification
    requested_fields = []
    if any(w in norm_q for w in ("thoi gian", "khi nao", "luc nao", "ngay", "gio")):
        requested_fields.append("recognition_time")
    if any(w in norm_q for w in ("camera", "o dau", "tai dau", "dia diem", "vi tri")):
        requested_fields.extend(["camera", "location"])
    if not requested_fields:
        requested_fields = ["recognition_time", "camera", "location"]

    # Deduplicate requested fields while preserving order
    dedup_fields = list(dict.fromkeys(requested_fields))

    return {
        "intent": intent,
        "entity_domain": domain,
        "entity_span": entity_span,
        "candidate_name": candidate_name,
        "requested_fields": dedup_fields,
    }


def generate_ngrams(tokens: list[str], n: int) -> list[str]:
    """Generate all valid consecutive token windows of length n while preserving order."""
    if n <= 0 or not tokens or n > len(tokens):
        return []
    return [" ".join(tokens[i : i + n]) for i in range(len(tokens) - n + 1)]


def calculate_match_score(
    target_name: str,
    target_id: str,
    term: str,
    candidate_name: str | None = None,
    is_exact_uuid: bool = False,
) -> float:
    """Calculate an explainable lexical and contextual relevance score [0.0, 1.0]."""
    if is_exact_uuid:
        return 1.0

    norm_target = normalize_vietnamese(target_name)
    norm_term = normalize_vietnamese(term)
    target_tokens = norm_target.split()
    term_tokens = norm_term.split()

    if not target_tokens or not term_tokens:
        return 0.0

    # If the search term is entirely generic role words, it receives zero score
    if is_pure_generic(term):
        return 0.0

    # 1. Exact full-name match (with or without accents)
    if target_name.strip().lower() == term.strip().lower():
        score = 1.0
    elif norm_target == norm_term:
        score = 0.98
    else:
        # Check token overlap
        specific_term_tokens = [t for t in term_tokens if t not in GENERIC_PERSON_WORDS]
        if not specific_term_tokens:
            return 0.0

        # Exact match on specific term tokens
        specific_phrase = " ".join(specific_term_tokens)
        if norm_target == specific_phrase:
            score = 0.96
        elif norm_target in specific_phrase or specific_phrase in norm_target:
            # Word-level coverage
            matched_tokens = sum(1 for tok in target_tokens if tok in specific_term_tokens)
            coverage = matched_tokens / len(target_tokens)
            # Surname vs Given name discrimination in Vietnamese multi-word names
            if len(target_tokens) > 1 and len(specific_term_tokens) == 1:
                if specific_term_tokens[0] == target_tokens[-1]:
                    # Given name (tên gọi) match: e.g. target="Nguyễn Văn Long", term="Long"
                    score = 0.60 * coverage + 0.35
                else:
                    # Surname only match: e.g. target="Nguyễn Văn Long", term="Nguyễn"
                    score = 0.45 * coverage + 0.25
            else:
                score = 0.70 * coverage + 0.20
        else:
            # Partial token intersection
            matched_tokens = sum(1 for tok in target_tokens if tok in specific_term_tokens)
            if matched_tokens == 0:
                return 0.0
            coverage = matched_tokens / len(target_tokens)
            score = 0.40 * coverage

    # 2. Contextual candidate agreement bonus
    if candidate_name and score > 0.0:
        norm_cand = normalize_vietnamese(candidate_name)
        if norm_cand == norm_target:
            score = min(1.0, score + 0.05)

    return round(score, 4)


def resolve_identity(
    original_question: str,
    contextual_scope: dict[str, Any] | str | None = None,
    candidate_name: str | None = None,
    entity_domain: str = "face_watchlist",
    max_candidates: int = 50,
    db: Any = None,
    session: Any = None,
    is_authenticated: bool = True,
) -> dict[str, Any]:
    """Execute context search and scoped keyword search with progressive n-gram backoff.

    Args:
        original_question: Full user query.
        contextual_scope: Optional pre-extracted scope dict or entity span string.
        candidate_name: Optional explicit candidate name.
        entity_domain: Target entity domain (default: 'face_watchlist').
        max_candidates: Maximum candidate results (default: 50).
        db: Database instance or mock.
        session: Active SQLAlchemy session if within existing transaction.
        is_authenticated: Authentication status of requesting user.

    Returns:
        Structured response with status ('resolved', 'ambiguous', 'not_found', 'database_error', 'authentication_error'),
        target_id, name, resolution_source, matching_stage, matched_terms, and debug metrics.
    """
    start_time = time.perf_counter()
    stages_executed: list[str] = []

    # Authentication check
    if operational_auth_required() and not is_authenticated:
        elapsed = (time.perf_counter() - start_time) * 1000.0
        return {
            "status": "authentication_error",
            "target_id": None,
            "name": None,
            "resolution_source": "auth",
            "matching_stage": "rejected",
            "matched_terms": [],
            "candidate_count": 0,
            "candidates": [],
            "message": "Truy cập bị từ chối: Yêu cầu thông tin xác thực phiên làm việc hợp lệ.",
            "metrics": {
                "total_latency_ms": round(elapsed, 2),
                "stages_executed": ["authentication_check"],
            },
        }

    # 1. Understand context and scope
    if isinstance(contextual_scope, str):
        scope = extract_context_scope(original_question)
        scope["entity_span"] = contextual_scope.strip()
    elif isinstance(contextual_scope, dict):
        scope = dict(contextual_scope)
    else:
        scope = extract_context_scope(original_question)

    effective_cand_name = candidate_name or scope.get("candidate_name")
    entity_span = scope.get("entity_span", "").strip()

    # If entity_span is still empty, fallback to candidate_name or original question snippet
    if not entity_span and effective_cand_name:
        entity_span = effective_cand_name

    logger.debug(
        "resolve_identity scope: entity_span='%s', candidate_name='%s'",
        entity_span,
        effective_cand_name,
    )

    # 2. Check for exact UUID in question, entity_span, or candidate_name
    uuid_str = None
    for text_src in (entity_span, effective_cand_name, original_question):
        if text_src:
            m = UUID_PATTERN.search(str(text_src))
            if m:
                uuid_str = m.group()
                break

    # Helper to execute db query safely across transaction or new session
    database = db or agent_config.get_database()

    def run_query(stmt_builder):
        if session is not None:
            return stmt_builder(session)
        with database.transaction() as s:
            return stmt_builder(s)

    # 3. Handle exact UUID shortcut
    if uuid_str:
        stages_executed.append("exact_uuid")
        try:
            target_uuid = UUID(uuid_str)
            target_row = run_query(
                lambda s: s.scalar(
                    select(Target).where(
                        Target.id == target_uuid,
                        Target.target_type.in_(("face", "person")),
                    )
                )
            )
            elapsed = (time.perf_counter() - start_time) * 1000.0
            if target_row:
                return {
                    "status": "resolved",
                    "target_id": str(target_row.id),
                    "name": target_row.name,
                    "resolution_source": "exact_uuid",
                    "matching_stage": "uuid",
                    "matched_terms": [uuid_str],
                    "candidate_count": 1,
                    "candidates": [
                        {
                            "id": str(target_row.id),
                            "name": target_row.name,
                            "score": 1.0,
                            "stage": "uuid",
                        }
                    ],
                    "confidence": 1.0,
                    "metrics": {
                        "total_latency_ms": round(elapsed, 2),
                        "stages_executed": stages_executed,
                    },
                }
            return {
                "status": "not_found",
                "target_id": None,
                "name": None,
                "resolution_source": "exact_uuid",
                "matching_stage": "uuid",
                "matched_terms": [uuid_str],
                "candidate_count": 0,
                "candidates": [],
                "metrics": {
                    "total_latency_ms": round(elapsed, 2),
                    "stages_executed": stages_executed,
                },
            }
        except SQLAlchemyError as exc:
            elapsed = (time.perf_counter() - start_time) * 1000.0
            logger.error("Database error during UUID lookup: %s", exc)
            return {
                "status": "database_error",
                "target_id": None,
                "name": None,
                "message": f"Database error during identity resolution: {exc}",
                "metrics": {"total_latency_ms": round(elapsed, 2), "stages_executed": stages_executed},
            }
        except Exception as exc:
            elapsed = (time.perf_counter() - start_time) * 1000.0
            return {
                "status": "database_error",
                "target_id": None,
                "name": None,
                "message": str(exc),
                "metrics": {"total_latency_ms": round(elapsed, 2), "stages_executed": stages_executed},
            }

    # 4. If neither entity_span nor candidate_name exists, return not_found
    if not entity_span and not effective_cand_name:
        elapsed = (time.perf_counter() - start_time) * 1000.0
        return {
            "status": "not_found",
            "target_id": None,
            "name": None,
            "resolution_source": "none",
            "matching_stage": "empty_scope",
            "matched_terms": [],
            "candidate_count": 0,
            "candidates": [],
            "metrics": {
                "total_latency_ms": round(elapsed, 2),
                "stages_executed": stages_executed,
            },
        }

    # Internal candidate collection keyed by Target UUID
    candidate_map: dict[str, dict[str, Any]] = {}

    def fetch_targets_by_phrases(phrases: list[str]) -> list[Target]:
        """Batch fetch Target entities matching any of the sanitized phrases."""
        clean_phrases = [p.strip() for p in phrases if p and p.strip() and not is_pure_generic(p)]
        if not clean_phrases:
            return []

        def _exec(s):
            clauses = []
            if s.bind.dialect.name == "sqlite":
                try:
                    s.connection().connection.driver_connection.create_function(
                        "datt_norm_vn", 1, normalize_vietnamese
                    )
                except Exception:
                    pass
                for p in clean_phrases:
                    literal = p.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                    norm_p = normalize_vietnamese(p)
                    clauses.append(Target.name.ilike(f"%{literal}%", escape="\\"))
                    if norm_p:
                        clauses.append(func.datt_norm_vn(Target.name).like(f"%{norm_p}%"))
            else:
                for p in clean_phrases:
                    literal = p.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                    clauses.append(Target.name.ilike(f"%{literal}%", escape="\\"))
            stmt = (
                select(Target)
                .options(defer(Target.embedding))
                .where(Target.target_type.in_(("face", "person")), or_(*clauses))
                .order_by(Target.created_at.desc(), Target.id)
                .limit(max_candidates)
            )
            return s.scalars(stmt).all()

        return run_query(_exec)

    try:
        # ---------------------------------------------------------------------
        # STAGE 1: Coordinated Initial Search (Branch A & Branch B)
        # ---------------------------------------------------------------------
        stages_executed.append("initial_search")

        initial_phrases: list[str] = []
        if effective_cand_name and not is_pure_generic(effective_cand_name):
            initial_phrases.append(effective_cand_name)
        if entity_span and not is_pure_generic(entity_span):
            initial_phrases.append(entity_span)

        # Batch query for initial phrases
        initial_targets = fetch_targets_by_phrases(initial_phrases)

        for target in initial_targets:
            tid = str(target.id)
            # Evaluate match score against candidate_name (Branch A) and full phrase (Branch B)
            score_a = (
                calculate_match_score(target.name, tid, effective_cand_name, effective_cand_name)
                if effective_cand_name
                else 0.0
            )
            score_b = (
                calculate_match_score(target.name, tid, entity_span, effective_cand_name)
                if entity_span
                else 0.0
            )
            best_score = max(score_a, score_b)
            matched_term = (
                effective_cand_name
                if score_a >= score_b and effective_cand_name
                else entity_span
            )
            stage_name = "context_search" if score_a >= score_b and score_a > 0 else "full_phrase"

            if best_score > 0.0:
                candidate_map[tid] = {
                    "id": tid,
                    "name": target.name,
                    "score": best_score,
                    "stage": stage_name,
                    "matched_term": matched_term,
                    "target": target,
                }

        # Check Early Resolution
        sorted_candidates = sorted(
            candidate_map.values(), key=lambda c: c["score"], reverse=True
        )

        if sorted_candidates:
            top = sorted_candidates[0]
            # Early resolution condition:
            # 1. Top score >= 0.85
            # 2. If there are multiple candidates, top score must be clearly dominant (> 0.15 diff)
            #    or exact full name match (score >= 0.96)
            is_dominant = (
                len(sorted_candidates) == 1
                or (top["score"] >= 0.96 and sorted_candidates[1]["score"] < 0.90)
                or (top["score"] >= 0.85 and (top["score"] - sorted_candidates[1]["score"]) >= 0.15)
            )

            if is_dominant:
                elapsed = (time.perf_counter() - start_time) * 1000.0
                return {
                    "status": "resolved",
                    "target_id": top["id"],
                    "name": top["name"],
                    "resolution_source": top["stage"],
                    "matching_stage": top["stage"],
                    "matched_terms": [top["matched_term"]],
                    "candidate_count": 1,
                    "candidates": [
                        {"id": c["id"], "name": c["name"], "score": c["score"], "stage": c["stage"]}
                        for c in sorted_candidates
                    ],
                    "confidence": top["score"],
                    "metrics": {
                        "total_latency_ms": round(elapsed, 2),
                        "stages_executed": stages_executed,
                    },
                }

        # ---------------------------------------------------------------------
        # STAGE 2: Progressive N-gram Backoff
        # ---------------------------------------------------------------------
        tokens = entity_span.split()
        n = len(tokens)

        # Iterate descending phrase length from N-1 down to 1
        for k in range(n - 1, 0, -1):
            stage_label = f"{k}_gram_backoff"
            stages_executed.append(stage_label)

            ngrams_k = generate_ngrams(tokens, k)
            # Exclude phrases that are purely generic words
            non_generic_ngrams = [p for p in ngrams_k if not is_pure_generic(p)]

            if not non_generic_ngrams:
                continue

            k_targets = fetch_targets_by_phrases(non_generic_ngrams)

            for target in k_targets:
                tid = str(target.id)
                for phrase in non_generic_ngrams:
                    k_score = calculate_match_score(
                        target.name, tid, phrase, effective_cand_name
                    )
                    if k_score > 0.0:
                        if tid not in candidate_map or k_score > candidate_map[tid]["score"]:
                            candidate_map[tid] = {
                                "id": tid,
                                "name": target.name,
                                "score": k_score,
                                "stage": f"{k}-gram",
                                "matched_term": phrase,
                                "target": target,
                            }

            # Check if an authoritative, unique identity can be resolved at this stage
            sorted_candidates = sorted(
                candidate_map.values(), key=lambda c: c["score"], reverse=True
            )

            if sorted_candidates:
                top = sorted_candidates[0]
                is_dominant = (
                    len(sorted_candidates) == 1
                    or (top["score"] >= 0.96 and sorted_candidates[1]["score"] < 0.90)
                    or (top["score"] >= 0.85 and (top["score"] - sorted_candidates[1]["score"]) >= 0.15)
                )
                if is_dominant:
                    elapsed = (time.perf_counter() - start_time) * 1000.0
                    return {
                        "status": "resolved",
                        "target_id": top["id"],
                        "name": top["name"],
                        "resolution_source": "progressive_ngram",
                        "matching_stage": top["stage"],
                        "matched_terms": [top["matched_term"]],
                        "candidate_count": 1,
                        "candidates": [
                            {
                                "id": c["id"],
                                "name": c["name"],
                                "score": c["score"],
                                "stage": c["stage"],
                            }
                            for c in sorted_candidates
                        ],
                        "confidence": top["score"],
                        "metrics": {
                            "total_latency_ms": round(elapsed, 2),
                            "stages_executed": stages_executed,
                        },
                    }

        # ---------------------------------------------------------------------
        # STAGE 3: Final Fusion, Conflict and Ambiguity Resolution
        # ---------------------------------------------------------------------
        elapsed = (time.perf_counter() - start_time) * 1000.0
        final_candidates = sorted(
            candidate_map.values(), key=lambda c: c["score"], reverse=True
        )

        # Filter out candidates with near-zero relevance (e.g. spurious partial overlap)
        credible_candidates = [c for c in final_candidates if c["score"] >= 0.30]

        if not credible_candidates:
            return {
                "status": "not_found",
                "target_id": None,
                "name": None,
                "resolution_source": "none",
                "matching_stage": "exhausted",
                "matched_terms": [],
                "candidate_count": 0,
                "candidates": [],
                "metrics": {
                    "total_latency_ms": round(elapsed, 2),
                    "stages_executed": stages_executed,
                },
            }

        # Multiple credible candidates without a dominant winner -> Ambiguous
        if len(credible_candidates) > 1:
            top1 = credible_candidates[0]
            top2 = credible_candidates[1]
            # If top two candidates have very close scores, request clarification
            if abs(top1["score"] - top2["score"]) < 0.15:
                return {
                    "status": "ambiguous",
                    "target_id": None,
                    "name": None,
                    "resolution_source": "hybrid_ngram",
                    "matching_stage": top1["stage"],
                    "matched_terms": [c["matched_term"] for c in credible_candidates[:5]],
                    "candidate_count": len(credible_candidates),
                    "candidates": [
                        {
                            "id": c["id"],
                            "name": c["name"],
                            "score": c["score"],
                            "stage": c["stage"],
                        }
                        for c in credible_candidates
                    ],
                    "confidence": top1["score"],
                    "metrics": {
                        "total_latency_ms": round(elapsed, 2),
                        "stages_executed": stages_executed,
                    },
                }

        # Single credible candidate remaining
        top = credible_candidates[0]
        if top["score"] >= 0.50:
            return {
                "status": "resolved",
                "target_id": top["id"],
                "name": top["name"],
                "resolution_source": top["stage"],
                "matching_stage": top["stage"],
                "matched_terms": [top["matched_term"]],
                "candidate_count": 1,
                "candidates": [
                    {
                        "id": c["id"],
                        "name": c["name"],
                        "score": c["score"],
                        "stage": c["stage"],
                    }
                    for c in credible_candidates
                ],
                "confidence": top["score"],
                "metrics": {
                    "total_latency_ms": round(elapsed, 2),
                    "stages_executed": stages_executed,
                },
            }

        # Score is too weak (< 0.50) -> do not pretend it is a verified person
        return {
            "status": "not_found",
            "target_id": None,
            "name": None,
            "resolution_source": "none",
            "matching_stage": "weak_match_discarded",
            "matched_terms": [],
            "candidate_count": 0,
            "candidates": [],
            "metrics": {
                "total_latency_ms": round(elapsed, 2),
                "stages_executed": stages_executed,
            },
        }

    except SQLAlchemyError as exc:
        elapsed = (time.perf_counter() - start_time) * 1000.0
        logger.error("Database error during identity resolution: %s", exc)
        return {
            "status": "database_error",
            "target_id": None,
            "name": None,
            "message": f"Database error during identity resolution: {exc}",
            "metrics": {
                "total_latency_ms": round(elapsed, 2),
                "stages_executed": stages_executed,
            },
        }
    except Exception as exc:
        elapsed = (time.perf_counter() - start_time) * 1000.0
        logger.error("Unexpected error during identity resolution: %s", exc)
        return {
            "status": "database_error",
            "target_id": None,
            "name": None,
            "message": str(exc),
            "metrics": {
                "total_latency_ms": round(elapsed, 2),
                "stages_executed": stages_executed,
            },
        }
