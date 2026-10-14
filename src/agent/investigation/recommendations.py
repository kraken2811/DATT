"""Next-Best-Action recommendation engine for DATT Operations Investigation Agent.

Generates contextual, actionable follow-up suggestions grounded in actual investigation results.
These suggestions are returned to the React UI as interactive action chips.
No static/hallucinated fallbacks are ever returned.
"""

from typing import Any
import re
import unicodedata


def normalized_text(val: str) -> str:
    """Normalize text by stripping diacritics and lower-casing."""
    return "".join(
        c for c in unicodedata.normalize("NFD", (val or "").lower().replace("đ", "d"))
        if not unicodedata.combining(c)
    )


def extract_camera_id(text: str) -> str | None:
    """Extract standard camera identifier like camera_01, camera_02 from text."""
    match = re.search(r"\bcamera[-_\s]*([A-Za-z0-9_-]+)\b", text, re.IGNORECASE)
    if match:
        val = match.group(1).strip()
        if val.lower() not in ("nao", "gi", "nay", "do", "khac", "tat ca", "cac"):
            return f"camera_{val}" if not val.lower().startswith("camera") else val
    return None


def generate_action_suggestions(
    investigation_context: dict[str, Any] | None,
    tools_called: list[str],
    last_reply: str = "",
    user_query: str = "",
    messages: list[Any] | None = None,
) -> list[dict[str, str]]:
    """Derive 0-4 contextual next-best-actions grounded in verified results.

    Returns an empty list [] if no relevant follow-up action applies.
    Never returns static generic fallbacks.
    """
    suggestions: list[dict[str, str]] = []
    ctx = investigation_context or {}
    entity = ctx.get("current_entity") or {}
    entity_type = entity.get("type")
    plate = entity.get("plate")
    target_name = entity.get("name")
    candidates = entity.get("candidates") or ctx.get("candidate_entities") or []
    camera_scope = ctx.get("camera_scope") or []
    tools_set = set(tools_called or [])
    executed_tools = set(ctx.get("executed_tools") or []) | tools_set

    q_norm = normalized_text(user_query)
    reply_lower = (last_reply or "").lower()

    # -------------------------------------------------------------------------
    # 1. Ambiguous Face Target Candidates (User must clarify/select identity)
    # -------------------------------------------------------------------------
    if entity_type == "face_ambiguous" or (len(candidates) > 1 and entity_type in ("face", "face_ambiguous")):
        for cand in candidates[:3]:
            cand_name = cand.get("name") or "đối tượng"
            cand_id = str(cand.get("id") or "")
            short_id = cand_id[:8] if cand_id else ""
            label = f"Chọn {cand_name} ({short_id})" if short_id else f"Chọn {cand_name}"
            query = f"Tìm lịch sử nhận diện của đối tượng {cand_name} có ID {cand_id}" if cand_id else f"Tìm lịch sử nhận diện của đối tượng {cand_name}"
            suggestions.append({
                "label": label,
                "action": "select_candidate",
                "query": query,
            })
        if len(suggestions) < 4 and target_name:
            suggestions.append({
                "label": "Xem danh sách đối tượng",
                "action": "list_candidates",
                "query": f"Liệt kê danh sách chi tiết các đối tượng có tên {target_name}",
            })

    # -------------------------------------------------------------------------
    # 2. Ambiguous Vehicle Candidates (User must clarify/select plate)
    # -------------------------------------------------------------------------
    elif entity_type == "vehicle_ambiguous" or (len(candidates) > 1 and entity_type in ("vehicle", "vehicle_ambiguous")):
        for cand in candidates[:3]:
            p = cand.get("plate") or "phương tiện"
            disp = cand.get("name") or ""
            label = f"Xe {p} ({disp})" if disp else f"Chọn xe {p}"
            query = f"Lịch sử xuất hiện của xe {p} hôm nay"
            suggestions.append({
                "label": label,
                "action": "select_candidate",
                "query": query,
            })

    # -------------------------------------------------------------------------
    # 3. Verified Face Investigation Next Actions
    # -------------------------------------------------------------------------
    elif entity_type == "face" or "investigate_face" in tools_set or ("search_watchlist" in tools_set and target_name and not plate):
        n_repr = target_name or "đối tượng này"
        has_history = "investigate_face" in executed_tools or "lich su nhan dien" in q_norm or "lịch sử nhận diện" in q_norm
        has_alerts = "get_alerts" in executed_tools or "canh bao" in q_norm or "alert" in q_norm
        has_notifs = "get_notifications_status" in executed_tools or "email" in q_norm or "thong bao" in q_norm
        has_yesterday = "hom qua" in q_norm

        if not has_history:
            suggestions.append({
                "label": "Lịch sử nhận diện",
                "action": "face_history",
                "query": f"Tìm lịch sử nhận diện của đối tượng {n_repr}",
            })
        if not has_alerts:
            suggestions.append({
                "label": "Kiểm tra cảnh báo",
                "action": "check_alerts",
                "query": f"Kiểm tra các cảnh báo liên quan đến đối tượng {n_repr}",
            })
        if not has_notifs:
            suggestions.append({
                "label": "Trạng thái Email",
                "action": "check_notifications",
                "query": f"Đã gửi email thông báo cho đối tượng {n_repr} chưa?",
            })
        if not has_yesterday:
            suggestions.append({
                "label": "Lịch sử hôm qua",
                "action": "investigate_yesterday",
                "query": f"Đối tượng {n_repr} hôm qua có xuất hiện không?",
            })

    # -------------------------------------------------------------------------
    # 4. Verified Vehicle Investigation Next Actions
    # -------------------------------------------------------------------------
    elif entity_type == "vehicle" or "investigate_vehicle" in tools_set or plate:
        p_repr = plate or "phương tiện này"
        has_history = "investigate_vehicle" in executed_tools or "lich su" in q_norm
        has_alerts = "get_alerts" in executed_tools or "canh bao" in q_norm
        has_notifs = "get_notifications_status" in executed_tools or "email" in q_norm or "thong bao" in q_norm
        has_yesterday = "hom qua" in q_norm
        has_cameras = "camera" in q_norm or "nhung camera" in q_norm

        if not has_history:
            suggestions.append({
                "label": "Lịch sử xuất hiện",
                "action": "vehicle_history",
                "query": f"Lịch sử xuất hiện của xe {p_repr} hôm nay",
            })
        if not has_cameras and len(suggestions) < 4:
            suggestions.append({
                "label": "Các camera ghi nhận",
                "action": "check_cameras",
                "query": f"Xe {p_repr} đã đi qua những camera nào?",
            })
        if not has_notifs and len(suggestions) < 4:
            suggestions.append({
                "label": "Trạng thái thông báo",
                "action": "check_notifications",
                "query": f"Trạng thái gửi email thông báo cho xe {p_repr} như thế nào?",
            })
        if not has_alerts and len(suggestions) < 4:
            suggestions.append({
                "label": "Kiểm tra cảnh báo",
                "action": "check_alerts",
                "query": f"Có cảnh báo an ninh nào liên quan đến xe {p_repr} không?",
            })
        if not has_yesterday and len(suggestions) < 4:
            suggestions.append({
                "label": "Thế hôm qua thì sao?",
                "action": "investigate_yesterday",
                "query": f"Thế hôm qua xe {p_repr} có xuất hiện ở camera nào không?",
            })

    # -------------------------------------------------------------------------
    # 5. Traffic Analytics Next Actions
    # -------------------------------------------------------------------------
    elif "get_traffic_analytics" in tools_set or "get_event_statistics" in tools_set or ("luu luong" in q_norm and not entity_type):
        cam_id = camera_scope[0] if camera_scope else (extract_camera_id(user_query) or "")
        cam_suffix = f" {cam_id}" if cam_id else ""

        suggestions.append({
            "label": "So sánh với hôm qua",
            "action": "compare_traffic",
            "query": f"So sánh lưu lượng{cam_suffix} hôm nay với hôm qua".strip(),
        })
        suggestions.append({
            "label": "Khung giờ cao điểm",
            "action": "peak_hours",
            "query": f"Khung giờ cao điểm của{cam_suffix} hôm nay là khi nào?".strip() if cam_suffix else "Khung giờ cao điểm hôm nay là khi nào?",
        })
        suggestions.append({
            "label": "Bất thường lưu lượng",
            "action": "check_anomalies",
            "query": f"Có bất thường nào về lưu lượng tại{cam_suffix} trong 2 giờ vừa rồi không?".strip() if cam_suffix else "Có gì bất thường về lưu lượng trong 2 giờ vừa rồi không?",
        })
        if len(suggestions) < 4:
            suggestions.append({
                "label": "Phân loại phương tiện",
                "action": "vehicle_breakdown",
                "query": f"Thống kê phân loại phương tiện tại{cam_suffix} hôm nay".strip() if cam_suffix else "Thống kê phân loại phương tiện trong 24 giờ qua",
            })

    # -------------------------------------------------------------------------
    # 6. Camera Status / Offline Next Actions
    # -------------------------------------------------------------------------
    elif "get_camera_status" in tools_set or "get_camera" in tools_set or ("camera" in q_norm and (camera_scope or extract_camera_id(user_query))):
        cam_id = camera_scope[0] if camera_scope else (extract_camera_id(user_query) or "camera này")
        is_offline = (
            "offline" in reply_lower
            or "mất kết nối" in reply_lower
            or "chưa xác minh" in reply_lower
            or "unverified" in reply_lower
            or "khắc phục" in q_norm
            or ctx.get("last_camera_status") == "offline"
        )
        if is_offline:
            suggestions.append({
                "label": "Kiểm tra nguồn video",
                "action": "check_video_source",
                "query": f"Kiểm tra thông tin nguồn video và cấu hình của {cam_id}",
            })
            suggestions.append({
                "label": "Hướng dẫn khắc phục",
                "action": "view_troubleshoot",
                "query": f"Theo tài liệu hướng dẫn, cách khắc phục khi {cam_id} bị offline hoặc mất kết nối?",
            })
        else:
            suggestions.append({
                "label": "Lưu lượng hôm nay",
                "action": "check_traffic",
                "query": f"Thống kê lưu lượng của {cam_id} hôm nay",
            })
            suggestions.append({
                "label": "Sự kiện gần nhất",
                "action": "check_events",
                "query": f"Cho tôi xem các sự kiện gần đây tại {cam_id}",
            })

    # -------------------------------------------------------------------------
    # 7. Anomaly Detection Next Actions
    # -------------------------------------------------------------------------
    elif "detect_traffic_anomalies" in tools_set:
        suggestions.append({
            "label": "So sánh lịch sử",
            "action": "compare_history",
            "query": "So sánh lưu lượng camera này với các tuần trước trong cùng khung giờ",
        })
        suggestions.append({
            "label": "Phân loại xe",
            "action": "check_classes",
            "query": "Thống kê phân loại phương tiện và lưu lượng trong 24 giờ qua",
        })
        suggestions.append({
            "label": "Kiểm tra cảnh báo",
            "action": "check_alerts",
            "query": "Có cảnh báo an ninh nào trong khoảng thời gian bất thường này không?",
        })

    # -------------------------------------------------------------------------
    # 8. Shift Handover Report Next Actions
    # -------------------------------------------------------------------------
    elif "generate_shift_handover_report" in tools_set:
        suggestions.append({
            "label": "Chi tiết camera offline",
            "action": "check_offline_cameras",
            "query": "Liệt kê danh sách chi tiết các camera đang ngoại tuyến và thời gian mất kết nối",
        })
        suggestions.append({
            "label": "Xem cảnh báo tồn đọng",
            "action": "check_pending_alerts",
            "query": "Những cảnh báo nào trong ca trực đang ở trạng thái pending hoặc thất bại?",
        })
        suggestions.append({
            "label": "Dự báo lưu lượng ngày mai",
            "action": "check_forecast",
            "query": "Dự báo lưu lượng giao thông ngày mai cho các camera trọng điểm",
        })

    # -------------------------------------------------------------------------
    # 9. Documentation / RAG Next Actions
    # -------------------------------------------------------------------------
    elif "get_knowledge" in tools_set:
        if any(w in q_norm for w in ("su kien", "bien so", "event", "nhan dien")):
            suggestions.append({
                "label": "Tìm kiếm sự kiện",
                "action": "search_plate_events",
                "query": "Tìm kiếm sự kiện nhận diện biển số xe gần đây",
            })
            suggestions.append({
                "label": "Kiểm tra danh sách xe",
                "action": "check_watchlist_vehicles",
                "query": "Danh sách phương tiện trong danh sách theo dõi hiện có những xe nào?",
            })
        elif "camera" in q_norm:
            suggestions.append({
                "label": "Kiểm tra camera",
                "action": "check_all_cameras",
                "query": "Kiểm tra danh sách và trạng thái các camera trong hệ thống",
            })

    # -------------------------------------------------------------------------
    # Priority sorting based on proposals in Agent's reply
    # -------------------------------------------------------------------------
    if reply_lower:
        def priority_score(s: dict[str, str]) -> int:
            score = 0
            act = s.get("action", "")
            lbl = s.get("label", "").lower()
            if "lịch sử nhận diện" in reply_lower and (act == "face_history" or "nhận diện" in lbl):
                score -= 10
            if "lịch sử xuất hiện" in reply_lower and (act == "vehicle_history" or "xuất hiện" in lbl):
                score -= 10
            if "cảnh báo" in reply_lower and act == "check_alerts":
                score -= 8
            if ("thông báo" in reply_lower or "email" in reply_lower) and act == "check_notifications":
                score -= 6
            if "nguồn video" in reply_lower and act == "check_video_source":
                score -= 10
            if "khắc phục" in reply_lower and act == "view_troubleshoot":
                score -= 8
            if "giờ cao điểm" in reply_lower and act == "peak_hours":
                score -= 6
            if "hôm qua" in reply_lower and (act in ("compare_traffic", "investigate_yesterday")):
                score -= 4
            return score

        suggestions.sort(key=priority_score)

    # -------------------------------------------------------------------------
    # Deduplication and filtering (0 to 4 suggestions)
    # -------------------------------------------------------------------------
    seen_labels = set()
    seen_queries = set()
    unique_suggestions = []
    for s in suggestions:
        lbl = s.get("label", "").strip()
        qry = s.get("query", "").strip()
        if not lbl or not qry:
            continue
        # Do not suggest the exact same query the user just submitted
        if normalized_text(qry) == q_norm:
            continue
        if lbl not in seen_labels and qry not in seen_queries:
            seen_labels.add(lbl)
            seen_queries.add(qry)
            unique_suggestions.append(s)
        if len(unique_suggestions) >= 4:
            break

    return unique_suggestions
