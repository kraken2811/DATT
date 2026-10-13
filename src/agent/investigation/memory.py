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
        if cam_match:
            cam_val = cam_match.group(1).strip()
            if cam_val.lower() not in ("nao", "gi", "nay", "do"):
                ctx["camera_scope"] = [cam_val]

        # 5. Fallback inspection from prior messages if current_entity is missing
        if not ctx.get("current_entity") and messages:
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
        is_camera_followup = any(w in q_norm for w in ("camera nao", "con camera", "nhung camera", "di qua camera"))
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

        if isinstance(tool_result, dict):
            # If tool was investigate_vehicle
            if tool_name == "investigate_vehicle":
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
