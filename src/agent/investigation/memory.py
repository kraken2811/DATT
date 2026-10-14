"""Structured Investigation Memory management for DATT AI Assistant.

Maintains multi-turn context for:
- current_entity (vehicle plate or face target)
- time_range (presets like 'today', 'yesterday' or ISO bounds)
- camera_scope
- last_event_id, last_alert_id, last_tool_results
- context_version

Handles follow-up queries:
- "Có cảnh báo không?" -> retains entity & time_range, inspects alerts
- "Thế hôm qua thì sao?" -> retains entity, shifts time_range to yesterday
- "Vậy email đã gửi chưa?" -> retains entity & alert, checks notification status
- "Xóa ngữ cảnh" / "Cuộc trò chuyện mới" -> resets memory
"""

from datetime import datetime, timezone, timedelta
import logging
import re
from typing import Any
import unicodedata

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from src.watchlists.vehicles import normalize_plate

logger = logging.getLogger("datt.agent.investigation.memory")
LOCAL_TZ = timezone(timedelta(hours=7))  # Asia/Ho_Chi_Minh (UTC+7)


def normalized_text(val: str) -> str:
    """Normalize text by stripping diacritics and lower-casing."""
    return "".join(
        c for c in unicodedata.normalize("NFD", (val or "").lower().replace("đ", "d"))
        if not unicodedata.combining(c)
    )


def extract_plate_from_text(text: str) -> str | None:
    """Extract standard Vietnamese plate pattern from text."""
    match = re.search(r"\b[0-9]{2}[A-Za-z][-.\s]?[0-9]{3,5}(?:\.[0-9]{2})?\b", text)
    if match:
        return match.group(0).strip()
    match2 = re.search(r"\b[0-9]{2}[A-Za-z][0-9]{4,5}\b", text)
    if match2:
        return match2.group(0).strip()
    return None


def parse_time_intent(question: str) -> dict[str, Any] | None:
    """Detect time range intent in question."""
    q_norm = normalized_text(question)
    now_ict = datetime.now(timezone.utc).astimezone(LOCAL_TZ)

    if "hom nay" in q_norm:
        start_ict = now_ict.replace(hour=0, minute=0, second=0, microsecond=0)
        return {
            "preset": "today",
            "from_time": start_ict.isoformat(),
            "to_time": now_ict.isoformat(),
            "label": "Hôm nay",
        }
    elif "hom qua" in q_norm:
        today_0 = now_ict.replace(hour=0, minute=0, second=0, microsecond=0)
        start_ict = today_0 - timedelta(days=1)
        end_ict = today_0 - timedelta(microseconds=1)
        return {
            "preset": "yesterday",
            "from_time": start_ict.isoformat(),
            "to_time": end_ict.isoformat(),
            "label": "Hôm qua",
        }
    elif any(w in q_norm for w in ("7 ngay", "tuan qua", "tuan nay")):
        start_ict = (now_ict - timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)
        return {
            "preset": "7_days",
            "from_time": start_ict.isoformat(),
            "to_time": now_ict.isoformat(),
            "label": "7 ngày qua",
        }
    elif any(w in q_norm for w in ("24 gio", "24h")):
        start_ict = now_ict - timedelta(hours=24)
        return {
            "preset": "24h",
            "from_time": start_ict.isoformat(),
            "to_time": now_ict.isoformat(),
            "label": "24 giờ qua",
        }
    return None


class InvestigationMemoryManager:
    """State manager for structured investigation context across conversation turns."""

    @staticmethod
    def get_initial_context() -> dict[str, Any]:
        return {
            "current_entity": None,
            "time_range": {
                "preset": "today",
                "label": "Hôm nay",
                "timezone": "Asia/Ho_Chi_Minh",
            },
            "camera_scope": [],
            "investigation_goal": None,
            "last_event_id": None,
            "last_alert_id": None,
            "last_tool_name": None,
            "context_version": 1,
        }

    @classmethod
    def resolve_context(
        cls,
        existing_context: dict[str, Any] | None,
        messages: list[Any],
        current_question: str,
    ) -> dict[str, Any]:
        """Update or derive structured investigation context for the current turn."""
        ctx = dict(existing_context) if existing_context else cls.get_initial_context()
        q_norm = normalized_text(current_question)

        # 1. Explicit context reset
        if any(w in q_norm for w in ("xoa ngu canh", "bat dau dieu tra moi", "cuoc tro chuyen moi", "reset ngu canh")):
            return cls.get_initial_context()

        # 2. Check for explicit vehicle plate in current question
        found_plate = extract_plate_from_text(current_question)
        if found_plate:
            norm_p = normalize_plate(found_plate)
            # If changing entity or first entity
            ctx["current_entity"] = {
                "type": "vehicle",
                "plate": found_plate,
                "normalized_plate": norm_p,
                "target_id": None,
                "name": None,
            }
            ctx["context_version"] = ctx.get("context_version", 1) + 1

        # 3. Check for time range updates
        time_intent = parse_time_intent(current_question)
        if time_intent:
            ctx["time_range"] = {**time_intent, "timezone": "Asia/Ho_Chi_Minh"}

        # 4. Check for camera filter updates
        cam_match = re.search(r"\bcamera\s+([\w-]+)\b", current_question, re.IGNORECASE)
        is_camera_followup = any(w in q_norm for w in ("camera nao", "con camera", "nhung camera", "di qua camera", "camera nay", "camera do"))
        if cam_match:
            cam_val = cam_match.group(1).strip()
            if cam_val.lower() not in ("nao", "gi", "nay", "do"):
                ctx["camera_scope"] = [cam_val]
        elif not is_camera_followup:
            # Standalone turn without explicit camera follow-up resets camera filter
            ctx["camera_scope"] = []

        # Check for standalone documentation / how-to inquiry
        doc_patterns = (
            "lam sao", "lam the nao", "cach nao", "huong dan", "tai lieu",
            "cach su dung", "cach dung", "cach tim", "cach tim kiem", "cach tra cuu",
            "cach xem", "cach them", "cach tao", "cach dang ky", "khac phuc",
            "xu ly the nao", "quy tac", "chinh sach", "cau hinh", "kien truc",
            "how to", "troubleshoot", "datt la gi", "tong quan", "cai dat", "trien khai"
        )
        is_doc_query = any(p in q_norm for p in doc_patterns)
        if is_doc_query and not found_plate and not cam_match:
            # Standalone documentation / how-to inquiry resets operational entity & camera filters
            ctx["current_entity"] = None
            ctx["camera_scope"] = []
            ctx["investigation_goal"] = "documentation_query"

        # 5. Fallback inspection from prior messages if current_entity is missing and not a doc query
        if not ctx.get("current_entity") and messages and not is_doc_query:
            for m in reversed(messages):
                if isinstance(m, AIMessage):
                    kw = m.additional_kwargs or {}
                    stored_ctx = kw.get("investigation_context")
                    if isinstance(stored_ctx, dict) and stored_ctx.get("current_entity"):
                        ctx["current_entity"] = stored_ctx["current_entity"]
                        if not time_intent and stored_ctx.get("time_range"):
                            ctx["time_range"] = stored_ctx["time_range"]
                        if stored_ctx.get("last_event_id"):
                            ctx["last_event_id"] = stored_ctx["last_event_id"]
                        if stored_ctx.get("last_alert_id"):
                            ctx["last_alert_id"] = stored_ctx["last_alert_id"]
                        break

                    # Fallback to vehicle_history_plate
                    if kw.get("vehicle_history_plate"):
                        ctx["current_entity"] = {
                            "type": "vehicle",
                            "plate": kw["vehicle_history_plate"],
                            "normalized_plate": normalize_plate(kw["vehicle_history_plate"]),
                            "target_id": None,
                            "name": kw.get("vehicle_history_name"),
                        }
                        break

                    # Fallback to face_history_target_id
                    if kw.get("face_history_target_id"):
                        ctx["current_entity"] = {
                            "type": "face",
                            "plate": None,
                            "normalized_plate": None,
                            "target_id": kw["face_history_target_id"],
                            "name": kw.get("face_history_name"),
                        }
                        break

        # 6. Detect follow-up intent types
        is_alert_followup = any(w in q_norm for w in ("canh bao", "alert", "co canh bao"))
        is_email_followup = any(w in q_norm for w in ("email", "gui email", "thong bao chua", "gui chua", "da gui"))
        is_date_followup = any(w in q_norm for w in ("thi sao", "con hom", "the con"))

        if is_alert_followup:
            ctx["investigation_goal"] = "check_alerts"
        elif is_email_followup:
            ctx["investigation_goal"] = "check_notifications"
        elif is_camera_followup:
            ctx["investigation_goal"] = "check_cameras"
        elif is_date_followup:
            ctx["investigation_goal"] = "timeline_history"

        return ctx

    @classmethod
    def update_from_tool_results(
        cls,
        context: dict[str, Any],
        tool_name: str,
        tool_args: dict[str, Any],
        tool_result: Any,
    ) -> dict[str, Any]:
        """Update last_event_id, last_alert_id, and entity details based on executed tools."""
        ctx = dict(context)
        ctx["last_tool_name"] = tool_name

        executed = list(ctx.get("executed_tools") or [])
        if tool_name not in executed:
            executed.append(tool_name)
        ctx["executed_tools"] = executed

        if isinstance(tool_result, dict):
            # If tool was search_watchlist
            if tool_name == "search_watchlist":
                face_wl = tool_result.get("face_watchlist") or []
                veh_wl = tool_result.get("vehicle_watchlist") or []
                id_res = tool_result.get("identity_resolution") or {}

                if face_wl or id_res.get("status") in ("resolved", "ambiguous"):
                    if id_res.get("status") == "resolved" and id_res.get("target_id"):
                        resolved_name = id_res.get("target_name") or (face_wl[0].get("name") if face_wl else None)
                        ctx["current_entity"] = {
                            "type": "face",
                            "plate": None,
                            "normalized_plate": None,
                            "target_id": id_res["target_id"],
                            "name": resolved_name,
                        }
                        ctx["candidate_entities"] = None
                    elif len(face_wl) == 1:
                        target = face_wl[0]
                        ctx["current_entity"] = {
                            "type": "face",
                            "plate": None,
                            "normalized_plate": None,
                            "target_id": target.get("id"),
                            "name": target.get("name"),
                        }
                        ctx["candidate_entities"] = None
                    elif len(face_wl) > 1:
                        query_name = tool_args.get("target") or tool_args.get("query") or tool_args.get("candidate_name") or (face_wl[0].get("name") if face_wl else None)
                        cands = [{"id": f.get("id"), "name": f.get("name"), "type": "face"} for f in face_wl[:5]]
                        ctx["current_entity"] = {
                            "type": "face_ambiguous",
                            "plate": None,
                            "normalized_plate": None,
                            "target_id": None,
                            "name": query_name,
                            "candidates": cands,
                        }
                        ctx["candidate_entities"] = cands

                elif veh_wl:
                    if len(veh_wl) == 1:
                        veh = veh_wl[0]
                        p_val = veh.get("plate_number")
                        ctx["current_entity"] = {
                            "type": "vehicle",
                            "plate": p_val,
                            "normalized_plate": veh.get("normalized_plate") or (normalize_plate(p_val) if p_val else None),
                            "target_id": veh.get("id"),
                            "name": veh.get("display_name"),
                        }
                        ctx["candidate_entities"] = None
                    else:
                        query_p = tool_args.get("plate_number") or tool_args.get("plate") or tool_args.get("query")
                        cands = [{"id": v.get("id"), "plate": v.get("plate_number"), "name": v.get("display_name"), "type": "vehicle"} for v in veh_wl[:5]]
                        ctx["current_entity"] = {
                            "type": "vehicle_ambiguous",
                            "plate": query_p,
                            "normalized_plate": normalize_plate(query_p) if query_p else None,
                            "target_id": None,
                            "name": None,
                            "candidates": cands,
                        }
                        ctx["candidate_entities"] = cands

            # If tool was investigate_vehicle
            elif tool_name == "investigate_vehicle":
                wl_record = (tool_result.get("summary") or {}).get("watchlist_record")
                ctx["current_entity"] = {
                    "type": "vehicle",
                    "plate": tool_result.get("target_plate") or tool_args.get("plate_number"),
                    "normalized_plate": tool_result.get("normalized_plate"),
                    "target_id": None,
                    "name": wl_record.get("display_name") if isinstance(wl_record, dict) else None,
                }
                timeline = tool_result.get("timeline", [])
                if timeline:
                    ctx["last_event_id"] = timeline[-1].get("event_id")
                alerts = tool_result.get("alerts", [])
                if alerts:
                    ctx["last_alert_id"] = alerts[0].get("alert_id")

            # If tool was investigate_face
            elif tool_name == "investigate_face":
                target = tool_result.get("target", {})
                if target:
                    ctx["current_entity"] = {
                        "type": "face",
                        "plate": None,
                        "normalized_plate": None,
                        "target_id": target.get("id"),
                        "name": target.get("name"),
                    }
                timeline = tool_result.get("timeline", [])
                if timeline:
                    ctx["last_event_id"] = timeline[-1].get("event_id")
                alerts = tool_result.get("alerts", [])
                if alerts:
                    ctx["last_alert_id"] = alerts[0].get("alert_id")

            # If tool was get_camera_status or get_camera
            elif tool_name in ("get_camera_status", "get_camera"):
                cam_id = tool_result.get("camera_id") or tool_args.get("camera_id")
                if cam_id:
                    ctx["camera_scope"] = [cam_id]
                    ctx["last_camera_status"] = tool_result.get("operational_status") or tool_result.get("status")
                    ctx["last_camera_source_type"] = tool_result.get("source_type")

            # If tool was traffic analytics or statistics
            elif tool_name in ("get_traffic_analytics", "get_event_statistics", "get_peak_traffic_hours"):
                cam_id = tool_args.get("camera_id") or tool_result.get("camera_id")
                if cam_id:
                    ctx["camera_scope"] = [cam_id]

            # If tool was detect_traffic_anomalies
            elif tool_name == "detect_traffic_anomalies":
                if tool_args.get("camera_id"):
                    ctx["camera_scope"] = [tool_args["camera_id"]]

            # If tool was get_alerts
            elif tool_name == "get_alerts":
                alerts = tool_result.get("alerts", [])
                if alerts:
                    ctx["last_alert_id"] = alerts[0].get("id") or alerts[0].get("alert_id")

            # If tool was search_events
            elif tool_name == "search_events":
                events = tool_result.get("events", [])
                if events:
                    ctx["last_event_id"] = events[0].get("id") or events[0].get("event_id")

        return ctx
