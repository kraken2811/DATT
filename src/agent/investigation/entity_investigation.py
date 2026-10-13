"""Deterministic multi-tool entity investigation and timeline reconstruction service.

Capabilities:
- Vehicle entity investigation (PlateEvent, VehiclePassage, VehicleWatchlist, Notification, Camera).
- Face entity investigation (Target, FaceEvent, Notification, Camera).
- Chronological timeline reconstruction (observed records only, no fabricated journeys).
- Duplicate observation handling & clustering.
- Grounded evidence linkage with real database UUIDs.
"""

from datetime import datetime, timezone, timedelta
import logging
import re
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select, and_, desc

from src.db.database import Database
from src.db.models import (
    Camera,
    DetectionEvent,
    FaceEvent,
    Notification,
    PlateEvent,
    Target,
    VehicleEvent,
    VehiclePassage,
    VehicleWatchlist,
)
from src.watchlists.vehicles import normalize_plate

logger = logging.getLogger("datt.agent.investigation")
LOCAL_TZ = timezone(timedelta(hours=7))  # Asia/Ho_Chi_Minh (UTC+7)


def utc_timestamp(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)


def format_ict_time(dt: datetime | None) -> str:
    if dt is None:
        return "N/A"
    dt_utc = utc_timestamp(dt)
    dt_ict = dt_utc.astimezone(LOCAL_TZ)
    return dt_ict.strftime("%H:%M:%S %d/%m/%Y")


def parse_time_window(
    preset_or_from: str | None = None,
    to_time: str | None = None,
) -> tuple[datetime | None, datetime | None, str]:
    """Parse time window with ICT semantics."""
    now_utc = datetime.now(timezone.utc)
    now_ict = now_utc.astimezone(LOCAL_TZ)

    if not preset_or_from:
        return None, None, "Toàn bộ thời gian ghi nhận"

    val = str(preset_or_from).strip().lower()
    if val in ("today", "hom nay", "hom_nay"):
        start_ict = now_ict.replace(hour=0, minute=0, second=0, microsecond=0)
        end_ict = now_ict
        return start_ict.astimezone(timezone.utc), end_ict.astimezone(timezone.utc), "Hôm nay"
    elif val in ("yesterday", "hom qua", "hom_qua"):
        today_0 = now_ict.replace(hour=0, minute=0, second=0, microsecond=0)
        start_ict = today_0 - timedelta(days=1)
        end_ict = today_0 - timedelta(microseconds=1)
        return start_ict.astimezone(timezone.utc), end_ict.astimezone(timezone.utc), "Hôm qua"
    elif val in ("7_days", "7 ngay", "tuan qua"):
        start_ict = (now_ict - timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)
        return start_ict.astimezone(timezone.utc), now_utc, "7 ngày qua"
    elif val in ("24h", "24 giờ qua"):
        start_ict = now_ict - timedelta(hours=24)
        return start_ict.astimezone(timezone.utc), now_utc, "24 giờ qua"

    # Explicit ISO timestamp parsing
    start_dt = None
    end_dt = None
    try:
        start_dt = datetime.fromisoformat(preset_or_from.replace("Z", "+00:00"))
        start_dt = utc_timestamp(start_dt)
    except Exception:
        pass

    if to_time:
        try:
            end_dt = datetime.fromisoformat(to_time.replace("Z", "+00:00"))
            end_dt = utc_timestamp(end_dt)
        except Exception:
            pass

    label = f"{format_ict_time(start_dt)} - {format_ict_time(end_dt) if end_dt else 'Hiện tại'}"
    return start_dt, end_dt, label


def resolve_camera_metadata(session, camera_identifiers: set[str]) -> dict[str, dict[str, Any]]:
    """Lookup camera details (name, location, status) by ID or registry key."""
    if not camera_identifiers:
        return {}

    uuids = []
    keys = []
    for cid in camera_identifiers:
        if not cid:
            continue
        try:
            uuids.append(UUID(cid))
        except (ValueError, TypeError):
            keys.append(cid)

    stmt = select(Camera)
    conds = []
    if uuids:
        conds.append(Camera.id.in_(uuids))
    if keys:
        conds.append(Camera.registry_key.in_(keys))
    if conds:
        stmt = stmt.where(or_(*conds))
        cams = session.scalars(stmt).all()
    else:
        cams = []

    lookup: dict[str, dict[str, Any]] = {}
    for cam in cams:
        info = {
            "id": str(cam.id),
            "name": cam.name or f"Camera {cam.id}",
            "location": cam.location or "Chưa cấu hình vị trí",
            "registry_key": cam.registry_key,
            "enabled": cam.enabled,
        }
        lookup[str(cam.id)] = info
        lookup[cam.id.hex] = info
        if cam.registry_key:
            lookup[cam.registry_key] = info

    return lookup


def investigate_vehicle_entity(
    db: Database,
    plate_number: str,
    from_time: str | None = None,
    to_time: str | None = None,
    camera_ids: list[str] | None = None,
    include_watchlist: bool = True,
    include_alerts: bool = True,
    include_notifications: bool = True,
    limit: int = 50,
) -> dict[str, Any]:
    """Execute deep operational investigation for a license plate.

    Returns structured evidence, chronological timeline, watchlist status,
    security alerts, and notification delivery logs.
    """
    clean_plate = (plate_number or "").strip()
    if not clean_plate:
        return {
            "status": "error",
            "message": "plate_number is required for vehicle investigation",
        }

    norm_plate = normalize_plate(clean_plate)
    start_utc, end_utc, time_label = parse_time_window(from_time, to_time)
    bounded_limit = max(1, min(100, limit))

    with db.transaction() as session:
        # 1. Watchlist lookup
        watchlist_record = None
        watchlist_status = "not_in_watchlist"
        if include_watchlist:
            wl_stmt = select(VehicleWatchlist).where(
                or_(
                    VehicleWatchlist.plate_number == norm_plate,
                    VehicleWatchlist.plate_number == clean_plate,
                )
            )
            wl_entry = session.scalars(wl_stmt).first()
            if wl_entry:
                watchlist_status = wl_entry.status
                watchlist_record = {
                    "id": str(wl_entry.id),
                    "plate_number": wl_entry.plate_number,
                    "display_name": wl_entry.display_name or "Chưa đặt tên",
                    "vehicle_type": wl_entry.vehicle_type,
                    "vehicle_color": wl_entry.vehicle_color,
                    "owner_info": wl_entry.owner_info,
                    "notes": wl_entry.notes,
                    "status": wl_entry.status,
                    "created_at": wl_entry.created_at.isoformat() if wl_entry.created_at else None,
                }

        # 2. Query PlateEvents & DetectionEvents
        plate_stmt = (
            select(PlateEvent, VehicleEvent, DetectionEvent)
            .join(VehicleEvent, PlateEvent.vehicle_event_id == VehicleEvent.id)
            .outerjoin(DetectionEvent, VehicleEvent.detection_event_id == DetectionEvent.id)
            .where(
                or_(
                    PlateEvent.normalized_plate == norm_plate,
                    PlateEvent.plate_text == clean_plate,
                    PlateEvent.plate_text.ilike(f"%{clean_plate}%"),
                )
            )
        )
        if start_utc:
            plate_stmt = plate_stmt.where(PlateEvent.created_at >= start_utc)
        if end_utc:
            plate_stmt = plate_stmt.where(PlateEvent.created_at <= end_utc)

        plate_stmt = plate_stmt.order_by(PlateEvent.created_at.asc()).limit(bounded_limit)
        plate_rows = session.execute(plate_stmt).all()

        # 3. Query VehiclePassages
        passage_stmt = select(VehiclePassage).where(
            or_(
                VehiclePassage.plate_text == norm_plate,
                VehiclePassage.plate_text == clean_plate,
                VehiclePassage.plate_text.ilike(f"%{norm_plate}%"),
            )
        )
        if start_utc:
            passage_stmt = passage_stmt.where(VehiclePassage.first_seen_at >= start_utc)
        if end_utc:
            passage_stmt = passage_stmt.where(VehiclePassage.first_seen_at <= end_utc)
        if camera_ids:
            passage_stmt = passage_stmt.where(VehiclePassage.camera_id.in_(camera_ids))

        passage_stmt = passage_stmt.order_by(VehiclePassage.first_seen_at.asc()).limit(bounded_limit)
        passage_rows = session.scalars(passage_stmt).all()

        # 4. Gather raw observations
        raw_observations: list[dict[str, Any]] = []
        camera_id_set: set[str] = set()

        for pe, ve, de in plate_rows:
            cam_id = str(de.camera_id) if (de and de.camera_id) else "unknown"
            if camera_ids and cam_id not in camera_ids:
                continue
            camera_id_set.add(cam_id)
            obs_dt = pe.created_at or (de.timestamp if de else None)
            raw_observations.append({
                "type": "plate_event",
                "event_id": f"plate:{pe.id}",
                "raw_id": str(pe.id),
                "timestamp": obs_dt,
                "camera_id": cam_id,
                "plate_text": pe.plate_text,
                "normalized_plate": pe.normalized_plate,
                "confidence": pe.confidence,
                "vehicle_class": ve.vehicle_class if ve else "vehicle",
                "snapshot_path": de.snapshot_path if de else None,
                "plate_crop_path": pe.plate_crop_path,
            })

        for vp in passage_rows:
            cam_id = str(vp.camera_id) if vp.camera_id else "unknown"
            camera_id_set.add(cam_id)
            raw_observations.append({
                "type": "passage",
                "event_id": f"passage:{vp.id}",
                "raw_id": str(vp.id),
                "timestamp": vp.first_seen_at,
                "camera_id": cam_id,
                "plate_text": vp.plate_text or clean_plate,
                "normalized_plate": norm_plate,
                "confidence": vp.plate_confidence,
                "vehicle_class": vp.vehicle_type or "vehicle",
                "snapshot_path": vp.best_vehicle_image_path,
                "plate_crop_path": vp.best_plate_image_path,
                "duration_ms": vp.duration_ms,
            })

        # Resolve camera identity details
        cam_meta = resolve_camera_metadata(session, camera_id_set)

        # Sort raw observations chronologically
        raw_observations.sort(key=lambda x: utc_timestamp(x["timestamp"]) or datetime.min.replace(tzinfo=timezone.utc))

        # 5. Deduplication / clustering
        # If multiple observations on the same camera occur within 30 seconds, group them
        timeline: list[dict[str, Any]] = []
        cluster_window_sec = 30.0

        for obs in raw_observations:
            obs_time = utc_timestamp(obs["timestamp"])
            cam_id = obs["camera_id"]
            cam_info = cam_meta.get(cam_id, {
                "name": f"Camera {cam_id}",
                "location": "Chưa xác định",
            })

            if timeline and timeline[-1]["camera_id"] == cam_id:
                last_time = utc_timestamp(timeline[-1]["_last_seen_dt"])
                if obs_time and last_time and (obs_time - last_time).total_seconds() <= cluster_window_sec:
                    # Update cluster
                    t_item = timeline[-1]
                    t_item["observation_count"] += 1
                    t_item["_last_seen_dt"] = obs_time
                    t_item["end_time_ict"] = format_ict_time(obs_time)
                    if obs["confidence"] and (t_item["ocr_confidence"] is None or obs["confidence"] > t_item["ocr_confidence"]):
                        t_item["ocr_confidence"] = obs["confidence"]
                    t_item["event_ids"].append(obs["event_id"])
                    continue

            # New observation entry
            timeline.append({
                "observation_index": len(timeline) + 1,
                "event_id": obs["event_id"],
                "event_ids": [obs["event_id"]],
                "observation_time_iso": obs_time.isoformat() if obs_time else None,
                "observation_time_ict": format_ict_time(obs_time),
                "end_time_ict": format_ict_time(obs_time),
                "camera_id": cam_id,
                "camera_name": cam_info["name"],
                "camera_location": cam_info["location"],
                "license_plate": obs["plate_text"],
                "ocr_confidence": obs["confidence"],
                "vehicle_class": obs["vehicle_class"],
                "observation_count": 1,
                "_last_seen_dt": obs_time,
                "snapshot_path": obs["snapshot_path"],
                "plate_crop_path": obs["plate_crop_path"],
                "associated_alert": False,
            })

        # Remove internal datetime tracking keys
        for t in timeline:
            t.pop("_last_seen_dt", None)

        # 6. Query Related Security Alerts & Notifications
        alerts_list: list[dict[str, Any]] = []
        notification_summary: dict[str, Any] = {
            "total": 0,
            "sent": 0,
            "pending": 0,
            "failed": 0,
            "suppressed": 0,
            "details": [],
        }

        if include_alerts or include_notifications:
            plate_raw_ids = [UUID(o["raw_id"]) for o in raw_observations if o["type"] == "plate_event"]
            notif_conds = []
            if plate_raw_ids:
                notif_conds.append(Notification.plate_event_id.in_(plate_raw_ids))
            if watchlist_record and watchlist_record.get("id"):
                notif_conds.append(Notification.vehicle_watchlist_id == UUID(watchlist_record["id"]))

            if notif_conds:
                notif_stmt = select(Notification).where(or_(*notif_conds)).order_by(Notification.created_at.desc()).limit(30)
                notifs = session.scalars(notif_stmt).all()
                for n in notifs:
                    status_key = n.status.lower() if n.status else "pending"
                    notification_summary["total"] += 1
                    if status_key in notification_summary:
                        notification_summary[status_key] += 1

                    n_cam = str(n.camera_id) if n.camera_id else "unknown"
                    cam_info = cam_meta.get(n_cam, {"name": f"Camera {n_cam}", "location": "N/A"})

                    n_item = {
                        "id": str(n.id),
                        "plate_event_id": str(n.plate_event_id) if n.plate_event_id else None,
                        "channel": n.channel,
                        "status": n.status,
                        "retry_count": n.retry_count,
                        "error": n.error,
                        "created_at_ict": format_ict_time(n.created_at),
                        "sent_at_ict": format_ict_time(n.sent_at),
                        "camera_name": cam_info["name"],
                    }
                    notification_summary["details"].append(n_item)
                    alerts_list.append({
                        "alert_id": str(n.id),
                        "alert_type": "VEHICLE_WATCHLIST_MATCH",
                        "status": n.status,
                        "camera_id": n_cam,
                        "camera_name": cam_info["name"],
                        "created_at_ict": format_ict_time(n.created_at),
                        "channel": n.channel,
                    })

                    # Mark timeline entries with associated alert
                    for t in timeline:
                        if n.plate_event_id and any(str(n.plate_event_id) in eid for eid in t["event_ids"]):
                            t["associated_alert"] = True

        # Build investigation summary
        total_obs = len(timeline)
        distinct_cams = len({t["camera_id"] for t in timeline})
        first_seen = timeline[0] if timeline else None
        last_seen = timeline[-1] if timeline else None

        # Build grounded provenance notes
        provenance_notes = (
            "Dữ liệu hành trình quan sát được thể hiện các lần phương tiện xuất hiện tại các vị trí camera "
            "theo trình tự thời gian ghi nhận thực tế. Hệ thống không tự suy diễn các vị trí trung gian "
            "hoặc khẳng định toàn bộ các lần nhận diện chắc chắn thuộc cùng một phương tiện vật lý nếu có sai số OCR."
        )

        return {
            "status": "success",
            "entity_type": "vehicle",
            "target_plate": clean_plate,
            "normalized_plate": norm_plate,
            "time_window": time_label,
            "summary": {
                "total_observations": total_obs,
                "distinct_cameras": distinct_cams,
                "first_observed": {
                    "time_ict": first_seen["observation_time_ict"] if first_seen else None,
                    "camera_name": first_seen["camera_name"] if first_seen else None,
                    "camera_location": first_seen["camera_location"] if first_seen else None,
                } if first_seen else None,
                "last_observed": {
                    "time_ict": last_seen["observation_time_ict"] if last_seen else None,
                    "camera_name": last_seen["camera_name"] if last_seen else None,
                    "camera_location": last_seen["camera_location"] if last_seen else None,
                } if last_seen else None,
                "watchlist_status": watchlist_status,
                "watchlist_record": watchlist_record,
                "total_alerts": len(alerts_list),
                "notifications_sent": notification_summary["sent"],
                "notifications_pending": notification_summary["pending"],
                "notifications_failed": notification_summary["failed"],
                "notifications_suppressed": notification_summary["suppressed"],
            },
            "timeline": timeline,
            "alerts": alerts_list,
            "notifications": notification_summary,
            "provenance_notes": provenance_notes,
            "evidence_ids": [t["event_id"] for t in timeline] + [a["alert_id"] for a in alerts_list],
        }


def investigate_face_entity(
    db: Database,
    target_id: str | None = None,
    name: str | None = None,
    from_time: str | None = None,
    to_time: str | None = None,
    camera_ids: list[str] | None = None,
    include_watchlist: bool = True,
    include_alerts: bool = True,
    include_notifications: bool = True,
    limit: int = 50,
) -> dict[str, Any]:
    """Execute deep operational investigation for a face target.

    Supports target resolution, disambiguation if multiple names match,
    FaceEvent chronological timeline, similarity scores, alerts, and notifications.
    """
    clean_target_id = (target_id or "").strip()
    clean_name = (name or "").strip()

    if not clean_target_id and not clean_name:
        return {
            "status": "error",
            "message": "Cần cung cấp target_id (UUID) hoặc tên người (name) để tiến hành điều tra khuôn mặt.",
        }

    start_utc, end_utc, time_label = parse_time_window(from_time, to_time)
    bounded_limit = max(1, min(100, limit))

    with db.transaction() as session:
        resolved_target: Target | None = None

        # 1. Target resolution
        if clean_target_id:
            try:
                t_uuid = UUID(clean_target_id)
                resolved_target = session.get(Target, t_uuid)
            except ValueError:
                return {
                    "status": "error",
                    "message": f"target_id '{clean_target_id}' không phải là UUID hợp lệ. Tên người không được dùng làm UUID.",
                }
            if not resolved_target:
                return {
                    "status": "not_found",
                    "message": f"Không tìm thấy đối tượng khuôn mặt có ID '{clean_target_id}'.",
                }
        else:
            # Name resolution: search Target table
            targets_stmt = select(Target).where(Target.name.ilike(f"%{clean_name}%"))
            matched_targets = session.scalars(targets_stmt).all()

            if not matched_targets:
                return {
                    "status": "not_found",
                    "message": f"Không tìm thấy đối tượng nào khớp với tên '{clean_name}' trong danh sách theo dõi khuôn mặt.",
                }

            if len(matched_targets) > 1:
                # Disambiguation required
                candidates = [
                    {
                        "target_id": str(t.id),
                        "name": t.name,
                        "target_type": t.target_type,
                        "active": t.active,
                    }
                    for t in matched_targets
                ]
                return {
                    "status": "disambiguation_needed",
                    "message": f"Tìm thấy {len(matched_targets)} đối tượng phù hợp với tên '{clean_name}'. Vui lòng chọn target_id chính xác:",
                    "candidates": candidates,
                }

            resolved_target = matched_targets[0]

        target_uuid = resolved_target.id
        target_info = {
            "id": str(resolved_target.id),
            "name": resolved_target.name,
            "target_type": resolved_target.target_type,
            "active": resolved_target.active,
            "created_at": resolved_target.created_at.isoformat() if resolved_target.created_at else None,
            "reference_metadata": resolved_target.reference_metadata or {},
        }

        # 2. Query FaceEvents
        face_stmt = (
            select(FaceEvent, DetectionEvent)
            .outerjoin(DetectionEvent, FaceEvent.detection_event_id == DetectionEvent.id)
            .where(FaceEvent.target_id == target_uuid)
        )
        if start_utc:
            face_stmt = face_stmt.where(FaceEvent.created_at >= start_utc)
        if end_utc:
            face_stmt = face_stmt.where(FaceEvent.created_at <= end_utc)
        if camera_ids:
            face_stmt = face_stmt.where(FaceEvent.camera_id.in_(camera_ids))

        face_stmt = face_stmt.order_by(FaceEvent.created_at.asc()).limit(bounded_limit)
        face_rows = session.execute(face_stmt).all()

        # 3. Gather observations
        raw_observations: list[dict[str, Any]] = []
        camera_id_set: set[str] = set()

        for fe, de in face_rows:
            cam_id = str(fe.camera_id) if fe.camera_id else (str(de.camera_id) if de and de.camera_id else "unknown")
            camera_id_set.add(cam_id)
            obs_dt = fe.created_at or (de.timestamp if de else None)
            raw_observations.append({
                "type": "face_event",
                "event_id": f"face:{fe.id}",
                "raw_id": str(fe.id),
                "timestamp": obs_dt,
                "camera_id": cam_id,
                "similarity": fe.similarity,
                "decision": fe.decision,
                "snapshot_path": de.snapshot_path if de else None,
                "face_crop_path": fe.face_crop_path,
            })

        cam_meta = resolve_camera_metadata(session, camera_id_set)

        # Sort chronologically
        raw_observations.sort(key=lambda x: utc_timestamp(x["timestamp"]) or datetime.min.replace(tzinfo=timezone.utc))

        # 4. Clustering / timeline assembly
        timeline: list[dict[str, Any]] = []
        cluster_window_sec = 30.0

        for obs in raw_observations:
            obs_time = utc_timestamp(obs["timestamp"])
            cam_id = obs["camera_id"]
            cam_info = cam_meta.get(cam_id, {"name": f"Camera {cam_id}", "location": "Chưa xác định"})

            if timeline and timeline[-1]["camera_id"] == cam_id:
                last_time = utc_timestamp(timeline[-1]["_last_seen_dt"])
                if obs_time and last_time and (obs_time - last_time).total_seconds() <= cluster_window_sec:
                    t_item = timeline[-1]
                    t_item["observation_count"] += 1
                    t_item["_last_seen_dt"] = obs_time
                    t_item["end_time_ict"] = format_ict_time(obs_time)
                    if obs["similarity"] and (t_item["similarity"] is None or obs["similarity"] > t_item["similarity"]):
                        t_item["similarity"] = obs["similarity"]
                    t_item["event_ids"].append(obs["event_id"])
                    continue

            timeline.append({
                "observation_index": len(timeline) + 1,
                "event_id": obs["event_id"],
                "event_ids": [obs["event_id"]],
                "observation_time_iso": obs_time.isoformat() if obs_time else None,
                "observation_time_ict": format_ict_time(obs_time),
                "end_time_ict": format_ict_time(obs_time),
                "camera_id": cam_id,
                "camera_name": cam_info["name"],
                "camera_location": cam_info["location"],
                "similarity": obs["similarity"],
                "decision": obs["decision"],
                "observation_count": 1,
                "_last_seen_dt": obs_time,
                "snapshot_path": obs["snapshot_path"],
                "face_crop_path": obs["face_crop_path"],
                "associated_alert": False,
            })

        for t in timeline:
            t.pop("_last_seen_dt", None)

        # 5. Security Alerts & Notifications
        alerts_list: list[dict[str, Any]] = []
        notification_summary: dict[str, Any] = {
            "total": 0,
            "sent": 0,
            "pending": 0,
            "failed": 0,
            "suppressed": 0,
            "details": [],
        }

        if include_alerts or include_notifications:
            face_raw_ids = [UUID(o["raw_id"]) for o in raw_observations]
            notif_conds = []
            if face_raw_ids:
                notif_conds.append(Notification.event_id.in_(face_raw_ids))
            notif_conds.append(Notification.target_id == target_uuid)

            notif_stmt = select(Notification).where(or_(*notif_conds)).order_by(Notification.created_at.desc()).limit(30)
            notifs = session.scalars(notif_stmt).all()
            for n in notifs:
                status_key = n.status.lower() if n.status else "pending"
                notification_summary["total"] += 1
                if status_key in notification_summary:
                    notification_summary[status_key] += 1

                n_cam = str(n.camera_id) if n.camera_id else "unknown"
                cam_info = cam_meta.get(n_cam, {"name": f"Camera {n_cam}", "location": "N/A"})

                notification_summary["details"].append({
                    "id": str(n.id),
                    "event_id": str(n.event_id) if n.event_id else None,
                    "channel": n.channel,
                    "status": n.status,
                    "retry_count": n.retry_count,
                    "error": n.error,
                    "created_at_ict": format_ict_time(n.created_at),
                    "sent_at_ict": format_ict_time(n.sent_at),
                    "camera_name": cam_info["name"],
                })
                alerts_list.append({
                    "alert_id": str(n.id),
                    "alert_type": "FACE_WATCHLIST_MATCH",
                    "status": n.status,
                    "camera_id": n_cam,
                    "camera_name": cam_info["name"],
                    "created_at_ict": format_ict_time(n.created_at),
                    "channel": n.channel,
                })

                for t in timeline:
                    if n.event_id and any(str(n.event_id) in eid for eid in t["event_ids"]):
                        t["associated_alert"] = True

        total_obs = len(timeline)
        first_seen = timeline[0] if timeline else None
        last_seen = timeline[-1] if timeline else None

        provenance_notes = (
            "Hành trình quan sát được của đối tượng khuôn mặt dựa trên độ tương đồng nhận diện khuôn mặt "
            "tại các camera được trang bị module nhận diện. Điểm tương đồng thể hiện độ tin cậy của thuật toán so khớp, "
            "không chứng minh hành trình vật lý liên tục giữa các vị trí ngoài tầm quét của camera."
        )

        return {
            "status": "success",
            "entity_type": "face",
            "target": target_info,
            "time_window": time_label,
            "summary": {
                "total_observations": total_obs,
                "distinct_cameras": len({t["camera_id"] for t in timeline}),
                "first_observed": {
                    "time_ict": first_seen["observation_time_ict"] if first_seen else None,
                    "camera_name": first_seen["camera_name"] if first_seen else None,
                    "camera_location": first_seen["camera_location"] if first_seen else None,
                } if first_seen else None,
                "last_observed": {
                    "time_ict": last_seen["observation_time_ict"] if last_seen else None,
                    "camera_name": last_seen["camera_name"] if last_seen else None,
                    "camera_location": last_seen["camera_location"] if last_seen else None,
                } if last_seen else None,
                "watchlist_status": "active" if resolved_target.active else "disabled",
                "total_alerts": len(alerts_list),
                "notifications_sent": notification_summary["sent"],
                "notifications_pending": notification_summary["pending"],
                "notifications_failed": notification_summary["failed"],
                "notifications_suppressed": notification_summary["suppressed"],
            },
            "timeline": timeline,
            "alerts": alerts_list,
            "notifications": notification_summary,
            "provenance_notes": provenance_notes,
            "evidence_ids": [t["event_id"] for t in timeline] + [a["alert_id"] for a in alerts_list],
        }
