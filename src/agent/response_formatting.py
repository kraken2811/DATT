"""Deterministic Vietnamese presentation; no model calls or tool execution."""
import json
import re
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

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
}
HEADINGS = {'get_camera': 'Thông tin camera', 'get_camera_status': 'Trạng thái camera',
            'get_event': 'Chi tiết sự kiện', 'search_events': 'Kết quả tra cứu sự kiện',
            'get_event_statistics': 'Thống kê hệ thống', 'search_watchlist': 'Danh sách theo dõi', 'get_knowledge': 'Tài liệu liên quan'}


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


def format_result(name, data, args=None):
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
    if name == 'get_knowledge':
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
    elif name == 'get_camera_status':
        intro = f"Camera {text(data.get('camera_id'))} có trạng thái {text(data.get('operational_status'))} trong dữ liệu trả về."
        if data.get('stream_reachability_verified') is not True:
            intro += ' Kết nối trực tiếp tới nguồn chưa được xác minh; trạng thái này không chứng minh camera bị mất mạng.'
    elif name == 'get_event_statistics':
        intro = 'Số liệu dưới đây là lịch sử tích lũy. Ngày dương lịch và khoảng 24 giờ trượt được trình bày riêng; lượt xe khác với biển số duy nhất.'
        for alias, canonical in (('busiest_cameras_by_traffic', 'busiest_cameras'), ('most_crowded_camera', 'highest_traffic_camera')):
            if alias in payload and canonical in payload and payload[alias] == payload[canonical]:
                payload.pop(alias)
    answer = intro + '\n\n' + '\n'.join(facts(payload) or ['Chưa có dữ liệu chi tiết để xác minh.'])
    if name == 'get_event_statistics':
        answer += '\n\nSố người/xe đang hiện diện tức thời không thể suy ra từ số liệu lịch sử; cần dữ liệu luồng video trực tiếp.'
    return answer


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


def format_tool_messages(messages):
    user_text, results = current_turn(messages)
    explicit_json = bool(re.search(r'(?:trả|xuất|hiển thị|cho|return|output|show|give).{0,50}\bjson\b|^\s*json\s*(?:please|nhé|đi)?\s*$', user_text, re.I))
    if re.search(r'(?:không|đừng|no|without|not).{0,30}\bjson\b', user_text, re.I):
        explicit_json = False
    parsed, sections = [], []
    for message, args in results:
        try:
            data = json.loads(message.content)
        except (TypeError, ValueError):
            data = None
        safe_data = safe_result(data)
        if isinstance(data, dict) and data.get('status') in ('error', 'failed', 'unavailable', 'timeout', 'unauthorized', 'forbidden', 'authorization_failed'):
            safe_data = {'status': data['status'], 'message': format_result(message.name, data, args)}
        parsed.append({'tool': message.name, 'result': safe_data})
        sections.append('**' + HEADINGS.get(message.name, 'Kết quả kiểm tra') + '**\n\n' + format_result(message.name, data, args))
    if explicit_json:
        return chr(96) * 3 + 'json\n' + json.dumps(parsed[0]['result'] if len(parsed) == 1 else parsed, ensure_ascii=False, indent=2) + '\n' + chr(96) * 3
    answer = '\n\n'.join(sections) or 'Chưa có kết quả công cụ để xác minh dữ liệu.'
    last_user = max((i for i, message in enumerate(messages) if isinstance(message, HumanMessage) and not str(message.content).startswith('[Hệ thống: Hạn mức')), default=-1)
    if any(str(message.content).startswith('[Hệ thống: Hạn mức') for message in messages[last_user + 1:]):
        answer = 'Đây là kết quả kiểm tra một phần vì đã đạt hạn mức gọi công cụ.\n\n' + answer
    return answer
