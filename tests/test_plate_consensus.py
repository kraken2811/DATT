from types import SimpleNamespace
import threading
import time
from unittest.mock import Mock

import numpy as np
import pytest

from src.ocr.plate_reader import PlateCandidate, is_valid_plate_format, normalize_plate_text
from src.ocr.plate_tracker import VehiclePlateManager, _OcrJob, _OCR_QUEUE_MAXSIZE
from src.runtime.shared_state import SharedRuntimeState
from src.ui.frame_renderer import get_vehicle_track_label


def candidate(text="29A-123.45", confidence=0.9, quality=85):
    crop = np.zeros((30, 100, 3), dtype=np.uint8)
    return PlateCandidate(
        plate_text=text,
        confidence=confidence,
        bbox_vehicle=(0, 0, 100, 30),
        bbox_native=(0, 0, 100, 30),
        raw_crop=crop,
        preprocessed_crop=crop,
        sharpness=100.0,
        quality_score=quality,
    )


def tracks(track=1, size=100):
    return SimpleNamespace(
        xyxy=np.array([[0, 0, size, size]]),
        tracker_id=np.array([track]),
        class_id=np.array([2]),  # car
        confidence=np.array([0.9]),
    )


@pytest.mark.parametrize(
    "text",
    [
        "12345",
        "ABCDE",
        "29A-123",
        "00A12345",
        "99Z00000",
        "3OG56789",
        "29A12!345",
        "29A12345678",
        "7XYZ890",
        "24C1405B",  # Ends in letter, invalid for Vietnamese plate
    ],
)
def test_invalid_garbage(text):
    assert not is_valid_plate_format(text)


@pytest.mark.parametrize(
    "text",
    [
        "29A-123.45",
        "59-X1 123.45",
        "59AB12345",
        "51G8888",
        "24C-140.58",
        "24C-140.59",
    ],
)
def test_vn_structures(text):
    assert is_valid_plate_format(text)


# ==============================================================================
# SECTION 11 REQUIRED TESTS: 2-STAGE CONFIRMATION FLOW
# ==============================================================================


def test_1_first_valid_observation_provisional_and_rendered(caplog):
    """1. First valid observation: SEARCHING -> PROVISIONAL, plate immediately available for rendering."""
    reader = Mock()
    reader.extract_license_plate.return_value = candidate("24C-140.58", confidence=0.88, quality=82)
    manager = VehiclePlateManager(reader, eval_interval=1)
    frame = np.zeros((200, 200, 3), dtype=np.uint8)

    with caplog.at_level("INFO", logger="datt.ocr.plate_tracker"):
        results = manager.process_vehicle_tracks(frame, vehicle_tracks=tracks(track=124), frame_id=9992)

    state = results[124]
    # State transitions to PROVISIONAL immediately
    assert state.status == "PROVISIONAL"
    assert state.provisional_plate == "24C14058"
    assert state.provisional_frame_id == 9992
    assert not state.confirmed_plate
    # Plate text is available immediately
    assert state.plate_text == "24C14058"

    # UI Renderer displays it immediately
    label, is_conf = get_vehicle_track_label("CAR", 124, 0.92, state.plate_text, state.status)
    assert label == "CAR-124 | 24C-140.58"
    assert is_conf is True

    # Diagnostic logging verification
    assert "[PLATE_PROVISIONAL]" in caplog.text
    assert "track_id=124" in caplog.text
    assert "normalized=24C14058" in caplog.text


def test_2_second_independent_matching_observation_confirms(caplog):
    """2. Second independent matching observation: PROVISIONAL -> CONFIRMED (normal 2-vote path)."""
    reader = Mock()
    reader.extract_license_plate.side_effect = [
        candidate("24C-140.58", confidence=0.85, quality=80),
        candidate("24C140.58", confidence=0.89, quality=84),
    ]
    manager = VehiclePlateManager(reader, eval_interval=1)
    frame = np.zeros((200, 200, 3), dtype=np.uint8)

    with caplog.at_level("INFO", logger="datt.ocr.plate_tracker"):
        st1 = manager.process_vehicle_tracks(frame, vehicle_tracks=tracks(track=124), frame_id=100)[124]
        assert st1.status == "PROVISIONAL"
        assert st1.provisional_plate == "24C14058"
        assert not st1.confirmed_plate

        # Second observation on independent frame (frame 105)
        st2 = manager.process_vehicle_tracks(frame, vehicle_tracks=tracks(track=124), frame_id=105)[124]
        assert st2.status == "CONFIRMED"
        assert st2.confirmed_plate == "24C14058"
        assert st2.confirmed_frame_id == 105
        assert st2.provisional_frame_id == 100
        assert st2.plate_text == "24C14058"

    # Exact 2 observations, no 3rd observation required!
    assert reader.extract_license_plate.call_count == 2
    assert "[PLATE_CONFIRM]" in caplog.text
    assert "first_frame=100" in caplog.text
    assert "confirm_frame=105" in caplog.text


def test_3_same_frame_processed_multiple_times_does_not_confirm():
    """3. Same frame processed multiple times must NOT confirm."""
    reader = Mock()
    reader.extract_license_plate.return_value = None
    manager = VehiclePlateManager(reader)
    frame = np.zeros((200, 200, 3), dtype=np.uint8)

    # Register initial track
    state = manager.process_vehicle_tracks(frame, vehicle_tracks=tracks(track=10), frame_id=1)[10]
    job = _OcrJob(10, 100, candidate().raw_crop, (0, 0, 100, 100), "car", 1, state.generation)

    # Deliver result for frame 100 five times (e.g. duplicates / redundant retries)
    for _ in range(5):
        manager._apply_ocr_result(job, candidate("24C-140.58"))

    # Must only count as 1 observation, status stays PROVISIONAL
    assert state.status == "PROVISIONAL"
    assert state.provisional_plate == "24C14058"
    assert not state.confirmed_plate
    assert [item["frame_id"] for item in state.plate_history] == [100]
    assert state.consensus_count == 1
    assert state.vote_scores == {"24C14058": pytest.approx(.9 * 1.85)}


def test_4_multiple_preprocessing_variants_from_one_frame_count_once():
    """4. Multiple preprocessing variants from one frame must count as one observation only."""
    reader = Mock()
    reader.extract_license_plate.return_value = None
    manager = VehiclePlateManager(reader)
    frame = np.zeros((200, 200, 3), dtype=np.uint8)

    state = manager.process_vehicle_tracks(frame, vehicle_tracks=tracks(track=20), frame_id=1)[20]
    job = _OcrJob(20, 50, candidate().raw_crop, (0, 0, 100, 100), "car", 1, state.generation)

    variants = ["24C-140.58", "24C 14058", "24C14058"]
    for var in variants:
        manager._apply_ocr_result(job, candidate(var))

    assert state.status == "PROVISIONAL"
    assert not state.confirmed_plate
    assert [item["frame_id"] for item in state.plate_history] == [50]
    assert len(state.plate_history) == 1
    assert state.vote_scores == {"24C14058": pytest.approx(.9 * 1.85)}


def test_5_second_observation_conflicts_does_not_confirm(caplog):
    """5. Second observation conflicts: must NOT confirm immediately."""
    reader = Mock()
    reader.extract_license_plate.side_effect = [
        candidate("24C-140.59", confidence=0.75, quality=70),
        candidate("24C-140.58", confidence=0.76, quality=72),
    ]
    manager = VehiclePlateManager(reader, eval_interval=1)
    frame = np.zeros((200, 200, 3), dtype=np.uint8)

    with caplog.at_level("INFO", logger="datt.ocr.plate_tracker"):
        # Frame 100 -> 24C14059 (PROVISIONAL)
        st1 = manager.process_vehicle_tracks(frame, vehicle_tracks=tracks(track=30), frame_id=100)[30]
        assert st1.status == "PROVISIONAL"
        assert st1.provisional_plate == "24C14059"

        # Frame 105 -> 24C14058 (Conflict!)
        st2 = manager.process_vehicle_tracks(frame, vehicle_tracks=tracks(track=30), frame_id=105)[30]
        # Neither is confirmed immediately
        assert st2.status == "CHECKING"
        assert not st2.confirmed_plate

    assert "[PLATE_CONFLICT]" in caplog.text


def test_6_conflict_requires_configured_agreement(caplog):
    """6. Three agreeing observations out of four resolve the conflict.
    frame 100: 24C-140.59
    frame 105: 24C-140.58
    frame 110: 24C-140.58
    frame 115: 24C-140.58
    -> CONFIRMED 24C14058
    """
    reader = Mock()
    reader.extract_license_plate.side_effect = [
        candidate("24C-140.59", confidence=0.70, quality=65),
        candidate("24C-140.58", confidence=0.85, quality=80),
        candidate("24C-140.58", confidence=0.90, quality=85),
        candidate("24C-140.58", confidence=0.90, quality=85),
    ]
    manager = VehiclePlateManager(reader, eval_interval=1)
    frame = np.zeros((200, 200, 3), dtype=np.uint8)

    with caplog.at_level("INFO", logger="datt.ocr.plate_tracker"):
        st1 = manager.process_vehicle_tracks(frame, vehicle_tracks=tracks(track=40), frame_id=100)[40]
        assert st1.status == "PROVISIONAL"
        assert st1.plate_text == "24C14059"

        st2 = manager.process_vehicle_tracks(frame, vehicle_tracks=tracks(track=40), frame_id=105)[40]
        assert st2.status == "CHECKING"
        assert not st2.confirmed_plate

        st3 = manager.process_vehicle_tracks(frame, vehicle_tracks=tracks(track=40), frame_id=110)[40]
        assert st3.status == "CHECKING"  # 2/3 is below the existing 0.75 agreement gate.
        assert not st3.confirmed_plate
        st3 = manager.process_vehicle_tracks(frame, vehicle_tracks=tracks(track=40), frame_id=115)[40]
        assert st3.status == "CONFIRMED"
        assert st3.confirmed_plate == "24C14058"
        assert st3.plate_text == "24C14058"

    assert "[PLATE_CONFIRM]" in caplog.text
    assert "plate=24C14058" in caplog.text


def test_7_better_conflicting_candidate_replaces_provisional(caplog):
    """7. Better conflicting candidate can replace provisional candidate."""
    reader = Mock()
    # Frame 1: Low-confidence/score candidate
    # Frame 2: Much higher confidence/score candidate
    reader.extract_license_plate.side_effect = [
        candidate("24C-140.59", confidence=0.45, quality=40),  # score = 85.0
        candidate("24C-140.58", confidence=0.95, quality=90),  # score = 185.0
    ]
    manager = VehiclePlateManager(reader, eval_interval=1)
    frame = np.zeros((200, 200, 3), dtype=np.uint8)

    with caplog.at_level("INFO", logger="datt.ocr.plate_tracker"):
        st1 = manager.process_vehicle_tracks(frame, vehicle_tracks=tracks(track=50), frame_id=1)[50]
        assert st1.provisional_plate == "24C14059"

        st2 = manager.process_vehicle_tracks(frame, vehicle_tracks=tracks(track=50), frame_id=2)[50]
        assert st2.provisional_plate == "24C14058"
        assert st2.plate_text == "24C14058"
        assert st2.status == "CHECKING"

    assert "action=REPLACE_PROVISIONAL" in caplog.text


def test_8_worse_conflicting_candidate_does_not_replace_provisional(caplog):
    """8. Worse conflicting candidate does NOT replace stronger provisional candidate."""
    reader = Mock()
    # Frame 1: Strong provisional
    # Frame 2: Weak conflicting candidate
    reader.extract_license_plate.side_effect = [
        candidate("24C-140.58", confidence=0.95, quality=90),  # score = 185.0
        candidate("24C-140.59", confidence=0.45, quality=40),  # score = 85.0
    ]
    manager = VehiclePlateManager(reader, eval_interval=1)
    frame = np.zeros((200, 200, 3), dtype=np.uint8)

    with caplog.at_level("INFO", logger="datt.ocr.plate_tracker"):
        st1 = manager.process_vehicle_tracks(frame, vehicle_tracks=tracks(track=60), frame_id=1)[60]
        assert st1.provisional_plate == "24C14058"

        st2 = manager.process_vehicle_tracks(frame, vehicle_tracks=tracks(track=60), frame_id=2)[60]
        # Stronger candidate remains provisional
        assert st2.provisional_plate == "24C14058"
        assert st2.plate_text == "24C14058"
        assert st2.status == "CHECKING"

    assert "action=KEEP_CURRENT" in caplog.text


def test_9_confirmed_plate_remains_sticky():
    """9. Confirmed plate remains sticky after:
    - invalid OCR
    - empty OCR
    - different low-quality OCR
    """
    reader = Mock()
    reader.extract_license_plate.side_effect = [
        # Normal 2-stage confirmation
        candidate("24C-140.58", confidence=0.88),
        candidate("24C140.58", confidence=0.90),
        # Subsequent bad observations
        candidate("INVALID-GARBAGE"),
        None,
        candidate("29A-999.99", confidence=0.35, quality=30),
    ]
    manager = VehiclePlateManager(reader, eval_interval=1, recheck_interval=1)
    frame = np.zeros((200, 200, 3), dtype=np.uint8)

    # Frame 1: PROVISIONAL
    st = manager.process_vehicle_tracks(frame, vehicle_tracks=tracks(track=70), frame_id=1)[70]
    assert st.status == "PROVISIONAL"

    # Frame 2: CONFIRMED
    st = manager.process_vehicle_tracks(frame, vehicle_tracks=tracks(track=70), frame_id=2)[70]
    assert st.status == "CONFIRMED"
    assert st.confirmed_plate == "24C14058"

    # Frame 3: Invalid OCR format (does not downgrade or overwrite)
    st = manager.process_vehicle_tracks(frame, vehicle_tracks=tracks(track=70), frame_id=3)[70]
    assert st.status == "CONFIRMED"
    assert st.confirmed_plate == "24C14058"
    assert st.plate_text == "24C14058"

    # Frame 4: Empty OCR (None)
    st = manager.process_vehicle_tracks(frame, vehicle_tracks=tracks(track=70), frame_id=4)[70]
    assert st.status == "CONFIRMED"
    assert st.confirmed_plate == "24C14058"

    # Frame 5: Different noisy OCR
    st = manager.process_vehicle_tracks(frame, vehicle_tracks=tracks(track=70), frame_id=5)[70]
    assert st.status == "CONFIRMED"
    assert st.confirmed_plate == "24C14058"
    assert st.plate_text == "24C14058"


def test_10_expired_reused_track_id_no_leak(caplog):
    """10. Expired/reused track ID: previous provisional/confirmed state does not leak."""
    reader = Mock()
    reader.extract_license_plate.return_value = candidate("24C-140.58")
    manager = VehiclePlateManager(reader, ttl_frames=50)
    frame = np.zeros((200, 200, 3), dtype=np.uint8)

    # Vehicle 1 on track 80 -> achieves PROVISIONAL
    old = manager.process_vehicle_tracks(frame, vehicle_tracks=tracks(track=80), frame_id=1)[80]
    assert old.status == "PROVISIONAL"
    assert old.provisional_plate == "24C14058"
    old_gen = old.generation
    old_job = _OcrJob(80, 100, candidate().raw_crop, (0, 0, 100, 100), "car", 1, old_gen)

    # Frame 100: Vehicle 1 expired (> 50 frames gap). New vehicle reuses track 80
    with caplog.at_level("INFO", logger="datt.ocr.plate_tracker"):
        # Process track without OCR candidate to see initial clean state
        manager.reader.extract_license_plate.return_value = None
        new = manager.process_vehicle_tracks(frame, vehicle_tracks=tracks(track=80), frame_id=100)[80]

    assert new is not old
    assert new.generation != old_gen
    assert new.status == "SEARCHING"
    assert not new.provisional_plate
    assert not new.confirmed_plate
    assert new.plate_text == ""
    assert "[PLATE_STATE_RESET]" in caplog.text
    assert "reason=ttl_expired" in caplog.text

    # Stale async job from old generation must be rejected
    manager._apply_ocr_result(old_job._replace(frame_id=110), candidate("29A-123.45"))
    assert not new.confirmed_plate
    assert "29A12345" not in new.vote_scores


def test_invalid_ocr_discarded_stays_searching():
    """Invalid OCR candidate format is discarded and vehicle remains SEARCHING."""
    reader = Mock()
    # 24C1405B has letter at end -> invalid VN plate format
    reader.extract_license_plate.return_value = candidate("24C1405B", confidence=0.90)
    manager = VehiclePlateManager(reader, eval_interval=1)
    frame = np.zeros((200, 200, 3), dtype=np.uint8)

    st = manager.process_vehicle_tracks(frame, vehicle_tracks=tracks(track=90), frame_id=1)[90]
    assert st.status == "SEARCHING"
    assert not st.provisional_plate
    assert not st.confirmed_plate
    assert st.plate_text == ""


def test_async_latest_queue_bounded_and_reset_rejects_old_result():
    """Async worker bounded queue and reset cleans up state properly."""
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
