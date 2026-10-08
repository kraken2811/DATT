"""Natural answers preserve evidence without additional model calls or API keys."""
import json
import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from src.agent.nodes import MockChatModel, agent_node
from src.agent.response_formatting import format_result


def turn(name, data, question='Kiểm tra dữ liệu', args=None):
    return [HumanMessage(content=question), AIMessage(content='', tool_calls=[
        {'name': name, 'args': args or {}, 'id': 'call_result'}]),
        ToolMessage(content=json.dumps(data, ensure_ascii=False), name=name, tool_call_id='call_result')]


def answer(name, data, question='Kiểm tra dữ liệu', args=None):
    return MockChatModel().invoke(turn(name, data, question, args)).content


def assert_natural(reply):
    assert 'json' not in reply.lower()
    assert '"status"' not in reply
    assert not reply.lstrip().startswith(('{', '['))


@pytest.mark.parametrize('name,data,facts', [
    ('get_camera', {'status': 'success', 'camera': {'id': 'CAM_01', 'name': 'Cổng A', 'enabled': False}}, ['CAM_01', 'Cổng A', 'không']),
    ('get_camera_status', {'status': 'success', 'camera_id': 'camera_01', 'operational_status': 'offline',
        'last_active': '2026-10-08T14:03:02+07:00', 'source_type': 'file', 'status_basis': 'database_heartbeat_lease',
        'stream_reachability_verified': False}, ['camera_01', 'offline', '2026-10-08T14:03:02+07:00', 'file', 'chưa được xác minh']),
    ('get_event', {'status': 'success', 'event': {'event_id': 'plate:abc_123', 'plate': '30A-12345',
        'camera_id': 'CAM_02', 'timestamp': '2026-10-08T07:03:02Z', 'confidence': 0.98765}},
        ['plate:abc_123', '30A-12345', 'CAM_02', '2026-10-08T07:03:02Z', '0.98765']),
    ('search_events', {'status': 'success', 'total': 125, 'count': 1, 'events': [{'event_id': 'face:77', 'target_id': 'target_123'}]},
        ['125', '1 sự kiện', 'face:77', 'target_123']),
    ('search_watchlist', {'status': 'success', 'total_matches': 2, 'vehicle_watchlist': [{'id': 'v_1', 'plate_number': '59B-123.45', 'status': 'active'}],
        'face_watchlist': [{'id': 'target_9', 'name': 'Nguyễn An', 'active': True}]}, ['2', 'v_1', '59B-123.45', 'active', 'target_9', 'Nguyễn An']),
])
def test_all_operational_results_are_natural_and_exact(name, data, facts):
    reply = answer(name, data)
    assert_natural(reply)
    for fact in facts:
        assert fact in reply


def test_statistics_preserve_all_periods_and_missing_is_not_zero():
    data = {'status': 'success', 'camera_id': 'CAM_01',
        'today_calendar_day': {'timezone': 'ICT (UTC+7)', 'day_start_local': '2026-10-08T00:00:00+07:00',
                              'total_events_today': 7, 'vehicle_passages_today': 0, 'unique_plates_today': None},
        'rolling_24h_interval': {'start_time': '2026-10-07T07:00:00Z', 'end_time': '2026-10-08T07:00:00Z', 'vehicle_passages': 21},
        'all_time_database_totals': {'total_business_events': 103},
        'busiest_cameras': [{'camera_id': 'CAM_02', 'passage_count': 17}], 'security_matches': {'total_matches': 3}, 'live_occupancy': None}
    reply = answer('get_event_statistics', data)
    assert_natural(reply)
    for value in ('CAM_01', 'CAM_02', '7', '21', '103', '17', '3', '2026-10-08T00:00:00+07:00', '2026-10-07T07:00:00Z', '2026-10-08T07:00:00Z'):
        assert value in reply
    assert 'Lượt xe hôm nay: 0' in reply
    assert 'Biển số duy nhất hôm nay: chưa có dữ liệu' in reply
    assert 'không thể suy ra' in reply


@pytest.mark.parametrize('name,data,expected', [
    ('search_events', {'status': 'success', 'events': [], 'total': 0, 'count': 0}, 'Không có sự kiện'),
    ('search_events', {'status': 'success', 'total': 0}, 'Danh sách sự kiện chưa khả dụng'),
    ('search_watchlist', {'status': 'success', 'vehicle_watchlist': [], 'face_watchlist': []}, 'Không tìm thấy bản ghi'),
    ('search_watchlist', {'status': 'success', 'vehicle_watchlist': []}, 'Khuôn mặt: dữ liệu chưa khả dụng'),
    ('get_knowledge', {'status': 'insufficient_context', 'results': []}, 'Chưa tìm được tài liệu đủ liên quan'),
    ('get_knowledge', {'status': 'success', 'results': []}, 'Không tìm thấy đoạn tài liệu'),
    ('get_knowledge', {'status': 'success'}, 'Dữ liệu tài liệu chưa khả dụng'),
    ('get_event', {'status': 'not_found'}, 'Không tìm thấy bản ghi'),
])
def test_zero_missing_and_insufficient_context_are_distinct(name, data, expected):
    reply = answer(name, data)
    assert_natural(reply)
    assert expected in reply


@pytest.mark.parametrize('status', ['error', 'failed', 'unavailable', 'timeout', 'unauthorized', 'forbidden', 'authorization_failed'])
def test_errors_and_authorization_do_not_echo_internal_details(status):
    reply = answer('search_watchlist', {'status': status, 'message': 'password=secret-value postgres://private; traceback'})
    assert_natural(reply)
    assert 'secret-value' not in reply and 'postgres://' not in reply
    assert ('Truy cập bị từ chối' in reply) if status in ('unauthorized', 'forbidden', 'authorization_failed') else ('không phải kết quả bằng 0' in reply)


def test_rag_preserves_passage_and_document_citations():
    reply = answer('get_knowledge', {'status': 'success', 'query': 'camera', 'results': [
        {'content': 'Kiểm tra file MP4.\nKhông suy luận mất mạng.', 'document_name': 'ADMIN_GUIDE.md', 'section': 'Camera offline', 'page': 0, 'score': 0.8765}]})
    assert_natural(reply)
    for fact in ('Kiểm tra file MP4.', 'Không suy luận mất mạng.', 'ADMIN_GUIDE.md', 'Camera offline', 'trang 0', '0.8765'):
        assert fact in reply
    assert '> ' in reply


def test_hybrid_retains_camera_and_documentation_results():
    messages = turn('get_camera_status', {'status': 'success', 'camera_id': 'CAM_07', 'operational_status': 'offline'}, 'Hướng dẫn camera offline')
    messages += [AIMessage(content='', tool_calls=[{'name': 'get_knowledge', 'args': {}, 'id': 'rag'}]),
                 ToolMessage(name='get_knowledge', tool_call_id='rag', content=json.dumps({'status': 'success', 'results': [
                     {'content': 'Kiểm tra ingestion worker.', 'document_name': 'GUIDE.md', 'section': 'Workers'}]}))]
    reply = MockChatModel().invoke(messages).content
    assert 'CAM_07' in reply and 'offline' in reply and 'GUIDE.md' in reply and 'Kiểm tra ingestion worker.' in reply


def test_budget_synthesis_preserves_verified_results():
    messages = turn('search_events', {'status': 'success', 'events': [], 'total': 0})
    messages.append(HumanMessage(content='[Hệ thống: Hạn mức gọi công cụ đã kết thúc]'))
    reply = MockChatModel().bind_tools([]).invoke(messages).content
    assert 'một phần' in reply and 'Tổng số kết quả phù hợp: 0' in reply


def test_current_turn_does_not_repeat_old_data_or_json_preference():
    old = turn('get_camera_status', {'status': 'success', 'camera_id': 'OLD_CAM', 'operational_status': 'online'}, 'Trả JSON')
    messages = old + [AIMessage(content='old reply')] + turn('search_events', {'status': 'success', 'events': [], 'total': 0})
    reply = MockChatModel().invoke(messages).content
    assert_natural(reply)
    assert 'OLD_CAM' not in reply


@pytest.mark.parametrize('question', ['Trả kết quả bằng JSON', 'Show JSON', 'JSON please'])
def test_explicit_current_json_request_is_honored(question):
    data = {'status': 'success', 'events': [], 'total': 0}
    reply = answer('search_events', data, question)
    assert reply.startswith(chr(96) * 3 + 'json')
    assert json.loads(reply.split('\n', 1)[1].rsplit('\n', 1)[0]) == data


@pytest.mark.parametrize('question', ['Không hiển thị JSON', 'Explain JSON', 'JSON là gì?'])
def test_merely_mentioning_json_does_not_request_payload(question):
    assert_natural(answer('search_events', {'status': 'success', 'events': []}, question))


def test_malformed_tool_output_is_not_dumped():
    messages = [HumanMessage(content='Tra cứu'), ToolMessage(name='get_camera', tool_call_id='bad', content='not-json private traceback')]
    reply = MockChatModel().invoke(messages).content
    assert 'không hợp lệ' in reply and 'traceback' not in reply


def test_agent_node_uses_one_existing_model_invocation(monkeypatch):
    from src.agent import nodes
    class CountingMock(MockChatModel):
        calls = 0
        def invoke(self, messages):
            self.calls += 1
            return super().invoke(messages)
    model = CountingMock()
    monkeypatch.setattr(nodes, 'get_llm', lambda: model)
    response = agent_node({'messages': turn('search_events', {'status': 'success', 'events': [], 'total': 0})})
    assert model.calls == 1
    assert_natural(response['messages'][0].content)


def test_explicit_json_error_does_not_expose_credentials():
    reply = answer('get_camera', {'status': 'error', 'message': 'password=secret-value'}, 'Trả JSON')
    assert 'secret-value' not in reply
    data = json.loads(reply.split('\n', 1)[1].rsplit('\n', 1)[0])
    assert data['status'] == 'error'


def test_old_budget_notice_does_not_mark_new_results_partial():
    messages = turn('search_events', {'status': 'success', 'events': []})
    messages += [HumanMessage(content='[Hệ thống: Hạn mức đã kết thúc]'), AIMessage(content='old')]
    messages += turn('search_events', {'status': 'success', 'events': [], 'total': 0})
    assert 'một phần' not in MockChatModel().invoke(messages).content


@pytest.mark.parametrize('question', ['Kiểm tra dữ liệu', 'Trả JSON'])
def test_camera_url_credentials_are_not_presented(question):
    reply = answer('get_camera', {'status': 'success', 'camera': {'id': 'CAM_09',
        'source_url': 'rtsp://admin:secret-value@host/live?token=private-token'}}, question)
    assert 'CAM_09' in reply and 'host/live' in reply
    assert 'secret-value' not in reply and 'private-token' not in reply


def test_mock_provider_runs_without_keys(monkeypatch):
    from src.agent.config import agent_config
    from src.agent.llm import get_configured_llm
    monkeypatch.setattr(agent_config, 'llm_provider', 'mock')
    monkeypatch.setattr(agent_config, 'openai_api_key', None)
    monkeypatch.setattr(agent_config, 'gemini_api_key', None)
    model = get_configured_llm()
    reply = model.invoke(turn('search_events', {'status': 'success', 'events': [], 'total': 0})).content
    assert_natural(reply)
