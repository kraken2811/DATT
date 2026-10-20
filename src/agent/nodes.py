"""Agent node and Tool node execution logic for LangGraph."""

import concurrent.futures
import json
import logging
import os
import re
import threading
from typing import Any
import uuid

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.language_models.chat_models import BaseChatModel

from src.agent.config import agent_config
from src.agent.face_history import respond as respond_face_history
from src.agent.investigation.memory import InvestigationMemoryManager
from src.agent.prompts import SYSTEM_PROMPT
from src.agent.response_formatting import (
    current_turn,
    format_tool_messages,
    extract_event_info_for_followup,
    format_single_vehicle_event,
    format_single_face_event,
    DETAIL_TECHNICAL,
    DETAIL_CONCISE,
    DETAIL_EXPLANATION,
)
from src.agent.state import AgentState
from src.agent.security import operational_auth_required
from src.agent.tools import ALL_AGENT_TOOLS
from src.agent.vehicle_history import (
    extract_plate,
    find_prior_vehicle_context,
    vehicle_filters,
    respond as respond_vehicle_history,
)
from src.watchlists.vehicles import normalize_plate

logger = logging.getLogger("datt.agent.nodes")


def operational_filters(question):
    """Carry requested ICT date bounds and explicit camera IDs into every operational tool."""
    dates = {k: v for k, v in vehicle_filters(question).items() if k in ('from_time', 'to_time')}
    camera = re.search(r'\b(cam(?:era)?[_-][\w-]+)\b|\bcamera\s+([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}|\d+)\b', question, re.I)
    if camera:
        value = camera.group(1) or camera.group(2)
        dates['camera_id'] = 'camera_' + value.zfill(2) if value.isdigit() else value
    return dates


def find_prior_face_context(messages: list[BaseMessage]) -> tuple[str | None, str | None, str | None]:
    """Find resolved target_id, latest_event_id, and name from recent face history exchange."""
    for m in reversed(messages[:-1]):
        if isinstance(m, AIMessage):
            tid = m.additional_kwargs.get("face_history_target_id")
            eid = m.additional_kwargs.get("face_history_latest_event_id")
            name = m.additional_kwargs.get("face_history_name")
            if tid or eid:
                return str(tid) if tid else None, str(eid) if eid else None, str(name) if name else None
    return None, None, None


def find_prior_event_context(messages: list[BaseMessage]) -> tuple[str | None, dict | None]:
    """Find latest event ID and event data from prior turns in the conversation."""
    for m in reversed(messages):
        if isinstance(m, AIMessage):
            kw = m.additional_kwargs or {}
            eid = kw.get("latest_event_id") or kw.get("face_history_latest_event_id") or kw.get("event_id")
            edata = kw.get("latest_event_data") or kw.get("latest_event")
            if eid or edata:
                resolved_eid = str(eid) if eid else (str(edata.get("event_id")) if isinstance(edata, dict) and edata.get("event_id") else None)
                return resolved_eid, edata
        elif isinstance(m, ToolMessage):
            try:
                data = json.loads(m.content)
                if isinstance(data, dict):
                    if "event" in data and isinstance(data["event"], dict):
                        ev = data["event"]
                        eid = ev.get("event_id") or ev.get("source_event_id") or ev.get("id")
                        return str(eid) if eid else None, ev
                    events = data.get("events")
                    if isinstance(events, list) and events and isinstance(events[0], dict):
                        ev = events[0]
                        eid = ev.get("event_id") or ev.get("source_event_id") or ev.get("id")
                        return str(eid) if eid else None, ev
            except Exception:
                pass
    return None, None


class MockChatModel:
    """Deterministic rule-based mock chat model for isolated unit tests and offline fixtures only.
    Not selectable in production runtime."""

    def __init__(self, tools: list[Any] | None = None) -> None:
        self.tools = {t.name: t for t in (tools or ALL_AGENT_TOOLS)}

    def bind_tools(self, tools: list[Any]) -> "MockChatModel":
        self.tools = {t.name: t for t in tools}
        return self

    def invoke(self, messages: list[BaseMessage]) -> AIMessage:
        last_msg = messages[-1] if messages else HumanMessage(content="")
        content = last_msg.content if isinstance(last_msg.content, str) else str(last_msg.content)

        # Check if tools are unbound / disabled
        tools_enabled = bool(self.tools)

        # 1. Check if prior message was a ToolMessage
        if isinstance(last_msg, ToolMessage) or (not tools_enabled and current_turn(messages)[1]):
            _, results = current_turn(messages)
            turn_start = max((i for i, m in enumerate(messages) if isinstance(m, HumanMessage) and not str(m.content).startswith('[Hệ thống: Hạn mức')), default=-1)
            is_face_routed = any(isinstance(m, AIMessage) and m.additional_kwargs.get('face_history') for m in messages[turn_start + 1:])
            has_ops_tools = any(
                getattr(m, "name", "") in ("get_alerts", "get_notifications_status", "get_traffic_analytics", "generate_operational_report")
                for m, _ in results
            )
            if is_face_routed or not has_ops_tools:
                face_response = respond_face_history(messages, self.tools)
                if face_response is not None:
                    return face_response
                vehicle_response = respond_vehicle_history(messages, self.tools)
                if vehicle_response is not None:
                    return vehicle_response
            tool_name = getattr(last_msg, "name", "")
            # Hybrid check: If first tool was get_camera_status and user asked for documentation guide
            user_msg = current_turn(messages)[0]
            lower_user = str(user_msg).lower()
            if (
                tools_enabled
                and "get_knowledge" in self.tools
                and tool_name == "get_camera_status"
                and ("tài liệu" in lower_user or "hướng dẫn" in lower_user or "xử lý" in lower_user or "khắc phục" in lower_user)
            ):
                # Call get_knowledge as part of legitimate multi-step execution
                return AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "get_knowledge",
                            "args": {"query": "Hướng dẫn khắc phục camera mất kết nối offline", "top_k": 3},
                            "id": f"call_{uuid.uuid4().hex[:8]}",
                        }
                    ],
                )

            eid, edata = extract_event_info_for_followup(results)
            extra_kw = {}
            if eid:
                extra_kw['latest_event_id'] = eid
            if edata:
                extra_kw['latest_event_data'] = edata
            return AIMessage(content=format_tool_messages(messages), additional_kwargs=extra_kw)

        lower_q = content.lower()
        try:
            op_filters = operational_filters(content)
        except ValueError:
            return AIMessage(content='Ngày tra cứu chưa hợp lệ. Bạn hãy cung cấp ngày theo dạng YYYY-MM-DD hoặc DD/MM/YYYY.')

        # 2. Prompt injection defense
        injection_patterns = [
            "ignore previous instructions", "dump all database", "dump database",
            "secrets", "system prompt", "drop table", "quên chỉ dẫn trước",
        ]
        if any(p in lower_q for p in injection_patterns):
            return AIMessage(
                content="Yêu cầu bị từ chối: Tôi không được phép tiết lộ cấu hình bảo mật hoặc trích xuất cơ sở dữ liệu hệ thống."
            )

        # 3. Creative requests (poems, jokes, chitchat) -> Direct response, NO tools
        if "bài thơ" in lower_q or "làm thơ" in lower_q or "poem" in lower_q:
            return AIMessage(
                content="Camera lặng lẽ bốn phương trời,\nGiám sát an ninh chẳng nghỉ ngơi.\nMỗi khung hình gửi niềm tin cậy,\nBình yên cuộc sống rạng nụ cười."
            )

        # 4. Short-term memory recall (e.g. secret markers or shift codes)
        if "marker" in lower_q or "secret" in lower_q or "bí mật" in lower_q or "mã ca trực" in lower_q or "mã trực" in lower_q or "mã của tôi" in lower_q:
            for m in messages[:-1]:
                m_txt = str(m.content)
                if "ALPHA-" in m_txt:
                    match = re.search(r"ALPHA-\d+", m_txt)
                    if match:
                        return AIMessage(content=f"Mã ca trực (secret marker) của bạn là: {match.group(0)}")
            return AIMessage(content="Tôi không có thông tin về secret marker hoặc mã ca trực nào trong phiên hội thoại này.")

        # Follow-up: Ask for event ID ("Cho tôi ID sự kiện đó", "ID sự kiện là gì")
        if any(p in lower_q for p in ("id sự kiện", "id su kien", "mã sự kiện", "ma su kien", "cho tôi id", "cho toi id", "id của sự kiện", "id cua su kien", "id đó", "id do", "event id", "event_id")):
            eid, edata = find_prior_event_context(messages)
            if eid:
                return AIMessage(
                    content=f"ID sự kiện vừa tra cứu là: `{eid}`.",
                    additional_kwargs={"latest_event_id": eid, "latest_event_data": edata},
                )

        # Follow-up: Deeper examination ("Xem kỹ hơn", "Debug sự kiện", "Xem chi tiết sự kiện đó")
        if any(p in lower_q for p in ("xem kỹ hơn", "xem ky hon", "xem chi tiết hơn", "xem chi tiet hon", "debug sự kiện", "debug su kien", "chi tiết sự kiện", "chi tiet su kien", "xem kỹ sự kiện", "xem ky su kien")):
            eid, edata = find_prior_event_context(messages)
            if eid and "get_event" in self.tools:
                return AIMessage(
                    content="",
                    tool_calls=[{"name": "get_event", "args": {"event_id": eid}, "id": f"call_{uuid.uuid4().hex[:8]}"}],
                    additional_kwargs={"latest_event_id": eid, "latest_event_data": edata},
                )
            elif edata:
                if edata.get('plate') or edata.get('event_type') in ('plate', 'vehicle', 'passage'):
                    content_str = format_single_vehicle_event(edata, detail_level=DETAIL_TECHNICAL, user_question=content)
                else:
                    content_str = format_single_face_event(edata, detail_level=DETAIL_TECHNICAL, user_question=content)
                return AIMessage(
                    content=content_str,
                    additional_kwargs={"latest_event_id": eid, "latest_event_data": edata},
                )

        # Multi-tool query (traffic + alerts + emails)
        is_multi_tool = (
            ("lượt xe" in lower_q or "lưu lượng" in lower_q or "xe" in lower_q)
            and ("cảnh báo" in lower_q or "alert" in lower_q)
            and ("email" in lower_q or "mail" in lower_q or "gửi" in lower_q or "thông báo" in lower_q)
        )
        if is_multi_tool:
            cam_id = op_filters.get("camera_id")
            tr = "today" if ("hôm nay" in lower_q or "hom nay" in lower_q) else ("yesterday" if "hôm qua" in lower_q else None)
            calls = []
            if "get_traffic_analytics" in self.tools:
                args = dict(op_filters)
                if tr:
                    args["time_range"] = tr
                calls.append({"name": "get_traffic_analytics", "args": args, "id": f"call_{uuid.uuid4().hex[:8]}"})
            elif "get_event_statistics" in self.tools:
                calls.append({"name": "get_event_statistics", "args": {"camera_id": cam_id}, "id": f"call_{uuid.uuid4().hex[:8]}"})

            if "get_alerts" in self.tools:
                args = dict(op_filters)
                calls.append({"name": "get_alerts", "args": args, "id": f"call_{uuid.uuid4().hex[:8]}"})

            if "get_notifications_status" in self.tools:
                args = dict(op_filters)
                calls.append({"name": "get_notifications_status", "args": args, "id": f"call_{uuid.uuid4().hex[:8]}"})

            if calls:
                return AIMessage(content="", tool_calls=calls)

        # Shift Handover Report generation
        if any(w in lower_q for w in ("ca trực", "bàn giao ca", "ca sáng", "ca chiều", "ca tối", "ca đêm")):
            if "generate_shift_handover_report" in self.tools:
                st = "current"
                if "sáng" in lower_q:
                    st = "morning"
                elif "chiều" in lower_q:
                    st = "afternoon"
                elif "tối" in lower_q or "đêm" in lower_q:
                    st = "night"
                cam_id = op_filters.get("camera_id")
                return AIMessage(
                    content="",
                    tool_calls=[{"name": "generate_shift_handover_report", "args": {"shift_type": st, "camera_id": cam_id}, "id": f"call_{uuid.uuid4().hex[:8]}"}],
                )

        # Anomaly Detection
        if any(w in lower_q for w in ("bất thường", "đột biến", "tăng vọt", "giảm sâu", "đông bất thường")):
            if "detect_traffic_anomalies" in self.tools:
                hrs = 2
                match_h = re.search(r"(\d+)\s*(?:tiếng|giờ|h)\b", lower_q)
                if match_h:
                    hrs = int(match_h.group(1))
                cam_id = op_filters.get("camera_id")
                return AIMessage(
                    content="",
                    tool_calls=[{"name": "detect_traffic_anomalies", "args": {"time_window_hours": hrs, "camera_id": cam_id}, "id": f"call_{uuid.uuid4().hex[:8]}"}],
                )

        # Vehicle Investigation
        plate_in_q = extract_plate(content)
        is_investigation_q = (
            "điều tra" in lower_q
            or "hành trình" in lower_q
            or "timeline" in lower_q
            or ("ở đâu" in lower_q and ("camera" in lower_q or "watchlist" in lower_q or "cảnh báo" in lower_q))
            or ("lần đầu" in lower_q and ("sau đó" in lower_q or "camera" in lower_q or "watchlist" in lower_q))
        )
        if plate_in_q and is_investigation_q and "investigate_vehicle" in self.tools:
            norm_p = normalize_plate(plate_in_q)
            tr = "today" if ("hôm nay" in lower_q or "hom nay" in lower_q) else ("yesterday" if "hôm qua" in lower_q else None)
            return AIMessage(
                content="",
                tool_calls=[{"name": "investigate_vehicle", "args": {"plate_number": norm_p, "from_time": tr}, "id": f"call_{uuid.uuid4().hex[:8]}"}],
            )

        # Face Investigation
        if ("điều tra" in lower_q or "hành trình" in lower_q) and ("khuôn mặt" in lower_q or "người" in lower_q or "đối tượng" in lower_q) and "investigate_face" in self.tools:
            name_cand = None
            m_name = re.search(r"(?:đối tượng|người|khuôn mặt)\s+([A-Za-zÀ-ỹ\s]+)", content, re.IGNORECASE)
            if m_name:
                name_cand = m_name.group(1).strip()
            return AIMessage(
                content="",
                tool_calls=[{"name": "investigate_face", "args": {"name": name_cand, "from_time": "today"}, "id": f"call_{uuid.uuid4().hex[:8]}"}],
            )

        # Follow-up: "Thế hôm qua thì sao?"
        if "hôm qua" in lower_q and any(w in lower_q for w in ("thì sao", "có không", "xuất hiện không", "thế còn")):
            prior_p, _ = find_prior_vehicle_context(messages)
            if prior_p and "investigate_vehicle" in self.tools:
                return AIMessage(
                    content="",
                    tool_calls=[{"name": "investigate_vehicle", "args": {"plate_number": prior_p, "from_time": "yesterday"}, "id": f"call_{uuid.uuid4().hex[:8]}"}],
                )

        # Operational Report generation
        if (
            "báo cáo" in lower_q
            or "tổng hợp hoạt động" in lower_q
            or "tóm tắt hoạt động" in lower_q
            or "report" in lower_q
        ):
            if "generate_operational_report" in self.tools:
                period = "today"
                if "7 ngày" in lower_q or "tuần" in lower_q:
                    period = "7_days"
                elif "24" in lower_q or "24h" in lower_q or "24 giờ" in lower_q:
                    period = "24h"
                elif "hôm qua" in lower_q:
                    period = "yesterday"

                cam_id = op_filters.get("camera_id")

                args = {"period": period, **op_filters}
                if cam_id:
                    args["camera_id"] = cam_id
                return AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "generate_operational_report",
                            "args": args,
                            "id": f"call_{uuid.uuid4().hex[:8]}",
                        }
                    ],
                )


        # Combined Vehicle History + Watchlist Alert
        plate_in_q = extract_plate(content)
        if plate_in_q and ("cảnh báo" in lower_q or "alert" in lower_q) and any(w in lower_q for w in ("xuất hiện", "ở đâu", "lịch sử", "hôm qua", "hôm nay")):
            norm_p = normalize_plate(plate_in_q)
            calls = []
            if "search_events" in self.tools:
                filters = vehicle_filters(content)
                calls.append({"name": "search_events", "args": {"plate": norm_p, "limit": 50, **filters}, "id": f"call_{uuid.uuid4().hex[:8]}"})
            if "get_alerts" in self.tools:
                calls.append({"name": "get_alerts", "args": {"plate_number": norm_p, **op_filters}, "id": f"call_{uuid.uuid4().hex[:8]}"})
            if calls:
                return AIMessage(content="", tool_calls=calls)

        # Contextual Follow-up Alert / Notification
        has_notif_intent = any(w in lower_q for w in ("cảnh báo", "email", "mail", "thông báo"))
        has_followup_question = (
            ("gửi" in lower_q and "chưa" in lower_q)
            or any(w in lower_q for w in ("có không", "gửi chưa", "chưa", "thành công", "thất bại", "vậy có", "phát sinh", "không?"))
        )
        if has_notif_intent and has_followup_question:
            prior_p, prior_n = find_prior_vehicle_context(messages)
            if prior_p:
                if any(w in lower_q for w in ("email", "mail", "thông báo")) and "get_notifications_status" in self.tools:
                    return AIMessage(
                        content="",
                        tool_calls=[{"name": "get_notifications_status", "args": {"plate_number": prior_p, **op_filters}, "id": f"call_{uuid.uuid4().hex[:8]}"}],
                    )
                if "get_alerts" in self.tools:
                    return AIMessage(
                        content="",
                        tool_calls=[{"name": "get_alerts", "args": {"plate_number": prior_p, **op_filters}, "id": f"call_{uuid.uuid4().hex[:8]}"}],
                    )
            prior_tid, prior_eid, prior_name = find_prior_face_context(messages)
            if prior_tid or prior_eid:
                args = {"limit": 10, **op_filters}
                if prior_eid:
                    args["event_id"] = prior_eid
                if prior_tid:
                    args["target_id"] = prior_tid
                if any(w in lower_q for w in ("email", "mail", "thông báo")) and "get_notifications_status" in self.tools:
                    return AIMessage(
                        content="",
                        tool_calls=[{"name": "get_notifications_status", "args": args, "id": f"call_{uuid.uuid4().hex[:8]}"}],
                    )
                if "get_alerts" in self.tools:
                    return AIMessage(
                        content="",
                        tool_calls=[{"name": "get_alerts", "args": args, "id": f"call_{uuid.uuid4().hex[:8]}"}],
                    )

        face_response = respond_face_history(messages, self.tools)
        if face_response is not None:
            return face_response
        vehicle_response = respond_vehicle_history(messages, self.tools)
        if vehicle_response is not None:
            return vehicle_response

        # If tools are disabled (budget exhausted or unbound), synthesize directly
        if not tools_enabled:
            tool_msgs = [m for m in messages if isinstance(m, ToolMessage)]
            if tool_msgs:
                return AIMessage(content=format_tool_messages(messages))
            return AIMessage(
                content="Hiện chưa thể xác minh thông tin từ hệ thống hoặc dữ liệu công cụ chưa khả dụng."
            )

        # 5. Hybrid question: Camera status first, then documentation
        if ("đang offline" in lower_q or "mất kết nối" in lower_q) and ("tài liệu" in lower_q or "hướng dẫn" in lower_q):
            cam_id = "camera_01"
            for word in content.split():
                clean_w = word.strip(".,:;!?\"'")
                if clean_w.upper().startswith("CAM") or clean_w.lower().startswith("camera"):
                    cam_id = clean_w
                    break
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "get_camera_status",
                        "args": {"camera_id": cam_id},
                        "id": f"call_{uuid.uuid4().hex[:8]}",
                    }
                ],
            )

        # 6. Intent-based tool routing
        # A. Camera status query & camera listing
        if ("camera" in lower_q or "cam" in lower_q) and ("online" in lower_q or "offline" in lower_q or "trạng thái" in lower_q or "status" in lower_q or "danh sách" in lower_q or "liệt kê" in lower_q):
            explicit_cam = None
            for word in content.split():
                clean_w = word.strip(".,:;!?\"'")
                if clean_w.lower() in ("camera", "cam", "camera nào", "cam nào"):
                    continue
                if clean_w.upper().startswith("CAM_") or clean_w.lower().startswith("camera_") or clean_w.lower().startswith("camera-") or (clean_w.upper().startswith("CAM") and len(clean_w) > 3):
                    explicit_cam = clean_w
                    break

            if explicit_cam:
                return AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "get_camera_status",
                            "args": {"camera_id": explicit_cam},
                            "id": f"call_{uuid.uuid4().hex[:8]}",
                        }
                    ],
                )

            # Query list of cameras by status filter
            status_filter = "offline" if "offline" in lower_q else ("online" if "online" in lower_q else ("disabled" if "disabled" in lower_q else "all"))
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "get_camera_status",
                        "args": {"camera_id": None, "status": status_filter},
                        "id": f"call_{uuid.uuid4().hex[:8]}",
                    }
                ],
            )

        # Traffic Analytics, Peak hours, Comparisons, and Categorized Counts
        is_traffic_analytics = (
            "khung giờ" in lower_q
            or "cao điểm" in lower_q
            or "so sánh" in lower_q
            or "tăng hay giảm" in lower_q
            or ("camera nào" in lower_q and ("nhiều lượt xe" in lower_q or "đông xe" in lower_q))
            or ("tổng hợp" in lower_q and ("xe máy" in lower_q or "ô tô" in lower_q or "xe tải" in lower_q))
            or ("lưu lượng" in lower_q and ("tuần này" in lower_q or "tuần qua" in lower_q or "7 ngày" in lower_q or "hôm nay" in lower_q or "hôm qua" in lower_q or "so với" in lower_q))
            or ("lượt xe" in lower_q and ("tuần này" in lower_q or "tuần qua" in lower_q or "7 ngày" in lower_q or "hôm nay" in lower_q or "hôm qua" in lower_q))
        )
        if is_traffic_analytics and "get_traffic_analytics" in self.tools:
            cam_id = op_filters.get("camera_id")

            grp = "camera"
            if "khung giờ" in lower_q or "cao điểm" in lower_q or "giờ" in lower_q:
                grp = "hour"
            elif any(w in lower_q for w in ("xe máy", "ô tô", "xe tải", "loại xe")):
                grp = "camera_and_type" if ("từng camera" in lower_q or "theo camera" in lower_q) else "type"
            elif "ngày" in lower_q and "theo ngày" in lower_q:
                grp = "day"

            tr = None
            if "7 ngày" in lower_q or "tuan qua" in lower_q or "tuần qua" in lower_q:
                tr = "7_days"
            elif "tuần này" in lower_q or "tuan nay" in lower_q:
                tr = "this_week"
            elif "tuần trước" in lower_q or "tuan truoc" in lower_q:
                tr = "last_week"
            elif "hôm nay" in lower_q or "hom nay" in lower_q:
                tr = "today"
            elif "hôm qua" in lower_q or "hom qua" in lower_q:
                tr = "yesterday"

            cw = None
            if "hôm qua" in lower_q and ("so sánh" in lower_q or "hôm nay" in lower_q):
                cw = "yesterday"
                tr = "today"
            elif "tuần trước" in lower_q or "tăng hay giảm" in lower_q:
                cw = "last_week"
                tr = "this_week"

            args = {"group_by": grp, **op_filters}
            if cam_id:
                args["camera_id"] = cam_id
            if tr:
                args["time_range"] = tr
            if cw:
                args["compare_with"] = cw

            return AIMessage(
                content="",
                tool_calls=[{"name": "get_traffic_analytics", "args": args, "id": f"call_{uuid.uuid4().hex[:8]}"}],
            )

        # Alert Center inspection
        if ("cảnh báo" in lower_q or "alert" in lower_q) and not any(w in lower_q for w in ("email", "mail", "thông báo")):
            if "get_alerts" in self.tools:
                st = None
                if "chưa" in lower_q and ("xử lý" in lower_q or "gửi" in lower_q):
                    st = "pending"
                elif "thất bại" in lower_q or "lỗi" in lower_q:
                    st = "failed"
                elif "thành công" in lower_q:
                    st = "sent"

                cam_id = op_filters.get("camera_id")

                p_num = extract_plate(content)
                args = {"limit": 20, **op_filters}
                if st:
                    args["status"] = st
                if cam_id:
                    args["camera_id"] = cam_id
                if p_num:
                    args["plate_number"] = normalize_plate(p_num)
                if "watchlist" in lower_q:
                    args["event_type"] = "all"

                return AIMessage(
                    content="",
                    tool_calls=[{"name": "get_alerts", "args": args, "id": f"call_{uuid.uuid4().hex[:8]}"}],
                )

        # Email Notification delivery status
        if ("email" in lower_q or "mail" in lower_q or "thông báo" in lower_q) and any(w in lower_q for w in ("gửi", "pending", "thử lại", "retry", "lỗi", "thất bại", "trạng thái")):
            if "get_notifications_status" in self.tools:
                st = None
                if "chưa" in lower_q or "pending" in lower_q:
                    st = "pending"
                elif "lỗi" in lower_q or "thất bại" in lower_q:
                    st = "failed"
                elif "thành công" in lower_q or "đã gửi" in lower_q:
                    st = "sent"

                p_num = extract_plate(content)
                args = {"limit": 20, **op_filters}
                if st:
                    args["status"] = st
                if p_num:
                    args["plate_number"] = normalize_plate(p_num)

                return AIMessage(
                    content="",
                    tool_calls=[{"name": "get_notifications_status", "args": args, "id": f"call_{uuid.uuid4().hex[:8]}"}],
                )

        # B. Event counts today / Statistics / Busiest / most crowded camera
        if (
            "bao nhiêu sự kiện" in lower_q
            or "thống kê" in lower_q
            or "đông nhất" in lower_q
            or "busiest" in lower_q
            or "lưu lượng" in lower_q
            or ("hôm nay" in lower_q and ("sự kiện" in lower_q or "xe" in lower_q))
        ):
            group = "camera" if ("đông nhất" in lower_q or "busiest" in lower_q) else "type"
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "get_event_statistics",
                        "args": {"group_by": group},
                        "id": f"call_{uuid.uuid4().hex[:8]}",
                    }
                ],
            )

        # C. Documentation / How-to / Troubleshooting / System Guides -> get_knowledge
        if (
            "tài liệu" in lower_q
            or "hướng dẫn" in lower_q
            or "khắc phục" in lower_q
            or "xử lý thế nào" in lower_q
            or "quy tắc" in lower_q
            or "chính sách" in lower_q
            or "cấu hình" in lower_q
            or "kiến trúc" in lower_q
            or "how to" in lower_q
            or "troubleshoot" in lower_q
            or "bytetrack" in lower_q
            or "giới thiệu" in lower_q
            or "datt là gì" in lower_q
            or "tổng quan" in lower_q
            or "cài đặt" in lower_q
            or "triển khai" in lower_q
            or "cách sử dụng" in lower_q
            or "cách dùng" in lower_q
            or "cách xem" in lower_q
            or "cách thêm" in lower_q
            or "cách tạo" in lower_q
            or "cách đăng ký" in lower_q
            or "làm sao" in lower_q
            or "làm thế nào" in lower_q
            or "làm cách nào" in lower_q
            or "cách tìm" in lower_q
            or "cách tìm kiếm" in lower_q
            or "cách tra cứu" in lower_q
            or "cách lọc" in lower_q
        ):
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "get_knowledge",
                        "args": {"query": content, "top_k": 5},
                        "id": f"call_{uuid.uuid4().hex[:8]}",
                    }
                ],
            )

        # D. Watchlist search (operational query)
        if "watchlist" in lower_q or "danh sách theo dõi" in lower_q:
            target = None
            if "biển số" in lower_q or "30a-" in lower_q:
                match = re.search(r"[0-9]{2}[A-Za-z]-[0-9]{4,5}", content)
                target = match.group(0) if match else None
            args = {"target": target, "limit": 10} if target else {"limit": 10}
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "search_watchlist",
                        "args": args,
                        "id": f"call_{uuid.uuid4().hex[:8]}",
                    }
                ],
            )

        # E. Operational events search (person detection or target or specific events)
        if (
            "target_" in lower_q
            or "xuất hiện" in lower_q
            or ("người" in lower_q and "sự kiện" in lower_q)
            or ("sự kiện" in lower_q and ("gần đây" in lower_q or "tra cứu" in lower_q or "tìm" in lower_q or "danh sách" in lower_q))
        ):
            person_id = None
            for w in content.split():
                if w.lower().startswith("target_"):
                    person_id = w.strip(".,:;!?\"'")
            args = {"limit": 10}
            if person_id:
                args["person_id"] = person_id
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "search_events",
                        "args": args,
                        "id": f"call_{uuid.uuid4().hex[:8]}",
                    }
                ],
            )

        # Only greetings receive the welcome; operational questions ask for detail.
        if content.strip() and not re.fullmatch(r"(?:xin chào|chào(?: bạn)?|hello|hi|hey)[\s.!?]*", lower_q.strip()):
            return AIMessage(content="Bạn có thể nêu rõ tên hoặc ID người, camera, biển số hay khoảng thời gian cần tra cứu để tôi kiểm tra dữ liệu chính xác hơn.")
        return AIMessage(
            content="Xin chào! Tôi là Trợ lý Vận hành Hệ thống DATT. Tôi có thể hỗ trợ bạn kiểm tra camera, tra cứu sự kiện, danh sách theo dõi, thống kê phương tiện hoặc tra cứu tài liệu hướng dẫn khắc phục sự cố."
        )


def get_llm():
    """Resolve configured resilient Chat Model."""
    from src.agent.llm import get_configured_llm
    return get_configured_llm()


def trim_messages(messages: list[BaseMessage], max_count: int = 20) -> list[BaseMessage]:
    """Preserve system message and keep most recent conversation turns starting with HumanMessage."""
    sys_msg = [m for m in messages if isinstance(m, SystemMessage)]
    non_sys = [m for m in messages if not isinstance(m, SystemMessage)]

    if len(non_sys) > max_count:
        non_sys = non_sys[-max_count:]

    # Ensure the non-system sequence always starts with a HumanMessage
    # to avoid orphan ToolMessages breaking strict provider APIs (like Google Gemini)
    first_human_idx = None
    for idx, m in enumerate(non_sys):
        if isinstance(m, HumanMessage):
            first_human_idx = idx
            break

    if first_human_idx is not None and first_human_idx > 0:
        non_sys = non_sys[first_human_idx:]

    return sys_msg + non_sys


def agent_node(state: AgentState) -> dict[str, Any]:
    """LangGraph Agent node: processes messages, injects system prompt, and calls LLM."""
    from src.agent.llm import LLMUnavailableException
    raw_messages = list(state.get("messages", []))

    # 1. Ensure system prompt is first message
    has_system = any(isinstance(m, SystemMessage) for m in raw_messages)
    if not has_system:
        messages = [SystemMessage(content=SYSTEM_PROMPT)] + raw_messages
    else:
        messages = raw_messages

    # Context trimming
    trimmed = trim_messages(messages, max_count=agent_config.max_history_messages)

    # Resolve structured investigation memory context
    current_question = ""
    for m in reversed(raw_messages):
        if isinstance(m, HumanMessage) and not str(m.content).startswith("[Hệ thống: Hạn mức"):
            current_question = str(m.content)
            break

    inv_ctx = InvestigationMemoryManager.resolve_context(
        existing_context=state.get("investigation_context"),
        messages=raw_messages,
        current_question=current_question,
    )

    # 3. Check execution budget
    cycles = state.get("tool_cycles", 0)
    total_calls = state.get("total_tool_calls", 0)
    budget_exhausted = (cycles >= agent_config.max_tool_cycles) or (total_calls >= agent_config.max_total_tool_calls)

    llm = get_llm()
    if not budget_exhausted and hasattr(llm, "bind_tools"):
        llm = llm.bind_tools(ALL_AGENT_TOOLS)
    elif hasattr(llm, "bind_tools"):
        llm = llm.bind_tools([])

    # If budget exhausted, instruct LLM to synthesize partial results
    if budget_exhausted:
        trimmed.append(
            HumanMessage(
                content=(
                    "[Hệ thống: Hạn mức gọi công cụ đã kết thúc "
                    f"({cycles}/{agent_config.max_tool_cycles} chu kỳ, "
                    f"{total_calls}/{agent_config.max_total_tool_calls} lượt gọi). "
                    "Hãy tổng hợp câu trả lời cuối cùng từ các dữ liệu và kết quả một phần đã thu thập được ở trên, "
                    "nêu rõ những thông tin đã xác minh được và lưu ý hạn chế dữ liệu nếu có.]"
                )
            )
        )

    try:
        response = llm.invoke(trimmed)
        extra = response.additional_kwargs or {}
        extra["investigation_context"] = inv_ctx
        response.additional_kwargs = extra
        return {"messages": [response], "investigation_context": inv_ctx}
    except LLMUnavailableException as exc:
        logger.error("LLM unavailable: %s", exc)
        return {
            "messages": [
                AIMessage(
                    content="Dịch vụ mô hình ngôn ngữ (LLM) hiện không khả dụng. Vui lòng thử lại sau.",
                    additional_kwargs={"status": "llm_unavailable", "reason": getattr(exc, "reason", "error"), "investigation_context": inv_ctx},
                )
            ],
            "error": "llm_unavailable",
            "investigation_context": inv_ctx,
        }


_tool_executor: concurrent.futures.ThreadPoolExecutor | None = None
_tool_executor_lock = threading.Lock()
_timed_out_tool_executions: set[concurrent.futures.Future] = set()
_timed_out_lock = threading.Lock()


def get_timed_out_task_count() -> int:
    """Return the number of currently active timed-out tool tasks."""
    with _timed_out_lock:
        return len(_timed_out_tool_executions)


def get_tool_executor() -> concurrent.futures.ThreadPoolExecutor:
    """Retrieve or initialize the bounded, managed ThreadPoolExecutor for agent tools."""
    global _tool_executor
    if _tool_executor is None:
        with _tool_executor_lock:
            if _tool_executor is None:
                max_workers = int(os.getenv("DATT_AGENT_TOOL_MAX_WORKERS", "4"))
                _tool_executor = concurrent.futures.ThreadPoolExecutor(
                    max_workers=max_workers,
                    thread_name_prefix="datt_agent_tool",
                )
    return _tool_executor


def shutdown_tool_executor(wait: bool = False) -> None:
    """Safely terminate the managed tool executor during app teardown or testing."""
    global _tool_executor
    with _tool_executor_lock:
        if _tool_executor is not None:
            _tool_executor.shutdown(wait=wait, cancel_futures=True)
            _tool_executor = None


def tool_node(state: AgentState) -> dict[str, Any]:
    """Safe execution of tool calls with argument validation, error handling, duplicate prevention, and execution budget."""
    messages = state.get("messages", [])
    if not messages:
        return {"messages": []}

    last_ai_message = messages[-1]
    tool_calls = getattr(last_ai_message, "tool_calls", None)
    if not tool_calls:
        return {"messages": []}

    tool_map = {t.name: t for t in ALL_AGENT_TOOLS}
    tool_counts = dict(state.get("tool_call_counts", {}))
    repeated_count = state.get("repeated_tool_calls", 0)
    total_calls = state.get("total_tool_calls", 0)
    inv_ctx = dict(state.get("investigation_context") or {})

    tool_results: list[ToolMessage] = []
    seen_in_batch: set[str] = set()

    for call in tool_calls:
        call_name = call.get("name")
        call_args = call.get("args", {})
        call_id = call.get("id", f"call_{uuid.uuid4().hex[:8]}")
        call_signature = f"{call_name}:{json.dumps(call_args, sort_keys=True)}"

        # A. Execution Budget Check
        if total_calls >= agent_config.max_total_tool_calls:
            logger.info("Total tool call budget reached (%s); skipping further calls", total_calls)
            tool_results.append(
                ToolMessage(
                    content=json.dumps(
                        {
                            "status": "budget_exhausted",
                            "message": f"Hạn mức tổng số lượt gọi công cụ ({agent_config.max_total_tool_calls}) đã đạt. Trả về kết quả một phần.",
                        },
                        ensure_ascii=False,
                    ),
                    tool_call_id=call_id,
                    name=call_name,
                )
            )
            continue

        # B. Duplicate call in same batch/turn check
        if call_signature in seen_in_batch:
            logger.info("Duplicate tool call in same batch detected for %s; skipping duplicate execution", call_signature)
            tool_results.append(
                ToolMessage(
                    content=json.dumps(
                        {
                            "status": "duplicate_call_skipped",
                            "message": f"Công cụ '{call_name}' đã được gọi trong cùng lượt xử lý với đối số tương tự. Tránh gọi trùng lặp.",
                        },
                        ensure_ascii=False,
                    ),
                    tool_call_id=call_id,
                    name=call_name,
                )
            )
            continue
        seen_in_batch.add(call_signature)

        # C. Repeated calls across turns check
        count = tool_counts.get(call_signature, 0) + 1
        tool_counts[call_signature] = count

        if count > agent_config.max_tool_repeats:
            repeated_count += 1
            logger.warning("Repeated tool call loop detected for %s; breaking loop", call_signature)
            tool_results.append(
                ToolMessage(
                    content=json.dumps(
                        {
                            "status": "loop_prevention",
                            "message": f"Công cụ '{call_name}' đã được gọi {count} lần với cùng đối số. Vui lòng tổng hợp câu trả lời từ dữ liệu đã có.",
                        },
                        ensure_ascii=False,
                    ),
                    tool_call_id=call_id,
                    name=call_name,
                )
            )
            continue

        target_tool = tool_map.get(call_name)
        if not target_tool:
            tool_results.append(
                ToolMessage(
                    content=json.dumps({"status": "error", "message": f"Unknown tool '{call_name}'"}),
                    tool_call_id=call_id,
                    name=call_name,
                )
            )
            continue

        # Authorization check for sensitive operational tools
        is_authenticated = state.get("is_authenticated", False)
        sensitive_tools = {tool.name for tool in ALL_AGENT_TOOLS} - {"get_knowledge"}
        require_auth = operational_auth_required()
        if require_auth and call_name in sensitive_tools and not is_authenticated:
            logger.warning(
                "Unauthorized attempt to access sensitive tool %s by unauthenticated user %s",
                call_name,
                state.get("user_id"),
            )
            tool_results.append(
                ToolMessage(
                    content=json.dumps(
                        {
                            "status": "unauthorized",
                            "message": f"Truy cập bị từ chối: Công cụ '{call_name}' yêu cầu thông tin xác thực phiên làm việc hợp lệ (Authorization Bearer token).",
                        },
                        ensure_ascii=False,
                    ),
                    tool_call_id=call_id,
                    name=call_name,
                )
            )
            continue

        # Backpressure check: shed load if worker pool is saturated by running timed-out tasks
        max_tool_workers = int(os.getenv("DATT_AGENT_TOOL_MAX_WORKERS", "4"))
        with _timed_out_lock:
            active_timed_out = len(_timed_out_tool_executions)
        if active_timed_out >= max_tool_workers:
            logger.warning(
                "[TOOL_BACKPRESSURE] Executor saturated (%d/%d timed-out tasks still running). Shedding tool '%s'",
                active_timed_out,
                max_tool_workers,
                call_name,
            )
            tool_results.append(
                ToolMessage(
                    content=json.dumps(
                        {
                            "status": "tool_executor_busy",
                            "message": f"Hệ thống đang bận xử lý các tác vụ trước đó ({active_timed_out} tác vụ nền đang chạy). Vui lòng thử lại sau.",
                        },
                        ensure_ascii=False,
                    ),
                    tool_call_id=call_id,
                    name=call_name,
                )
            )
            continue

        # Execute tool safely with bounded timeout via managed executor
        total_calls += 1
        executor = get_tool_executor()
        future = executor.submit(target_tool.invoke, call_args)
        try:
            res = future.result(timeout=agent_config.tool_timeout_sec)
            inv_ctx = InvestigationMemoryManager.update_from_tool_results(
                context=inv_ctx,
                tool_name=call_name,
                tool_args=call_args,
                tool_result=res,
            )
            if call_name in sensitive_tools and isinstance(res, dict) and res.get('status') == 'error':
                # Older operational tools may wrap driver exceptions in their message.
                # Keep the structured result while excluding private connection details
                # from model prompts, saved tool messages and explicit JSON replies.
                res = {**res, 'message': 'Dữ liệu công cụ chưa khả dụng; chưa thể xác minh kết quả.'}
            content_str = json.dumps(res, ensure_ascii=False) if isinstance(res, (dict, list)) else str(res)
            tool_results.append(
                ToolMessage(
                    content=content_str,
                    tool_call_id=call_id,
                    name=call_name,
                )
            )
        except concurrent.futures.TimeoutError:
            with _timed_out_lock:
                _timed_out_tool_executions.add(future)
                running_timed_out = len(_timed_out_tool_executions)
            logger.warning(
                "Tool %s (call_id=%s) timed out after %.1fs; background thread continues (active timed-out tasks: %d).",
                call_name,
                call_id,
                agent_config.tool_timeout_sec,
                running_timed_out,
            )

            def _on_timed_out_complete(fut: concurrent.futures.Future) -> None:
                with _timed_out_lock:
                    _timed_out_tool_executions.discard(fut)
                try:
                    fut.result()
                    logger.info(
                        "Timed-out tool %s (call_id=%s) background execution completed (discarded safely).",
                        call_name,
                        call_id,
                    )
                except Exception as ex:
                    logger.debug(
                        "Timed-out tool %s (call_id=%s) background execution raised %s (discarded safely).",
                        call_name,
                        call_id,
                        type(ex).__name__,
                    )

            future.add_done_callback(_on_timed_out_complete)
            tool_results.append(
                ToolMessage(
                    content=json.dumps(
                        {
                            "status": "timeout",
                            "message": f"Công cụ '{call_name}' phản hồi quá thời gian quy định ({agent_config.tool_timeout_sec}s).",
                        },
                        ensure_ascii=False,
                    ),
                    tool_call_id=call_id,
                    name=call_name,
                )
            )
        except Exception as exc:
            logger.error("Error executing tool %s (%s)", call_name, type(exc).__name__)
            tool_results.append(
                ToolMessage(
                    content=json.dumps({"status": "error", "message": "Dữ liệu công cụ chưa khả dụng; chưa thể xác minh kết quả."}, ensure_ascii=False),
                    tool_call_id=call_id,
                    name=call_name,
                )
            )

    return {
        "messages": tool_results,
        "tool_call_counts": tool_counts,
        "repeated_tool_calls": repeated_count,
        "tool_cycles": state.get("tool_cycles", 0) + 1,
        "total_tool_calls": total_calls,
        "investigation_context": inv_ctx,
    }


def should_continue(state: AgentState) -> str:
    """Conditional edge router: determines if graph should call tools or finish."""
    if state.get("error") == "llm_unavailable":
        return "__end__"

    messages = state.get("messages", [])
    if not messages:
        return "__end__"

    last_message = messages[-1]
    tool_calls = getattr(last_message, "tool_calls", None)
    if tool_calls and len(tool_calls) > 0:
        cycles = state.get("tool_cycles", 0)
        total_calls = state.get("total_tool_calls", 0)
        repeated = state.get("repeated_tool_calls", 0)
        if (
            cycles >= agent_config.max_tool_cycles
            or total_calls >= agent_config.max_total_tool_calls
            or repeated >= 3
        ):
            logger.info("Ending tool loop due to budget or repeat threshold")
            return "__end__"
        return "tools"

    return "__end__"
