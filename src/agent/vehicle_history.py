"""Deterministic vehicle and license-plate history routing for offline and online modes."""
import json
import re
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.agent.response_formatting import current_turn, facts, format_tool_messages, safe_result, wants_json, text
from src.watchlists.vehicles import normalize_plate


def normalized(value: str) -> str:
    """Strip accents and lower-case text for robust Vietnamese intent matching."""
    return ''.join(
        c for c in unicodedata.normalize('NFD', value.lower().replace('đ', 'd'))
        if not unicodedata.combining(c)
    )


def extract_plate(question: str) -> str | None:
    """Extract standard Vietnamese or alphanumeric license plate."""
    # Match standard Vietnamese format e.g. 30A-12345, 30A-123.45, 51F-9999, 29B 12345
    match = re.search(r'\b[0-9]{2}[A-Za-z][-.\s]?[0-9]{3,5}(?:\.[0-9]{2})?\b', question)
    if match:
        return match.group(0).strip()
    match2 = re.search(r'\b[0-9]{2}[A-Za-z][0-9]{4,5}\b', question)
    if match2:
        return match2.group(0).strip()
    return None


def extract_vehicle_display_name(question: str) -> str | None:
    """Extract vehicle display name if specified by user."""
    # 1. Quoted string anywhere after vehicle keywords
    quoted = re.search(r'["“\']([^"”\']+)["”\']', question)
    if quoted:
        candidate = quoted.group(1).strip()
        if candidate:
            return candidate

    q_norm = normalized(question)
    # 2. Pattern: "có tên <name>" or "mang tên <name>"
    match_ten = re.search(r'(?:co\s+ten\s+|mang\s+ten\s+)', q_norm)
    if match_ten:
        tail = question[match_ten.end():].strip()
        end = re.search(r'\s+(?:da|tung|duoc|o|tai|luc|khi|trong|ngay|hom nay|hom qua|nhan dien|xuat hien)\b', normalized(tail))
        if end:
            tail = tail[:end.start()]
        return tail.strip(' .,:;!?"\'“”')

    # 3. Pattern: "xe của <owner>" e.g. "xe của Long" or "chiếc xe có tên..." or "xe Xe của Long"
    match_xe = re.search(r'\b(?:chiec\s+)?xe\s+(?:(?:xe\s+)?cua\s+[\w\s]+)', q_norm)
    if match_xe:
        start_idx = match_xe.start()
        sub = re.search(r'(?:cua\s+[\w\s]+)', q_norm[start_idx:])
        if sub:
            tail = question[start_idx + sub.start():].strip()
            end = re.search(r'\s+(?:da|tung|duoc|o|tai|luc|khi|trong|ngay|hom nay|hom qua|nhan dien|xuat hien)\b', normalized(tail))
            if end:
                tail = tail[:end.start()]
            raw_tail = tail.strip(' .,:;!?"\'“”')
            return f"Xe {raw_tail}" if raw_tail.lower().startswith("của") else raw_tail

    return None


def find_prior_vehicle_context(messages: list) -> tuple[str | None, str | None]:
    """Inspect previous turns in the active thread to resolve 'xe này' / 'biển số này'."""
    for msg in reversed(messages[:-1]):
        if isinstance(msg, AIMessage):
            kw = msg.additional_kwargs or {}
            if kw.get('vehicle_history_plate'):
                return kw.get('vehicle_history_plate'), kw.get('vehicle_history_name')
            for tc in (msg.tool_calls or []):
                p_arg = tc.get('args', {}).get('plate') or tc.get('args', {}).get('plate_number')
                if p_arg:
                    return normalize_plate(p_arg), None
            content = str(msg.content or '')
            p = extract_plate(content)
            if p:
                return normalize_plate(p), None
        elif isinstance(msg, HumanMessage):
            content = str(msg.content or '')
            p = extract_plate(content)
            if p:
                return normalize_plate(p), None
        elif isinstance(msg, ToolMessage):
            try:
                data = json.loads(msg.content)
                if isinstance(data, dict):
                    events = data.get('events', [])
                    if events and events[0].get('plate'):
                        return normalize_plate(events[0]['plate']), None
            except Exception:
                pass
    return None, None


def vehicle_history_subject(question: str, messages: list | None = None) -> dict[str, Any] | None:
    """Analyze question for vehicle history and operational intent.

    Returns dict with intent details or None if unrelated.
    """
    q_norm = normalized(question)

    # Ignore pure documentation / troubleshooting questions unless vehicle history is explicitly asked
    if any(word in q_norm for word in ('huong dan', 'tai lieu', 'cau hinh', 'kien truc')):
        if not any(w in q_norm for w in ('bien so', '30a-', 'lich su xe', 'xe xuat hien')):
            return None

    # Exclude pure face queries
    if ('khuon mat' in q_norm or re.search(r'\bnguoi\b', q_norm)) and not any(w in q_norm for w in ('xe', 'bien so', 'phuong tien')):
        return None

    # Check for vehicle keywords
    has_vehicle_kw = any(w in q_norm for w in ('xe', 'bien so', 'phuong tien', 'o to', 'xe may', 'luot xe'))
    plate = extract_plate(question)
    has_plate = plate is not None

    # Check for follow-up date questions in active vehicle thread:
    # e.g. "Hôm qua thì sao?", "Còn hôm nay?", "Thế còn hôm qua?"
    is_date_followup = any(w in q_norm for w in ('thi sao', 'con ', 'the con')) or (
        len(q_norm.split()) <= 6 and any(w in q_norm for w in ('hom nay', 'hom qua', 'tuan nay', 'tuan qua', '7 ngay', 'ngay '))
    )
    prior_plate, prior_name = (None, None)
    if is_date_followup and not has_vehicle_kw and not has_plate:
        prior_plate, prior_name = find_prior_vehicle_context(messages or [])
        if prior_plate:
            has_vehicle_kw = True

    if not has_vehicle_kw and not has_plate:
        return None

    # Check for history or status intent
    is_history = any(w in q_norm for w in (
        'xuat hien', 'nhan dien', 'lich su', 'thoi gian', 'dia diem', 'camera nao',
        'tung', 'di qua', 'khu vuc', 'ghi nhan', 'luot xe', 'lan nao', 'lan dau', 'lan gan nhat', 'cuoi cung'
    )) or bool(prior_plate and is_date_followup)
    is_watchlist_check = any(w in q_norm for w in ('watchlist', 'danh sach theo doi')) and (
        not is_history or any(w in q_norm for w in ('co trong', 'thuoc', 'kiem tra', 'khong')))

    if not is_history and not is_watchlist_check and not has_plate:
        return None

    # Resolve entity
    norm_plate = normalize_plate(plate) if plate else (prior_plate if prior_plate else None)
    display_name = extract_vehicle_display_name(question) or (prior_name if prior_plate else None)
    is_follow_up = bool(prior_plate)

    if is_watchlist_check and not norm_plate and not display_name and not re.search(
        r'\b(?:xe|bien(?:\s+so)?|phuong\s+tien)\s+(?:nay|do)\b', q_norm
    ):
        # A list request has no single vehicle to resolve; retain the general watchlist listing route.
        return None

    if not norm_plate and not display_name:
        # Check follow-up reference: "xe này", "biển số này", "chiếc xe này"
        if re.search(r'\b(?:xe|bien(?:\s+so)?|chiec\s+xe|phuong\s+tien)\s+(?:nay|do)\b', q_norm):
            prior_plate, prior_name = find_prior_vehicle_context(messages or [])
            if prior_plate:
                norm_plate = prior_plate
                display_name = prior_name
                is_follow_up = True

    # Identify operation details
    is_first_and_latest = ('lan dau' in q_norm and ('lan cuoi' in q_norm or 'lan gan nhat' in q_norm)) or ('dau va lan cuoi' in q_norm)
    is_first = not is_first_and_latest and any(w in q_norm for w in ('lan dau', 'lan dau tien', 'dau tien'))
    is_latest = not is_first_and_latest and any(w in q_norm for w in ('lan gan nhat', 'xuat hien lan cuoi', 'cuoi cung', 'moi nhat', 'gan day nhat'))
    is_route = any(w in q_norm for w in ('khu vuc nao', 'nhung khu vuc', 'di qua nhung', 'xuat hien o nhung camera nao'))
    is_timeline = any(w in q_norm for w in ('hanh trinh', 'timeline', 'truoc hay', 'thu tu', 'lan luot', 'nhin thay tai', 'truoc hay camera'))
    is_passage = any(w in q_norm for w in ('so luot', 'luot xe', 'luot di qua', 'passage'))

    return {
        'plate': norm_plate,
        'raw_plate': plate,
        'display_name': display_name,
        'is_watchlist_check': is_watchlist_check,
        'is_first_and_latest': is_first_and_latest,
        'is_first': is_first,
        'is_latest': is_latest,
        'is_route': is_route,
        'is_timeline': is_timeline,
        'is_passage': is_passage,
        'is_follow_up': is_follow_up,
    }


def vehicle_filters(question: str) -> dict[str, str]:
    """Parse requested dates and camera filters with ICT (UTC+7) boundary semantics."""
    query = normalized(question)
    ict = timezone(timedelta(hours=7))
    now = datetime.now(ict)
    filters: dict[str, str] = {}

    # Camera filter (e.g. "Camera 01", "camera_01", "CAM_GATE", or UUID)
    # Ignore "camera nào" as it's a question, not a filter
    # If question compares or mentions multiple cameras, do NOT filter by camera!
    cams_in_q = re.findall(r'\bcamera\s+(?:cam(?:era)?[_-]?[\w-]+|\w+)\b', question, re.I)
    is_multi_cam_q = len(cams_in_q) >= 2 or any(w in query for w in ('truoc hay', 'timeline', 'hanh trinh', 'cac camera', 'nhung camera'))
    if 'camera nao' not in query and not is_multi_cam_q:
        camera = re.search(
            r'\bcamera\s+((?:cam(?:era)?[_-]?[\w-]+)|(?:[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})|\w+)\b',
            question,
            re.IGNORECASE,
        )
        if camera:
            cam_val = camera.group(1).strip()
            if cam_val.lower() not in ('nao', 'nay', 'do', 'gi'):
                filters['camera_id'] = cam_val

    # Date filter
    date = re.search(r'\bngay\s+(\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4})\b', query)
    if date:
        value = date.group(1)
        day = datetime.strptime(value, '%Y-%m-%d' if '-' in value else '%d/%m/%Y').replace(tzinfo=ict)
        end = day + timedelta(days=1) - timedelta(microseconds=1)
    elif 'hom nay' in query or 'hom qua' in query:
        day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = now
        if 'hom qua' in query:
            end = day - timedelta(microseconds=1)
            day -= timedelta(days=1)
    elif 'tuan qua' in query or 'tuan nay' in query or '7 ngay' in query:
        day = now - timedelta(days=7)
        end = now
    else:
        return filters

    return {**filters, 'from_time': day.isoformat(), 'to_time': end.isoformat()}


def _call(name: str, args: dict[str, Any], question: str, meta: dict[str, Any] | None = None) -> AIMessage:
    extra = {'vehicle_history': True, 'vehicle_history_question': question}
    if meta:
        extra.update(meta)
    return AIMessage(
        content='',
        additional_kwargs=extra,
        tool_calls=[{'name': name, 'args': args, 'id': 'call_' + uuid.uuid4().hex[:8]}],
    )


def respond(messages: list, tools: dict) -> AIMessage | None:
    """Unified vehicle and license-plate operational history responder."""
    question, results = current_turn(messages)
    original_question = question

    # Check if this turn or prior turn was vehicle routed
    turn_start = max(
        (i for i, m in enumerate(messages) if isinstance(m, HumanMessage) and not str(m.content).startswith('[Hệ thống: Hạn mức')),
        default=-1,
    )
    routed_meta = next(
        (m.additional_kwargs for m in messages[turn_start + 1:] if isinstance(m, AIMessage) and m.additional_kwargs.get('vehicle_history')),
        None,
    )
    if routed_meta and routed_meta.get('vehicle_history_question'):
        original_question = routed_meta['vehicle_history_question']

    info = vehicle_history_subject(question, messages)
    if info is None and routed_meta:
        # Re-derive from stored question
        info = vehicle_history_subject(original_question, messages)

    if info is None:
        return None

    # Handle ambiguous identity selection turn
    prior = messages[:-1]
    last_ai = next((m for m in reversed(prior) if isinstance(m, AIMessage)), None)
    candidates = last_ai.additional_kwargs.get('vehicle_history_candidates', []) if last_ai else []
    if candidates and not info.get('plate'):
        selected = extract_plate(question)
        if selected and normalize_plate(selected) in candidates:
            info['plate'] = normalize_plate(selected)
            original_question = last_ai.additional_kwargs.get('vehicle_history_question', question)

    # 1. If no tool has run yet in this turn
    if not results:
        # If user asked about vehicle without specifying plate or name
        if not info.get('plate') and not info.get('display_name'):
            return AIMessage(
                content='Bạn muốn tra cứu thông tin của xe nào? Vui lòng cung cấp biển số xe (ví dụ: 30A-12345) hoặc tên xe đã đăng ký trong danh sách theo dõi.'
            )

        # A. Watchlist membership query
        if info.get('is_watchlist_check'):
            if 'search_watchlist' not in tools:
                return AIMessage(content='Chưa thể tra cứu danh sách theo dõi phương tiện vì công cụ hiện không khả dụng.')
            args = {'watchlist_type': 'vehicle', 'limit': 10}
            if info.get('plate'):
                args['plate_number'] = info['plate']
            elif info.get('display_name'):
                args['query'] = info['display_name']
            return _call('search_watchlist', args, original_question, {'vehicle_target': info.get('plate') or info.get('display_name')})

        # B. Search by vehicle display name first to resolve to plate
        if not info.get('plate') and info.get('display_name'):
            if 'search_watchlist' not in tools:
                return AIMessage(content='Chưa thể tra cứu danh tính phương tiện vì công cụ tra cứu danh sách theo dõi không khả dụng.')
            return _call(
                'search_watchlist',
                {'query': info['display_name'], 'watchlist_type': 'vehicle', 'limit': 50},
                original_question,
                {'resolving_vehicle_name': info['display_name']},
            )

        # C. Explicit plate query -> query search_events directly!
        norm_plate = info['plate']
        if 'search_events' not in tools:
            return AIMessage(content='Chưa thể tra cứu lịch sử sự kiện phương tiện vì công cụ hiện không khả dụng.')

        try:
            filters = vehicle_filters(original_question)
        except ValueError:
            return AIMessage(content='Ngày tra cứu chưa hợp lệ. Bạn hãy cung cấp ngày theo dạng YYYY-MM-DD hoặc DD/MM/YYYY.')

        event_args = {'plate': norm_plate, 'limit': 50, **filters}
        if info.get('is_passage'):
            event_args['event_type'] = 'passage'
        return _call('search_events', event_args, original_question, {'vehicle_history_plate': norm_plate})

    # 2. Results returned from tools
    # A. Result from search_watchlist
    watchlist_results = [(m, args) for m, args in results if getattr(m, 'name', '') == 'search_watchlist']
    event_results = [(m, args) for m, args in results if getattr(m, 'name', '') == 'search_events']

    if watchlist_results and not event_results:
        try:
            wl_data = json.loads(watchlist_results[0][0].content)
        except (TypeError, ValueError):
            return AIMessage(content=format_tool_messages(messages))

        if not isinstance(wl_data, dict) or wl_data.get('status') != 'success':
            return AIMessage(content=format_tool_messages(messages))

        rows = wl_data.get('vehicle_watchlist', [])

        # If user asked whether vehicle is in Watchlist
        if info.get('is_watchlist_check'):
            if wants_json(question):
                return AIMessage(content=format_tool_messages(messages))
            target_repr = info.get('plate') or info.get('display_name') or 'phương tiện'
            if not rows:
                return AIMessage(
                    content=f'Biển số {text(target_repr)} hiện KHÔNG CÓ trong Danh sách theo dõi phương tiện (Vehicle Watchlist).'
                )
            row = rows[0]
            status_text = 'Đang hoạt động' if row.get('status') == 'active' else 'Đã tắt'
            details = [
                f"- Biển số: {text(row.get('plate_number'))}",
                f"- Tên hiển thị: {text(row.get('display_name') or 'chưa có')}",
                f"- Loại xe: {text(row.get('vehicle_type'))}",
                f"- Màu xe: {text(row.get('vehicle_color') or 'chưa xác định')}",
                f"- Chủ phương tiện: {text(row.get('owner_info') or 'chưa có thông tin')}",
                f"- Trạng thái theo dõi: {status_text}",
            ]
            return AIMessage(
                content=f'Biển số {text(row.get("plate_number"))} hiện ĐANG CÓ trong Danh sách theo dõi phương tiện (Vehicle Watchlist):\n\n'
                + '\n'.join(details)
                + '\n\nLưu ý: Đăng ký trong Watchlist là trạng thái quản trị hiện tại, không thay thế cho lịch sử nhận diện thực tế.',
                additional_kwargs={'vehicle_history_plate': row.get('plate_number'), 'vehicle_history_name': row.get('display_name')},
            )

        # Resolving display name -> plate
        if not rows:
            name_repr = info.get('display_name') or 'phương tiện'
            return AIMessage(
                content=format_tool_messages(messages) if wants_json(question)
                else f'Không tìm thấy phương tiện phù hợp với tên "{text(name_repr)}" trong Vehicle Watchlist. Chưa truy vấn lịch sử nhận diện.'
            )

        if len(rows) > 1:
            candidates = [str(r.get('plate_number')).upper() for r in rows if r.get('plate_number')]
            answer = f'Có nhiều phương tiện phù hợp với tên "{text(info.get("display_name"))}". Bạn hãy chọn đúng biển số trước khi tra cứu lịch sử nhận diện:\n\n'
            answer += '\n'.join(f"- {text(r.get('display_name'))} — Biển số: {text(r.get('plate_number'))}" for r in rows)
            if wants_json(question):
                answer += '\n\n' + format_tool_messages(messages)
            return AIMessage(
                content=answer,
                additional_kwargs={'vehicle_history_candidates': candidates, 'vehicle_history_question': original_question},
            )

        # Exactly 1 match found -> resolve plate and call search_events!
        resolved_row = rows[0]
        norm_plate = normalize_plate(resolved_row.get('plate_number'))
        display_name = resolved_row.get('display_name') or info.get('display_name')

        if 'search_events' not in tools:
            return AIMessage(
                content=f'Đã xác định phương tiện "{text(display_name)}" có biển số {norm_plate}, nhưng công cụ tra cứu sự kiện không khả dụng.'
            )

        try:
            filters = vehicle_filters(original_question)
        except ValueError:
            return AIMessage(content='Ngày tra cứu chưa hợp lệ.')

        event_args = {'plate': norm_plate, 'limit': 50, **filters}
        if info.get('is_passage'):
            event_args['event_type'] = 'passage'

        return _call(
            'search_events',
            event_args,
            original_question,
            {'vehicle_history_plate': norm_plate, 'vehicle_history_name': display_name},
        )

    # B. Result from search_events
    if event_results:
        if wants_json(question):
            return AIMessage(content=format_tool_messages(messages))

        try:
            events_data = json.loads(event_results[-1][0].content)
        except (TypeError, ValueError):
            return AIMessage(content=format_tool_messages(messages))

        if not isinstance(events_data, dict) or events_data.get('status') != 'success':
            err_msg = events_data.get('message', 'Tra cứu sự kiện thất bại.') if isinstance(events_data, dict) else 'Dữ liệu không hợp lệ.'
            return AIMessage(content=f'Lỗi khi tra cứu lịch sử sự kiện phương tiện: {err_msg}')

        records = events_data.get('events')
        total = events_data.get('total', len(records) if isinstance(records, list) else 0)
        norm_plate = event_results[-1][1].get('plate') or info.get('plate') or 'phương tiện'
        display_name = routed_meta.get('vehicle_history_name') if routed_meta else info.get('display_name')

        if not isinstance(records, list):
            return AIMessage(content=f'Đã xác định biển số {norm_plate}, nhưng dữ liệu lịch sử nhận diện chưa khả dụng. Chưa thể xác minh số lần nhận diện.')

        plate_label = f'Biển số {norm_plate}'
        if display_name:
            plate_label += f' ("{text(display_name)}")'

        filters_applied = {k: v for k, v in event_results[-1][1].items() if k in ('from_time', 'to_time', 'camera_id', 'event_type')}
        interval_text = ('\n\nKhoảng tra cứu:\n' + '\n'.join(facts(filters_applied))) if filters_applied else ''

        if total == 0 or len(records) == 0:
            return AIMessage(
                content=f'Tôi chưa tìm thấy sự kiện nhận diện biển số {norm_plate} trong khoảng thời gian bạn yêu cầu. Tổng số kết quả phù hợp: 0.' + interval_text,
                additional_kwargs={'vehicle_history_plate': norm_plate, 'vehicle_history_name': display_name},
            )

        # DATT events are chronological or reverse chronological
        # Sort by timestamp to find earliest and latest deterministically
        def parse_ts(r):
            ts_str = r.get('timestamp') or ''
            try:
                return datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
            except Exception:
                return datetime.min.replace(tzinfo=timezone.utc)

        sorted_records = sorted(records, key=parse_ts)
        first_event = sorted_records[0]
        latest_event = sorted_records[-1]

        def format_event_loc(e):
            c_name = e.get('camera_name') or e.get('camera_id') or 'chưa rõ camera'
            c_loc = e.get('camera_location')
            loc_str = f'{c_name}' + (f' ({c_loc})' if c_loc else '')
            ts = e.get('timestamp', 'chưa có thời gian')
            conf = e.get('confidence')
            conf_str = f', độ tin cậy OCR: {conf:.2f}' if isinstance(conf, float) else ''
            return f"lúc {ts} tại {loc_str}{conf_str}"

        # If user specifically asked for both first and latest
        if info.get('is_first_and_latest'):
            answer = f'Lần đầu tiên {plate_label.lower()} được hệ thống ghi nhận là {format_event_loc(first_event)}. Lần cuối cùng (gần nhất) được ghi nhận là {format_event_loc(latest_event)}. Tổng số lượt hệ thống ghi nhận: {total}.'
        # If user specifically asked for observation timeline / travel sequence
        elif info.get('is_timeline'):
            cams_mentioned = re.findall(r'(?:cam(?:era)?[_\s-]?\w+)', original_question, re.IGNORECASE)
            if len(cams_mentioned) >= 2:
                c1_id = cams_mentioned[0].lower().replace(" ", "").replace("_", "").replace("-", "")
                c2_id = cams_mentioned[1].lower().replace(" ", "").replace("_", "").replace("-", "")
                c1_clean = lambda r: str(r.get('camera_id', '') or '').lower().replace(" ", "").replace("_", "").replace("-", "") + " " + str(r.get('camera_name', '') or '').lower().replace(" ", "").replace("_", "").replace("-", "")
                first_c1 = next((r for r in sorted_records if c1_id in c1_clean(r)), None)
                first_c2 = next((r for r in sorted_records if c2_id in c1_clean(r)), None)
                if first_c1 and first_c2:
                    ts1 = parse_ts(first_c1)
                    ts2 = parse_ts(first_c2)
                    earlier_cam = cams_mentioned[0] if ts1 <= ts2 else cams_mentioned[1]
                    later_cam = cams_mentioned[1] if ts1 <= ts2 else cams_mentioned[0]
                    answer = f'{plate_label} được nhìn thấy tại {earlier_cam} trước ({format_event_loc(first_c1 if ts1 <= ts2 else first_c2)}), sau đó mới xuất hiện tại {later_cam} ({format_event_loc(first_c2 if ts1 <= ts2 else first_c1)}).'
                else:
                    timeline_items = [f"{i+1}. {format_event_loc(r)}" for i, r in enumerate(sorted_records[:10])]
                    answer = f'Hành trình quan sát (Observation Timeline) của {plate_label} qua các camera theo thứ tự thời gian:\n' + '\n'.join(timeline_items)
            else:
                timeline_items = [f"{i+1}. {format_event_loc(r)}" for i, r in enumerate(sorted_records[:10])]
                answer = f'Hành trình quan sát (Observation Timeline) của {plate_label} qua các camera theo thứ tự thời gian:\n' + '\n'.join(timeline_items)
        # If user specifically asked for latest appearance
        elif info.get('is_latest'):
            answer = f'{plate_label} xuất hiện lần gần nhất {format_event_loc(latest_event)}. Tổng số lượt hệ thống ghi nhận: {total}.'
        # If user specifically asked for first appearance
        elif info.get('is_first'):
            answer = f'Lần đầu tiên {plate_label.lower()} được hệ thống ghi nhận là {format_event_loc(first_event)}. Tổng số lượt hệ thống ghi nhận: {total}.'
        # If user specifically asked for passage / count
        elif info.get('is_passage'):
            cam_str = f" tại Camera {event_results[-1][1].get('camera_id')}" if event_results[-1][1].get('camera_id') else ""
            answer = f'{plate_label} được ghi nhận có {total} lượt đi qua{cam_str}. Lần gần nhất {format_event_loc(latest_event)}.'
        # If user asked for route / locations
        elif info.get('is_route'):
            cams = set()
            for r in records:
                c_name = r.get('camera_name') or r.get('camera_id')
                c_loc = r.get('camera_location')
                if c_name:
                    cams.add(f"{c_name}" + (f" ({c_loc})" if c_loc else ""))
            cams_str = ", ".join(sorted(cams)) if cams else "chưa có dữ liệu địa điểm"
            answer = f'{plate_label} từng được hệ thống ghi nhận tại các khu vực: {cams_str}. Tổng số lượt ghi nhận: {total}. Lần gần nhất {format_event_loc(latest_event)}.'
        # General vehicle history
        else:
            answer = f'{plate_label} được hệ thống ghi nhận {total} lần. Lần gần nhất được ghi nhận {format_event_loc(latest_event)}.'

        # Detailed facts listing
        event_facts = facts(safe_result(records[:10]))
        more_notice = f'\n\n(Hiển thị {min(len(records), 10)}/{total} bản ghi mới nhất)' if total > 10 else ''

        disclaimer = (
            '\n\nTên và vị trí camera là cấu hình hiện tại; chưa xác minh vị trí tại thời điểm nhận diện. '
            'Trường thiếu được ghi là chưa có dữ liệu.'
        )

        return AIMessage(
            content=answer + interval_text + '\n\nChi tiết các lần ghi nhận:\n' + '\n'.join(event_facts) + more_notice + disclaimer,
            additional_kwargs={'vehicle_history_plate': norm_plate, 'vehicle_history_name': display_name},
        )

    return None
