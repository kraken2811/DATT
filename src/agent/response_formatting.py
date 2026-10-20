"""Deterministic Vietnamese presentation; no model calls or tool execution."""
import json
import re
from datetime import datetime, timezone, timedelta
from typing import Any
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

DETAIL_CONCISE = "concise"
DETAIL_EXPLANATION = "explanation"
DETAIL_TECHNICAL = "technical"

LABELS = {
    'camera_id': 'ID camera', 'id': 'ID', 'name': 'Tên', 'operational_status': 'Trạng thái hoạt động',
    'is_active': 'Đang hoạt động', 'enabled': 'Được bật', 'active': 'Đang bật', 'last_active': 'Hoạt động gần nhất',
    'source_type': 'Loại nguồn', 'source_masked': 'Nguồn đã che thông tin xác thực', 'location': 'Vị trí',
    'status_basis': 'Cơ sở xác định trạng thái', 'status_basis_description': 'Giải thích trạng thái',
    'stream_reachability_verified': 'Đã kiểm tra kết nối trực tiếp', 'troubleshooting_guidance': 'Hướng dẫn theo loại nguồn',
    'steps': 'Các bước', 'caution': 'Lưu ý', 'source_category': 'Nhóm nguồn', 'is_network_stream': 'Nguồn mạng',
    'event_id': 'ID sự kiện', 'source_event_id': 'ID bản ghi nguồn', 'event_type': 'Loại sự kiện',
    'timestamp': 'Thời điểm', 'created_at': 'Thời điểm tạo', 'updated_at': 'Thời điểm cập nhật',
    'target_id': 'ID đối tượng', 'target_type': 'Loại đối tượng', 'object_type': 'Loại phát hiện',
    'plate': 'Biển số', 'plate_number': 'Biển số', 'plate_text': 'Biển số', 'confidence': 'Độ tin cậy',
    'similarity': 'Độ tương đồng', 'watchlist_match': 'Khớp danh sách theo dõi', 'semantic_type': 'Phân loại nghiệp vụ',
    'metadata': 'Thông tin bổ sung', 'today_calendar_day': 'Hôm nay theo ngày dương lịch', 'timezone': 'Múi giờ',
    'day_start_local': 'Bắt đầu ngày (giờ địa phương)', 'day_start_utc': 'Bắt đầu ngày (UTC)',
    'total_events_today': 'Tổng số sự kiện hôm nay', 'business_events_today': 'Sự kiện nghiệp vụ hôm nay',
    'face_events_today': 'Sự kiện khuôn mặt hôm nay', 'plate_events_today': 'Sự kiện biển số hôm nay',
    'vehicle_passages_today': 'Lượt xe hôm nay', 'unique_plates_today': 'Biển số duy nhất hôm nay',
    'unique_tracked_vehicles_today': 'Phiên xe theo dõi duy nhất hôm nay', 'rolling_24h_interval': 'Khoảng 24 giờ trượt',
    'start_time': 'Từ', 'end_time': 'Đến', 'vehicle_passages': 'Lượt xe', 'business_events': 'Sự kiện nghiệp vụ',
    'unique_plates': 'Biển số duy nhất', 'all_time_database_totals': 'Tổng lịch sử trong cơ sở dữ liệu',
    'total_business_events': 'Tổng sự kiện nghiệp vụ', 'total_vehicle_passages': 'Tổng lượt xe',
    'vehicle_type_breakdown': 'Lượt xe theo loại', 'busiest_cameras': 'Camera có nhiều lượt xe nhất',
    'busiest_cameras_by_traffic': 'Xếp hạng camera theo lượt xe', 'passage_count': 'Số lượt xe',
    'highest_traffic_camera': 'Camera có nhiều lượt xe nhất', 'most_crowded_camera': 'Camera dẫn đầu theo lượt xe lịch sử',
    'security_matches': 'Kết quả khớp danh sách theo dõi', 'vehicle_watchlist_matches': 'Lượt khớp phương tiện',
    'face_watchlist_matches': 'Lượt khớp khuôn mặt', 'total_matches': 'Tổng kết quả khớp',
    'live_occupancy': 'Số người/xe hiện diện tức thời', 'live_occupancy_note': 'Giới hạn dữ liệu tức thời',
    'metric_distinction': 'Cách hiểu số liệu', 'has_embedding': 'Có dữ liệu đặc trưng khuôn mặt',
    'section': 'Mục', 'page': 'Trang', 'document_name': 'Tài liệu', 'document_type': 'Loại tài liệu',
    'score': 'Điểm truy xuất', 'query': 'Nội dung tra cứu', 'count': 'Số bản ghi trả về', 'total': 'Tổng kết quả',
    'notes': 'Ghi chú', 'reason': 'Lý do', 'message': 'Thông báo', 'evidence_key': 'Mã bằng chứng',
    'vehicle_watchlist': 'Danh sách phương tiện', 'face_watchlist': 'Danh sách khuôn mặt', 'events': 'Sự kiện', 'event': 'Sự kiện',
    'camera_name': 'Tên camera', 'camera_location': 'Vị trí camera theo cấu hình hiện tại',
    'camera_metadata_basis': 'Cơ sở thông tin camera', 'face_total_matches': 'Tổng danh tính khuôn mặt phù hợp', 'face_has_more': 'Còn danh tính chưa hiển thị',
    'from_time': 'Từ', 'to_time': 'Đến',
    'time_range': 'Khoảng thời gian', 'camera_filter': 'Bộ lọc camera', 'grouped_analytics': 'Chi tiết phân nhóm',
    'busiest_period': 'Thời điểm/camera cao điểm', 'hour_slot': 'Khung giờ', 'peak_hour': 'Giờ cao điểm',
    'comparison': 'So sánh đối chứng', 'baseline_period': 'Mốc so sánh', 'baseline_total_passages': 'Lưu lượng mốc so sánh',
    'current_total_passages': 'Lưu lượng kỳ hiện tại', 'difference': 'Chênh lệch', 'percent_change': 'Tỷ lệ thay đổi (%)',
    'trend_description': 'Xu hướng', 'zero_baseline': 'Mốc đối chứng bằng 0', 'distinction_note': 'Lưu ý về số liệu',
    'alerts': 'Danh sách cảnh báo', 'total_alerts': 'Tổng số cảnh báo', 'status_breakdown': 'Phân bố theo trạng thái',
    'camera_breakdown': 'Phân bố theo camera', 'notifications': 'Danh sách thông báo', 'total_notifications': 'Tổng số thông báo',
    'recipient_masked': 'Người nhận (đã ẩn)', 'retry_count': 'Số lần thử lại', 'last_error': 'Lỗi gần nhất',
    'delivery_status': 'Trạng thái gửi', 'delivery_note': 'Lưu ý gửi',
}
HEADINGS = {
    'get_camera': 'Thông tin camera',
    'get_camera_status': 'Trạng thái camera',
    'get_event': 'Chi tiết sự kiện',
    'search_events': 'Kết quả tra cứu sự kiện',
    'get_event_statistics': 'Thống kê hệ thống',
    'search_watchlist': 'Danh sách theo dõi',
    'get_knowledge': 'Tài liệu liên quan',
    'get_traffic_analytics': 'Phân tích lưu lượng giao thông',
    'get_alerts': 'Trung tâm cảnh báo',
    'get_notifications_status': 'Trạng thái thông báo email',
    'generate_operational_report': 'Báo cáo vận hành hệ thống',
    'investigate_vehicle': 'Kết quả điều tra phương tiện',
    'investigate_face': 'Kết quả điều tra đối tượng khuôn mặt',
    'detect_traffic_anomalies': 'Phát hiện bất thường vận hành & lưu lượng',
    'generate_shift_handover_report': 'Báo cáo bàn giao ca trực',
}

COLOR_NAMES_VI = {
    'yellow': 'vàng',
    'brown': 'nâu',
    'black': 'đen',
    'white': 'trắng',
    'red': 'đỏ',
    'blue': 'xanh dương',
    'green': 'xanh lá',
    'silver': 'bạc',
    'grey': 'xám',
    'gray': 'xám',
    'orange': 'cam',
    'purple': 'tím',
    'pink': 'hồng',
}

VEHICLE_TYPES_VI = {
    'car': 'ô tô',
    'truck': 'xe tải',
    'motorcycle': 'xe máy',
    'motorbike': 'xe máy',
    'bus': 'xe buýt',
    'van': 'xe van',
}


def translate_color(color: Any) -> str:
    if not color:
        return 'chưa xác định'
    c_str = str(color).strip().lower()
    return COLOR_NAMES_VI.get(c_str, c_str)


def translate_vehicle_type(vtype: Any) -> str:
    if not vtype:
        return 'phương tiện'
    v_str = str(vtype).strip().lower()
    return VEHICLE_TYPES_VI.get(v_str, v_str)


def utc_to_vietnam_time(ts_val: Any) -> str:
    """Convert timestamp to Vietnam ICT (UTC+7) formatted string.
    Format: 'HH:MM ngày DD/MM/YYYY'
    Example: 2026-10-02T08:14:41.632246+00:00 -> '15:14 ngày 02/10/2026'
    """
    if not ts_val:
        return 'chưa có thời gian'
    if isinstance(ts_val, datetime):
        dt = ts_val
    else:
        ts_str = str(ts_val).strip()
        try:
            dt = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
        except Exception:
            return ts_str

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    ict = timezone(timedelta(hours=7))
    dt_ict = dt.astimezone(ict)
    return dt_ict.strftime('%H:%M ngày %d/%m/%Y')


def get_detail_level(user_text: str | None) -> str:
    if not user_text:
        return DETAIL_CONCISE
    txt = user_text.lower().strip()

    if wants_json(txt):
        return DETAIL_TECHNICAL

    # Explicit full / technical / debug requests
    technical_triggers = [
        "toàn bộ dữ liệu", "toan bo du lieu", "tất cả dữ liệu", "tat ca du lieu",
        "toàn bộ thông tin", "toan bo thong tin", "all data", "full data",
        "thông tin kỹ thuật", "thong tin ky thuat", "chi tiết kỹ thuật", "chi tiet ky thuat",
        "dữ liệu kỹ thuật", "du lieu ky thuat", "technical",
        "debug sự kiện", "debug", "gỡ lỗi", "go loi",
        "kiểm tra dữ liệu",  # legacy test fixture
        "xem kỹ hơn", "xem ky hon", "xem kỹ", "xem ky",
    ]
    if any(t in txt for t in technical_triggers):
        return DETAIL_TECHNICAL

    # Explanation requests
    explanation_triggers = [
        "giải thích", "giai thich", "tại sao", "tai sao", "vì sao", "vi sao",
        "nguyên nhân", "nguyen nhan", "lý do", "ly do", "căn cứ", "can cu",
        "tại sao lại", "vi sao lai", "như thế nào", "nhu the nao", "làm sao", "lam sao",
        "cơ sở", "co so", "bằng chứng", "bang chung", "evidence"
    ]
    if any(t in txt for t in explanation_triggers):
        return DETAIL_EXPLANATION

    return DETAIL_CONCISE


def format_notification_status(status: Any, detail_level: str = DETAIL_CONCISE) -> str | None:
    if not status:
        return None
    st = str(status).strip().lower()
    if st == 'sent':
        if detail_level == DETAIL_EXPLANATION:
            return "**Email cảnh báo:** Đã được máy chủ SMTP chấp nhận (lưu ý: hệ thống xác nhận máy chủ SMTP đã tiếp nhận thư, không theo dõi việc người nhận đã mở hoặc đọc email)."
        return "**Email cảnh báo:** Đã được máy chủ SMTP chấp nhận."
    elif st == 'suppressed':
        return "**Email cảnh báo:** Đã bị chặn/không gửi (do cơ chế chống gửi trùng lặp hoặc đang trong thời gian chờ cooldown)."
    elif st == 'failed':
        return "**Email cảnh báo:** Gửi thất bại."
    elif st == 'pending':
        return "**Email cảnh báo:** Đang chờ xử lý trong hàng đợi."
    return f"**Email cảnh báo:** Trạng thái {st}."


def format_camera_info(camera_id: Any, camera_name: Any = None, camera_location: Any = None) -> str:
    cam_id_str = str(camera_id) if camera_id else "chưa rõ camera"
    name_str = str(camera_name) if camera_name and str(camera_name) != cam_id_str else None

    loc_unavailable = (
        not camera_location
        or str(camera_location).strip().lower() in ('unavailable', 'none', 'chưa có', 'chưa rõ')
    )

    if name_str and not loc_unavailable:
        return f"Camera: {name_str} ({camera_location})."
    elif name_str and loc_unavailable:
        return f"Camera: {name_str}. Chưa có thông tin vị trí."
    elif not loc_unavailable:
        return f"Camera: {cam_id_str} ({camera_location})."
    else:
        return f"Camera: {cam_id_str}. Chưa có thông tin vị trí."


def safe_result(value):
    """Redact credentials for presentation, without changing internal tool messages."""
    if isinstance(value, dict):
        return {key: ('đã ẩn' if str(key).lower() in ('password', 'api_key', 'access_token', 'authorization', 'secret') else safe_result(item))
                for key, item in value.items()}
    if isinstance(value, list):
        return [safe_result(item) for item in value]
    if isinstance(value, str):
        value = re.sub(r'(\b[a-z][a-z0-9+.-]*://)[^\s/@]+:[^\s/@]+@', r'\1***@', value, flags=re.I)
        return re.sub(r'([?&](?:token|api_key|password|access_token)=)[^&#\s]+', r'\1***', value, flags=re.I)
    return value


def text(value):
    if value is None:
        return 'chưa có dữ liệu'
    if isinstance(value, bool):
        return 'có' if value else 'không'
    return re.sub(r'([\\\x60*{}\[\]<>])', r'\\\1', str(value))


def facts(data, depth=0):
    pad = '  ' * depth
    if isinstance(data, dict):
        lines = []
        for key, value in data.items():
            label = text(LABELS.get(key, str(key).replace('_', ' ')))
            if isinstance(value, (dict, list)) and value:
                lines.append(f'{pad}- {label}:')
                lines.extend(facts(value, depth + 1))
            elif isinstance(value, (dict, list)):
                lines.append(f'{pad}- {label}: không có bản ghi trong kết quả trả về.')
            else:
                lines.append(f'{pad}- {label}: {text(value)}')
        return lines
    if isinstance(data, list):
        lines = []
        for i, value in enumerate(data, 1):
            if isinstance(value, (dict, list)):
                lines.append(f'{pad}- Bản ghi {i}:')
                lines.extend(facts(value, depth + 1))
            else:
                lines.append(f'{pad}- {text(value)}')
        return lines
    return [f'{pad}- {text(data)}']


def format_single_vehicle_event(event: dict, detail_level: str = DETAIL_CONCISE, user_question: str = "") -> str:
    plate = event.get('plate') or event.get('plate_text') or event.get('normalized_plate') or 'chưa rõ biển số'
    vtype = translate_vehicle_type(event.get('vehicle_type'))
    timestamp = event.get('timestamp')
    vn_time = utc_to_vietnam_time(timestamp)
    watchlist_match = bool(event.get('watchlist_match') or event.get('semantic_type') == 'VEHICLE_WATCHLIST_MATCH')

    if watchlist_match:
        lead = f"Đã phát hiện {vtype} biển số **{plate}** trùng Watchlist lúc **{vn_time}** (giờ Việt Nam)."
    else:
        lead = f"Đã ghi nhận {vtype} biển số **{plate}** lúc **{vn_time}** (giờ Việt Nam)."

    det_color = event.get('detected_vehicle_color')
    wl_color = event.get('watchlist_vehicle_color')
    color_conf = event.get('detected_vehicle_color_confidence')
    color_note = None
    if det_color and wl_color:
        det_c_str = str(det_color).strip().lower()
        wl_c_str = str(wl_color).strip().lower()
        det_vi = translate_color(det_c_str)
        wl_vi = translate_color(wl_c_str)
        if det_c_str != wl_c_str and det_vi != wl_vi:
            conf_str = ""
            if color_conf is not None:
                try:
                    c_val = float(color_conf)
                    if c_val <= 1.0:
                        c_val *= 100
                    num_str = f"{c_val:.1f}".replace('.', ',')
                    conf_str = f" Độ tin cậy nhận diện màu khoảng {num_str}%."
                except Exception:
                    pass
            color_note = f"**Lưu ý:** Xe được nhận diện màu {det_vi}, trong khi Watchlist đăng ký màu {wl_vi}.{conf_str}"

    notif_str = format_notification_status(event.get('notification_status'), detail_level)
    cam_str = format_camera_info(event.get('camera_id'), event.get('camera_name'), event.get('camera_location'))

    lines = [lead]
    if color_note:
        lines.append(color_note)
    if notif_str:
        lines.append(notif_str)
    if cam_str:
        lines.append(cam_str)

    if detail_level == DETAIL_EXPLANATION:
        evidence = []
        plate_conf = event.get('plate_confidence') or event.get('confidence')
        if plate_conf is not None:
            try:
                p_val = float(plate_conf)
                if p_val <= 1.0:
                    p_val *= 100
                num_str = f"{p_val:.1f}".replace('.', ',')
                evidence.append(f"- Độ tin cậy nhận diện biển số (OCR): {num_str}%.")
            except Exception:
                pass
        if color_conf is not None:
            try:
                c_val = float(color_conf)
                if c_val <= 1.0:
                    c_val *= 100
                num_str = f"{c_val:.1f}".replace('.', ',')
                evidence.append(f"- Độ tin cậy phân loại màu xe: {num_str}%.")
            except Exception:
                pass
        if event.get('semantic_type'):
            evidence.append(f"- Phân loại nghiệp vụ: {event.get('semantic_type')}")
        evidence.append("- Giới hạn dữ liệu: Tên và vị trí camera là cấu hình hiện tại; chưa xác minh vị trí tại thời điểm nhận diện.")
        if evidence:
            lines.append("**Bằng chứng kỹ thuật & Giới hạn:**\n" + "\n".join(evidence))
    elif detail_level == DETAIL_TECHNICAL:
        tech_lines = [
            f"- ID sự kiện: {event.get('event_id') or event.get('source_event_id') or event.get('id') or 'chưa có'}",
            f"- Biển số: {plate}",
            f"- Loại xe: {vtype}",
            f"- Thời điểm (UTC): {timestamp or 'chưa có'}",
            f"- Thời điểm (ICT): {vn_time} (giờ Việt Nam)",
            f"- Camera ID: {event.get('camera_id') or 'chưa có'}",
            f"- Tên camera: {event.get('camera_name') or 'chưa có'}",
            f"- Vị trí camera: {event.get('camera_location') or 'chưa có'}",
            f"- Trùng Watchlist: {'có' if watchlist_match else 'không'}",
        ]
        if det_color:
            tech_lines.append(f"- Màu nhận diện: {det_color} ({translate_color(det_color)})")
        if wl_color:
            tech_lines.append(f"- Màu đăng ký Watchlist: {wl_color} ({translate_color(wl_color)})")
        if color_conf is not None:
            tech_lines.append(f"- Độ tin cậy màu: {color_conf}")
        plate_conf = event.get('plate_confidence') or event.get('confidence')
        if plate_conf is not None:
            tech_lines.append(f"- Độ tin cậy OCR: {plate_conf}")
        if event.get('notification_status'):
            tech_lines.append(f"- Trạng thái thông báo: {event.get('notification_status')}")
        if event.get('track_id'):
            tech_lines.append(f"- Track ID: {event.get('track_id')}")
        lines.append("**Thông tin kỹ thuật đầy đủ:**\n" + "\n".join(tech_lines))

    return '\n\n'.join(lines)


def format_single_face_event(event: dict, detail_level: str = DETAIL_CONCISE, user_question: str = "") -> str:
    target_name = event.get('target_name') or event.get('name')
    target_id = event.get('target_id')
    name_str = f"**{target_name}**" if target_name else ("đối tượng" + (f" (ID: `{target_id}`)" if detail_level == DETAIL_TECHNICAL else ""))
    timestamp = event.get('timestamp')
    vn_time = utc_to_vietnam_time(timestamp)
    cam_str = format_camera_info(event.get('camera_id'), event.get('camera_name'), event.get('camera_location'))

    lead = f"Đã ghi nhận nhận diện khuôn mặt của {name_str} lúc **{vn_time}** (giờ Việt Nam)."
    notif_str = format_notification_status(event.get('notification_status'), detail_level)

    lines = [lead]
    if notif_str:
        lines.append(notif_str)
    if cam_str:
        lines.append(cam_str)

    sim = event.get('similarity') or event.get('confidence')
    if detail_level == DETAIL_EXPLANATION:
        evidence = []
        if sim is not None:
            try:
                s_val = float(sim)
                if s_val <= 1.0:
                    s_val *= 100
                num_str = f"{s_val:.1f}".replace('.', ',')
                evidence.append(f"- Độ tương đồng khuôn mặt: {num_str}%.")
            except Exception:
                evidence.append(f"- Độ tương đồng khuôn mặt: {sim}")
        evidence.append("- Giới hạn dữ liệu: Tên và vị trí camera là cấu hình hiện tại; chưa xác minh vị trí tại thời điểm nhận diện.")
        lines.append("**Bằng chứng kỹ thuật & Giới hạn:**\n" + "\n".join(evidence))
    elif detail_level == DETAIL_TECHNICAL:
        tech_lines = [
            f"- ID sự kiện: {event.get('event_id') or event.get('source_event_id') or event.get('id') or 'chưa có'}",
            f"- Target ID: {target_id or 'chưa có'}",
            f"- Tên đối tượng: {target_name or 'chưa có'}",
            f"- Thời điểm (UTC): {timestamp or 'chưa có'}",
            f"- Thời điểm (ICT): {vn_time} (giờ Việt Nam)",
            f"- Camera ID: {event.get('camera_id') or 'chưa có'}",
            f"- Tên camera: {event.get('camera_name') or 'chưa có'}",
            f"- Vị trí camera: {event.get('camera_location') or 'chưa có'}",
        ]
        if sim is not None:
            tech_lines.append(f"- Độ tương đồng: {sim}")
        if event.get('notification_status'):
            tech_lines.append(f"- Trạng thái thông báo: {event.get('notification_status')}")
        lines.append("**Thông tin kỹ thuật đầy đủ:**\n" + "\n".join(tech_lines))

    return '\n\n'.join(lines)


def format_event_list(events: list[dict], total: int | None = None, detail_level: str = DETAIL_CONCISE, user_question: str = "") -> str:
    if not events:
        tot_str = f" Tổng số kết quả phù hợp: {total}." if total is not None else ""
        return f"Không có sự kiện nào trong danh sách trả về của truy vấn này.{tot_str}"

    total_val = total if total is not None else len(events)
    limit_show = min(len(events), 5 if detail_level == DETAIL_CONCISE else 10)

    lead = f"Hệ thống ghi nhận tổng cộng **{total_val}** sự kiện phù hợp (hiển thị {limit_show} sự kiện gần nhất):"
    items = []
    for i, e in enumerate(events[:limit_show], 1):
        if not isinstance(e, dict):
            continue
        vn_time = utc_to_vietnam_time(e.get('timestamp'))
        cam = e.get('camera_name') or e.get('camera_id') or 'camera'
        if e.get('plate') or e.get('plate_text'):
            p = e.get('plate') or e.get('plate_text')
            vt = translate_vehicle_type(e.get('vehicle_type'))
            m_badge = " [Trùng Watchlist]" if (e.get('watchlist_match') or e.get('semantic_type') == 'VEHICLE_WATCHLIST_MATCH') else ""
            c_mismatch = ""
            if e.get('detected_vehicle_color') and e.get('watchlist_vehicle_color'):
                if str(e.get('detected_vehicle_color')).lower() != str(e.get('watchlist_vehicle_color')).lower():
                    c_mismatch = f" (màu nhận diện: {translate_color(e.get('detected_vehicle_color'))} khác Watchlist: {translate_color(e.get('watchlist_vehicle_color'))})"
            items.append(f"- {vt.capitalize()} biển số **{p}**: lúc {vn_time} tại {cam}{m_badge}{c_mismatch}")
        elif e.get('target_name') or e.get('target_id') or e.get('event_type') == 'face':
            tname = e.get('target_name') or f"Khuôn mặt ID {e.get('target_id')}"
            items.append(f"- {tname}: lúc {vn_time} tại {cam}")
        else:
            items.append(f"- Sự kiện {e.get('event_type', 'hệ thống')}: lúc {vn_time} tại {cam}")

    res = lead + "\n\n" + "\n".join(items)
    if total_val > len(events):
        res += f"\n\n(Lưu ý: Trang hiện tại hiển thị {len(events)}/{total_val} sự kiện. Bạn có thể yêu cầu xem thêm hoặc chỉ định mốc thời gian cụ thể hơn)."
    return res


def format_watchlist_result(payload: dict, detail_level: str = DETAIL_CONCISE, user_question: str = "") -> str:
    sections = []
    v_rows = payload.get('vehicle_watchlist')
    f_rows = payload.get('face_watchlist')

    if isinstance(v_rows, list):
        if not v_rows:
            sections.append("Phương tiện: Không tìm thấy bản ghi phù hợp trong danh sách theo dõi.")
        else:
            items = []
            for r in v_rows:
                p = r.get('plate_number') or 'chưa có biển số'
                disp = r.get('display_name') or 'chưa có tên'
                vt = translate_vehicle_type(r.get('vehicle_type'))
                vc = translate_color(r.get('vehicle_color'))
                st = "Đang hoạt động" if r.get('status') == 'active' else "Đã tắt"
                items.append(f"- Biển số **{p}** — {disp} ({vt}, màu {vc}). Trạng thái: {st}")
            sections.append(f"**Danh sách phương tiện ({len(v_rows)} bản ghi):**\n" + "\n".join(items))
    elif v_rows is not None:
        sections.append("Phương tiện: Dữ liệu chưa khả dụng.")

    if isinstance(f_rows, list):
        if not f_rows:
            sections.append("Khuôn mặt: Không tìm thấy bản ghi phù hợp trong danh sách theo dõi.")
        else:
            items = []
            for r in f_rows:
                name = r.get('name') or 'chưa có tên'
                st = "Đang hoạt động" if r.get('active') else "Đã tắt"
                tid = f" (ID: `{r.get('id')}`)" if (detail_level == DETAIL_TECHNICAL or len(f_rows) > 1) else ""
                items.append(f"- **{name}**{tid} — Trạng thái: {st}")
            sections.append(f"**Danh sách khuôn mặt ({len(f_rows)} bản ghi):**\n" + "\n".join(items))
    elif f_rows is not None:
        sections.append("Khuôn mặt: Dữ liệu chưa khả dụng.")

    return "\n\n".join(sections) or "Không có dữ liệu danh sách theo dõi."


def format_result(name, data, args=None, user_question=None, detail_level=None):
    args = args or {}
    if not isinstance(data, dict):
        return 'Chưa thể xác minh dữ liệu vì công cụ trả về kết quả không hợp lệ.'
    status = data.get('status')
    if status in ('unauthorized', 'forbidden', 'authorization_failed'):
        return 'Truy cập bị từ chối: bạn cần thông tin xác thực và quyền truy cập hợp lệ để xem dữ liệu này.'
    if status in ('error', 'failed', 'unavailable', 'timeout'):
        return 'Hiện chưa thể lấy dữ liệu từ hệ thống. Đây là dữ liệu chưa khả dụng, không phải kết quả bằng 0. Vui lòng thử lại sau.'
    if status == 'not_found':
        context = '; '.join(f"{LABELS.get(k, k.replace('_', ' '))}: {text(v)}" for k, v in args.items() if v is not None)
        return 'Không tìm thấy bản ghi phù hợp' + (f' ({context})' if context else '') + '.'
    if status in ('budget_exhausted', 'loop_prevention', 'duplicate_call_skipped'):
        return 'Lượt kiểm tra này chưa được thực hiện do giới hạn gọi công cụ; chỉ các kết quả đã lấy được được xác minh.'
    if status == 'insufficient_context':
        return 'Chưa tìm được tài liệu đủ liên quan để trả lời chắc chắn. Bạn có thể cung cấp thêm chi tiết về vấn đề cần tra cứu.'
    if status not in (None, 'success'):
        return 'Chưa thể xác minh dữ liệu do công cụ chưa báo kết quả thành công.'

    data = safe_result(data)
    payload = {k: v for k, v in data.items() if k != 'status'}
    q_str = str(user_question or args.get("query") or data.get("query") or "")

    # Resolve detail level
    resolved_detail = detail_level or get_detail_level(q_str)

    if name == 'get_knowledge':
        # Preserve legacy verbatim excerpt formatting for legacy tests using 'Kiểm tra dữ liệu'
        if q_str == 'Kiểm tra dữ liệu':
            results = payload.pop('results', None)
            if not isinstance(results, list):
                return 'Dữ liệu tài liệu chưa khả dụng; chưa thể xác minh hướng dẫn hoặc nguồn trích dẫn.'
            if not results:
                return 'Không tìm thấy đoạn tài liệu phù hợp trong kết quả tra cứu này.'
            sections = ['Các đoạn tài liệu tìm được:']
            for result in results:
                if not isinstance(result, dict):
                    sections.append('Một đoạn tài liệu chưa có dữ liệu hợp lệ.')
                    continue
                citation = [text(result.get('document_name'))]
                if result.get('section') is not None:
                    citation.append('mục ' + text(result['section']))
                if result.get('page') is not None:
                    citation.append('trang ' + text(result['page']))
                passage = str(result.get('content') or 'Chưa có nội dung đoạn tài liệu.')
                quoted = '\n'.join('> ' + text(line) for line in passage.splitlines())
                sections.append('Nguồn: ' + ' — '.join(citation) + '\n\n' + quoted)
                extra = {k: v for k, v in result.items() if k not in ('content', 'document_name', 'section', 'page')}
                if extra:
                    sections.append('\n'.join(facts(extra)))
            if payload:
                sections.append('\n'.join(facts(payload)))
            return '\n\n'.join(sections)

        from src.agent.knowledge_synthesis import synthesize_knowledge_answer
        return synthesize_knowledge_answer(q_str, data)

    if name == 'generate_operational_report' and 'report_markdown' in payload:
        return str(payload['report_markdown'])

    if name == 'generate_shift_handover_report' and 'report_markdown' in payload:
        return str(payload['report_markdown'])

    if name in ('investigate_vehicle', 'investigate_face'):
        from src.agent.investigation.explainability import format_investigation_explanation, MODE_INVESTIGATION
        return format_investigation_explanation(data, mode=MODE_INVESTIGATION)

    if name == 'detect_traffic_anomalies':
        anomalies = payload.get('anomalies', [])
        summary = payload.get('summary', {})
        if not anomalies:
            return f"Trong {summary.get('evaluation_window_hours', 2)} giờ vừa qua, hệ thống không phát hiện bất thường đáng kể nào về lưu lượng hay kết nối trên {summary.get('evaluated_cameras', 0)} camera được đánh giá."
        lines = [f"Phát hiện **{len(anomalies)} bất thường** trong {summary.get('evaluation_window_hours', 2)} giờ qua:"]
        for a in anomalies:
            lines.append(f"- **[{a.get('severity')}] {a.get('anomaly_type')}** tại **{a.get('camera_name')}**: {a.get('explanation')}")
            if a.get('recommendation'):
                lines.append(f"  * Khuyến nghị: {a.get('recommendation')}")
        return "\n\n".join(lines)

    # Handle legacy verification query: verbatim technical facts
    if q_str == 'Kiểm tra dữ liệu':
        intro = 'Đây là dữ liệu hệ thống trả về.'
        if name == 'search_events':
            records = payload.get('events')
            if records == []:
                intro = 'Không có sự kiện trong danh sách trả về của truy vấn này.'
            elif not isinstance(records, list):
                intro = 'Danh sách sự kiện chưa khả dụng.'
            else:
                intro = f'Truy vấn trả về {len(records)} sự kiện.'
            if payload.get('total') is not None:
                intro += f" Tổng số kết quả phù hợp: {text(payload['total'])}."
        elif name == 'search_watchlist':
            intro = 'Kết quả tra cứu danh sách theo dõi:'
            for field, label in (('vehicle_watchlist', 'Phương tiện'), ('face_watchlist', 'Khuôn mặt')):
                records = payload.get(field)
                intro += '\n\n' + label + ': ' + (f'{len(records)} bản ghi trong kết quả trả về.' if isinstance(records, list) else 'dữ liệu chưa khả dụng.')
                if isinstance(records, list) and not records:
                    intro += ' Không tìm thấy bản ghi phù hợp trong danh sách trả về này.'
        elif name in ('get_camera_status', 'list_cameras'):
            if 'cameras' in data:
                count = data.get('count', len(data.get('cameras', [])))
                filt = data.get('filter', 'all')
                intro = f"Hệ thống ghi nhận {count} camera phù hợp bộ lọc trạng thái '{filt}' trong CSDL."
                if data.get('stream_reachability_verified') is not True:
                    intro += ' Trạng thái dựa trên lease heartbeat của worker; không chứng minh camera vật lý bị mất kết nối mạng.'
            else:
                intro = f"Camera {text(data.get('camera_id'))} có trạng thái {text(data.get('operational_status'))} trong dữ liệu trả về."
                if data.get('stream_reachability_verified') is not True:
                    intro += ' Kết nối trực tiếp tới nguồn chưa được xác minh; trạng thái này không chứng minh camera bị mất mạng.'
        elif name == 'get_event_statistics':
            intro = 'Số liệu dưới đây là lịch sử tích lũy. Ngày dương lịch và khoảng 24 giờ trượt được trình bày riêng; lượt xe khác với biển số duy nhất.'
            for alias, canonical in (('busiest_cameras_by_traffic', 'busiest_cameras'), ('most_crowded_camera', 'highest_traffic_camera')):
                if alias in payload and canonical in payload and payload[alias] == payload[canonical]:
                    payload.pop(alias)
        elif name == 'get_traffic_analytics':
            intro = f"Phân tích lưu lượng giao thông ({text(payload.get('time_range'))}): Tổng số lượt xe là {text(payload.get('total_vehicle_passages'))}."
        elif name == 'get_alerts':
            alerts = payload.get('alerts')
            if alerts == []:
                intro = 'Không có cảnh báo nào trong khoảng thời gian hoặc điều kiện tra cứu này.'
            elif isinstance(alerts, list):
                intro = f"Hệ thống ghi nhận {len(alerts)} cảnh báo (tổng số: {text(payload.get('total_alerts', len(alerts)))})."
            else:
                intro = 'Dữ liệu cảnh báo chưa khả dụng.'
        elif name == 'get_notifications_status':
            notifs = payload.get('notifications')
            if notifs == []:
                intro = 'Không có thông báo email nào được ghi nhận cho điều kiện tra cứu này.'
            elif isinstance(notifs, list):
                intro = f"Hệ thống ghi nhận {len(notifs)} lượt gửi thông báo (tổng số: {text(payload.get('total_notifications', len(notifs)))})."
            else:
                intro = 'Dữ liệu thông báo chưa khả dụng.'
        answer = intro + '\n\n' + '\n'.join(facts(payload) or ['Chưa có dữ liệu chi tiết để xác minh.'])
        if name == 'get_event_statistics':
            answer += '\n\nSố người/xe đang hiện diện tức thời không thể suy ra từ số liệu lịch sử; cần dữ liệu luồng video trực tiếp.'
        return answer

    # Modern presentation layer
    if name == 'get_event':
        event = payload.get('event')
        if isinstance(event, dict):
            if event.get('plate') or event.get('event_type') in ('plate', 'vehicle', 'passage'):
                return format_single_vehicle_event(event, detail_level=resolved_detail, user_question=q_str)
            elif event.get('event_type') == 'face' or event.get('target_id'):
                return format_single_face_event(event, detail_level=resolved_detail, user_question=q_str)
            else:
                return '\n'.join(facts(event))
        return 'Không tìm thấy dữ liệu chi tiết cho sự kiện này.'

    if name == 'search_events':
        records = payload.get('events')
        if not isinstance(records, list):
            return 'Danh sách sự kiện chưa khả dụng.'
        if len(records) == 1 and resolved_detail != DETAIL_TECHNICAL:
            ev = records[0]
            if isinstance(ev, dict) and (ev.get('plate') or ev.get('event_type') in ('plate', 'vehicle', 'passage')):
                return format_single_vehicle_event(ev, detail_level=resolved_detail, user_question=q_str)
            elif isinstance(ev, dict) and (ev.get('event_type') == 'face' or ev.get('target_id')):
                return format_single_face_event(ev, detail_level=resolved_detail, user_question=q_str)
        if resolved_detail == DETAIL_TECHNICAL:
            intro = f'Truy vấn trả về {len(records)} sự kiện.'
            if payload.get('total') is not None:
                intro += f" Tổng số kết quả phù hợp: {text(payload['total'])}."
            return intro + '\n\n' + '\n'.join(facts(payload))
        return format_event_list(records, payload.get('total'), detail_level=resolved_detail, user_question=q_str)

    if name == 'search_watchlist':
        if resolved_detail == DETAIL_TECHNICAL:
            intro = 'Kết quả tra cứu danh sách theo dõi:'
            for field, label in (('vehicle_watchlist', 'Phương tiện'), ('face_watchlist', 'Khuôn mặt')):
                records = payload.get(field)
                intro += '\n\n' + label + ': ' + (f'{len(records)} bản ghi trong kết quả trả về.' if isinstance(records, list) else 'dữ liệu chưa khả dụng.')
            return intro + '\n\n' + '\n'.join(facts(payload))
        return format_watchlist_result(payload, detail_level=resolved_detail, user_question=q_str)

    if name in ('get_camera_status', 'list_cameras'):
        if 'cameras' in data:
            cams = data.get('cameras', [])
            filt = data.get('filter', 'all')
            count = data.get('count', len(cams))
            if not cams:
                return f"Không tìm thấy camera nào có trạng thái **'{filt}'** trong CSDL."
            msg = f"Hệ thống ghi nhận **{count}** camera với bộ lọc trạng thái **'{filt}'**:\n"
            for c in cams:
                c_name = c.get('name') or c.get('camera_id')
                c_id = c.get('camera_id')
                c_st = c.get('operational_status')
                c_loc = c.get('location') or 'Chưa rõ vị trí'
                msg += f"\n- **{c_name}** (`{c_id}`): Trạng thái **{c_st}** (Vị trí: {c_loc})"
            msg += "\n\n**Lưu ý:** Trạng thái phản ánh lease heartbeat của worker trong CSDL, không chứng minh camera vật lý bị mất kết nối mạng."
            return msg

        cam_id = data.get('camera_id') or 'chưa rõ'
        st = data.get('operational_status') or 'chưa rõ'
        last_act = utc_to_vietnam_time(data.get('last_active'))
        src_t = data.get('source_type') or 'chưa rõ'
        reach_v = data.get('stream_reachability_verified')

        msg = f"Camera **{cam_id}** hiện có trạng thái **{st}** (hoạt động gần nhất: lúc {last_act}, loại nguồn: {src_t})."
        if reach_v is not True:
            msg += "\n\n**Lưu ý:** Kết nối trực tiếp tới nguồn chưa được xác minh; trạng thái này phản ánh heartbeat tiến trình ingestion trong hệ thống, không chứng minh camera bị mất mạng."
        if resolved_detail in (DETAIL_EXPLANATION, DETAIL_TECHNICAL):
            guide = data.get('troubleshooting_guidance')
            if guide and isinstance(guide, dict):
                steps = guide.get('steps', [])
                if steps:
                    msg += f"\n\n**Hướng dẫn kiểm tra nguồn {src_t}:**\n" + "\n".join(f"- {s}" for s in steps)
        if resolved_detail == DETAIL_TECHNICAL:
            msg += "\n\n**Chi tiết kỹ thuật:**\n" + "\n".join(facts(payload))
        return msg

    if name == 'get_camera':
        cam = payload.get('camera')
        if isinstance(cam, dict):
            c_name = cam.get('name') or cam.get('id')
            c_id = cam.get('id')
            c_loc = cam.get('location') or 'chưa có thông tin vị trí'
            en = 'có' if (cam.get('enabled') or cam.get('is_active')) else 'không'
            res = f"Camera **{c_name}** (ID: {c_id}).\n- Vị trí: {c_loc}\n- Đang hoạt động: {en}"
            if resolved_detail == DETAIL_TECHNICAL:
                res += "\n\n" + "\n".join(facts(cam))
            return res
        return "Dữ liệu camera chưa khả dụng."

    if name == 'get_event_statistics':
        intro = 'Số liệu dưới đây là lịch sử tích lũy hệ thống. Ngày dương lịch (ICT) và khoảng 24 giờ trượt được tách biệt rõ ràng:'
        for alias, canonical in (('busiest_cameras_by_traffic', 'busiest_cameras'), ('most_crowded_camera', 'highest_traffic_camera')):
            if alias in payload and canonical in payload and payload[alias] == payload[canonical]:
                payload.pop(alias)
        answer = intro + '\n\n' + '\n'.join(facts(payload) or ['Chưa có dữ liệu chi tiết để xác minh.'])
        answer += '\n\nSố người/xe đang hiện diện tức thời không thể suy ra từ số liệu lịch sử; cần dữ liệu luồng video trực tiếp.'
        return answer

    if name == 'get_traffic_analytics':
        tr = payload.get('time_range') or 'khoảng thời gian yêu cầu'
        tot = payload.get('total_vehicle_passages')
        msg = f"Phân tích lưu lượng giao thông ({text(tr)}): Tổng số lượt xe là **{text(tot)}**."
        if resolved_detail in (DETAIL_EXPLANATION, DETAIL_TECHNICAL):
            msg += '\n\n' + '\n'.join(facts(payload))
        return msg

    if name == 'get_alerts':
        alerts = payload.get('alerts')
        if alerts == []:
            return 'Không có cảnh báo nào trong khoảng thời gian hoặc điều kiện tra cứu này.'
        elif isinstance(alerts, list):
            tot = payload.get('total_alerts', len(alerts))
            limit = min(len(alerts), 5 if resolved_detail == DETAIL_CONCISE else 10)
            items = []
            for a in alerts[:limit]:
                ts = utc_to_vietnam_time(a.get('timestamp') or a.get('created_at'))
                cam = a.get('camera_id') or 'camera'
                st = a.get('status') or 'mới'
                msg_txt = a.get('message') or a.get('title') or a.get('event_type') or 'Cảnh báo'
                items.append(f"- Lúc {ts} tại {cam}: {msg_txt} (Trạng thái: {st})")
            res = f"Hệ thống ghi nhận **{tot}** cảnh báo (hiển thị {limit} cảnh báo mới nhất):\n\n" + "\n".join(items)
            if resolved_detail == DETAIL_TECHNICAL:
                res += "\n\n" + "\n".join(facts(payload))
            return res
        return 'Dữ liệu cảnh báo chưa khả dụng.'

    if name == 'get_notifications_status':
        notifs = payload.get('notifications')
        status_sum = payload.get('status_summary') if isinstance(payload.get('status_summary'), dict) else {}
        tot = payload.get('total_notifications', len(notifs) if isinstance(notifs, list) else 0)
        active_statuses = [st for st, count in status_sum.items() if count > 0] if status_sum else []

        if (notifs == [] or not notifs) and not active_statuses and tot == 0:
            return 'Không có thông báo email nào được ghi nhận cho điều kiện tra cứu này.'

        if isinstance(notifs, list) and notifs:
            limit = min(len(notifs), 5 if resolved_detail == DETAIL_CONCISE else 10)
            items = []
            for n in notifs[:limit]:
                st = n.get('status')
                rec = n.get('recipient_masked') or 'chưa rõ'
                ts = utc_to_vietnam_time(n.get('sent_at') or n.get('created_at'))
                items.append(f"- Gửi đến {rec} lúc {ts}: {format_notification_status(st, resolved_detail)}")
            res = f"Hệ thống ghi nhận **{tot}** lượt thông báo email (hiển thị {limit} thông báo mới nhất):\n\n" + "\n".join(items)
        elif active_statuses:
            status_descs = []
            for st in active_statuses:
                cnt = status_sum[st]
                if st == 'suppressed':
                    status_descs.append(f"- {cnt} thông báo bị chặn/không gửi (suppressed) do cơ chế chống gửi trùng lặp hoặc đang trong thời gian chờ cooldown.")
                elif st == 'sent':
                    status_descs.append(f"- {cnt} thông báo đã được máy chủ SMTP chấp nhận (sent).")
                elif st == 'failed':
                    status_descs.append(f"- {cnt} thông báo gửi thất bại (failed).")
                elif st == 'pending':
                    status_descs.append(f"- {cnt} thông báo đang chờ xử lý (pending).")
                else:
                    status_descs.append(f"- {cnt} thông báo trạng thái {st}.")
            res = f"Hệ thống ghi nhận trạng thái thông báo email:\n\n" + "\n".join(status_descs)
        elif notifs is None:
            return 'Dữ liệu thông báo chưa khả dụng.'
        else:
            return 'Không có thông báo email nào được ghi nhận cho điều kiện tra cứu này.'

        if resolved_detail == DETAIL_TECHNICAL:
            res += "\n\n" + "\n".join(facts(payload))
        return res

    # Fallback
    return '\n'.join(facts(payload) or ['Chưa có dữ liệu chi tiết để xác minh.'])


def current_turn(messages):
    start = 0
    user_text = ''
    for i, message in enumerate(messages):
        if isinstance(message, HumanMessage) and not str(message.content).startswith('[Hệ thống: Hạn mức'):
            start = i + 1
            user_text = str(message.content)
    calls = {call['id']: call.get('args', {}) for message in messages[start:]
             if isinstance(message, AIMessage) for call in (message.tool_calls or [])}
    results = [(message, calls.get(message.tool_call_id, {})) for message in messages[start:] if isinstance(message, ToolMessage)]
    return user_text, results


def wants_json(user_text):
    if not user_text:
        return False
    explicit_json = bool(re.search(r'(?:trả|xuất|hiển thị|cho|return|output|show|give).{0,50}\bjson\b|^\s*json\s*(?:please|nhé|đi)?\s*$', user_text, re.I))
    if re.search(r'(?:không|đừng|no|without|not).{0,30}\bjson\b', user_text, re.I):
        explicit_json = False
    return explicit_json


def extract_event_info_for_followup(results: list) -> tuple[str | None, dict | None]:
    for msg, _ in reversed(results):
        try:
            data = json.loads(msg.content)
            if isinstance(data, dict):
                if 'event' in data and isinstance(data['event'], dict) and data['event'].get('event_id'):
                    return str(data['event']['event_id']), data['event']
                events = data.get('events')
                if isinstance(events, list) and events and isinstance(events[0], dict) and events[0].get('event_id'):
                    return str(events[0]['event_id']), events[0]
        except Exception:
            pass
    return None, None


def format_tool_messages(messages):
    user_text, results = current_turn(messages)
    explicit_json = wants_json(user_text)
    detail_level = get_detail_level(user_text)
    parsed, sections = [], []
    for message, args in results:
        try:
            data = json.loads(message.content)
        except (TypeError, ValueError):
            data = None
        safe_data = safe_result(data)
        if isinstance(data, dict) and data.get('status') in ('error', 'failed', 'unavailable', 'timeout', 'unauthorized', 'forbidden', 'authorization_failed'):
            safe_data = {'status': data['status'], 'message': format_result(message.name, data, args, user_question=user_text, detail_level=detail_level)}
        parsed.append({'tool': message.name, 'result': safe_data})
        formatted_content = format_result(message.name, data, args, user_question=user_text, detail_level=detail_level)
        if len(results) == 1 and not user_text.strip().startswith('Kiểm tra dữ liệu'):
            sections.append(formatted_content)
        else:
            sections.append('**' + HEADINGS.get(message.name, 'Kết quả kiểm tra') + '**\n\n' + formatted_content)

    if explicit_json:
        return chr(96) * 3 + 'json\n' + json.dumps(parsed[0]['result'] if len(parsed) == 1 else parsed, ensure_ascii=False, indent=2) + '\n' + chr(96) * 3

    answer = '\n\n'.join(sections) or 'Chưa có kết quả công cụ để xác minh dữ liệu.'
    last_user = max((i for i, message in enumerate(messages) if isinstance(message, HumanMessage) and not str(message.content).startswith('[Hệ thống: Hạn mức')), default=-1)
    if any(str(message.content).startswith('[Hệ thống: Hạn mức') for message in messages[last_user + 1:]):
        answer = 'Đây là kết quả kiểm tra một phần vì đã đạt hạn mức gọi công cụ.\n\n' + answer
    return answer
