"""Verification script: Render vehicle tracking overlay on a real runtime video frame.

Verifies:
1. Exact label string matches:
   CAR-46 | 29K-104.25
   MOTORCYCLE-12 | 24X1-124.42
   TRUCK-8 | 29K-404.35
2. Unconfirmed / CHECKING / SEARCHING vehicles keep current tracking format without plate text.
3. Renders onto an actual runtime frame from:
   data/uploads/Video xe máy - xe hơi chạy trên đường [9_nwSrwpKYA].mp4
4. Saves annotated verification image to scratch/real_runtime_frame_overlay_verify.jpg.
"""

from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import cv2
import numpy as np

import config
from src.ocr.plate_tracker import PlateTrackState
from src.ui.frame_renderer import (
    format_plate_display,
    get_vehicle_track_label,
    render_frame,
)


class MockDetections:
    def __init__(self, xyxy, tracker_id=None, confidence=None, class_id=None):
        self.xyxy = np.array(xyxy, dtype=np.float32)
        self.tracker_id = np.array(tracker_id) if tracker_id is not None else None
        self.confidence = np.array(confidence) if confidence is not None else None
        self.class_id = np.array(class_id) if class_id is not None else None

    def __len__(self):
        return len(self.xyxy)


def find_video_path(requested: str | None = None) -> str:
    if requested and Path(requested).is_file():
        return str(Path(requested).resolve())
    search_dirs = [Path("data/uploads"), Path(r"C:\Users\User\Downloads"), Path(".")]
    for s_dir in search_dirs:
        if s_dir.exists():
            matches = list(s_dir.glob("*9_nwSrwpKYA*.mp4"))
            if matches:
                return str(matches[0].resolve())
    raise FileNotFoundError("Could not find video file '*9_nwSrwpKYA*.mp4'")


def main() -> None:
    video_path = Path(find_video_path())
    assert video_path.exists(), f"Video file not found at {video_path}"

    cap = cv2.VideoCapture(str(video_path))
    assert cap.isOpened(), "Could not open real runtime video"

    # Read frame 40 from real video
    for _ in range(40):
        ret, frame = cap.read()
        if not ret:
            break
    cap.release()

    assert frame is not None and frame.size > 0, "Failed to read real runtime frame"
    h, w = frame.shape[:2]
    print(f"[VERIFY] Loaded real runtime frame: {w}x{h}")

    # Set up 3 real-world vehicle tracks in view:
    # 1. Car track 46: CONFIRMED plate 29K10425 -> must render 'CAR-46 | 29K-104.25'
    # 2. Motorcycle track 12: CONFIRMED plate 24X112442 -> must render 'MOTORCYCLE-12 | 24X1-124.42'
    # 3. Truck track 8: CONFIRMED plate 29K40435 -> must render 'TRUCK-8 | 29K-404.35'
    # 4. Car track 55: CHECKING state (unconfirmed) -> must NOT render plate, keep 'CAR | C-55 | 0.91'
    # 5. Motorcycle track 60: SEARCHING state -> must NOT render plate, keep 'MOTORCYCLE | C-60 | 0.87'

    boxes = [
        [150.0, 300.0, 420.0, 560.0],  # Car 46
        [480.0, 320.0, 600.0, 520.0],  # Motorcycle 12
        [680.0, 180.0, 950.0, 500.0],  # Truck 8
        [50.0, 400.0, 220.0, 600.0],   # Car 55 (checking)
        [1020.0, 350.0, 1140.0, 530.0], # Motorcycle 60 (searching)
    ]
    tracker_ids = [46, 12, 8, 55, 60]
    confidences = [0.94, 0.90, 0.95, 0.91, 0.87]
    class_ids = [
        config.CAR_CLASS_ID,
        config.MOTORCYCLE_CLASS_ID,
        config.TRUCK_CLASS_ID,
        config.CAR_CLASS_ID,
        config.MOTORCYCLE_CLASS_ID,
    ]

    car_tracks = MockDetections(
        xyxy=boxes,
        tracker_id=tracker_ids,
        confidence=confidences,
        class_id=class_ids,
    )

    plate_results = {
        # Confirmed car plate
        46: PlateTrackState(
            track_id=46,
            vehicle_class="car",
            plate_text="29K10425",
            confidence=0.91,
            plate_bbox_native=(240, 480, 330, 515),
            status="RECOGNIZED",
        ),
        # Confirmed motorcycle plate
        12: PlateTrackState(
            track_id=12,
            vehicle_class="motorcycle",
            plate_text="24X112442",
            confidence=0.88,
            plate_bbox_native=(520, 460, 565, 490),
            status="RECOGNIZED",
        ),
        # Confirmed truck plate
        8: PlateTrackState(
            track_id=8,
            vehicle_class="truck",
            plate_text="29K40435",
            confidence=0.93,
            plate_bbox_native=(780, 420, 850, 455),
            status="RECOGNIZED",
        ),
        # Unconfirmed CHECKING plate - must NOT show plate text
        55: PlateTrackState(
            track_id=55,
            vehicle_class="car",
            candidate_text="30H99999",
            status="CHECKING",
        ),
        # SEARCHING plate
        60: PlateTrackState(
            track_id=60,
            vehicle_class="motorcycle",
            status="SEARCHING",
        ),
    }

    # Verify individual label strings
    lbl_46, is_conf_46 = get_vehicle_track_label("CAR", 46, 0.94, "29K10425", "RECOGNIZED")
    lbl_12, is_conf_12 = get_vehicle_track_label("MOTORCYCLE", 12, 0.90, "24X112442", "RECOGNIZED")
    lbl_8, is_conf_8 = get_vehicle_track_label("TRUCK", 8, 0.95, "29K40435", "RECOGNIZED")
    lbl_55, is_conf_55 = get_vehicle_track_label("CAR", 55, 0.91, "", "CHECKING")
    lbl_60, is_conf_60 = get_vehicle_track_label("MOTORCYCLE", 60, 0.87, "", "SEARCHING")

    print(f"[LABEL CHECK 1] Car 46        : {lbl_46} (confirmed={is_conf_46})")
    print(f"[LABEL CHECK 2] Motorcycle 12 : {lbl_12} (confirmed={is_conf_12})")
    print(f"[LABEL CHECK 3] Truck 8       : {lbl_8} (confirmed={is_conf_8})")
    print(f"[LABEL CHECK 4] Checking 55   : {lbl_55} (confirmed={is_conf_55})")
    print(f"[LABEL CHECK 5] Searching 60  : {lbl_60} (confirmed={is_conf_60})")

    assert lbl_46 == "CAR-46 | 29K-104.25", f"Mismatch: {lbl_46}"
    assert lbl_12 == "MOTORCYCLE-12 | 24X1-124.42", f"Mismatch: {lbl_12}"
    assert lbl_8 == "TRUCK-8 | 29K-404.35", f"Mismatch: {lbl_8}"
    assert lbl_55 == "CAR | C-55 | 0.91", f"Mismatch: {lbl_55}"
    assert lbl_60 == "MOTORCYCLE | C-60 | 0.87", f"Mismatch: {lbl_60}"
    assert is_conf_46 is True
    assert is_conf_12 is True
    assert is_conf_8 is True
    assert is_conf_55 is False
    assert is_conf_60 is False

    # Render complete frame
    annotated = render_frame(
        frame=frame,
        tracks=None,
        people_count=0,
        car_tracks=car_tracks,
        car_count=5,
        car_count_label="VEHICLES IN VIEW",
        plate_results=plate_results,
    )

    out_dir = Path("scratch")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "real_runtime_frame_overlay_verify.jpg"
    cv2.imwrite(str(out_path), annotated)
    assert out_path.exists() and out_path.stat().st_size > 0, "Failed to save annotated frame"

    print(f"[SUCCESS] Real runtime frame annotated and saved to: {out_path.resolve()}")
    print("[SUCCESS] Verified format: CAR-46 | 29K-104.25")


if __name__ == "__main__":
    main()
