import cv2
import numpy as np
import onnxruntime as ort
import supervision as sv
from pathlib import Path
import subprocess
import shutil
import imageio_ffmpeg
import yt_dlp
from yt_dlp.utils import DownloadError
from typing import Any, cast
import time
import threading
from dataclasses import dataclass


YOUTUBE_LINK = "https://youtu.be/Cp4RRAEgpeU"

# ===========================================================================
# EXPERIMENT CONFIGURATION: YOLO11s 640 Continuous Baseline
# ===========================================================================

# --- Model & Input Size ---
MODEL_PATH = "models/yolo11s_640.onnx"
IMG_SIZE = 640

# --- Tiling Parameters ---
TILE_MODE = True

# Test A: Single tile (1x1) - Full Frame
TILE_ROWS = 1
TILE_COLS = 1

# Test B: Two tiles (1x2) - Split Frame (Uncomment to enable Test B)
# TILE_ROWS = 1
# TILE_COLS = 2

TILE_OVERLAP = 0.15

# --- Detection & Post-Processing ---
PERSON_CLASS_ID = 0
CONF_THRESHOLD = 0.35
NMS_THRESHOLD = 0.45
MAX_DETECTIONS = 100

# --- Tracking Parameters (ByteTrack) ---
TRACK_ACTIVATION_THRESHOLD = 0.40
LOST_TRACK_BUFFER = 30
MINIMUM_MATCHING_THRESHOLD = 0.80
MINIMUM_CONSECUTIVE_FRAMES = 2
TRACKER_FRAME_RATE = 30.0

# --- Display & Frame Parameters ---
SHOW_RAW_DETECTIONS = False
WIDTH = 1280
HEIGHT = 720

PROVIDERS = [
    ("DmlExecutionProvider", {"device_id": 0}),
    "CPUExecutionProvider"
]


def get_stream_url(url: str) -> str:
    print("Dang lay stream bang yt-dlp...")

    ydl_opts: dict[str, Any] = {
        "format": "bestvideo[height<=720]/best[height<=720]/bestvideo/best",
        "quiet": True,
        "noplaylist": True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:  # type: ignore[arg-type]
            info = ydl.extract_info(url, download=False)
    except DownloadError as exc:
        raise RuntimeError(f"Khong lay duoc stream YouTube: {exc}") from exc

    if not info:
        raise RuntimeError("Khong lay duoc thong tin video tu YouTube")
    stream = info.get("url")
    if not isinstance(stream, str) or not stream:
        raise RuntimeError("Khong lay duoc URL video tu YouTube")
    return cast(str, stream)


def letterbox(image: np.ndarray, size: int = IMG_SIZE) -> tuple[np.ndarray, float, int, int]:
    h, w = image.shape[:2]
    scale = min(size / w, size / h)
    nw = int(w * scale)
    nh = int(h * scale)

    resized = cv2.resize(image, (nw, nh))
    canvas = np.zeros((size, size, 3), dtype=np.uint8)

    dx = (size - nw) // 2
    dy = (size - nh) // 2

    canvas[dy:dy + nh, dx:dx + nw] = resized
    return canvas, scale, dx, dy


class ZoneCounter:
    """Current frame-wide occupancy counter for active ByteTrack person tracks."""

    def __init__(self, *args, **kwargs):
        self.people_count = 0

    def update(self, detections: sv.Detections, frame_shape: tuple[int, ...] | None = None) -> int:
        """Calculate current people occupancy in the full camera frame."""
        if detections.tracker_id is None or len(detections.tracker_id) == 0:
            self.people_count = 0
            return 0

        # Filter for active person tracks (PERSON_CLASS_ID = 0)
        if detections.class_id is not None:
            is_person = detections.class_id == PERSON_CLASS_ID
            person_tracks = detections.tracker_id[is_person]
            person_boxes = detections.xyxy[is_person]
        else:
            person_tracks = detections.tracker_id
            person_boxes = detections.xyxy

        if len(person_tracks) == 0:
            self.people_count = 0
            return 0

        # Adapt automatically to any input resolution [0, 0, frame_w, frame_h]
        if frame_shape is not None:
            h, w = frame_shape[:2]
            cx = (person_boxes[:, 0] + person_boxes[:, 2]) / 2.0
            cy = person_boxes[:, 3]
            in_frame = (cx >= 0) & (cx <= w) & (cy >= 0) & (cy <= h)
            person_tracks = person_tracks[in_frame]

        self.people_count = len(person_tracks)
        return self.people_count


def make_tiles(width: int, height: int) -> list[tuple[int, int, int, int]]:
    if not TILE_MODE:
        return [(0, 0, width, height)]
    if TILE_ROWS < 1 or TILE_COLS < 1 or not 0.0 <= TILE_OVERLAP < 0.9:
        raise ValueError("Invalid tile configuration")
    tile_w = width / TILE_COLS
    tile_h = height / TILE_ROWS
    tiles = []
    for row in range(TILE_ROWS):
        for col in range(TILE_COLS):
            x1 = max(0, int(col * tile_w - tile_w * TILE_OVERLAP / 2))
            y1 = max(0, int(row * tile_h - tile_h * TILE_OVERLAP / 2))
            x2 = min(width, int((col + 1) * tile_w + tile_w * TILE_OVERLAP / 2))
            y2 = min(height, int((row + 1) * tile_h + tile_h * TILE_OVERLAP / 2))
            tiles.append((x1, y1, x2, y2))
    return tiles


def empty_detections() -> sv.Detections:
    return sv.Detections(
        xyxy=np.empty((0, 4), dtype=np.float32),
        confidence=np.empty((0,), dtype=np.float32),
        class_id=np.empty((0,), dtype=int),
    )


def decode_person_boxes(
    output: np.ndarray,
    scale: float,
    dx: int,
    dy: int,
    tx1: int,
    ty1: int,
    frame_w: int,
    frame_h: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Map YOLO xywh (letterboxed tile) to person xyxy in original frame coords."""
    # Ultralytics ONNX layout: (1, 4+C, N) -> (N, 4+C)
    preds = np.asarray(output)
    if preds.ndim == 3:
        preds = preds[0]
    preds = np.ascontiguousarray(preds.T)
    scores = np.max(preds[:, 4:], axis=1)
    class_ids = np.argmax(preds[:, 4:], axis=1)
    mask = (class_ids == PERSON_CLASS_ID) & (scores > CONF_THRESHOLD)
    if not np.any(mask):
        return np.empty((0, 4), dtype=np.float32), np.empty((0,), dtype=np.float32)

    boxes = preds[mask, :4]
    conf = scores[mask].astype(np.float32)
    xc, yc, w, h = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    x1 = tx1 + (xc - w / 2 - dx) / scale
    y1 = ty1 + (yc - h / 2 - dy) / scale
    x2 = tx1 + (xc + w / 2 - dx) / scale
    y2 = ty1 + (yc + h / 2 - dy) / scale
    xyxy = np.stack([x1, y1, x2, y2], axis=1)
    xyxy[:, [0, 2]] = np.clip(xyxy[:, [0, 2]], 0, frame_w)
    xyxy[:, [1, 3]] = np.clip(xyxy[:, [1, 3]], 0, frame_h)
    valid = (xyxy[:, 2] - xyxy[:, 0] >= 4) & (xyxy[:, 3] - xyxy[:, 1] >= 8)
    return xyxy[valid].astype(np.float32), conf[valid]


def keep_top_k(detections: sv.Detections, max_detections: int) -> sv.Detections:
    if max_detections < 1 or len(detections) <= max_detections:
        return detections
    if detections.confidence is None:
        return detections.select(slice(0, max_detections))
    order = np.argsort(detections.confidence)[::-1][:max_detections]
    return detections.select(order)


def detect_tiled(frame: np.ndarray, session: ort.InferenceSession, input_name: str, img_size: int = IMG_SIZE):
    """Person-only tiled YOLO, global NMS, then top-K. Never dump raw tiles into ByteTrack."""
    frame_h, frame_w = frame.shape[:2]
    tiles = make_tiles(frame_w, frame_h)
    tile_boxes: list[np.ndarray] = []
    tile_scores: list[np.ndarray] = []
    yolo_start = time.perf_counter()
    for tx1, ty1, tx2, ty2 in tiles:
        tile = frame[ty1:ty2, tx1:tx2]
        if tile.size == 0:
            continue
        img, scale, dx, dy = letterbox(tile, img_size)
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB).transpose(2, 0, 1)
        tensor = np.ascontiguousarray(img.astype(np.float32) / 255.0)[None, ...]
        output = session.run(None, {input_name: tensor})[0]
        if not isinstance(output, np.ndarray):
            raise TypeError(f"YOLO output must be a NumPy array, got {type(output).__name__}")
        xyxy, conf = decode_person_boxes(
            output, scale, dx, dy, tx1, ty1, frame_w, frame_h
        )
        if len(xyxy):
            tile_boxes.append(xyxy)
            tile_scores.append(conf)
    yolo_ms = (time.perf_counter() - yolo_start) * 1000

    if tile_boxes:
        boxes = np.concatenate(tile_boxes, axis=0)
        scores = np.concatenate(tile_scores, axis=0)
        detections = sv.Detections(
            xyxy=boxes,
            confidence=scores,
            class_id=np.zeros(len(boxes), dtype=int),
        )
    else:
        detections = empty_detections()

    before_nms = len(detections)
    if before_nms:
        # IoS, not IoU: a clipped edge box is often nested in the full-person box
        # from the neighboring tile, so IoU can stay below a typical NMS threshold.
        detections = detections.with_nms(
            threshold=NMS_THRESHOLD,
            class_agnostic=True,
            overlap_metric=sv.OverlapMetric.IOS,
        )
    detections = keep_top_k(detections, MAX_DETECTIONS)
    after_nms = len(detections)
    return detections, len(tiles), yolo_ms, before_nms, after_nms


def read_frame_bytes(stream, size: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        chunk = stream.read(size - len(chunks))
        if not chunk:
            break
        chunks.extend(chunk)
    return bytes(chunks)


@dataclass(frozen=True)
class CapturedFrame:
    sequence: int
    captured_at: float
    capture_latency_ms: float
    frame: np.ndarray


class CameraReader:
    """Continuously reads FFmpeg and keeps only the newest frame."""
    def __init__(self, process, width: int, height: int):
        self.process = process
        self.width = width
        self.height = height
        self.frame_size = width * height * 3
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.latest: CapturedFrame | None = None
        self.stream_fps = 0.0
        self.error: Exception | None = None
        self.finished = False
        self._thread = threading.Thread(target=self._read_loop, name="ffmpeg-capture", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def _read_loop(self) -> None:
        count = 0
        window_start = time.perf_counter()
        sequence = 0
        try:
            if self.process.stdout is None:
                raise RuntimeError("FFmpeg stdout is unavailable")
            while not self.stop_event.is_set():
                read_start = time.perf_counter()
                raw = read_frame_bytes(self.process.stdout, self.frame_size)
                read_end = time.perf_counter()
                if len(raw) != self.frame_size:
                    break
                frame = np.frombuffer(raw, np.uint8).reshape(
                    self.height, self.width, 3
                ).copy()
                sequence += 1
                count += 1
                now = time.perf_counter()
                with self.lock:
                    self.latest = CapturedFrame(
                        sequence=sequence,
                        captured_at=now,
                        capture_latency_ms=(read_end - read_start) * 1000,
                        frame=frame,
                    )
                elapsed = now - window_start
                if elapsed >= 1.0:
                    with self.lock:
                        self.stream_fps = count / elapsed
                    count = 0
                    window_start = now
        except Exception as exc:
            with self.lock:
                self.error = exc
        finally:
            with self.lock:
                self.finished = True

    def latest_frame(self) -> tuple[CapturedFrame | None, float]:
        with self.lock:
            if self.error is not None:
                raise RuntimeError("Camera capture failed") from self.error
            return self.latest, self.stream_fps

    def close(self) -> None:
        self.stop_event.set()
        if self.process.poll() is None:
            self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)
        self._thread.join(timeout=5)
        if self.process.stdout is not None:
            self.process.stdout.close()


def main():
    model_path = Path(MODEL_PATH)
    if not model_path.is_absolute():
        model_path = Path(__file__).resolve().parent / model_path

    if not model_path.exists():
        raise FileNotFoundError(f"Khong tim thay model: {model_path}")

    session = ort.InferenceSession(str(model_path), providers=PROVIDERS)

    model_inputs = session.get_inputs()
    input_name = model_inputs[0].name
    input_shape = model_inputs[0].shape

    print("==================================================")
    print("YOLO11s 640 Continuous Baseline Test")
    print("==================================================")
    print(f"Model Path : {model_path.name}")
    print(f"Input Name : {input_name}")
    print(f"Input Shape: {input_shape}")
    print(f"IMG_SIZE   : {IMG_SIZE}")
    print(f"Tiling     : {TILE_ROWS}x{TILE_COLS} (Overlap: {TILE_OVERLAP:.2f})")
    print(f"Providers  : {session.get_providers()}")
    print("==================================================")

    # Validate ONNX input dimensions against configured IMG_SIZE
    if input_name != "images":
        print(f"[WARNING] Expected input name 'images', got '{input_name}'")

    if len(input_shape) == 4:
        expected_b, expected_c, expected_h, expected_w = input_shape
        if (
            isinstance(expected_h, int)
            and isinstance(expected_w, int)
            and expected_h > 0
            and expected_w > 0
        ):
            if expected_h != IMG_SIZE or expected_w != IMG_SIZE:
                raise ValueError(
                    f"\n[ERROR] The configured IMG_SIZE does not match the ONNX model input size.\n"
                    f"Model expects: {expected_h}x{expected_w}\n"
                    f"Configured IMG_SIZE: {IMG_SIZE}\n"
                    f"Please switch IMG_SIZE={expected_h} or export a {IMG_SIZE} ONNX model."
                )

    zone_counter = ZoneCounter()
    tracker = sv.ByteTrack(
        track_activation_threshold=TRACK_ACTIVATION_THRESHOLD,
        lost_track_buffer=LOST_TRACK_BUFFER,
        minimum_matching_threshold=MINIMUM_MATCHING_THRESHOLD,
        frame_rate=TRACKER_FRAME_RATE,
        minimum_consecutive_frames=MINIMUM_CONSECUTIVE_FRAMES,
    )

    box_annotator = sv.BoxAnnotator(thickness=2)
    label_annotator = sv.LabelAnnotator(text_scale=0.5, text_thickness=1)

    class_names = {
        PERSON_CLASS_ID: "Person",
    }

    show_raw = SHOW_RAW_DETECTIONS
    print("Hotkeys: D = toggle raw detections / tracking; Q = quit")

    ffmpeg_path = shutil.which("ffmpeg") or imageio_ffmpeg.get_ffmpeg_exe()
    stream_url = get_stream_url(YOUTUBE_LINK)
    print("Stream URL acquired successfully.")

    ffmpeg_command = [
        ffmpeg_path,
        "-nostdin",
        "-fflags", "nobuffer",
        "-flags", "low_delay",
        "-probesize", "32",
        "-analyzeduration", "0",
        "-loglevel", "error",
        "-i", stream_url,
        "-an",
        "-vsync", "0",
        "-f", "rawvideo",
        "-pix_fmt", "bgr24",
        "-vf", f"scale={WIDTH}:{HEIGHT}",
        "-",
    ]
    ffmpeg = subprocess.Popen(ffmpeg_command, stdout=subprocess.PIPE)
    camera = CameraReader(ffmpeg, WIDTH, HEIGHT)

    try:
        camera.start()
        frame_count = 0
        metrics_start = time.perf_counter()
        processing_fps = 0.0
        last_sequence = 0
        last_capture_latency_ms = 0.0
        last_frame_age_ms = 0.0

        while True:
            captured, stream_fps = camera.latest_frame()
            if captured is None or captured.sequence == last_sequence:
                if camera.finished:
                    print("Stream ket thuc hoac frame khong day du")
                    break
                key = cv2.waitKey(1) & 0xFF
                if key == ord("q"):
                    break
                time.sleep(0.001)
                continue

            last_sequence = captured.sequence
            frame = captured.frame.copy()
            last_capture_latency_ms = captured.capture_latency_ms
            last_frame_age_ms = (time.perf_counter() - captured.captured_at) * 1000

            # Run YOLO detection & NMS/filtering on every newest frame.
            detection_start = time.perf_counter()
            raw_detections, tile_count, yolo_ms, before_nms, after_nms = detect_tiled(
                frame, session, input_name, IMG_SIZE
            )
            detection_ms = (time.perf_counter() - detection_start) * 1000

            # 3. Update ByteTrack
            tracked_detections = tracker.update_with_detections(raw_detections)

            # 4. Update full-frame people occupancy counter
            people_in_view = zone_counter.update(tracked_detections, frame.shape)

            # 5. Display result & Annotate
            display_detections: sv.Detections = (
                raw_detections if show_raw else tracked_detections
            )

            labels = []
            if (
                display_detections.class_id is not None
                and display_detections.confidence is not None
            ):
                for i, cls in enumerate(display_detections.class_id):
                    score = float(display_detections.confidence[i])
                    if show_raw:
                        identity = "YOLO"
                    elif display_detections.tracker_id is not None:
                        identity = f"#{display_detections.tracker_id[i]}"
                    else:
                        identity = "pending"
                    labels.append(f"{class_names[int(cls)]} {identity} {score:.2f}")

            frame_count += 1
            total_elapsed = time.perf_counter() - metrics_start
            if total_elapsed >= 1.0:
                processing_fps = frame_count / total_elapsed
                print(
                    f"Stream FPS: {stream_fps:.1f} | Processing FPS: {processing_fps:.1f} | "
                    f"Frame age: {last_frame_age_ms:.0f} ms | Capture: {last_capture_latency_ms:.0f} ms | "
                    f"YOLO latency: {yolo_ms:.0f} ms | "
                    f"Detection latency: {detection_ms:.0f} ms | "
                    f"Detections: {len(raw_detections)} | Tracks: {len(tracked_detections)} | "
                    f"People in view: {people_in_view}"
                )
                frame_count = 0
                metrics_start = time.perf_counter()

            frame = box_annotator.annotate(scene=frame, detections=display_detections)  # type: ignore
            frame = label_annotator.annotate(scene=frame, detections=display_detections, labels=labels)  # type: ignore

            # Simplified HUD
            debug_lines = [
                f"Model: {model_path.name}",
                f"Input: {IMG_SIZE}",
                f"Tiles: {tile_count}",
                "",
                f"Detections: {len(raw_detections)}",
                f"Tracks: {len(tracked_detections)}",
                "",
                f"YOLO latency: {yolo_ms:.0f} ms",
                f"Detection latency: {detection_ms:.0f} ms",
                "",
                f"Stream FPS: {stream_fps:.1f}",
                f"Processing FPS: {processing_fps:.1f}",
                f"Frame age: {last_frame_age_ms:.0f} ms",
                f"Capture latency: {last_capture_latency_ms:.0f} ms",
                "",
                f"People in view: {people_in_view}",
            ]

            y = 26
            for line in debug_lines:
                if line == "":
                    y += 6
                    continue
                cv2.putText(
                    frame,
                    line,
                    (16, y),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.55,
                    (0, 255, 0),
                    2,
                )
                y += 22

            cv2.imshow("YOLO11s FFmpeg ByteTrack", frame)

            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break
            if key == ord("d"):
                show_raw = not show_raw

    finally:
        if ffmpeg.poll() is None:
            ffmpeg.terminate()
        try:
            ffmpeg.wait(timeout=5)
        except subprocess.TimeoutExpired:
            ffmpeg.kill()
            ffmpeg.wait()
        if ffmpeg.stdout is not None:
            ffmpeg.stdout.close()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
