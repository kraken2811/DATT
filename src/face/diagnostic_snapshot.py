"""Opt-in, one-shot export only. Never initializes or runs a model."""

import hashlib
import inspect
import json
import logging
import os
from pathlib import Path
import time

import cv2
import numpy as np

DIRECTORY = Path(__file__).resolve().parents[2] / "scratch" / "face_diag"


def export_if_requested(frame, tracks, frame_id, native_frame, embedder):
    request = DIRECTORY / "request.json"
    if not request.is_file():
        return
    claimed = None
    try:
        options = json.loads(request.read_text(encoding="utf-8"))
        boxes = getattr(tracks, "xyxy", None)
        ids = getattr(tracks, "tracker_id", None)
        if boxes is None or ids is None or not len(boxes):
            return
        native = native_frame if native_frame is not None else frame
        h, w = native.shape[:2]
        fh, fw = frame.shape[:2]
        choices = []
        for box, tid in zip(boxes, ids):
            if tid is None or (options.get("track_id") is not None
                               and int(tid) != int(options["track_id"])):
                continue
            b = np.rint(np.asarray(box) * [w/fw, h/fh, w/fw, h/fh]).astype(int)
            b[[0, 2]] = np.clip(b[[0, 2]], 0, w)
            b[[1, 3]] = np.clip(b[[1, 3]], 0, h)
            area = int((b[2]-b[0]) * (b[3]-b[1]))
            if b[2] > b[0] and b[3] > b[1]:
                choices.append((area, int(tid), b.tolist()))
        if not choices:
            return
        _, tid, bbox = max(choices, key=lambda item: item[0])
        # Claim exactly once across threads/processes. Metadata is published last.
        claimed = DIRECTORY / "request.processing.json"
        os.replace(request, claimed)
        captured = native.copy()
        detector = getattr(embedder, "_det_model", None)
        if detector is None:
            detector = getattr(getattr(embedder, "_app", None), "models", {}).get("detection")
        session = getattr(detector, "session", None)
        model_file = getattr(detector, "model_file", None)
        runtime = {
            "model_pack": getattr(embedder, "model_name", None),
            "initialized": getattr(embedder, "_initialized", False),
            "init_error": getattr(embedder, "_init_error", None),
            "model_file": str(model_file) if model_file else None,
            "model_sha256": hashlib.sha256(Path(model_file).read_bytes()).hexdigest()
                if model_file and Path(model_file).is_file() else None,
            "class": type(detector).__name__ if detector is not None else None,
            "providers": session.get_providers() if session is not None else [],
            "provider_options": session.get_provider_options() if session is not None else {},
            "det_size": getattr(detector, "input_size", None),
            "det_sizes": getattr(detector, "input_sizes", None),
            "det_thresh": getattr(detector, "det_thresh", None),
            "nms_thresh": getattr(detector, "nms_thresh", None),
            "detect_signature": str(inspect.signature(detector.detect)) if detector is not None else None,
            "wrapper_source": inspect.getsource(type(embedder).detect_faces_in_roi),
        }
        ok, png = cv2.imencode(".png", captured)
        if not ok:
            raise RuntimeError("PNG encoding failed")
        payload = png.tobytes()
        (DIRECTORY / "native_frame.tmp.png").write_bytes(payload)
        os.replace(DIRECTORY / "native_frame.tmp.png", DIRECTORY / "native_frame.png")
        metadata = {
            "request_id": options["request_id"], "pid": os.getpid(),
            "timestamp": time.time(), "frame_id": int(frame_id), "track_id": tid,
            "person_bbox_xyxy": bbox, "native_size_wh": [w, h],
            "coordinate_space": "native_frame", "selection": "requested track or largest person",
            "frame_sha256": hashlib.sha256(payload).hexdigest(), "runtime": runtime,
        }
        (DIRECTORY / "snapshot.tmp.json").write_text(
            json.dumps(metadata, indent=2, default=lambda v: v.tolist()), encoding="utf-8")
        os.replace(DIRECTORY / "snapshot.tmp.json", DIRECTORY / "snapshot.json")
        claimed.unlink()
    except FileNotFoundError:
        # Another caller may have claimed the request already.
        if claimed is not None:
            logging.getLogger(__name__).exception("Diagnostic snapshot file unavailable")
    except Exception as exc:
        logging.getLogger(__name__).exception("Diagnostic snapshot failed; pipeline continues")
        if claimed is not None:
            try:
                (DIRECTORY / "error.json").write_text(json.dumps({
                    "request_id": options.get("request_id"), "error": repr(exc)
                }), encoding="utf-8")
            except OSError:
                pass
