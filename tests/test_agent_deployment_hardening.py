"""Deployment security/failure contracts using disposable data; never a live PG/LLM probe."""
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
import json
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from sqlalchemy import select

from src.agent import graph, nodes
from src.agent.api import auth, routes
from src.agent.config import agent_config
from src.agent.memory import checkpoint
from src.agent.tools import ALL_AGENT_TOOLS
from src.agent.tools.alerts import get_alerts
from src.agent.tools.notifications import get_notifications_status
from src.agent.tools.reports import generate_operational_report
from src.db.database import Database
from src.db.models import (AgentConversation, Base, Camera, FaceEvent, Notification,
                           PlateEvent, Target, VehicleEvent, VehiclePassage, VehicleWatchlist)
from src.ui.web_server import app

SECRET = 'only-disposable-test-fixtures-' + 'a' * 32
SENSITIVE = [t.name for t in ALL_AGENT_TOOLS if t.name != 'get_knowledge']


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    url = 'sqlite:///' + (tmp_path / 'hardening.db').as_posix()
    for key, value in {'DATT_DATABASE_URL': url, 'DATT_REQUIRE_PERSISTENCE': '0',
                       'DATT_ENVIRONMENT': 'test', 'DATT_STRICT_AUTH': '0',
                       'DATT_REQUIRE_OPERATIONAL_AUTH': '0', 'DATT_AGENT_AUTH_SECRET': SECRET}.items():
        monkeypatch.setenv(key, value)
    db = Database(url)
    Base.metadata.create_all(db.engine)
    monkeypatch.setattr(agent_config, 'get_database', lambda: Database(url))
    monkeypatch.setattr(nodes, 'get_llm', lambda: nodes.MockChatModel())
    saver = MemorySaver()
    monkeypatch.setattr(checkpoint, '_checkpointer_instance', saver)
    monkeypatch.setattr(graph, '_compiled_graph', None)
    yield db
    db.dispose()


@pytest.mark.parametrize('flag', ['DATT_STRICT_AUTH', 'DATT_REQUIRE_OPERATIONAL_AUTH', 'DATT_REQUIRE_PERSISTENCE'])
@pytest.mark.parametrize('tool_name', SENSITIVE)
@pytest.mark.parametrize('authenticated', [False, True])
def test_every_operational_tool_has_the_same_auth_guard(monkeypatch, flag, tool_name, authenticated):
    monkeypatch.setenv(flag, '1')
    invoke = Mock(return_value={'status': 'success', 'fixture': 'private'})
    tool = SimpleNamespace(name=tool_name, invoke=invoke)
    monkeypatch.setattr(nodes, 'ALL_AGENT_TOOLS', [tool])
    message = AIMessage(content='', tool_calls=[{'id': 'guard', 'name': tool_name, 'args': {}}])
    result = nodes.tool_node({'messages': [message], 'is_authenticated': authenticated})
    data = json.loads(result['messages'][0].content)
    assert data['status'] == ('success' if authenticated else 'unauthorized')
    assert invoke.call_count == int(authenticated)
    if not authenticated:
        assert 'private' not in result['messages'][0].content


def test_user_id_alone_does_not_authenticate_graph(isolated_db, monkeypatch):
    monkeypatch.setenv('DATT_REQUIRE_OPERATIONAL_AUTH', '1')
    result = graph.run_agent_message('Tìm lịch sử biển số 30A-12345', 'claimed-id', user_id='admin')
    assert 'yêu cầu thông tin xác thực' in result['reply']
    assert 'Tổng số kết quả phù hợp: 0' not in result['reply']


@pytest.mark.parametrize('tool_name', SENSITIVE)
def test_operational_error_results_do_not_expose_driver_details(monkeypatch, tool_name):
    result = {'status': 'error', 'message': 'PRIVATE_DATABASE_PASSWORD'}
    tool = SimpleNamespace(name=tool_name, invoke=Mock(return_value=result))
    monkeypatch.setattr(nodes, 'ALL_AGENT_TOOLS', [tool])
    call = AIMessage(content='', tool_calls=[{'id': 'private-error', 'name': tool_name, 'args': {}}])
    output = nodes.tool_node({'messages': [call], 'is_authenticated': True})['messages'][0]
    data = json.loads(output.content)
    assert set(data) == set(result) and data['status'] == 'error'
    assert 'PRIVATE_DATABASE_PASSWORD' not in output.content
    assert 'chưa khả dụng' in data['message']


@pytest.mark.parametrize('path', ['/api/cameras', '/api/targets', '/api/watchlist/vehicles',
    '/api/event_center/events', '/api/events/faces', '/api/events/plates', '/api/alerts', '/events/faces'])
def test_direct_operational_api_requires_auth(isolated_db, monkeypatch, path):
    monkeypatch.setenv('DATT_REQUIRE_OPERATIONAL_AUTH', '1')
    client = TestClient(app)
    assert client.get(path).status_code == 401
    token = auth.create_auth_token('fixture-operator')
    assert client.get(path, headers={'Authorization': 'Bearer ' + token}).status_code == 200


def test_authenticated_preflight_does_not_require_a_bearer_token(isolated_db, monkeypatch):
    monkeypatch.setenv('DATT_STRICT_AUTH', '1')
    r = TestClient(app).options('/api/cameras', headers={'Origin': 'https://example.invalid',
        'Access-Control-Request-Method': 'GET', 'Access-Control-Request-Headers': 'Authorization'})
    assert r.status_code == 200


@pytest.mark.parametrize('method,path', [('get', '/cameras'), ('post', '/register_target'),
    ('get', '/switch_camera'), ('post', '/set_video_source'), ('post', '/select_source'),
    ('post', '/stop_camera'), ('get', '/preview_feed'), ('get', '/watchlists/vehicles')])
def test_legacy_operational_aliases_cannot_bypass_auth(isolated_db, monkeypatch, method, path):
    monkeypatch.setenv('DATT_STRICT_AUTH', '1')
    assert TestClient(app).request(method, path).status_code == 401


def test_camera_html_shell_stays_accessible_without_exposing_records(isolated_db, monkeypatch):
    monkeypatch.setenv('DATT_STRICT_AUTH', '1')
    response = TestClient(app).get('/cameras', headers={'Accept': 'text/html'})
    assert response.status_code == 200 and response.headers['content-type'].startswith('text/html')


def test_anonymous_foreign_session_never_reads_checkpoint(isolated_db, monkeypatch):
    client = TestClient(app)
    first = client.post('/api/agent/chat', headers={'X-Session-Id': 'anon-a'},
                        json={'thread_id': 'anonymous-thread', 'message': 'Mã ca trực ALPHA-9123'})
    assert first.status_code == 200
    read = Mock(side_effect=AssertionError('foreign checkpoint must never be queried'))
    monkeypatch.setattr(routes, 'get_checkpointer', read)
    other = client.get('/api/agent/conversations/anonymous-thread', headers={'X-Session-Id': 'anon-b'})
    assert other.status_code == 200
    assert other.json()['status'] == 'not_found'
    assert other.json()['messages'] == []
    assert other.json()['created_at'] is None
    read.assert_not_called()
    # Writes remain forbidden even in anonymous development mode.
    assert client.delete('/api/agent/conversations/anonymous-thread', headers={'X-Session-Id': 'anon-b'}).status_code == 403


def test_signed_foreign_identity_is_forbidden_before_checkpoint(isolated_db, monkeypatch):
    client = TestClient(app)
    owner = {'Authorization': 'Bearer ' + auth.create_auth_token('owner')}
    other = {'Authorization': 'Bearer ' + auth.create_auth_token('other')}
    assert client.post('/api/agent/conversations', headers=owner, json={'thread_id': 'signed-thread'}).status_code == 200
    checkpoint_read = Mock()
    monkeypatch.setattr(routes, 'get_checkpointer', checkpoint_read)
    assert client.get('/api/agent/conversations/signed-thread', headers=other).status_code == 403
    checkpoint_read.assert_not_called()


@pytest.mark.parametrize('legacy_key', [None, 'datt_secure_internal_secret_key'])
def test_production_has_no_public_or_ephemeral_signing_fallback(monkeypatch, legacy_key):
    monkeypatch.setenv('DATT_REQUIRE_PERSISTENCE', '1')
    monkeypatch.setenv('DATT_STRICT_AUTH', '1')
    monkeypatch.delenv('DATT_AGENT_AUTH_SECRET', raising=False)
    monkeypatch.delenv('DATT_SECRET_KEY', raising=False)
    monkeypatch.setattr(auth, 'AUTH_SECRET', legacy_key)
    with pytest.raises(RuntimeError, match='signing key'):
        auth.validate_auth_configuration()


def test_explicit_development_uses_an_ephemeral_key(monkeypatch):
    monkeypatch.setenv('DATT_REQUIRE_PERSISTENCE', '0')
    monkeypatch.setenv('DATT_ENVIRONMENT', 'development')
    monkeypatch.delenv('DATT_AGENT_AUTH_SECRET', raising=False)
    monkeypatch.delenv('DATT_SECRET_KEY', raising=False)
    monkeypatch.setattr(auth, 'AUTH_SECRET', None)
    key = auth.configured_auth_secret()
    assert len(key) >= 32
    assert key != 'datt_secure_internal_secret_key'
    assert auth.configured_auth_secret() == key
    monkeypatch.delenv('DATT_REQUIRE_PERSISTENCE')
    with pytest.raises(RuntimeError):
        auth.configured_auth_secret()


def test_production_requires_strict_auth_and_sufficient_key(monkeypatch):
    monkeypatch.setenv('DATT_REQUIRE_PERSISTENCE', '1')
    monkeypatch.setenv('DATT_AGENT_AUTH_SECRET', 'short')
    with pytest.raises(RuntimeError, match='32 characters'):
        auth.validate_auth_configuration()
    monkeypatch.setenv('DATT_AGENT_AUTH_SECRET', SECRET)
    monkeypatch.setenv('DATT_STRICT_AUTH', '0')
    with pytest.raises(RuntimeError, match='STRICT_AUTH'):
        auth.validate_auth_configuration()
    monkeypatch.setenv('DATT_STRICT_AUTH', '1')
    auth.validate_auth_configuration()


@pytest.mark.parametrize('mode', ['missing_url', 'init_error', 'cached_memory', 'explicit_memory'])
def test_required_persistence_never_uses_memory(monkeypatch, mode, caplog):
    monkeypatch.setenv('DATT_REQUIRE_PERSISTENCE', '1')
    monkeypatch.setattr(checkpoint, '_checkpointer_instance', MemorySaver() if mode == 'cached_memory' else None)
    monkeypatch.setattr(checkpoint, '_pg_pool', None)
    monkeypatch.setattr(checkpoint, 'get_postgres_connection_string', lambda: 'postgresql://fixture' if mode == 'init_error' else None)
    if mode == 'init_error':
        import psycopg_pool
        monkeypatch.setattr(psycopg_pool, 'ConnectionPool', Mock(side_effect=RuntimeError('PRIVATE_DRIVER_SECRET')))
    with pytest.raises(checkpoint.CheckpointUnavailable):
        checkpoint.get_checkpointer(force_memory=mode == 'explicit_memory')
    assert 'PRIVATE_DRIVER_SECRET' not in caplog.text


def test_graph_persistence_failure_is_an_error_not_success(isolated_db, monkeypatch):
    monkeypatch.setenv('DATT_REQUIRE_PERSISTENCE', '1')
    result = graph.run_agent_message('xin chào', 'must-persist', user_id='fixture', is_authenticated=True)
    assert result['status'] == 'error'
    assert result['tools_called'] == []
    assert 'được thực thi thành công' not in result['reply']


def test_failed_pg_setup_releases_pool_and_never_returns_memory(monkeypatch, caplog):
    import psycopg_pool
    from langgraph.checkpoint.postgres import PostgresSaver
    pool = Mock()
    monkeypatch.setenv('DATT_REQUIRE_PERSISTENCE', '1')
    monkeypatch.setattr(checkpoint, '_checkpointer_instance', None)
    monkeypatch.setattr(checkpoint, '_pg_pool', None)
    monkeypatch.setattr(checkpoint, 'get_postgres_connection_string', lambda: 'postgresql://fixture')
    monkeypatch.setattr(psycopg_pool, 'ConnectionPool', Mock(return_value=pool))
    monkeypatch.setattr(PostgresSaver, 'setup', Mock(side_effect=RuntimeError('PRIVATE_SETUP_FAILURE')))
    with pytest.raises(checkpoint.CheckpointUnavailable):
        checkpoint.get_checkpointer()
    pool.open.assert_called_once()
    pool.close.assert_called_once()
    assert checkpoint._pg_pool is None and checkpoint._checkpointer_instance is None
    assert 'PRIVATE_SETUP_FAILURE' not in caplog.text


@pytest.mark.parametrize('method,path', [('post', '/api/agent/chat'), ('post', '/api/agent/conversations'),
    ('get', '/api/agent/conversations'), ('get', '/api/agent/conversations/t'),
    ('patch', '/api/agent/conversations/t'), ('delete', '/api/agent/conversations/t')])
def test_registry_factory_failure_is_503_and_never_executes_graph_or_deletion(isolated_db, monkeypatch, method, path):
    monkeypatch.setattr(agent_config, 'get_database', Mock(side_effect=RuntimeError('PRIVATE_DATABASE_URL')))
    execution, clearing = Mock(), Mock()
    monkeypatch.setattr(routes, 'run_agent_message', execution)
    monkeypatch.setattr(routes, 'clear_thread_checkpoint', clearing)
    data = {'message': 'xin chào', 'title': 'test'}
    r = TestClient(app).request(method, path, **({'json': data} if method in ('post', 'patch') else {}))
    assert r.status_code == 503
    assert 'PRIVATE_DATABASE_URL' not in r.text
    execution.assert_not_called()
    clearing.assert_not_called()


def test_activity_write_failure_does_not_claim_success(isolated_db, monkeypatch):
    monkeypatch.setattr(routes, 'run_agent_message', lambda **kw: {'status': 'success', 'reply': 'fixture'})
    monkeypatch.setattr(routes, 'touch_conversation', Mock(side_effect=RuntimeError('PRIVATE_ACTIVITY_ERROR')))
    r = TestClient(app).post('/api/agent/chat', json={'thread_id': 'activity-error', 'message': 'xin chào'})
    assert r.status_code == 503
    assert 'PRIVATE_ACTIVITY_ERROR' not in r.text


def test_registry_commit_failure_prevents_graph_execution(isolated_db, monkeypatch):
    @contextmanager
    def failing_commit():
        with isolated_db.transaction() as session:
            yield session
            raise RuntimeError('PRIVATE_COMMIT_FAILURE')
    fake_db = SimpleNamespace(transaction=failing_commit, dispose=Mock())
    monkeypatch.setattr(agent_config, 'get_database', lambda: fake_db)
    execute = Mock()
    monkeypatch.setattr(routes, 'run_agent_message', execute)
    response = TestClient(app).post('/api/agent/chat', json={'thread_id': 'rollback', 'message': 'xin chào'})
    assert response.status_code == 503 and 'PRIVATE_COMMIT_FAILURE' not in response.text
    execute.assert_not_called()
    with isolated_db.transaction() as session:
        assert session.scalar(select(AgentConversation).where(AgentConversation.thread_id == 'rollback')) is None


def test_missing_registry_cannot_read_or_delete_an_orphan_checkpoint(isolated_db, monkeypatch):
    read, clear = Mock(), Mock()
    monkeypatch.setattr(routes, 'get_checkpointer', read)
    monkeypatch.setattr(routes, 'clear_thread_checkpoint', clear)
    client = TestClient(app)
    assert client.get('/api/agent/conversations/missing').json()['status'] == 'not_found'
    assert client.delete('/api/agent/conversations/missing').status_code == 404
    read.assert_not_called()
    clear.assert_not_called()


def test_checkpoint_failure_is_503_and_failed_delete_keeps_registry(isolated_db, monkeypatch):
    client = TestClient(app)
    assert client.post('/api/agent/conversations', json={'thread_id': 'failed-delete'}).status_code == 200
    monkeypatch.setattr(routes, 'get_checkpointer', Mock(side_effect=RuntimeError('PRIVATE_CHECKPOINT_ERROR')))
    response = client.get('/api/agent/conversations/failed-delete')
    assert response.status_code == 503
    assert 'PRIVATE_CHECKPOINT_ERROR' not in response.text
    monkeypatch.setattr(routes, 'clear_thread_checkpoint', lambda *a, **kw: False)
    assert client.delete('/api/agent/conversations/failed-delete').status_code == 503
    with isolated_db.transaction() as session:
        assert session.scalar(select(AgentConversation).where(AgentConversation.thread_id == 'failed-delete')) is not None


def test_pg_deletion_uses_the_registry_transaction_and_bound_identity():
    session = Mock(bind=SimpleNamespace(dialect=SimpleNamespace(name='postgresql')))
    assert checkpoint.clear_thread_checkpoint("own-thread';DROP TABLE x", 'fixture-user', session=session)
    assert session.execute.call_count == 3
    for call in session.execute.call_args_list:
        statement, params = call.args
        assert ':tid' in str(statement)
        assert params == {'tid': "fixture-user:own-thread';DROP TABLE x"}
        assert 'DROP TABLE' not in str(statement)


@pytest.fixture
def notifications_db(isolated_db):
    now = datetime(2026, 9, 1, 6, tzinfo=timezone.utc)
    target, watch, other_watch, cam1, cam2 = (uuid4() for _ in range(5))
    face, old_face, p1, p2, p3, p4, vehicle = (uuid4() for _ in range(7))
    with isolated_db.transaction() as s:
        s.add_all([Camera(id=cam1, registry_key='camera_01', name='Gate A', source_type='local', source='fixture.mp4'),
                   Camera(id=cam2, registry_key='camera_02', name='Gate B', source_type='local', source='fixture.mp4'),
                   Target(id=target, name='Long', target_type='face'),
                   VehicleWatchlist(id=watch, plate_number='30A12345', display_name='Xe Long'),
                   VehicleWatchlist(id=other_watch, plate_number='51F99999', display_name='Xe khác'),
                   VehicleEvent(id=vehicle, vehicle_class='car', track_id=1)])
        s.flush()
        s.add_all([FaceEvent(id=face, target_id=target, camera_id='camera_01', decision='FACE_MATCH', created_at=now),
                   FaceEvent(id=old_face, target_id=target, camera_id='camera_01', decision='FACE_MATCH', created_at=now - timedelta(days=1))])
        for ident, plate in ((p1, '30A12345'), (p2, '30A12345'), (p3, '51F99999'), (p4, '51F99999')):
            s.add(PlateEvent(id=ident, vehicle_event_id=vehicle, plate_text=plate, normalized_plate=plate, created_at=now))
        s.flush()
        rows = [('camera_01', face, None, 'sent', now, None),
                ('camera_01', None, p1, 'failed', now, watch),
                ('camera_02', None, p2, 'failed', now, watch),
                ('camera_01', None, p3, 'pending', now, other_watch),
                ('camera_01', old_face, None, 'failed', now - timedelta(days=1), None),
                ('camera_01', None, p1, 'suppressed', now, watch),
                ('camera_02', None, p4, 'sent', now, other_watch)]
        for i, (camera, fid, pid, status, timestamp, wid) in enumerate(rows):
            s.add(Notification(camera_id=camera, event_id=fid, plate_event_id=pid, target_id=target if fid else None,
                vehicle_watchlist_id=wid, recipient=f'fixture{i}@example.invalid', status=status, created_at=timestamp, payload={}))
        for i, camera in enumerate(['camera_01'] + ['camera_02'] * 5):
            s.add(VehiclePassage(camera_id=camera, track_id=i, session_key=f'fixture-{i}', vehicle_type='car',
                                 first_seen_at=now, last_seen_at=now))
    return {'face': str(face), 'target': str(target), 'watch': str(watch), 'camera': str(cam1)}


DAY = {'from_time': '2026-09-01T00:00:00+00:00', 'to_time': '2026-09-01T23:59:59+00:00'}
FILTER_CASES = [({}, 7), ({**DAY, 'camera_id': 'camera_01'}, 4),
    ({**DAY, 'camera_id': 'camera_01', 'status': 'failed'}, 1),
    ({**DAY, 'event_type': 'FACE_WATCHLIST_MATCH'}, 1),
    ({'target_name': 'Long', 'plate_number': '30A-123.45', 'status': 'failed'}, 2),
    ({**DAY, 'camera_id': 'camera_01', 'target_name': 'Long', 'plate_number': '30A12345', 'status': 'failed'}, 1),
    ({'search': '%'}, 0), ({'search': 'fixture1@'}, 1), ({'camera_id': 'missing'}, 0)]


@pytest.mark.parametrize('tool,total_key,rows_key,summary_key', [
    (get_alerts, 'total_alerts', 'alerts', 'status_breakdown'),
    (get_notifications_status, 'total_notifications', 'notifications', 'status_summary')])
@pytest.mark.parametrize('filters,total', FILTER_CASES)
def test_filtered_rows_totals_statuses_and_rankings_agree(notifications_db, tool, total_key, rows_key, summary_key, filters, total):
    result = tool.invoke({**filters, 'limit': 1})
    assert result['status'] == 'success'
    assert result[total_key] == total
    assert len(result[rows_key]) == min(1, total)
    assert sum(result[summary_key].values()) == total
    if filters.get('status'):
        assert result[summary_key][filters['status']] == total
    if tool is get_alerts:
        assert sum(c['alert_count'] for c in result['top_cameras_by_alerts']) == total
        if filters.get('camera_id') == 'camera_01':
            assert all(c['camera_id'] == 'camera_01' for c in result['top_cameras_by_alerts'])


@pytest.mark.parametrize('field,count', [('event_id', 1), ('target_id', 2), ('vehicle_id', 3), ('camera_uuid', 4)])
@pytest.mark.parametrize('tool,total_key', [(get_alerts, 'total_alerts'), (get_notifications_status, 'total_notifications')])
def test_event_entity_and_camera_uuid_filters(notifications_db, field, count, tool, total_key):
    data = notifications_db
    args = {'event_id': 'face:' + data['face']} if field == 'event_id' else (
        {'target_id': data['target']} if field == 'target_id' else (
        {'target_id': data['watch']} if field == 'vehicle_id' else {'camera_id': data['camera'], **DAY}))
    result = tool.invoke(args)
    assert result['status'] == 'success'
    assert result[total_key] == count


@pytest.mark.parametrize('tool', [get_alerts, get_notifications_status])
@pytest.mark.parametrize('filters', [{'event_id': 'invalid'}, {'target_id': 'invalid'}, {'status': 'bogus'},
    {'event_type': 'bogus'}, {'from_time': 'not-a-date'}, {'from_time': '2026-09-02', 'to_time': '2026-09-01'}])
def test_invalid_filters_never_broaden_to_all_records(notifications_db, tool, filters):
    result = tool.invoke(filters)
    assert result['status'] == 'error'
    assert 'total_alerts' not in result and 'total_notifications' not in result


@pytest.mark.parametrize('tool', [get_alerts, get_notifications_status, generate_operational_report])
def test_database_failures_are_unavailable_without_fake_zero_counts(isolated_db, monkeypatch, tool):
    monkeypatch.setattr(agent_config, 'get_database', Mock(side_effect=RuntimeError('PRIVATE_DATABASE_URL')))
    result = tool.invoke({})
    assert result['status'] == 'error'
    assert 'PRIVATE_DATABASE_URL' not in json.dumps(result)
    assert 'metrics' not in result and 'total_alerts' not in result and 'total_notifications' not in result


@pytest.mark.parametrize('tool', [get_alerts, get_notifications_status, generate_operational_report])
def test_database_query_failure_is_not_an_empty_dataset(isolated_db, monkeypatch, tool):
    db = Mock()
    db.transaction.side_effect = RuntimeError('PRIVATE_QUERY_FAILURE')
    monkeypatch.setattr(agent_config, 'get_database', lambda: db)
    result = tool.invoke({})
    assert result['status'] == 'error' and 'PRIVATE_QUERY_FAILURE' not in json.dumps(result)
    assert 'metrics' not in result and 'total_alerts' not in result and 'total_notifications' not in result
    db.dispose.assert_called_once()


def test_report_zero_cameras_and_empty_activity_is_not_health(isolated_db):
    result = generate_operational_report.invoke({})
    assert result['status'] == 'success'
    assert result['metrics']['cameras']['total'] == 0
    assert result['metrics']['cameras']['availability_percent'] is None
    assert result['metrics']['traffic']['total_passages'] == 0
    assert result['data_availability'] == {'camera_records': False, 'recorded_activity': False, 'health_verified': False}
    assert 'ngưỡng ổn định' not in result['report_markdown']
    assert 'chưa được xác minh' in result['report_markdown'].lower()


def test_empty_alert_and_notification_datasets_are_honest_zero(isolated_db):
    for tool, total, summary in ((get_alerts, 'total_alerts', 'status_breakdown'),
                                 (get_notifications_status, 'total_notifications', 'status_summary')):
        result = tool.invoke({})
        assert result['status'] == 'success'
        assert result[total] == 0 and sum(result[summary].values()) == 0


def test_empty_activity_with_camera_heartbeat_is_not_proof_of_health(isolated_db):
    with isolated_db.transaction() as session:
        session.add(Camera(name='Fixture', registry_key='camera_01', source_type='local', source='fixture.mp4',
                           last_active=datetime.now(timezone.utc)))
    result = generate_operational_report.invoke({})
    assert result['status'] == 'success'
    assert result['metrics']['cameras']['total'] == 1 and result['metrics']['cameras']['online'] == 1
    assert not result['data_availability']['recorded_activity']
    assert not result['data_availability']['health_verified']
    assert 'thiếu dữ liệu ingest' in result['report_markdown']


@pytest.mark.parametrize('uuid_alias', [False, True])
def test_report_rankings_respect_camera_and_custom_date(notifications_db, uuid_alias):
    camera = notifications_db['camera'] if uuid_alias else 'camera_01'
    result = generate_operational_report.invoke({'camera_id': camera, 'period': 'custom', **DAY})
    assert result['status'] == 'success'
    assert result['metrics']['cameras']['total'] == 1
    assert result['metrics']['traffic']['total_passages'] == 1
    assert result['metrics']['traffic']['busiest_cameras'] == [{'camera_id': 'camera_01', 'passages': 1}]
    assert result['metrics']['alerts_and_notifications']['total_alerts'] == 4
    assert not result['data_availability']['health_verified']


@pytest.mark.parametrize('question,tool_name', [
    ('Hôm nay Camera 01 có bao nhiêu cảnh báo?', 'get_alerts'),
    ('Có bao nhiêu email cảnh báo gửi thất bại hôm nay tại Camera 01?', 'get_notifications_status'),
    ('Tổng hợp hoạt động hệ thống hôm nay tại Camera 01.', 'generate_operational_report')])
def test_mock_operational_routes_keep_date_and_camera(question, tool_name):
    result = nodes.MockChatModel().invoke([HumanMessage(content=question)])
    call = result.tool_calls[0]
    assert call['name'] == tool_name
    assert call['args']['camera_id'] == 'camera_01'
    assert 'from_time' in call['args'] and 'to_time' in call['args']
    if tool_name == 'get_notifications_status':
        assert call['args']['status'] == 'failed'


def test_multi_tool_carries_identical_requested_filters():
    response = nodes.MockChatModel().invoke([HumanMessage(content='Camera 01 ngày 01/09/2026 có bao nhiêu lượt xe, cảnh báo và email?')])
    assert len(response.tool_calls) == 3
    for call in response.tool_calls:
        assert call['args']['camera_id'] == 'camera_01'
        assert call['args']['from_time'] == '2026-09-01T00:00:00+07:00'
        assert call['args']['to_time'] == '2026-09-01T23:59:59.999999+07:00'
