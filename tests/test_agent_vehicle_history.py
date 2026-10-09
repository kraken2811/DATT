"""Offline regressions using real tools/SQL with isolated recorded vehicle events."""
import json
from datetime import datetime, timezone, timedelta
from uuid import UUID, uuid4

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver

from src.agent import graph, nodes
from src.agent.config import agent_config
from src.agent.tools.events import search_events
from src.agent.tools.watchlist import search_watchlist
from src.agent.vehicle_history import extract_plate, extract_vehicle_display_name, normalize_plate, vehicle_history_subject
from src.db.database import Database
from src.db.models import (
    Base,
    Camera,
    DetectionEvent,
    FaceEvent,
    PlateEvent,
    Target,
    VehicleEvent,
    VehiclePassage,
    VehicleWatchlist,
    VehicleWatchlistResult,
)

CAMERA_GATE_ID = UUID('33333333-3333-4333-8333-333333333333')
CAMERA_NORTH_ID = UUID('44444444-4444-4444-8444-444444444444')
WATCHLIST_CAR_ID = UUID('55555555-5555-4555-8555-555555555555')
WATCHLIST_CAR_2_ID = UUID('66666666-6666-4666-8666-666666666666')
FACE_LONG_ID = UUID('11111111-1111-4111-8111-111111111111')

OCT_8_RECOGNIZED = datetime(2026, 10, 8, 8, 30, 0, tzinfo=timezone.utc)
OCT_8_LATER = datetime(2026, 10, 8, 14, 15, 0, tzinfo=timezone.utc)
OCT_7_YESTERDAY = datetime(2026, 10, 7, 10, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def vehicle_db(tmp_path, monkeypatch):
    url = 'sqlite:///' + (tmp_path / 'vehicle_history.db').as_posix()
    db = Database(url)
    Base.metadata.create_all(db.engine)
    with db.transaction() as session:
        session.add_all([
            Camera(id=CAMERA_GATE_ID, registry_key='CAM_GATE', name='Cổng chính', location='Cổng A, tầng 1', source_type='local', source='gate.mp4'),
            Camera(id=CAMERA_NORTH_ID, registry_key='CAM_NORTH', name='Cổng Bắc', location='Bãi đỗ xe phía Bắc', source_type='local', source='north.mp4'),
            VehicleWatchlist(
                id=WATCHLIST_CAR_ID,
                plate_number='30A-12345',
                vehicle_type='car',
                vehicle_color='black',
                display_name='Xe của Long',
                owner_info='Nguyễn Văn Long',
                notes='Xe quản lý',
                status='active',
            ),
            VehicleWatchlist(
                id=WATCHLIST_CAR_2_ID,
                plate_number='30A-99999',
                vehicle_type='car',
                vehicle_color='white',
                display_name='Xe của Long (Xe phụ)',
                owner_info='Nguyễn Văn Long',
                notes='Xe dự phòng',
                status='active',
            ),
            Target(id=FACE_LONG_ID, name='Long', target_type='face', active=True),
        ])
        session.flush()

        # Detections and events
        v1 = VehicleEvent(id=uuid4(), detection_event_id=None, vehicle_class='car', track_id=1, last_seen=OCT_8_RECOGNIZED, vehicle_color='black')
        v2 = VehicleEvent(id=uuid4(), detection_event_id=None, vehicle_class='car', track_id=2, last_seen=OCT_8_LATER, vehicle_color='black')
        v3_unregistered = VehicleEvent(id=uuid4(), detection_event_id=None, vehicle_class='car', track_id=3, last_seen=OCT_7_YESTERDAY, vehicle_color='white')
        session.add_all([v1, v2, v3_unregistered])
        session.flush()

        pe1 = PlateEvent(
            id=uuid4(),
            vehicle_event_id=v1.id,
            plate_text='30A-12345',
            normalized_plate='30A12345',
            confidence=0.9543,
            created_at=OCT_8_RECOGNIZED,
        )
        pe2 = PlateEvent(
            id=uuid4(),
            vehicle_event_id=v2.id,
            plate_text='30A-12345',
            normalized_plate='30A12345',
            confidence=0.9123,
            created_at=OCT_8_LATER,
        )
        # Unregistered vehicle in watchlist
        pe3_unreg = PlateEvent(
            id=uuid4(),
            vehicle_event_id=v3_unregistered.id,
            plate_text='51F-88888',
            normalized_plate='51F88888',
            confidence=0.8877,
            created_at=OCT_7_YESTERDAY,
        )
        session.add_all([pe1, pe2, pe3_unreg])
        session.flush()

        # Watchlist results (MATCH and NO_MATCH)
        wr1 = VehicleWatchlistResult(
            id=uuid4(),
            plate_event_id=pe1.id,
            watchlist_id=WATCHLIST_CAR_ID,
            normalized_plate='30A12345',
            decision='MATCH',
            display_name='Xe của Long',
            camera_id='CAM_GATE',
            created_at=OCT_8_RECOGNIZED,
        )
        wr2 = VehicleWatchlistResult(
            id=uuid4(),
            plate_event_id=pe2.id,
            watchlist_id=WATCHLIST_CAR_ID,
            normalized_plate='30A12345',
            decision='MATCH',
            display_name='Xe của Long',
            camera_id=str(CAMERA_NORTH_ID),
            created_at=OCT_8_LATER,
        )
        wr3 = VehicleWatchlistResult(
            id=uuid4(),
            plate_event_id=pe3_unreg.id,
            watchlist_id=None,
            normalized_plate='51F88888',
            decision='NO_MATCH',
            display_name=None,
            camera_id='CAM_GATE',
            created_at=OCT_7_YESTERDAY,
        )
        session.add_all([wr1, wr2, wr3])

        # Passages
        vp1 = VehiclePassage(
            id=uuid4(),
            camera_id='CAM_GATE',
            track_id=1,
            session_key='sess_vp1',
            plate_text='30A-12345',
            plate_confidence=0.9543,
            vehicle_color='black',
            last_seen_at=OCT_8_RECOGNIZED,
        )
        session.add(vp1)

        # Face events for Long
        fe1 = FaceEvent(
            id=uuid4(),
            camera_id='CAM_GATE',
            target_id=FACE_LONG_ID,
            decision='FACE_MATCH',
            similarity=0.92,
            created_at=OCT_8_RECOGNIZED,
        )
        session.add(fe1)

    monkeypatch.setattr(agent_config, 'get_database', lambda: Database(url))
    monkeypatch.setattr(nodes, 'get_llm', lambda: nodes.MockChatModel())
    monkeypatch.setenv('DATT_STRICT_AUTH', '0')
    monkeypatch.setenv('DATT_REQUIRE_OPERATIONAL_AUTH', '0')
    saver = InMemorySaver()

    def ask(question, thread='vehicle-history', user='fixture-operator', authenticated=True):
        return graph.run_agent_message(question, thread, user, authenticated, saver)

    yield db, ask, saver
    db.dispose()


# 1. Exact plate lookup
def test_vehicle_exact_plate_lookup(vehicle_db):
    _, ask, _ = vehicle_db
    result = ask('Tìm xe biển số 30A-12345.')
    assert result['tools_called'] == ['search_events']
    answer = result['reply']
    assert '30A12345' in answer or '30A-12345' in answer
    assert '2' in answer or 'ghi nhận' in answer
    assert 'Cổng chính' in answer or 'CAM_GATE' in answer
    assert 'cấu hình hiện tại' in answer


# 2. Normalized plate lookup
def test_vehicle_normalized_plate_lookup(vehicle_db):
    _, ask, _ = vehicle_db
    result = ask('Cho tôi lịch sử nhận diện biển số 30A-123.45')
    assert result['tools_called'] == ['search_events']
    assert '30A12345' in result['reply']


# 3. Vehicle lookup outside Watchlist (unregistered plate)
def test_vehicle_unregistered_plate_search(vehicle_db):
    _, ask, _ = vehicle_db
    result = ask('Tìm xe biển số 51F-88888.')
    assert result['tools_called'] == ['search_events']
    assert '51F88888' in result['reply']
    assert '1' in result['reply'] or 'ghi nhận' in result['reply']


# 4. Search by display name resolves to plate then queries events
def test_vehicle_search_by_display_name_resolved(vehicle_db):
    _, ask, _ = vehicle_db
    # "Xe của Long (Xe phụ)" has unique plate 30A-99999
    result = ask('Tìm lịch sử chiếc xe có tên "Xe của Long (Xe phụ)"')
    assert 'search_watchlist' in result['tools_called']
    assert 'search_events' in result['tools_called']
    assert '30A99999' in result['reply'] or 'Xe của Long (Xe phụ)' in result['reply']


# 5. Ambiguous display name asks user to disambiguate
def test_vehicle_ambiguous_display_name_prompts_selection(vehicle_db):
    _, ask, _ = vehicle_db
    # Both "Xe của Long" and "Xe của Long (Xe phụ)" match query "Xe của Long"
    result = ask('Tìm lịch sử xe Xe của Long')
    answer = result['reply']
    assert 'nhiều phương tiện phù hợp' in answer
    assert '30A-12345' in answer or '30A12345' in answer
    assert '30A-99999' in answer or '30A99999' in answer


# 6. Watchlist membership query distinguishes registration from historical search
def test_vehicle_watchlist_membership_check(vehicle_db):
    _, ask, _ = vehicle_db
    # Registered plate
    r1 = ask('Biển số 30A-12345 có trong Watchlist không?')
    assert r1['tools_called'] == ['search_watchlist']
    assert 'ĐANG CÓ trong Danh sách theo dõi' in r1['reply']
    assert 'Nguyễn Văn Long' in r1['reply']

    # Unregistered plate
    r2 = ask('Biển số 51F-88888 có trong Watchlist không?')
    assert r2['tools_called'] == ['search_watchlist']
    assert 'KHÔNG CÓ trong Danh sách theo dõi' in r2['reply']


# 7. First and latest recognition
def test_vehicle_first_and_latest_recognition(vehicle_db):
    _, ask, _ = vehicle_db
    r_latest = ask('Xe 30A-12345 xuất hiện lần cuối khi nào?')
    assert 'lần gần nhất' in r_latest['reply']
    assert OCT_8_LATER.isoformat() in r_latest['reply']

    r_first = ask('Lần đầu tiên biển số 30A-12345 được ghi nhận là khi nào?')
    assert 'Lần đầu tiên' in r_first['reply']
    assert OCT_8_RECOGNIZED.isoformat() in r_first['reply']


# 8. Route query: locations visited
def test_vehicle_route_locations(vehicle_db):
    _, ask, _ = vehicle_db
    result = ask('Xe 30A-12345 đã đi qua những khu vực nào?')
    answer = result['reply']
    assert 'Cổng chính' in answer or 'CAM_GATE' in answer
    assert 'Cổng Bắc' in answer or 'CAM_NORTH' in answer


# 9. Time filtering: explicit date
def test_vehicle_explicit_date_filtering(vehicle_db):
    _, ask, _ = vehicle_db
    result = ask('Hôm qua ngày 2026-10-07 xe 51F-88888 có xuất hiện không?')
    assert result['tools_called'] == ['search_events']
    assert '51F88888' in result['reply']
    assert OCT_7_YESTERDAY.isoformat() in result['reply']


# 10. Time filtering: zero results for non-matching date
def test_vehicle_zero_results_reporting(vehicle_db):
    _, ask, _ = vehicle_db
    result = ask('Ngày 2026-10-01 xe 30A-12345 có xuất hiện không?')
    assert result['tools_called'] == ['search_events']
    assert 'chưa tìm thấy' in result['reply'].lower() or '0' in result['reply']


# 11. Follow-up query referencing 'xe này' resolves entity from active thread
def test_vehicle_follow_up_xe_nay_resolves_context(vehicle_db):
    _, ask, _ = vehicle_db
    # Turn 1: Discuss plate 30A-12345
    r1 = ask('Tìm xe biển số 30A-12345.', thread='follow-up-thread')
    assert '30A12345' in r1['reply']

    # Turn 2: Follow-up question referencing 'xe này'
    r2 = ask('Xe này đã đi qua những khu vực nào?', thread='follow-up-thread')
    assert r2['tools_called'] == ['search_events']
    assert '30A12345' in r2['reply']
    assert 'Cổng chính' in r2['reply'] or 'CAM_GATE' in r2['reply']


# 12. Explicit JSON output request
def test_vehicle_wants_json_output(vehicle_db):
    _, ask, _ = vehicle_db
    result = ask('Tìm xe biển số 30A-12345 xuất json')
    assert '```json' in result['reply']
    assert '"status": "success"' in result['reply']


# 13. Face History and Vehicle History coexist seamlessly
def test_face_and_vehicle_history_coexistence(vehicle_db):
    _, ask, _ = vehicle_db
    # Face query in same agent
    r_face = ask('Long đã được nhận diện ở camera nào?', thread='coexist-thread')
    assert 'search_watchlist' in r_face['tools_called']
    assert 'search_events' in r_face['tools_called']
    assert 'Long' in r_face['reply']

    # Vehicle query in same agent
    r_vehicle = ask('Tìm xe biển số 30A-12345.', thread='coexist-thread')
    assert r_vehicle['tools_called'] == ['search_events']
    assert '30A12345' in r_vehicle['reply']


# 14. Unknown vehicle prompt when no identifier provided
def test_vehicle_missing_identifier_prompt(vehicle_db):
    _, ask, _ = vehicle_db
    result = ask('Tìm lịch sử xe')
    assert 'search_events' not in result['tools_called']
    assert 'Vui lòng cung cấp biển số xe' in result['reply']


# 15. Historical Watchlist MATCH and NO_MATCH distinction
def test_vehicle_historical_watchlist_match_and_nomatch(vehicle_db):
    _, ask, _ = vehicle_db
    # 30A-12345 matched in watchlist
    res_match = search_events.invoke({'plate': '30A12345', 'watchlist_match': True})
    assert res_match['count'] == 2
    assert all(e['watchlist_match'] is True for e in res_match['events'])

    # 51F-88888 did not match
    res_nomatch = search_events.invoke({'plate': '51F88888', 'watchlist_match': False})
    assert res_nomatch['count'] == 1
    assert res_nomatch['events'][0]['watchlist_match'] is False


# 16. Missing camera metadata handled gracefully
def test_vehicle_missing_camera_metadata_handled_gracefully(vehicle_db):
    db, ask, _ = vehicle_db
    # Insert event with unconfigured camera ID
    with db.transaction() as session:
        ve = VehicleEvent(id=uuid4(), detection_event_id=None, vehicle_class='car', track_id=99, last_seen=OCT_8_RECOGNIZED)
        session.add(ve)
        session.flush()
        pe = PlateEvent(id=uuid4(), vehicle_event_id=ve.id, plate_text='99A-11111', normalized_plate='99A11111', confidence=0.85, created_at=OCT_8_RECOGNIZED)
        session.add(pe)
        session.flush()
        wr = VehicleWatchlistResult(id=uuid4(), plate_event_id=pe.id, watchlist_id=None, normalized_plate='99A11111', decision='NO_MATCH', camera_id='UNKNOWN_CAM', created_at=OCT_8_RECOGNIZED)
        session.add(wr)

    result = ask('Tìm xe biển số 99A-11111')
    assert result['tools_called'] == ['search_events']
    assert '99A11111' in result['reply']
    assert 'UNKNOWN_CAM' in result['reply']


# 17. OCR duplicates versus passage counts
def test_vehicle_passage_count_query(vehicle_db):
    _, ask, _ = vehicle_db
    result = ask('Thống kê số lượt xe này đi qua Camera CAM_GATE')
    # Asking without plate prompts for identifier
    assert 'Vui lòng cung cấp biển số xe' in result['reply']

    # With plate
    result2 = ask('Thống kê số lượt xe biển số 30A-12345 đi qua Camera CAM_GATE')
    assert result2['tools_called'] == ['search_events']
    assert 'lượt đi qua' in result2['reply'] or 'ghi nhận' in result2['reply']


# 18. Zero results versus database errors
def test_vehicle_database_error_distinction(vehicle_db, monkeypatch):
    _, ask, _ = vehicle_db
    monkeypatch.setattr('src.agent.tools.events.query_events', lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError('Connection lost')))
    result = ask('Tìm xe biển số 30A-12345')
    assert '0 kết quả' not in result['reply']
    assert 'thất bại' in result['reply'].lower() or 'lỗi' in result['reply'].lower() or 'không khả dụng' in result['reply'].lower()


# 19. Pagination and total count reported accurately
def test_vehicle_pagination_and_total_count(vehicle_db):
    _, ask, _ = vehicle_db
    res = search_events.invoke({'plate': '30A12345', 'limit': 1})
    assert res['total'] == 3
    assert res['count'] == 1


# 20. Authorization and user isolation between distinct users
def test_vehicle_user_isolation(vehicle_db):
    _, ask, _ = vehicle_db
    r_user1 = ask('Tìm xe biển số 30A-12345', thread='thread-user-iso', user='user-1')
    assert '30A12345' in r_user1['reply']

    # User 2 in a different thread does NOT have User 1's entity context
    r_user2 = ask('Xe này đã đi qua những khu vực nào?', thread='thread-user-iso-2', user='user-2')
    assert 'Vui lòng cung cấp biển số xe' in r_user2['reply']

