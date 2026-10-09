"""Deterministic face-history routing for offline mode; no fabricated records."""
import json
import re
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone

from langchain_core.messages import AIMessage, HumanMessage

from src.agent.response_formatting import current_turn, facts, format_tool_messages, safe_result, wants_json, text


def normalized(value):
    return ''.join(c for c in unicodedata.normalize('NFD', value.lower().replace('đ', 'd')) if not unicodedata.combining(c))


def history_subject(question):
    """Return None for other intents, empty string when a name is required."""
    query = normalized(question)
    if any(word in query for word in ('huong dan', 'tai lieu', 'cau hinh', 'kien truc')):
        return None
    if ('xe' in query or 'bien so' in query) and 'khuon mat' not in query and not re.search(r'\bnguoi\b', query):
        return None
    history = any(word in query for word in ('khop', 'nhan dien', 'xuat hien', 'lich su', 'thoi gian', 'dia diem', 'camera nao', 'tung'))
    face = 'khuon mat' in query or bool(re.search(r'\bnguoi\b', query))
    # Keep the legacy generic event-ID routing separate from facial identities.
    if 'target_' in query and 'khuon mat' not in query:
        return None
    if not history:
        return None
    identifier = re.search(r'\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b', query)
    if identifier and face:
        return identifier.group()
    match = re.search(r'(?:khuon mat|\bnguoi)\s+', query)
    if match:
        tail = question[match.end():].strip()
    elif re.search(r'(?:da|tung|duoc)\s+(?:duoc\s+)?(?:nhan dien|xuat hien)|xuat hien|camera nao', query):
        # Personal names preceding the recognition verb: "Long đã được nhận diện...".
        tail = re.split(r'\b(?:da|tung|duoc|xuat hien)\b', query, maxsplit=1)[0].strip()
        tail = question[:len(tail)].strip()
        if normalized(tail).startswith(('hay ', 'tra cuu ', 'cho toi ', 'camera ', 'thoi gian ', 'dia diem ', 'su kien', 'phuong tien', 'xe ')):
            return None
    else:
        return '' if face else None
    quoted = re.match(r'["“\']([^"”\']+)["”\']', tail)
    if quoted:
        return quoted.group(1).strip()
    end = re.search(r'\s+(?:tung|da|duoc|co|o|tai|luc|khi|trong|ngay|hom nay|hom qua|truoc day|nhan dien|xuat hien|khop|camera|thoi gian|dia diem|lan nao|la ai|va|tra ve|xuat json)\b', normalized(tail))
    if end:
        tail = tail[:end.start()]
    return tail.strip(' .,:;!?"\'“”')


def history_filters(question):
    """Honor common requested dates; boundaries are ICT, recorded times unchanged."""
    query = normalized(question)
    ict = timezone(timedelta(hours=7))
    now = datetime.now(ict)
    filters = {}
    camera = re.search(r'\bcamera\s+((?:cam(?:era)?[_-][\w-]+)|(?:[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}))\b', question, re.I)
    if camera:
        filters['camera_id'] = camera.group(1)
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
    else:
        return filters
    return {**filters, 'from_time': day.isoformat(), 'to_time': end.isoformat()}


def _call(name, args, question):
    return AIMessage(content='', additional_kwargs={'face_history': True, 'face_history_question': question}, tool_calls=[{'name': name, 'args': args, 'id': 'call_' + uuid.uuid4().hex[:8]}])


def respond(messages, tools):
    """Handle watchlist -> matched events, including ambiguity and unavailable data."""
    question, results = current_turn(messages)
    original_question = question
    subject = history_subject(question)
    if subject and normalized(subject) in ('nay', 'do', 'nguoi nay', 'nguoi do', 'khuon mat nay', 'doi tuong nay'):
        subject = None
        for m in reversed(messages[:-1]):
            if isinstance(m, AIMessage):
                tid = m.additional_kwargs.get('face_history_target_id')
                if tid:
                    subject = str(tid)
                    break
    # A selection is valid only in the immediately preceding ambiguity exchange.
    if subject is None:
        prior = messages[:-1]
        last_ai = next((m for m in reversed(prior) if isinstance(m, AIMessage)), None)
        candidates = last_ai.additional_kwargs.get('face_history_candidates', []) if last_ai else []
        selected = re.search(r'\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b', question, re.I)
        if selected and selected.group().lower() in candidates:
            subject = selected.group().lower()
            original_question = last_ai.additional_kwargs.get('face_history_question', question)
        elif not subject and last_ai and last_ai.additional_kwargs.get('face_history_target_id'):
            # General follow up check
            if any(w in normalized(question) for w in ('nguoi nay', 'khuon mat nay', 'nay', 'do')):
                subject = str(last_ai.additional_kwargs['face_history_target_id'])
    # During the same selection turn, identify the workflow by tool arguments.
    turn_start = max((i for i, m in enumerate(messages) if isinstance(m, HumanMessage) and not str(m.content).startswith('[Hệ thống: Hạn mức')), default=-1)
    routed = any(isinstance(m, AIMessage) and m.additional_kwargs.get('face_history') for m in messages[turn_start + 1:])
    for message in messages[turn_start + 1:]:
        if isinstance(message, AIMessage) and message.additional_kwargs.get('face_history_question'):
            original_question = message.additional_kwargs['face_history_question']
            break
    if subject is None and routed and results and results[0][1].get('watchlist_type') == 'face':
        subject = results[0][1].get('target_id') or results[0][1].get('query')
    if subject is None:
        return None
    if not results:
        if not subject:
            return AIMessage(content='Bạn muốn tra cứu lịch sử nhận diện của ai? Vui lòng cung cấp tên hoặc ID trong Face Watchlist.')
        if 'search_watchlist' not in tools:
            return AIMessage(content='Chưa thể tra cứu danh tính và lịch sử nhận diện vì công cụ hiện không khả dụng.')
        try:
            uuid.UUID(subject)
            args = {'target_id': subject}
        except ValueError:
            args = {'query': subject}
        try:
            history_filters(original_question)
        except ValueError:
            return AIMessage(content='Ngày tra cứu chưa hợp lệ. Bạn hãy cung cấp ngày theo dạng YYYY-MM-DD hoặc DD/MM/YYYY.')
        return _call('search_watchlist', {**args, 'watchlist_type': 'face', 'limit': 50}, original_question)
    try:
        identity = json.loads(results[0][0].content)
    except (TypeError, ValueError):
        return AIMessage(content=format_tool_messages(messages))
    rows = identity.get('face_watchlist') if isinstance(identity, dict) else None
    if not isinstance(identity, dict) or identity.get('status') != 'success' or not isinstance(rows, list):
        return AIMessage(content=format_tool_messages(messages))
    if not rows:
        return AIMessage(content=format_tool_messages(messages) if wants_json(question) else f'Không tìm thấy người phù hợp với {text(subject)} trong Face Watchlist. Chưa truy vấn lịch sử nhận diện.')
    if len(rows) != 1 or identity.get('face_has_more') or (identity.get('face_total_matches') or len(rows)) > 1:
        candidates = [str(row['id']).lower() for row in rows if row.get('id')]
        answer = 'Có nhiều người phù hợp. Bạn hãy chọn đúng ID trước khi tra cứu lịch sử nhận diện:\n\n'
        answer += '\n'.join(f"- {text(row.get('name'))} — ID: {text(row.get('id'))}" for row in rows)
        if identity.get('face_has_more'):
            answer += '\n\nDanh sách chưa đầy đủ; bạn có thể cung cấp tên chính xác hơn hoặc ID.'
        if wants_json(question):
            answer += '\n\n' + format_tool_messages(messages)
        return AIMessage(content=answer, additional_kwargs={'face_history_candidates': candidates, 'face_history_question': original_question})
    person = rows[0]
    try:
        target_id = str(uuid.UUID(str(person.get('id'))))
    except ValueError:
        return AIMessage(content='Bản ghi danh tính chưa có ID hợp lệ; chưa thể truy vấn lịch sử nhận diện.')
    event_results = [(m, args) for m, args in results if m.name == 'search_events']
    if not event_results:
        if 'search_events' in tools:
            return _call('search_events', {'target_id': target_id, 'event_type': 'face', 'watchlist_match': True, 'limit': 20, **history_filters(original_question)}, original_question)
        return AIMessage(content=f'Đã tìm thấy {text(person.get("name"))} (ID: {target_id}), nhưng chưa lấy được lịch sử nhận diện do giới hạn công cụ. Không thể kết luận có 0 lần nhận diện.')
    if wants_json(question):
        return AIMessage(content=format_tool_messages(messages))
    try:
        events = json.loads(event_results[-1][0].content)
    except (TypeError, ValueError):
        events = None
    if not isinstance(events, dict) or events.get('status') != 'success':
        return AIMessage(content=format_tool_messages(messages))
    label = f'{text(person.get("name"))} (ID: {target_id})'
    records = events.get('events')
    if not isinstance(records, list):
        return AIMessage(content=f'Đã xác định {label}, nhưng dữ liệu lịch sử nhận diện chưa khả dụng. Chưa thể xác minh số lần nhận diện.')
    filters = {k: v for k, v in event_results[-1][1].items() if k in ('from_time', 'to_time', 'camera_id')}
    interval = '\n\nKhoảng tra cứu:\n\n' + '\n'.join(facts(filters)) if filters else ''
    if not records and events.get('total') == 0:
        return AIMessage(
            content=f'Chưa tìm thấy lịch sử nhận diện khớp khuôn mặt của {label} trong phạm vi tra cứu này. Tổng số kết quả phù hợp: 0.' + interval,
            additional_kwargs={'face_history': True, 'face_history_target_id': target_id, 'face_history_name': person.get('name')},
        )
    intro = f'Lịch sử nhận diện khớp khuôn mặt của {label}: trả về {len(records)} bản ghi. Tổng số kết quả phù hợp: {text(events.get("total"))}.'
    return AIMessage(
        content=intro + interval + '\n\n' + '\n'.join(facts(safe_result(records))) + '\n\nTên và vị trí camera là cấu hình hiện tại; chưa xác minh vị trí tại thời điểm nhận diện. Trường thiếu được ghi là chưa có dữ liệu.',
        additional_kwargs={'face_history': True, 'face_history_target_id': target_id, 'face_history_name': person.get('name')},
    )
