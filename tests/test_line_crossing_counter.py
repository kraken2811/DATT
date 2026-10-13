"""Unit tests for LineCrossingCounter."""

from datetime import datetime, timezone
import numpy as np
import pytest
import supervision as sv

from src.counter.line_crossing import LineCrossingCounter, _segments_intersect


def create_detection(tracker_id: int, xyxy: list[float], class_id: int = 0) -> sv.Detections:
    return sv.Detections(
        xyxy=np.array([xyxy], dtype=np.float32),
        confidence=np.array([0.9], dtype=np.float32),
        class_id=np.array([class_id], dtype=np.int32),
        tracker_id=np.array([tracker_id], dtype=np.int32),
    )


def test_segment_intersection():
    # Perpendicular intersection
    p1 = (0.5, 0.2)
    p2 = (0.5, 0.8)
    q1 = (0.2, 0.5)
    q2 = (0.8, 0.5)
    assert _segments_intersect(p1, p2, q1, q2) is True

    # Non-intersecting parallel segments
    assert _segments_intersect((0.1, 0.1), (0.1, 0.9), (0.5, 0.1), (0.5, 0.9)) is False


def test_single_person_crosses_in():
    counter = LineCrossingCounter(
        camera_id="cam_mall_01",
        line_p1=(0.0, 0.5),
        line_p2=(1.0, 0.5),
        in_direction="normal",
        hysteresis_frames=1,
        min_crossing_distance=0.02,
    )
    frame_shape = (1000, 1000, 3)

    # Frame 1: Person at top (y = 400)
    det1 = create_detection(tracker_id=101, xyxy=[480, 200, 520, 400], class_id=0)
    crossings = counter.update(det1, frame_shape=frame_shape, current_time=1.0)
    assert len(crossings) == 0

    # Frame 2: Person at top still (y = 420)
    det2 = create_detection(tracker_id=101, xyxy=[480, 220, 520, 420], class_id=0)
    crossings = counter.update(det2, frame_shape=frame_shape, current_time=1.1)
    assert len(crossings) == 0

    # Frame 3: Person moves across line to bottom (y = 600)
    det3 = create_detection(tracker_id=101, xyxy=[480, 400, 520, 600], class_id=0)
    crossings = counter.update(det3, frame_shape=frame_shape, current_time=1.2)
    assert len(crossings) == 1
    c = crossings[0]
    assert c.object_type == "person"
    assert c.direction == "in"
    assert c.track_id == 101
    assert "cross:cam_mall_01" in c.idempotency_key
    assert counter.counts["person"]["in"] == 1


def test_person_remains_visible_without_repeated_counting():
    counter = LineCrossingCounter(
        camera_id="cam_mall_01",
        line_p1=(0.0, 0.5),
        line_p2=(1.0, 0.5),
        hysteresis_frames=1,
        cooldown_seconds=3.0,
    )
    frame_shape = (1000, 1000, 3)

    # Step across line
    counter.update(create_detection(102, [480, 200, 520, 400], 0), frame_shape, current_time=1.0)
    counter.update(create_detection(102, [480, 210, 520, 420], 0), frame_shape, current_time=1.1)
    evs1 = counter.update(create_detection(102, [480, 400, 520, 600], 0), frame_shape, current_time=1.2)
    assert len(evs1) == 1

    # Remains on bottom side for next 10 frames
    for t in range(13, 25):
        evs = counter.update(create_detection(102, [480, 410, 520, 610], 0), frame_shape, current_time=t * 0.1)
        assert len(evs) == 0

    assert counter.counts["person"]["in"] == 1


def test_person_changes_direction_after_cooldown():
    counter = LineCrossingCounter(
        camera_id="cam_mall_01",
        line_p1=(0.0, 0.5),
        line_p2=(1.0, 0.5),
        hysteresis_frames=1,
        cooldown_seconds=2.0,
    )
    frame_shape = (1000, 1000, 3)

    # 1. Crosses IN (top to bottom)
    counter.update(create_detection(103, [480, 200, 520, 400], 0), frame_shape, current_time=1.0)
    counter.update(create_detection(103, [480, 210, 520, 420], 0), frame_shape, current_time=1.1)
    evs1 = counter.update(create_detection(103, [480, 400, 520, 600], 0), frame_shape, current_time=1.2)
    assert len(evs1) == 1
    assert evs1[0].direction == "in"

    # 2. Reverses back (bottom to top) after cooldown
    counter.update(create_detection(103, [480, 400, 520, 600], 0), frame_shape, current_time=4.0)
    counter.update(create_detection(103, [480, 390, 520, 580], 0), frame_shape, current_time=4.1)
    evs2 = counter.update(create_detection(103, [480, 200, 520, 400], 0), frame_shape, current_time=4.2)
    assert len(evs2) == 1
    assert evs2[0].direction == "out"

    assert counter.counts["person"]["in"] == 1
    assert counter.counts["person"]["out"] == 1


def test_vehicle_class_breakdown_and_direction():
    counter = LineCrossingCounter(
        camera_id="cam_parking_01",
        line_p1=(0.1, 0.5),
        line_p2=(0.9, 0.5),
        hysteresis_frames=1,
    )
    frame_shape = (1000, 1000, 3)

    # Car (class 2) crosses IN
    counter.update(create_detection(201, [300, 200, 500, 400], class_id=2), frame_shape, current_time=1.0)
    counter.update(create_detection(201, [300, 250, 500, 450], class_id=2), frame_shape, current_time=1.1)
    evs_car = counter.update(create_detection(201, [300, 400, 500, 600], class_id=2), frame_shape, current_time=1.2)
    assert len(evs_car) == 1
    assert evs_car[0].object_type == "vehicle"
    assert evs_car[0].object_class == "car"
    assert evs_car[0].direction == "in"

    # Motorcycle (class 3) crosses OUT
    counter.update(create_detection(301, [600, 500, 700, 700], class_id=3), frame_shape, current_time=2.0)
    counter.update(create_detection(301, [600, 450, 700, 650], class_id=3), frame_shape, current_time=2.1)
    evs_moto = counter.update(create_detection(301, [600, 200, 700, 400], class_id=3), frame_shape, current_time=2.2)
    assert len(evs_moto) == 1
    assert evs_moto[0].object_type == "vehicle"
    assert evs_moto[0].object_class == "motorcycle"
    assert evs_moto[0].direction == "out"

    assert counter.counts["vehicle"]["in"] == 1
    assert counter.counts["vehicle"]["out"] == 1
    assert counter.counts["by_class"]["car"]["in"] == 1
    assert counter.counts["by_class"]["motorcycle"]["out"] == 1


def test_analytics_disabled_emits_no_events():
    counter = LineCrossingCounter(
        camera_id="cam_gate",
        line_p1=(0.0, 0.5),
        line_p2=(1.0, 0.5),
        enabled=False,
    )
    frame_shape = (1000, 1000, 3)

    counter.update(create_detection(401, [480, 200, 520, 400], 0), frame_shape, current_time=1.0)
    evs = counter.update(create_detection(401, [480, 400, 520, 600], 0), frame_shape, current_time=1.1)
    assert len(evs) == 0
    assert counter.counts["person"]["in"] == 0


def test_person_and_vehicle_same_track_id_isolation():
    """Verify that a person and a vehicle sharing the same tracker_id do not collide."""
    counter = LineCrossingCounter(
        camera_id="cam_shared_id",
        line_p1=(0.0, 0.5),
        line_p2=(1.0, 0.5),
        hysteresis_frames=1,
    )
    frame_shape = (1000, 1000, 3)

    # Frame 1: Person track_id=1 and Car track_id=1 both on top side
    det_person_1 = create_detection(tracker_id=1, xyxy=[100, 200, 200, 400], class_id=0)
    det_car_1 = create_detection(tracker_id=1, xyxy=[500, 200, 700, 400], class_id=2)
    counter.update(det_person_1, frame_shape, current_time=1.0)
    counter.update(det_car_1, frame_shape, current_time=1.0)

    # Frame 2: Person track_id=1 and Car track_id=1 approach line
    det_person_2 = create_detection(tracker_id=1, xyxy=[100, 250, 200, 450], class_id=0)
    det_car_2 = create_detection(tracker_id=1, xyxy=[500, 250, 700, 450], class_id=2)
    counter.update(det_person_2, frame_shape, current_time=1.1)
    counter.update(det_car_2, frame_shape, current_time=1.1)

    # Frame 3: Person track_id=1 crosses IN, Car track_id=1 also crosses IN
    det_person_3 = create_detection(tracker_id=1, xyxy=[100, 400, 200, 600], class_id=0)
    det_car_3 = create_detection(tracker_id=1, xyxy=[500, 400, 700, 600], class_id=2)
    evs_p = counter.update(det_person_3, frame_shape, current_time=1.2)
    evs_c = counter.update(det_car_3, frame_shape, current_time=1.2)

    assert len(evs_p) == 1
    assert len(evs_c) == 1
    assert evs_p[0].object_type == "person"
    assert evs_c[0].object_type == "vehicle"
    assert evs_p[0].idempotency_key != evs_c[0].idempotency_key
    assert "person:1" in evs_p[0].idempotency_key
    assert "vehicle:1" in evs_c[0].idempotency_key
    assert counter.counts["person"]["in"] == 1
    assert counter.counts["vehicle"]["in"] == 1

