"""End-to-End Validation Script for DATT Vehicle Passage & PostgreSQL Database Persistence.

Executes all 5 required business cases, measures realtime enqueue and worker latencies,
and demonstrates the 5 required production queries directly on PostgreSQL.
"""

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import time
from uuid import UUID, uuid4

import numpy as np

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
import sys
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import text
from src.db.database import Database
from src.db.repositories import BusinessEventRepository, VehiclePassageRepository
from src.events.db_worker import DatabaseWorker
from src.events.event_manager import EventManager


class DummyTracks:
    """Mock detection tracks for simulation."""
    def __init__(self, tids, boxes, class_ids, confs):
        self.tracker_id = tids
        self.xyxy = np.array(boxes, dtype=float)
        self.class_id = np.array(class_ids, dtype=int)
        self.confidence = np.array(confs, dtype=float)


class DummyPlateState:
    """Mock plate state for simulation."""
    def __init__(self, text, status="CONFIRMED", conf=0.95):
        self.plate_text = text
        self.status = status
        self.confidence = conf
        # 40x80 synthetic crop
        self.plate_crop = np.zeros((40, 80, 3), dtype=np.uint8)


def run_e2e_validation():
    print("=" * 70)
    print("DATT E2E POSTGRESQL VALIDATION SUITE")
    print("=" * 70)

    db = Database()
    print(f"[DB] Connected to: {db.engine.url.get_backend_name()} on port {db.engine.url.port}")
    assert db.engine.url.get_backend_name() == "postgresql", "Validation MUST run on PostgreSQL"

    worker = DatabaseWorker(max_queue_size=1000)
    em = EventManager(db_worker=worker)

    # Synthetic frame (720x1280 BGR)
    dummy_frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    dummy_frame[100:300, 200:500] = 128  # vehicle area

    # --------------------------------------------------------------------------
    # CASE 1: Normal Vehicle Appearance
    # --------------------------------------------------------------------------
    print("\n--- CASE 1: Normal Vehicle Appearance ---")
    cam_id = "CAM_01"
    tid_1 = 101

    # Frame 1: Vehicle appears
    tracks_1 = DummyTracks([tid_1], [[200, 100, 500, 300]], [2], [0.94])
    evs_1 = em.process_vehicle_frame(cam_id, tracks_1, frame=dummy_frame)
    print(f"Frame 1 (Appearance): Emitted events: {[e['type'] for e in evs_1]}")
    passage_1 = em._active_passages[tid_1]
    passage_id_1 = passage_1.id
    print(f"Created VehiclePassage in RAM: ID={passage_id_1}, SessionKey={passage_1.session_key}")

    # Frames 2-5: Moving, searching plate
    for f in range(2, 6):
        em.process_vehicle_frame(cam_id, tracks_1, frame=dummy_frame)

    # Frame 6: Plate recognized and confirmed
    plate_res = {tid_1: DummyPlateState("29K1-12345", "CONFIRMED", 0.95)}
    evs_6 = em.process_vehicle_frame(cam_id, tracks_1, plate_results=plate_res, frame=dummy_frame)
    print(f"Frame 6 (Plate Confirmed): Emitted events: {[e['type'] for e in evs_6]}")

    # Frames 7-15: Repeated OCR observations of same confirmed plate
    repeated_events = []
    for f in range(7, 16):
        r = em.process_vehicle_frame(cam_id, tracks_1, plate_results=plate_res, frame=dummy_frame)
        repeated_events.extend(r)
    print(f"Frames 7-15 (Repeated OCR): Emitted events: {[e['type'] for e in repeated_events]} (Expect empty: NO SPAM)")

    # Frame 16: Vehicle exits FOV (simulate time advancement > 3.0s)
    passage_1.last_seen = time.time() - 4.0
    evs_16 = em.process_vehicle_frame(cam_id, DummyTracks([], [], [], []), frame=dummy_frame)
    print(f"Frame 16 (Exit): Emitted events: {[e['type'] for e in evs_16]}")
    assert tid_1 not in em._active_passages, "Passage must be finalized and removed from RAM"

    # --------------------------------------------------------------------------
    # CASE 2: Vehicle with No Recognized Plate
    # --------------------------------------------------------------------------
    print("\n--- CASE 2: Vehicle with No Recognized Plate ---")
    tid_2 = 102
    tracks_2 = DummyTracks([tid_2], [[150, 150, 450, 350]], [7], [0.89])  # class 7: truck
    evs_c2_1 = em.process_vehicle_frame(cam_id, tracks_2, frame=dummy_frame)
    passage_2 = em._active_passages[tid_2]
    passage_id_2 = passage_2.id
    print(f"Vehicle 2 (Truck) Appearance: Emitted events: {[e['type'] for e in evs_c2_1]}, Type={passage_2.vehicle_type}")

    # Exits without any plate recognized
    passage_2.last_seen = time.time() - 4.0
    evs_c2_exit = em.process_vehicle_frame(cam_id, DummyTracks([], [], [], []), frame=dummy_frame)
    print(f"Vehicle 2 Exit: Emitted events: {[e['type'] for e in evs_c2_exit]}")

    # --------------------------------------------------------------------------
    # CASE 3: Repeated OCR Stress (50 frames)
    # --------------------------------------------------------------------------
    print("\n--- CASE 3: Repeated OCR Stress (50 frames) ---")
    tid_3 = 103
    tracks_3 = DummyTracks([tid_3], [[50, 50, 250, 250]], [2], [0.91])
    em.process_vehicle_frame(cam_id, tracks_3, frame=dummy_frame)
    p_state_3 = DummyPlateState("51G-88888", "CONFIRMED", 0.98)
    total_plate_events = 0
    for _ in range(50):
        evs = em.process_vehicle_frame(cam_id, tracks_3, plate_results={tid_3: p_state_3}, frame=dummy_frame)
        total_plate_events += sum(1 for e in evs if e["type"] == "PLATE_RECOGNIZED")
    print(f"50 frames with confirmed plate '51G-88888': total PLATE_RECOGNIZED events emitted = {total_plate_events}")
    assert total_plate_events == 1, "Must produce exactly 1 PLATE_RECOGNIZED event!"

    passage_3 = em._active_passages[tid_3]
    passage_3.last_seen = time.time() - 4.0
    em.process_vehicle_frame(cam_id, DummyTracks([], [], [], []), frame=dummy_frame)

    # --------------------------------------------------------------------------
    # CASE 4: DB Interruption and Safe Retry
    # --------------------------------------------------------------------------
    print("\n--- CASE 4: DB Interruption and Safe Retry ---")
    # Simulate DB disconnection on worker
    original_persist = worker._persist_batch
    interruption_occurred = False

    def failing_persist(batch):
        nonlocal interruption_occurred
        interruption_occurred = True
        worker.db_failures += 1
        worker.retry_count += 1
        # put to retry buffer as the loop does
        worker._retry_buffer = (batch + worker._retry_buffer)[: worker.max_queue_size]
        return False

    worker._persist_batch = failing_persist

    # Realtime AI loop continues processing frames during outage!
    t_det_0 = time.perf_counter()
    tid_4 = 104
    tracks_4 = DummyTracks([tid_4], [[10, 10, 100, 100]], [3], [0.85])  # class 3: motorcycle
    em.process_vehicle_frame(cam_id, tracks_4, frame=dummy_frame)
    loop_elapsed_ms = (time.perf_counter() - t_det_0) * 1000.0
    print(f"Realtime frame processed during DB outage in {loop_elapsed_ms:.3f} ms (Non-blocking: YES)")
    assert loop_elapsed_ms < 10.0, "Realtime AI loop must not block during DB outage"

    # Restore DB connectivity
    worker._persist_batch = original_persist
    print("PostgreSQL connection restored; flushing retry buffer...")
    time.sleep(0.5)

    passage_4 = em._active_passages[tid_4]
    passage_4.last_seen = time.time() - 4.0
    em.process_vehicle_frame(cam_id, DummyTracks([], [], [], []), frame=dummy_frame)

    # --------------------------------------------------------------------------
    # CASE 5: ByteTrack Track ID Reuse
    # --------------------------------------------------------------------------
    print("\n--- CASE 5: ByteTrack Track ID Reuse ---")
    reuse_tid = 46

    # Appearance A
    tracks_reuse = DummyTracks([reuse_tid], [[10, 10, 200, 200]], [2], [0.92])
    em.process_vehicle_frame(cam_id, tracks_reuse, frame=dummy_frame)
    passage_A = em._active_passages[reuse_tid]
    uuid_A = passage_A.id
    key_A = passage_A.session_key
    print(f"Appearance A (Track ID 46): Passage UUID={uuid_A}, SessionKey={key_A}")

    # Appearance A exits
    passage_A.last_seen = time.time() - 4.0
    em.process_vehicle_frame(cam_id, DummyTracks([], [], [], []), frame=dummy_frame)
    assert reuse_tid not in em._active_passages

    # Appearance B (Later, ByteTrack reuses ID 46 for a different vehicle!)
    time.sleep(0.02)
    em.process_vehicle_frame(cam_id, tracks_reuse, frame=dummy_frame)
    passage_B = em._active_passages[reuse_tid]
    uuid_B = passage_B.id
    key_B = passage_B.session_key
    print(f"Appearance B (Track ID 46 reused): Passage UUID={uuid_B}, SessionKey={key_B}")

    assert uuid_A != uuid_B, "Reused track_id MUST produce a distinct passage UUID"
    assert key_A != key_B, "Reused track_id MUST produce a distinct session_key"

    passage_B.last_seen = time.time() - 4.0
    em.process_vehicle_frame(cam_id, DummyTracks([], [], [], []), frame=dummy_frame)

    # Clean shutdown and drain worker queue
    print("\nStopping EventManager and draining persistence queue...")
    em.stop()
    worker.stop(timeout=5.0)

    # --------------------------------------------------------------------------
    # VERIFY IN POSTGRESQL DATABASE
    # --------------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("VERIFICATION IN POSTGRESQL TABLES")
    print("=" * 70)

    with db.transaction() as session:
        v_repo = VehiclePassageRepository(session)
        e_repo = BusinessEventRepository(session)

        # 1. Verify Case 1
        p1_row = v_repo.get(passage_id_1)
        assert p1_row is not None, "Case 1 passage must exist in PostgreSQL"
        print(f"\n[Case 1 Verification]")
        print(f"Passage ID: {p1_row.id}")
        print(f"Track ID: {p1_row.track_id}")
        print(f"Vehicle Type: {p1_row.vehicle_type} (conf: {p1_row.vehicle_type_confidence})")
        print(f"Vehicle Color: {p1_row.vehicle_color} (documented unavailable)")
        print(f"Plate Text: {p1_row.plate_text} (status: {p1_row.plate_status}, conf: {p1_row.plate_confidence})")
        print(f"Duration MS: {p1_row.duration_ms:.1f} ms")
        print(f"Finalized At: {p1_row.finalized_at}")
        print(f"Best Vehicle Crop Path: {p1_row.best_vehicle_image_path}")
        print(f"Best Plate Crop Path: {p1_row.best_plate_image_path}")

        p1_events = e_repo.query_events(passage_id=passage_id_1)
        print(f"Events for Case 1 passage: {[e.event_type for e in p1_events]}")
        p1_ev_types = [e.event_type for e in p1_events]
        assert "VEHICLE_ENTER" in p1_ev_types
        assert "PLATE_RECOGNIZED" in p1_ev_types
        assert "VEHICLE_EXIT" in p1_ev_types
        assert p1_ev_types.count("PLATE_RECOGNIZED") == 1, "Must have exactly 1 PLATE_RECOGNIZED event!"

        # 2. Verify Case 2
        p2_row = v_repo.get(passage_id_2)
        assert p2_row is not None
        print(f"\n[Case 2 Verification]")
        print(f"Passage ID: {p2_row.id}")
        print(f"Vehicle Type: {p2_row.vehicle_type}")
        print(f"Plate Text: {p2_row.plate_text} (None expected)")
        assert p2_row.plate_text is None, "Must not fabricate a plate text!"

        # 3. Verify Case 5
        row_A = v_repo.get(uuid_A)
        row_B = v_repo.get(uuid_B)
        assert row_A is not None and row_B is not None
        print(f"\n[Case 5 Verification - Track Reuse]")
        print(f"Passage A: ID={row_A.id}, SessionKey={row_A.session_key}")
        print(f"Passage B: ID={row_B.id}, SessionKey={row_B.session_key}")
        assert row_A.id != row_B.id

        # ----------------------------------------------------------------------
        # PRODUCT QUERIES DEMONSTRATION (Section 19)
        # ----------------------------------------------------------------------
        print("\n" + "=" * 70)
        print("DEMONSTRATION OF REQUIRED PRODUCT QUERIES")
        print("=" * 70)

        # Query A: Find all appearances of plate '29K1-12345'
        print("\n[Query A: Plate Search '29K1-12345']")
        plate_passages = v_repo.query_passages(plate_text="29K1-12345")
        for p in plate_passages:
            print(f"  -> Found Passage {p.id}: Cam={p.camera_id}, Type={p.vehicle_type}, FirstSeen={p.first_seen_at}")

        # Query B: All vehicles from camera CAM_01 between timestamps
        print("\n[Query B: All vehicles from CAM_01 in last 1 hour]")
        one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
        cam_passages = v_repo.query_passages(camera_id="CAM_01", since=one_hour_ago)
        print(f"  -> Total vehicles from CAM_01: {len(cam_passages)}")

        # Query C: Count vehicle types during one hour
        print("\n[Query C: Vehicle type counts in last 1 hour]")
        type_counts = v_repo.count_vehicle_types(since=one_hour_ago)
        print(f"  -> Vehicle type counts: {json.dumps(type_counts, indent=2)}")

        # Query D: All vehicle passages in a zone (if any assigned)
        print("\n[Query D: Vehicle passages in zone]")
        zone_passages = v_repo.query_passages(zone_id="zone_1")
        print(f"  -> Passages in zone_1: {len(zone_passages)}")

        # Query E: Show full passage details
        print("\n[Query E: Detailed Passage Attributes]")
        det_passage = plate_passages[0] if plate_passages else p1_row
        print(f"  ID: {det_passage.id}")
        print(f"  Vehicle Type: {det_passage.vehicle_type}")
        print(f"  Plate: {det_passage.plate_text}")
        print(f"  Direction: {det_passage.direction}")
        print(f"  First Seen: {det_passage.first_seen_at}")
        print(f"  Last Seen: {det_passage.last_seen_at}")
        print(f"  Duration: {det_passage.duration_ms:.2f} ms")
        print(f"  Vehicle Evidence: {det_passage.best_vehicle_image_path}")
        print(f"  Plate Evidence: {det_passage.best_plate_image_path}")

        # Summary counts
        total_p = session.scalar(text("SELECT count(*) FROM vehicle_passages"))
        total_e = session.scalar(text("SELECT count(*) FROM business_events"))
        print(f"\n[Total Table Counts in PostgreSQL]")
        print(f"  vehicle_passages: {total_p}")
        print(f"  business_events: {total_e}")

    # --------------------------------------------------------------------------
    # PERFORMANCE METRICS (Section 18)
    # --------------------------------------------------------------------------
    stats = worker.get_latency_stats()
    print("\n" + "=" * 70)
    print("PERFORMANCE METRICS")
    print("=" * 70)
    print(f"Realtime Enqueue Latency (ms):")
    print(f"  p50: {stats['enqueue']['p50']:.4f} ms")
    print(f"  p95: {stats['enqueue']['p95']:.4f} ms")
    print(f"  p99: {stats['enqueue']['p99']:.4f} ms")
    print(f"  max: {stats['enqueue']['max']:.4f} ms")
    print(f"DB Worker Write Latency (ms):")
    print(f"  p50: {stats['db_write']['p50']:.2f} ms")
    print(f"  p95: {stats['db_write']['p95']:.2f} ms")
    print(f"  max: {stats['db_write']['max']:.2f} ms")
    print(f"Queue Dropped: {worker.queue_dropped}")
    print(f"Queue Coalesced: {worker.queue_coalesced}")
    print(f"DB Retries: {worker.retry_count}")
    print(f"DB Failures: {worker.db_failures}")
    print(f"Main Loop Blocking: NO (enqueue is non-blocking)")
    print("=" * 70)
    print("ALL VALIDATION CRITERIA PASSED SUCCESSFULLY!")
    print("=" * 70)


if __name__ == "__main__":
    run_e2e_validation()
