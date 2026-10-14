"""Documentation intent classification and feature domain extraction for DATT RAG."""

from enum import Enum
import re
from typing import Any
import unicodedata


class DocIntent(str, Enum):
    """Categorized documentation retrieval intents."""
    GENERAL_INTRODUCTION = "general_introduction"
    USER_GUIDE = "user_guide"
    TECHNICAL_ARCHITECTURE = "technical_architecture"
    TROUBLESHOOTING = "troubleshooting"
    INSTALLATION_DEPLOYMENT = "installation_deployment"


def normalize_vietnamese_text(text: str) -> str:
    """Normalize Vietnamese diacritics to lowercase ASCII for robust keyword matching."""
    if not text:
        return ""
    t = text.lower().replace("đ", "d").replace("Đ", "d")
    nfkd = unicodedata.normalize("NFD", t)
    cleaned = "".join(c for c in nfkd if not unicodedata.combining(c))
    cleaned = re.sub(r"[^\w\s-]", " ", cleaned)
    return " ".join(cleaned.split())


def classify_doc_intent(query: str) -> dict[str, Any]:
    """Identify documentation intent and target feature domain from a user query.

    Args:
        query: User input query in Vietnamese or English.

    Returns:
        dict containing:
        - intent: DocIntent enum value
        - feature_domain: 'ALL', 'CAMERA', 'WATCHLIST', 'EVENT_CENTER', 'ALERT_CENTER', 'THEME', 'AI_ASSISTANT'
        - is_user_guide: bool
        - search_terms: list of recommended keywords to enhance semantic lookup
    """
    raw_q = query.strip()
    norm_q = normalize_vietnamese_text(raw_q)

    # 1. Check for Troubleshooting Intent
    trouble_cues = [
        "khac phuc", "sua loi", "su co", "mat ket noi", "offline",
        "khong xem duoc", "khong nhan dien duoc", "loi", "troubleshoot",
        "xu ly khi", "khong the ket noi", "bi lag", "bi ngat",
    ]
    if any(cue in norm_q for cue in trouble_cues) and not any(
        w in norm_q for w in ("cai dat", "deploy", "kien truc")
    ):
        return {
            "intent": DocIntent.TROUBLESHOOTING.value,
            "feature_domain": "TROUBLESHOOTING",
            "is_user_guide": False,
            "search_terms": ["khắc phục sự cố", "troubleshooting", "offline", "kết nối"],
        }

    # 2. Check for Installation & Deployment Intent
    install_cues = [
        "cai dat", "trien khai", "deploy", "docker", "docker compose",
        "docker-compose", "cau hinh moi truong", "yeu cau phan cung",
        "yeu cau he thong", "gpu", "cuda", "colab", "run only", "setup",
    ]
    if any(cue in norm_q for cue in install_cues) and not any(
        w in norm_q for w in ("huong dan su dung he thong", "cach su dung camera")
    ):
        return {
            "intent": DocIntent.INSTALLATION_DEPLOYMENT.value,
            "feature_domain": "DEPLOYMENT",
            "is_user_guide": False,
            "search_terms": ["cài đặt", "triển khai", "yêu cầu hệ thống", "docker"],
        }

    # 3. Check for Technical Architecture Intent
    tech_cues = [
        "kien truc", "cau truc he thong", "cong nghe", "technical",
        "yolo", "scrfd", "adaface", "easyocr", "bytetrack", "database schema",
        "pgvector", "mo hinh ai", "deep learning", "pipeline", "kien truc va dac ta",
    ]
    if any(cue in norm_q for cue in tech_cues) and not any(
        w in norm_q for w in ("huong dan su dung", "cach su dung", "cach them", "cach xem")
    ):
        return {
            "intent": DocIntent.TECHNICAL_ARCHITECTURE.value,
            "feature_domain": "ARCHITECTURE",
            "is_user_guide": False,
            "search_terms": ["kiến trúc kỹ thuật", "mô hình AI", "đặc tả kỹ thuật"],
        }

    # 4. Check for General System Introduction Intent
    intro_cues = [
        "gioi thieu he thong", "datt la gi", "he thong datt la gi",
        "he thong dung de lam gi", "datt dung de lam gi", "tong quan he thong",
    ]
    if any(cue in norm_q for cue in intro_cues) and not any(
        w in norm_q for w in ("huong dan su dung", "cach su dung", "cach lam", "cac buoc")
    ):
        return {
            "intent": DocIntent.GENERAL_INTRODUCTION.value,
            "feature_domain": "GENERAL",
            "is_user_guide": False,
            "search_terms": ["giới thiệu hệ thống", "hệ thống dùng để làm gì", "tổng quan"],
        }

    # 5. End-user Operation Guide (Default for how-to, user-guide, feature operations)
    # Detect specific feature domain
    domain = "ALL"
    terms = ["hướng dẫn sử dụng", "thao tác người dùng"]

    if any(w in norm_q for w in ("event", "su kien", "event center", "tra cuu su kien", "loc su kien", "tim kiem su kien")):
        domain = "EVENT_CENTER"
        terms.extend(["Event Center", "tra cứu sự kiện", "lọc sự kiện", "ảnh bằng chứng", "tìm kiếm sự kiện"])
    elif any(w in norm_q for w in ("camera", "cam", "nguon", "stream", "giam sat", "toan man hinh", "fullscreen")):
        domain = "CAMERA"
        terms.extend(["quản lý camera", "giám sát trực tiếp", "chọn camera", "xem camera"])
    elif any(w in norm_q for w in ("watchlist", "khuon mat", "bien so", "them nguoi", "dang ky", "upload", "anh")):
        domain = "WATCHLIST"
        terms.extend(["Face Watchlist", "Vehicle Watchlist", "thêm đối tượng", "đăng ký"])
    elif any(w in norm_q for w in ("alert", "canh bao", "alert center", "email", "thong bao", "toast")):
        domain = "ALERT_CENTER"
        terms.extend(["Alert Center", "cảnh báo email", "Global Toast Alert"])
    elif any(w in norm_q for w in ("theme", "mau", "giao dien", "sidebar", "cai dat", "banh rang")):
        domain = "THEME"
        terms.extend(["Theme Accent Color", "Sidebar", "cài đặt giao diện"])
    elif any(w in norm_q for w in ("ai assistant", "tro ly", "chat")):
        domain = "AI_ASSISTANT"
        terms.extend(["AI Assistant", "trợ lý thông minh"])

    return {
        "intent": DocIntent.USER_GUIDE.value,
        "feature_domain": domain,
        "is_user_guide": True,
        "search_terms": terms,
    }


def calculate_adjusted_score(
    doc_title: str,
    section: str,
    content: str,
    base_score: float,
    intent: str,
    feature_domain: str,
) -> float:
    """Adjust retrieval similarity score based on classified documentation intent and target feature domain."""
    score = base_score
    doc_lower = (doc_title or "").lower()
    sec_lower = (section or "").lower()
    content_lower = (content or "").lower()

    if intent == DocIntent.USER_GUIDE.value:
        # Prioritize actual operational user guide passages over technical overviews
        if any(w in doc_lower for w in ("user guide", "user_guide", "hướng dẫn sử dụng", "user manual")):
            score += 0.15
        elif any(w in doc_lower for w in ("admin guide", "admin_guide")):
            score += 0.08
        elif any(w in doc_lower for w in ("readme", "technical_guide", "technical guide", "architecture")):
            score -= 0.08

        # Feature domain boosting
        if feature_domain == "CAMERA" and any(w in content_lower or w in sec_lower for w in ("camera", "dashboard", "giám sát", "màn hình", "monitor")):
            score += 0.06
        elif feature_domain == "WATCHLIST" and any(w in content_lower or w in sec_lower for w in ("watchlist", "khuôn mặt", "biển số", "đối tượng", "đăng ký")):
            score += 0.06
        elif feature_domain == "EVENT_CENTER" and any(w in content_lower or w in sec_lower for w in ("event center", "sự kiện", "tra cứu", "bằng chứng")):
            score += 0.06
        elif feature_domain == "ALERT_CENTER" and any(w in content_lower or w in sec_lower for w in ("alert center", "cảnh báo", "email", "toast")):
            score += 0.06
        elif feature_domain == "THEME" and any(w in content_lower or w in sec_lower for w in ("theme", "màu", "bánh răng", "cài đặt")):
            score += 0.06

    elif intent == DocIntent.TECHNICAL_ARCHITECTURE.value:
        if any(w in doc_lower for w in ("technical", "architecture", "kiến trúc", "schema")):
            score += 0.15
        elif any(w in doc_lower for w in ("user guide", "user_guide")):
            score -= 0.05

    elif intent == DocIntent.TROUBLESHOOTING.value:
        if any(w in content_lower or w in sec_lower for w in ("khắc phục", "sự cố", "troubleshoot", "offline", "lỗi", "mất kết nối")):
            score += 0.20

    elif intent == DocIntent.INSTALLATION_DEPLOYMENT.value:
        if any(w in content_lower or w in sec_lower for w in ("cài đặt", "triển khai", "docker", "setup", "yêu cầu hệ thống", "gpu", "cuda")):
            score += 0.15

    elif intent == DocIntent.GENERAL_INTRODUCTION.value:
        if any(w in doc_lower for w in ("readme", "tổng quan", "giới thiệu")) or any(w in sec_lower for w in ("tổng quan", "giới thiệu")):
            score += 0.10

    return min(1.0, max(0.0, score))

