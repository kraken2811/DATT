"""One-shot export correctness, independent of live cameras/model downloads."""

import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from src.face import diagnostic_snapshot as diag


class FakeEmbedder:
    def detect_faces_in_roi(self, roi):
        return []


class SnapshotTests(unittest.TestCase):
    def test_exact_frame_native_coordinates_and_one_shot(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(diag, "DIRECTORY", Path(tmp)):
            root = Path(tmp)
            frame = np.zeros((40, 60, 3), dtype=np.uint8)
            native = np.arange(80*120*3, dtype=np.uint8).reshape(80, 120, 3)
            tracks = SimpleNamespace(xyxy=np.array([[5, 6, 25, 36]]), tracker_id=[17])
            (root / "request.json").write_text(json.dumps({"request_id": "one", "track_id": 17}))
            diag.export_if_requested(frame, tracks, 42, native, FakeEmbedder())
            meta = json.loads((root / "snapshot.json").read_text())
            self.assertEqual(meta["person_bbox_xyxy"], [10, 12, 50, 72])
            self.assertEqual((meta["frame_id"], meta["track_id"]), (42, 17))
            np.testing.assert_array_equal(cv2.imread(str(root / "native_frame.png")), native)
            self.assertEqual(meta["frame_sha256"], hashlib.sha256((root / "native_frame.png").read_bytes()).hexdigest())
            before = (root / "snapshot.json").read_bytes()
            diag.export_if_requested(frame, tracks, 43, native, FakeEmbedder())
            self.assertEqual(before, (root / "snapshot.json").read_bytes())
            self.assertFalse((root / "request.json").exists())

    def test_no_request_does_nothing(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(diag, "DIRECTORY", Path(tmp)):
            diag.export_if_requested(None, None, None, None, None)
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_missing_track_keeps_request_pending(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(diag, "DIRECTORY", Path(tmp)):
            root = Path(tmp)
            (root / "request.json").write_text(json.dumps({"request_id": "one", "track_id": 99}))
            frame = np.zeros((40, 60, 3), dtype=np.uint8)
            tracks = SimpleNamespace(xyxy=np.array([[5, 6, 25, 36]]), tracker_id=[17])
            diag.export_if_requested(frame, tracks, 42, None, FakeEmbedder())
            self.assertTrue((root / "request.json").exists())
            self.assertFalse((root / "snapshot.json").exists())


if __name__ == "__main__":
    unittest.main()
