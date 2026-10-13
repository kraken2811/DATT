"""Next-Best-Action recommendation engine for DATT Operations Investigation Agent.

Generates contextual, actionable follow-up suggestions grounded in actual investigation results.
These suggestions are returned to the React UI as interactive action chips.
"""

from typing import Any


def generate_action_suggestions(
    investigation_context: dict[str, Any] | None,
    tools_called: list[str],
    last_reply: str = "",
) -> list[dict[str, str]]:
    """Derive 2-4 contextual next-best-actions grounded in verified results."""
    suggestions: list[dict[str, str]] = []
    ctx = investigation_context or {}
    entity = ctx.get("current_entity") or {}
    entity_type = entity.get("type")
    plate = entity.get("plate")
    target_name = entity.get("name")
    tools_set = set(tools_called or [])

    # 1. Vehicle Investigation Next Actions
    if "investigate_vehicle" in tools_set or entity_type == "vehicle":
        p_repr = plate or "phương tiện này"
        if "canh bao" not in last_reply.lower() and "alert" not in last_reply.lower():
            suggestions.append({
                "label": "Kiểm tra cảnh báo",
                "action": "check_alerts",
                "query": f"Kiểm tra các cảnh báo an ninh liên quan đến xe {p_repr}",
            })
        if "email" not in last_reply.lower() and "thong bao" not in last_reply.lower():
            suggestions.append({
                "label": "Trạng thái Email",
                "action": "check_notifications",
                "query": f"Trạng thái gửi email thông báo cho xe {p_repr} như thế nào?",
            })
        if "hôm qua" not in last_reply.lower():
            suggestions.append({
                "label": "Thế hôm qua thì sao?",
                "action": "investigate_yesterday",
                "query": f"Thế hôm qua xe {p_repr} có xuất hiện ở camera nào không?",
            })
        if len(suggestions) < 3:
            suggestions.append({
                "label": "Xem camera khác",
                "action": "check_other_cameras",
                "query": f"Xe {p_repr} còn đi qua những camera nào khác?",
            })

    # 2. Face Investigation Next Actions
    elif "investigate_face" in tools_set or entity_type == "face":
        n_repr = target_name or "đối tượng này"
        suggestions.append({
            "label": "Kiểm tra cảnh báo",
            "action": "check_alerts",
            "query": f"Có cảnh báo nào về đối tượng {n_repr} không?",
        })
        suggestions.append({
            "label": "Trạng thái Email",
            "action": "check_notifications",
            "query": f"Đã gửi email thông báo cho đối tượng {n_repr} chưa?",
        })
        suggestions.append({
            "label": "Lịch sử hôm qua",
            "action": "investigate_yesterday",
            "query": f"Đối tượng {n_repr} hôm qua có xuất hiện không?",
        })

    # 3. Anomaly Detection Next Actions
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

    # 4. Shift Handover Next Actions
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

    # 5. General Camera Status / Offline Next Actions
    elif "get_camera_status" in tools_set or "get_camera" in tools_set:
        if "offline" in last_reply.lower() or "mất kết nối" in last_reply.lower():
            suggestions.append({
                "label": "Tài liệu khắc phục",
                "action": "view_troubleshoot",
                "query": "Theo tài liệu hướng dẫn, cách khắc phục khi camera bị offline hoặc mất kết nối?",
            })
            suggestions.append({
                "label": "Kiểm tra cấu hình",
                "action": "check_config",
                "query": "Kiểm tra thông tin nguồn video và cấu hình của camera này",
            })
        else:
            suggestions.append({
                "label": "Lưu lượng 24h",
                "action": "check_traffic",
                "query": "Cho tôi xem lưu lượng của camera này trong 24 giờ qua",
            })

    # Default fallback suggestions
    if not suggestions:
        suggestions = [
            {
                "label": "Kiểm tra Camera",
                "action": "check_camera",
                "query": "Kiểm tra trạng thái hoạt động của camera_01",
            },
            {
                "label": "Phát hiện bất thường",
                "action": "check_anomalies",
                "query": "Có gì bất thường về lưu lượng trong 2 giờ vừa rồi không?",
            },
            {
                "label": "Báo cáo ca trực",
                "action": "shift_report",
                "query": "Tổng hợp báo cáo bàn giao ca trực hiện tại",
            },
        ]

    # Return top 3 non-repetitive suggestions
    seen_labels = set()
    unique_suggestions = []
    for s in suggestions:
        if s["label"] not in seen_labels:
            seen_labels.add(s["label"])
            unique_suggestions.append(s)
        if len(unique_suggestions) >= 4:
            break

    return unique_suggestions
