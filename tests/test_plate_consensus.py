from types import SimpleNamespace
import threading
import time
from unittest.mock import Mock

import numpy as np
import pytest

from src.ocr.plate_reader import PlateCandidate, is_valid_plate_format, normalize_plate_text
from src.ocr.plate_tracker import VehiclePlateManager, _OcrJob, _OCR_QUEUE_MAXSIZE
from src.runtime.shared_state import SharedRuntimeState


def candidate(text="29A-123.45", confidence=0.9, quality=85):
    crop = np.zeros((30, 100, 3), dtype=np.uint8)
    return PlateCandidate(text, confidence, (0, 0, 100, 30), (0, 0, 100, 30), crop, crop, 100, quality)


def tracks(track=1, size=100):
    return SimpleNamespace(xyxy=np.array([[0, 0, size, size]]), tracker_id=np.array([track]),
                           class_id=np.array([3]), confidence=np.array([0.9]))


@pytest.mark.parametrize("text", ["12345", "ABCDE", "29A-123", "00A12345", "99Z00000", "3OG56789", "29A12!345", "29A12345678", "7XYZ890"])
def test_invalid_garbage(text):
    assert not is_valid_plate_format(text)


@pytest.mark.parametrize("text", ["29A-123.45", "59-X1 123.45", "59AB12345", "51G8888"])
def test_vn_structures(text):
    assert is_valid_plate_format(text)


def test_consensus_and_confirmed_cadence():
    reader = Mock()
    reader.extract_license_plate.side_effect = [candidate("29a 123.45"), candidate("29A-12345"), candidate("29A12345")]
    manager = VehiclePlateManager(reader, eval_interval=1, recheck_interval=180)
    frame = np.zeros((300, 300, 3), dtype=np.uint8)
    for index in range(1, 4):
        state = manager.process_vehicle_tracks(frame, vehicle_tracks=tracks(), frame_id=index)[1]
        assert state.status == ("RECOGNIZED" if index == 3 else "CHECKING")
        if index < 3:
            assert state.plate_text == ""
    assert state.plate_text == "29A12345"
    assert state.consensus_count == 3
    for index in range(4, 100):
        manager.process_vehicle_tracks(frame, vehicle_tracks=tracks(size=min(299, index + 100)), frame_id=index)
    assert reader.extract_license_plate.call_count == 3


def test_conflicting_near_strings_and_bounded_votes():
    reader = Mock()
    reader.extract_license_plate.side_effect = [candidate("29A12345" if i % 2 else "29A12346") for i in range(30)]
    manager = VehiclePlateManager(reader, eval_interval=1, history_size=6)
    for index in range(30):
        state = manager.process_vehicle_tracks(np.zeros((200, 200, 3), dtype=np.uint8), vehicle_tracks=tracks(), frame_id=index)[1]
        assert state.status == "CHECKING"
    assert len(state.plate_history) == 6
    assert sum(state.vote_scores.values()) == 6
    assert state.plate_text == ""


def test_quality_and_duplicate_frames_do_not_vote():
    reader = Mock(return_value=None)
    reader.extract_license_plate.return_value = candidate(confidence=0.3)
    manager = VehiclePlateManager(reader, eval_interval=1)
    for index in range(5):
        state = manager.process_vehicle_tracks(np.zeros((200, 200, 3), dtype=np.uint8), vehicle_tracks=tracks(), frame_id=index)[1]
    assert state.status == "SEARCHING"
    job = _OcrJob(1, 10, candidate().raw_crop, (0, 0, 100, 100), "motorcycle", 1, state.generation)
    for _ in range(5):
        manager._apply_ocr_result(job, candidate())
    assert state.consensus_count == 1
    assert state.status == "CHECKING"


def test_async_latest_queue_bounded_and_reset_rejects_old_result():
    entered, release = threading.Event(), threading.Event()
    def slow(**_):
        entered.set()
        release.wait(3)
        return candidate()
    reader = Mock()
    reader.extract_license_plate.side_effect = slow
    manager = VehiclePlateManager(reader, async_worker=True, eval_interval=1)
    frame = np.zeros((200, 200, 3), dtype=np.uint8)
    manager.process_vehicle_tracks(frame, vehicle_tracks=tracks(), frame_id=1)
    assert entered.wait(2)
    try:
        for index in range(2, 30):
            manager.process_vehicle_tracks(frame, vehicle_tracks=tracks(), frame_id=index)
        assert manager.ocr_queue_size == 1
        for index in range(2, 40):
            manager.process_vehicle_tracks(frame, vehicle_tracks=tracks(track=index), frame_id=30)
        assert manager.ocr_queue_size == _OCR_QUEUE_MAXSIZE
        manager.reset_tracks()
        # Reuse same track ID while the old OCR job is still in flight.
        manager.reader = Mock()
        manager.reader.extract_license_plate.return_value = None
        manager.process_vehicle_tracks(frame, vehicle_tracks=tracks(), frame_id=1)
        release.set()
        deadline = time.monotonic() + 2
        while manager.ocr_queue_size and time.monotonic() < deadline:
            time.sleep(0.01)
        assert manager.get_plate_state(1).consensus_count == 0
    finally:
        release.set()
        manager._worker.stop()
    assert not manager._worker._thread.is_alive()


def test_frame_and_vehicle_counts_share_observation_during_gap():
    state = SharedRuntimeState()
    frame = np.ones((40, 40, 3), dtype=np.uint8)
    state.update(annotated_frame=frame, car_count=3, vehicles_in_view=3, vehicles_in_zone=2)
    first_id = state.get_telemetry().frame_id
    state.update(annotated_frame=None, car_count=0, vehicles_in_view=0, vehicles_in_zone=0)
    frame_id, displayed, fallback, _ = state.get_frame_for_stream()
    telemetry = state.get_telemetry()
    assert frame_id == telemetry.frame_id == first_id
    assert displayed is frame and fallback and telemetry.is_fallback
    assert telemetry.car_count == telemetry.vehicles_in_view == 3
    assert telemetry.vehicles_in_zone == 2
    state.update(annotated_frame=np.zeros_like(frame), car_count=0, vehicles_in_view=0)
    assert state.get_frame_for_stream()[0] == state.get_telemetry().frame_id
    assert state.get_telemetry().car_count == 0
    state.clear_frames()
    assert state.get_frame_for_stream()[1] is None
