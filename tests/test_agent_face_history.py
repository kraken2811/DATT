"""Offline regressions using real tools/SQL with isolated recorded face events."""
import json
from datetime import datetime, timezone
from uuid import UUID

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver

from src.agent import graph, nodes
from src.agent.config import agent_config
from src.agent.face_history import history_subject
from src.agent.tools.events import search_events
from src.agent.tools.watchlist import search_watchlist
from src.db.database import Database
from src.db.models import Base, Camera, FaceEvent, Target

LONG = UUID('11111111-1111-4111-8111-111111111111')
OTHER = UUID('22222222-2222-4222-8222-222222222222')
CAMERA = UUID('33333333-3333-4333-8333-333333333333')
RECOGNIZED = datetime(2026, 10, 8, 8, 9, 10, tzinfo=timezone.utc)
REGISTERED = datetime(2025, 1, 1, tzinfo=timezone.utc)


@pytest.fixture
def history_db(tmp_path, monkeypatch):
    url = 'sqlite:///' + (tmp_path / 'history.db').as_posix()
    db = Database(url)
    Base.metadata.create_all(db.engine)
    with db.transaction() as session:
        session.add_all([
            Target(id=LONG, name='Long', target_type='face', active=False, created_at=REGISTERED),
            Target(id=OTHER, name='Mai', target_type='person'),
            Camera(id=CAMERA, registry_key='CAM_GATE', name='Cổng chính', location='Cổng A, tầng 1', source_type='local', source='fixture.mp4'),
        ])
        session.flush()
        session.add_all([
            FaceEvent(camera_id='CAM_GATE', target_id=LONG, decision='FACE_MATCH', similarity=0.9123, created_at=RECOGNIZED),
            FaceEvent(camera_id=str(CAMERA), target_id=LONG, decision='FACE_MATCH', similarity=0.8123, created_at=RECOGNIZED.replace(hour=9)),
            FaceEvent(camera_id='CAM_GATE', target_id=LONG, decision='FACE_NO_MATCH', created_at=RECOGNIZED.replace(hour=10)),
            FaceEvent(camera_id='CAM_GATE', target_id=OTHER, decision='FACE_MATCH', created_at=RECOGNIZED.replace(hour=11)),
        ])
    monkeypatch.setattr(agent_config, 'get_database', lambda: Database(url))
    monkeypatch.setattr(nodes, 'get_llm', lambda: nodes.MockChatModel())
    monkeypatch.setenv('DATT_STRICT_AUTH', '0')
    monkeypatch.setenv('DATT_REQUIRE_OPERATIONAL_AUTH', '0')
    saver = InMemorySaver()

    def ask(question, thread='face-history', user='fixture-operator', authenticated=True):
        return graph.run_agent_message(question, thread, user, authenticated, saver)

    yield db, ask, saver
    db.dispose()


@pytest.mark.parametrize('question', [
    'Hãy cho tôi thời gian khớp của khuôn mặt Long',
    'Tra cứu thời gian và địa điểm khuôn mặt Long từng được nhận diện',
    'Khuôn mặt Long đã nhận diện ở camera nào?',
    'Các lần xuất hiện của khuôn mặt Long?',
    'Người Long đã được nhận diện khi nào?',
    'Long đã được nhận diện ở camera nào?',
    'Khuôn mặt "Long" khớp lúc nào?',
    'Lịch sử khuôn mặt Long',
    'Người Long có xuất hiện trước đây không?',
    'Long xuất hiện ở camera nào?',
])
def test_history_resolves_then_queries_only_matched_identity(history_db, question):
    _, ask, saver = history_db
    result = ask(question)
    assert result['tools_called'] == ['search_watchlist', 'search_events']
    answer = result['reply']
    assert 'Xin chào' not in answer
    assert '```' not in answer and '"status"' not in answer
    assert 'Long' in answer and str(LONG) in answer
    assert 'Tổng số kết quả phù hợp: 2' in answer
    assert RECOGNIZED.isoformat() in answer
    assert RECOGNIZED.replace(hour=9).isoformat() in answer
    assert RECOGNIZED.replace(hour=10).isoformat() not in answer
    assert RECOGNIZED.replace(hour=11).isoformat() not in answer
    assert REGISTERED.isoformat() not in answer  # registration is not recognition
    assert 'CAM_GATE' in answer and str(CAMERA) in answer
    assert 'Cổng chính' in answer and 'Cổng A, tầng 1' in answer
    assert 'cấu hình hiện tại' in answer and '0.9123' in answer
    state = graph.build_agent_graph(saver).get_state(graph.make_thread_config('face-history', user_id='fixture-operator'))
    calls = [call for m in state.values['messages'] if isinstance(m, AIMessage) for call in m.tool_calls]
    assert calls[0]['name'] == 'search_watchlist'
    assert calls[0]['args']['watchlist_type'] == 'face'
    assert calls[1]['args'] == {'target_id': str(LONG), 'event_type': 'face', 'watchlist_match': True, 'limit': 20}


@pytest.mark.parametrize('alias', ['target', 'target_id', 'query'])
@pytest.mark.parametrize('value', ['Long', str(LONG)])
def test_watchlist_aliases_filter_face_records(history_db, alias, value):
    result = search_watchlist.invoke({alias: value, 'watchlist_type': 'face'})
    assert [r['id'] for r in result['face_watchlist']] == [str(LONG)]
    assert result['vehicle_watchlist'] == []
    assert result['face_total_matches'] == 1


def test_face_search_literal_wildcards_and_type(history_db):
    db, _, _ = history_db
    with db.transaction() as session:
        session.add(Target(name='Long', target_type='vehicle'))
        session.add(Target(name='Long 2', target_type='face'))
    result = search_watchlist.invoke({'query': 'Long 2', 'watchlist_type': 'face'})
    assert [r['name'] for r in result['face_watchlist']] == ['Long 2']
    assert search_watchlist.invoke({'query': '%', 'watchlist_type': 'face'})['face_watchlist'] == []
    assert search_watchlist.invoke({'query': '_', 'watchlist_type': 'face'})['face_watchlist'] == []
    assert search_watchlist.invoke({'query': 'Long', 'watchlist_type': 'face'})['face_total_matches'] == 2


def test_ambiguous_name_requires_selection_and_keeps_checkpoint_isolation(history_db):
    db, ask, _ = history_db
    with db.transaction() as session:
        session.get(Target, OTHER).name = 'Long'
    result = ask('Thời gian khớp của khuôn mặt Long?')
    assert result['tools_called'] == ['search_watchlist']
    assert 'chọn đúng ID' in result['reply']
    assert str(LONG) in result['reply'] and str(OTHER) in result['reply']
    stranger = ask('Chọn ' + str(LONG), user='different-operator')
    assert stranger['tools_called'] == []
    chosen = ask('Chọn ' + str(LONG))
    assert chosen['tools_called'] == ['search_watchlist', 'search_events']
    assert 'Tổng số kết quả phù hợp: 2' in chosen['reply']


def test_ambiguity_count_is_not_hidden_by_limit(history_db):
    db, _, _ = history_db
    with db.transaction() as session:
        session.get(Target, OTHER).name = 'Long'
    data = search_watchlist.invoke({'query': 'Long', 'watchlist_type': 'face', 'limit': 1})
    assert len(data['face_watchlist']) == 1
    assert data['face_total_matches'] == 2 and data['face_has_more'] is True
    messages = [HumanMessage(content='Lịch sử khuôn mặt Long'), AIMessage(content='', tool_calls=[{'name': 'search_watchlist', 'args': {'watchlist_type': 'face'}, 'id': 'w'}]), ToolMessage(content=json.dumps(data), name='search_watchlist', tool_call_id='w')]
    result = nodes.MockChatModel().invoke(messages)
    assert not result.tool_calls
    assert 'chưa đầy đủ' in result.content


def test_no_identity_does_not_search_all_face_events(history_db):
    _, ask, _ = history_db
    result = ask('Thời gian khớp khuôn mặt KhôngCóTênNày?')
    assert result['tools_called'] == ['search_watchlist']
    assert 'Không tìm thấy người' in result['reply']
    assert 'Chưa truy vấn lịch sử' in result['reply']


def test_identity_without_events_reports_zero(history_db):
    db, ask, _ = history_db
    with db.transaction() as session:
        session.add(Target(name='An', target_type='face'))
    result = ask('Tra cứu lịch sử khuôn mặt An')
    assert result['tools_called'] == ['search_watchlist', 'search_events']
    assert 'Chưa tìm thấy lịch sử nhận diện' in result['reply']
    assert 'Tổng số kết quả phù hợp: 0' in result['reply']


def test_missing_camera_metadata_retains_recorded_time_and_id(history_db):
    db, ask, _ = history_db
    with db.transaction() as session:
        session.add(FaceEvent(camera_id='CAM_UNKNOWN', target_id=LONG, decision='FACE_MATCH', created_at=RECOGNIZED.replace(hour=12)))
    result = ask('Lịch sử khuôn mặt Long')
    assert 'CAM_UNKNOWN' in result['reply']
    assert RECOGNIZED.replace(hour=12).isoformat() in result['reply']
    assert 'Tên camera: chưa có dữ liệu' in result['reply']
    assert 'Vị trí camera theo cấu hình hiện tại: chưa có dữ liệu' in result['reply']


def test_static_registry_metadata_and_uuid_hex_are_resolved(history_db, tmp_path, monkeypatch):
    db, _, _ = history_db
    config = tmp_path / 'cameras.yaml'
    config.write_text('cameras:\n  CAM_STATIC:\n    name: Camera tĩnh\n    location: Sảnh B\n    url: rtsp://secret:password@host/live\n', encoding='utf-8')
    monkeypatch.setattr('src.agent.tools.events.DEFAULT_CONFIG_PATH', config)
    with db.transaction() as session:
        session.add(FaceEvent(camera_id='CAM_STATIC', target_id=LONG, decision='FACE_MATCH', created_at=RECOGNIZED))
        session.add(FaceEvent(camera_id=CAMERA.hex, target_id=LONG, decision='FACE_MATCH', created_at=RECOGNIZED))
    result = search_events.invoke({'target_id': str(LONG), 'event_type': 'face', 'watchlist_match': True})
    static = next(e for e in result['events'] if e['camera_id'] == 'CAM_STATIC')
    assert static['camera_name'] == 'Camera tĩnh' and static['camera_location'] == 'Sảnh B'
    hexadecimal = next(e for e in result['events'] if e['camera_id'] == CAMERA.hex)
    assert hexadecimal['camera_name'] == 'Cổng chính'
    assert 'password' not in json.dumps(result)


def test_missing_timestamp_is_not_invented(history_db, monkeypatch):
    _, ask, _ = history_db
    monkeypatch.setattr('src.agent.tools.events.query_events', lambda *a, **k: {'total': 1, 'events': [{'event_id': 'face:recorded-id', 'camera_id': 'CAM_GATE', 'timestamp': None, 'target_id': str(LONG), 'watchlist_match': True}]})
    result = ask('Thời gian khớp khuôn mặt Long')
    assert 'Thời điểm: chưa có dữ liệu' in result['reply']
    assert REGISTERED.isoformat() not in result['reply']
    assert RECOGNIZED.isoformat() not in result['reply']
    assert 'Tổng số kết quả phù hợp: 1' in result['reply']


def test_unicode_name_and_exact_uuid(history_db):
    db, ask, _ = history_db
    with db.transaction() as session:
        session.get(Target, LONG).name = 'Nguyễn Đăng Long'
    named = ask('Tra cứu địa điểm khuôn mặt Nguyễn Đăng Long từng được nhận diện')
    assert 'Nguyễn Đăng Long' in named['reply']
    assert named['tools_called'] == ['search_watchlist', 'search_events']
    identified = ask('Thời gian khớp khuôn mặt ' + str(LONG))
    assert identified['tools_called'] == ['search_watchlist', 'search_events']
    assert str(LONG) in identified['reply']


def test_face_budget_reports_unretrieved_history_not_zero(history_db, monkeypatch):
    _, ask, _ = history_db
    monkeypatch.setattr(agent_config, 'max_tool_cycles', 1)
    result = ask('Lịch sử khuôn mặt Long')
    assert result['tools_called'] == ['search_watchlist']
    assert 'chưa lấy được lịch sử' in result['reply']
    assert 'Không thể kết luận có 0' in result['reply']


def test_search_preserves_time_interval_and_pagination(history_db):
    result = search_events.invoke({'target_id': str(LONG), 'event_type': 'face', 'watchlist_match': True, 'limit': 1})
    assert result['total'] == 2 and result['count'] == 1
    assert result['events'][0]['timestamp'] == RECOGNIZED.replace(hour=9).isoformat()
    interval = search_events.invoke({'target_id': str(LONG), 'event_type': 'face', 'watchlist_match': True, 'from_time': RECOGNIZED.isoformat(), 'to_time': RECOGNIZED.replace(minute=10).isoformat()})
    assert interval['total'] == 1 and interval['events'][0]['timestamp'] == RECOGNIZED.isoformat()


@pytest.mark.parametrize('day,expected', [('hôm nay', 0), ('hôm qua', 2), ('ngày 2026-10-08', 2), ('ngày 08/10/2026', 2)])
def test_history_requested_day_uses_ict_boundaries(history_db, monkeypatch, day, expected):
    _, ask, _ = history_db
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 9, 12, tzinfo=timezone.utc).astimezone(tz)
    monkeypatch.setattr('src.agent.face_history.datetime', FixedDateTime)
    result = ask('Người Long có xuất hiện trong ' + day + ' không?')
    assert result['tools_called'] == ['search_watchlist', 'search_events']
    assert f'Tổng số kết quả phù hợp: {expected}' in result['reply']
    assert 'Khoảng tra cứu' in result['reply'] and '+07:00' in result['reply']
    if expected:
        assert '2026-10-08T00:00:00+07:00' in result['reply']
        assert RECOGNIZED.isoformat() in result['reply']


def test_ambiguous_selection_keeps_requested_date(history_db):
    db, ask, _ = history_db
    with db.transaction() as session:
        session.get(Target, OTHER).name = 'Long'
    ambiguous = ask('Người Long đã nhận diện ngày 2026-10-07?')
    assert ambiguous['tools_called'] == ['search_watchlist']
    chosen = ask('Chọn ' + str(LONG))
    assert 'Tổng số kết quả phù hợp: 0' in chosen['reply']
    assert '2026-10-07T00:00:00+07:00' in chosen['reply']


def test_invalid_calendar_date_does_not_run_unfiltered_history(history_db):
    _, ask, _ = history_db
    result = ask('Khuôn mặt Long đã nhận diện ngày 2026-02-31?')
    assert result['tools_called'] == []
    assert 'Ngày tra cứu chưa hợp lệ' in result['reply']


def test_date_immediately_after_name_is_not_part_of_name(history_db):
    _, ask, _ = history_db
    result = ask('Lịch sử khuôn mặt Long ngày 2026-10-08')
    assert result['tools_called'] == ['search_watchlist', 'search_events']
    assert 'Tổng số kết quả phù hợp: 2' in result['reply']


def test_requested_camera_is_not_ignored(history_db):
    _, ask, _ = history_db
    result = ask('Lịch sử khuôn mặt Long tại camera CAM_GATE')
    assert result['tools_called'] == ['search_watchlist', 'search_events']
    assert 'Tổng số kết quả phù hợp: 1' in result['reply']
    assert str(CAMERA) not in result['reply']
    assert 'ID camera: CAM_GATE' in result['reply']


def test_auth_failure_does_not_bypass_watchlist_or_claim_zero(history_db, monkeypatch):
    _, ask, _ = history_db
    monkeypatch.setenv('DATT_REQUIRE_OPERATIONAL_AUTH', '1')
    result = ask('Lịch sử khuôn mặt Long', user='unauth_fixture', authenticated=False)
    assert result['tools_called'] == ['search_watchlist']
    assert 'Truy cập bị từ chối' in result['reply']
    assert 'Tổng số kết quả' not in result['reply']


def test_backend_failure_is_unavailable_not_zero(history_db, monkeypatch):
    _, ask, _ = history_db
    def fail(*args, **kwargs):
        raise RuntimeError('fixture failure')
    monkeypatch.setattr('src.agent.tools.events.query_events', fail)
    result = ask('Lịch sử khuôn mặt Long')
    assert result['tools_called'] == ['search_watchlist', 'search_events']
    assert 'chưa khả dụng' in result['reply']
    assert 'không phải kết quả bằng 0' in result['reply']
    assert 'fixture failure' not in result['reply']


def test_json_only_when_current_turn_requests_it(history_db):
    _, ask, _ = history_db
    result = ask('Lịch sử khuôn mặt Long, trả về JSON')
    assert '```json' in result['reply']
    payload = json.loads(result['reply'].split('```json\n')[1].split('\n```')[0])
    assert [r['tool'] for r in payload] == ['search_watchlist', 'search_events']
    next_result = ask('Lịch sử khuôn mặt Long')
    assert '```' not in next_result['reply']
    assert next_result['tools_called'] == ['search_watchlist', 'search_events']
    greeting = ask('Xin chào')
    assert greeting['tools_called'] == [] and greeting['sources'] == []


def test_sources_and_unique_badges_are_current_turn_only(monkeypatch):
    class FixtureGraph:
        def invoke(self, initial, config):
            user = initial['messages'][0]
            return {'messages': [
                HumanMessage(content='old'),
                ToolMessage(content=json.dumps({'results': [{'document_name': 'Old.pdf'}]}), name='get_knowledge', tool_call_id='old'),
                ToolMessage(content='{}', name='search_watchlist', tool_call_id='old-w'),
                AIMessage(content='old reply'), user,
                ToolMessage(content='{}', name='search_watchlist', tool_call_id='new1'),
                ToolMessage(content='{}', name='search_watchlist', tool_call_id='new2'),
                ToolMessage(content=json.dumps({'results': [{'document_name': 'Current.pdf', 'page': 0}]}), name='get_knowledge', tool_call_id='new-k'),
                AIMessage(content='current reply'),
            ]}
    monkeypatch.setattr(graph, 'get_agent_graph', lambda **kwargs: FixtureGraph())
    result = graph.run_agent_message('new request', 'metadata')
    assert result['reply'] == 'current reply'
    assert result['tools_called'] == ['search_watchlist', 'get_knowledge']
    assert [s['title'] for s in result['sources']] == ['Current.pdf']
    assert result['sources'][0]['page'] == 0


def test_missing_name_and_unsupported_operation_never_get_greeting():
    model = nodes.MockChatModel()
    result = model.invoke([HumanMessage(content='Tra cứu thời gian khớp khuôn mặt')])
    assert not result.tool_calls and 'cung cấp tên hoặc ID' in result.content
    result = model.invoke([HumanMessage(content='Kiểm tra dữ liệu vận hành bị thiếu')])
    assert 'Xin chào' not in result.content
    assert history_subject('Hướng dẫn nhận diện khuôn mặt Long') is None
