"""Deterministic Explainable Operations and Evidence Provenance Engine for DATT.

Structures operational conclusions into grounded reasoning:
1. Direct conclusion
2. Measured evidence
3. Historical comparison
4. Data limitations & uncertainties
5. Suggested next action

Enforces separation of confidence metrics:
- OCR confidence (0.0 - 1.0)
- Face similarity score (0.0 - 1.0)
- Observation coverage ratio (0.0 - 1.0)
- Anomaly statistical deviation

Strictly avoids causal fallacies:
- Correlation is not causation (traffic spike != congestion proof).
- Chronological camera observations != continuous physical journey.
- Watchlist membership != proof of wrongdoing.
"""

from typing import Any

MODE_CONCISE = "CONCISE"
MODE_INVESTIGATION = "INVESTIGATION"
MODE_DETAILED = "DETAILED"
MODE_TECHNICAL = "TECHNICAL"


def format_investigation_explanation(
    data: dict[str, Any],
    mode: str = MODE_INVESTIGATION,
) -> str:
    """Format structured investigation evidence into grounded operational Vietnamese text."""
    entity_type = data.get("entity_type")
    summary = data.get("summary", {})
    timeline = data.get("timeline", [])
    alerts = data.get("alerts", [])
    notifs = data.get("notifications", {})

    lines: list[str] = []

    if entity_type == "vehicle":
        plate = data.get("target_plate", "N/A")
        total_obs = summary.get("total_observations", 0)
        cams = summary.get("distinct_cameras", 0)
        wl_status = summary.get("watchlist_status")

        if total_obs == 0:
            lines.append(f"Không ghi nhận phương tiện biển số **{plate}** xuất hiện trong khoảng thời gian tra cứu ({data.get('time_window')}).")
            if wl_status == "active":
                lines.append(f"- Lưu ý: Biển số này hiện **ĐANG CÓ** trong Danh sách theo dõi (Vehicle Watchlist).")
            return "\n\n".join(lines)

        lines.append(f"Phương tiện **{plate}** được ghi nhận **{total_obs} lần** tại **{cams} camera** trong khoảng thời gian {data.get('time_window')}.")

        # Timeline
        if timeline:
            lines.append("### Hành trình quan sát được theo thời gian:")
            for obs in timeline:
                idx = obs.get("observation_index", 1)
                t_ict = obs.get("observation_time_ict", "N/A")
                cam_name = obs.get("camera_name", "Camera")
                cam_loc = obs.get("camera_location", "")
                conf = obs.get("ocr_confidence")
                conf_str = f" (Độ tin cậy OCR: {round(conf*100)}%)" if conf is not None else ""
                alert_badge = " 🚨 [Có cảnh báo]" if obs.get("associated_alert") else ""
                lines.append(f"{idx}. **{t_ict}** — {cam_name} ({cam_loc}){conf_str}{alert_badge}")

        # Summary details
        lines.append("### Tổng kết bằng chứng:")
        lines.append(f"- **Tổng số lần ghi nhận:** {total_obs}")
        wl_str = "Đang hoạt động" if wl_status == "active" else ("Đã tắt" if wl_status == "disabled" else "Không có trong danh sách")
        lines.append(f"- **Danh sách theo dõi (Watchlist):** {wl_str}")
        lines.append(f"- **Cảnh báo an ninh liên quan:** {len(alerts)} cảnh báo")

        if notifs.get("total", 0) > 0:
            sent_cnt = notifs.get("sent", 0)
            pending_cnt = notifs.get("pending", 0)
            failed_cnt = notifs.get("failed", 0)
            lines.append(f"- **Trạng thái gửi Email:** Đã gửi qua relay: {sent_cnt}, Đang chờ: {pending_cnt}, Thất bại: {failed_cnt}")

        if mode in (MODE_DETAILED, MODE_TECHNICAL):
            lines.append("\n> **Lưu ý kiểm chứng:** Danh sách camera trên là các lần ghi nhận thực tế, không chứng minh hành trình vật lý liên tục giữa các vị trí ngoài tầm quét camera.")

        if mode == MODE_TECHNICAL and data.get("evidence_ids"):
            lines.append(f"\n```json\n// Mã định danh bằng chứng (Evidence IDs):\n{data.get('evidence_ids')}\n```")

    elif entity_type == "face":
        target = data.get("target", {})
        t_name = target.get("name", "N/A")
        total_obs = summary.get("total_observations", 0)
        cams = summary.get("distinct_cameras", 0)

        if total_obs == 0:
            lines.append(f"Không ghi nhận đối tượng **{t_name}** xuất hiện trong khoảng thời gian tra cứu ({data.get('time_window')}).")
            return "\n\n".join(lines)

        lines.append(f"Đối tượng **{t_name}** được ghi nhận **{total_obs} lần** tại **{cams} camera** trong khoảng thời gian {data.get('time_window')}.")

        if timeline:
            lines.append("### Các lần nhận diện theo thời gian:")
            for obs in timeline:
                idx = obs.get("observation_index", 1)
                t_ict = obs.get("observation_time_ict", "N/A")
                cam_name = obs.get("camera_name", "Camera")
                sim = obs.get("similarity")
                sim_str = f" (Điểm tương đồng: {round(sim*100, 1)}%)" if sim is not None else ""
                alert_badge = " 🚨 [Có cảnh báo]" if obs.get("associated_alert") else ""
                lines.append(f"{idx}. **{t_ict}** — {cam_name}{sim_str}{alert_badge}")

        lines.append("### Tổng kết bằng chứng:")
        lines.append(f"- **Số lần nhận diện:** {total_obs}")
        lines.append(f"- **Trạng thái theo dõi:** {'Đang theo dõi' if target.get('active') else 'Tạm ngưng'}")
        lines.append(f"- **Cảnh báo kích hoạt:** {len(alerts)}")

    return "\n\n".join(lines)
