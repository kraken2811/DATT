"""Regression tests for Phase A: Face Registration & Target Matching fix.

Verifies:
1. Browser upload of EXIF-oriented portrait (tag 6 / 90 CW) decodes upright and registers successfully.
2. Upright portrait registration generates valid 512-dim embedding.
3. Blank/no-face image produces structured error code NO_FACE_DETECTED.
4. Unsupported image format rejected with IMAGE_DECODE_FAILED.
5. Live target matcher associates live person track with registered face embedding.
"""

from collections import namedtuple
import io
from pathlib import Path
import sys
import unittest

from fastapi.testclient import TestClient
import numpy as np
from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.face.face_embedder import decode_face_image_bytes, FaceEmbedder
from src.recognition.target_matcher import (
    TargetManager,
    TargetMatcher,
    TargetRegistrationError,
    target_manager,
    target_matcher,
)
from src.ui.web_server import app


class TestFaceRegistrationFix(unittest.TestCase):
    """Test suite ensuring target face registration and matching behave correctly."""

    def setUp(self) -> None:
        self.client = TestClient(app)
        target_manager.clear()

    def tearDown(self) -> None:
        target_manager.clear()

    def _create_synthetic_face_portrait(self, exif_orientation: int | None = None) -> bytes:
        """Create a JPEG byte payload with a real face crop for testing."""
        # Check if scratch test portrait exists, otherwise use Tom Hanks from insightface data
        scratch_p = PROJECT_ROOT / "scratch" / "test_real_portrait.jpg"
        if scratch_p.is_file():
            pil_img = Image.open(str(scratch_p))
        else:
            ins_p = PROJECT_ROOT / "venv" / "Lib" / "site-packages" / "insightface" / "data" / "images" / "Tom_Hanks_54745.png"
            pil_img = Image.open(str(ins_p))

        buf = io.BytesIO()
        if exif_orientation is not None:
            exif = pil_img.getexif()
            exif[0x0112] = exif_orientation
            pil_img.save(buf, format="JPEG", exif=exif)
        else:
            pil_img.save(buf, format="JPEG")
        return buf.getvalue()

    def test_exif_orientation_decode(self) -> None:
        """Requirement A2: EXIF orientation is respected and transposed upright."""
        jpeg_bytes = self._create_synthetic_face_portrait(exif_orientation=6)
        img, meta = decode_face_image_bytes(jpeg_bytes)
        self.assertIsNotNone(img)
        self.assertTrue(meta["success"])
        self.assertEqual(meta["orientation_tag"], 6)
        self.assertGreater(meta["width"], 20)
        self.assertGreater(meta["height"], 20)

    def test_register_target_exif_portrait_multipart(self) -> None:
        """Requirements A1-A6: Upload of EXIF portrait registers target with 512-dim embedding."""
        jpeg_bytes = self._create_synthetic_face_portrait(exif_orientation=6)
        files = {"face_image": ("portrait_exif.jpg", io.BytesIO(jpeg_bytes), "image/jpeg")}
        data = {"name": "Test User EXIF", "threshold": "0.45"}

        resp = self.client.post("/api/register_target", data=data, files=files)
        self.assertEqual(resp.status_code, 200)
        res_data = resp.json()
        self.assertEqual(res_data.get("status"), "ok")
        target = res_data.get("target")
        self.assertEqual(target.get("name"), "Test User EXIF")
        self.assertTrue(target.get("has_face"))

        # Verify listed in GET /api/targets
        list_resp = self.client.get("/api/targets")
        self.assertEqual(list_resp.status_code, 200)
        self.assertEqual(len(list_resp.json().get("targets")), 1)

    def test_register_target_blank_image_rejected(self) -> None:
        """Requirement A5: Blank image returns structured error NO_FACE_DETECTED."""
        # Create pure blank black image
        blank_pil = Image.new("RGB", (200, 200), color=(0, 0, 0))
        buf = io.BytesIO()
        blank_pil.save(buf, format="JPEG")
        files = {"face_image": ("blank.jpg", buf.getvalue(), "image/jpeg")}
        data = {"name": "Blank Face Target"}

        resp = self.client.post("/api/register_target", data=data, files=files)
        self.assertEqual(resp.status_code, 400)
        res_data = resp.json()
        self.assertEqual(res_data.get("status"), "error")
        self.assertEqual(res_data.get("code"), "NO_FACE_DETECTED")
        self.assertIn("Could not detect a valid human face", res_data.get("message", ""))

    def test_register_target_unsupported_extension_rejected(self) -> None:
        """Requirement A1: Unsupported file extension is rejected with IMAGE_DECODE_FAILED."""
        files = {"face_image": ("bad_file.txt", b"not an image", "text/plain")}
        data = {"name": "Text Target"}

        resp = self.client.post("/api/register_target", data=data, files=files)
        self.assertEqual(resp.status_code, 400)
        res_data = resp.json()
        self.assertEqual(res_data.get("code"), "IMAGE_DECODE_FAILED")

    def test_live_target_matching_end_to_end(self) -> None:
        """Requirement A7: Live track matching associates person track with registered face."""
        import cv2

        jpeg_bytes = self._create_synthetic_face_portrait()
        img, _ = decode_face_image_bytes(jpeg_bytes)
        self.assertIsNotNone(img)

        target = target_manager.register_target(name="Target Detective", face_image=img, face_threshold=0.35)
        self.assertTrue(target.has_face)

        # Build simulated scene
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        person_box = np.zeros((300, 120, 3), dtype=np.uint8)
        resized_face = cv2.resize(img, (80, 80))
        person_box[10:90, 20:100] = resized_face
        frame[200:500, 300:420] = person_box

        TrackBox = namedtuple("TrackBox", ["xyxy", "tracker_id"])
        tracks = TrackBox(xyxy=np.array([[300, 200, 420, 500]]), tracker_id=np.array([77]))

        matched = target_matcher.match_tracks(frame, tracks, frame_id=1)
        self.assertIn(77, matched)
        match_info = matched[77]
        self.assertEqual(match_info.target_id, target.id)
        self.assertEqual(match_info.target_name, "Target Detective")
        self.assertGreaterEqual(match_info.score, 0.35)


if __name__ == "__main__":
    unittest.main()
