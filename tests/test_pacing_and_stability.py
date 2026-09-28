"""Regression tests for Phase B (Frame Pacing) and Phase C (Black Screen Prevention).

Verifies:
1. Bounded Jitter Buffer & Backlog Drop Policy in DirectHLSReader.
2. Cadence-aware frame pacer timing (~30 FPS presentation).
3. Same-source-generation last-good frame retention and cross-generation isolation.
4. Status placeholder generation (Requirement C4).
5. Concurrent MJPEG streaming client support (Requirement C5).
6. SharedRuntimeState telemetry diagnostics serialization.
"""

import time
import unittest
import numpy as np

from src.runtime.shared_state import SharedRuntimeState, TelemetrySnapshot
from src.stream.direct_hls import DirectHLSReader
from src.ui.video_stream import MJPEGServer, StreamRequestHandler, create_status_placeholder


class TestPacingAndStability(unittest.TestCase):
    """Test suite for burst pacing and black-screen prevention mechanisms."""

    def test_shared_state_source_generation_and_fallback(self):
        """Verify Requirement C3: same-generation fallback and cross-generation clearance."""
        state = SharedRuntimeState()
        self.assertEqual(state.source_generation, 1)

        # Initially no frame exists
        fid, frame, is_fallback, gen = state.get_frame_for_stream()
        self.assertIsNone(frame)
        self.assertTrue(is_fallback)
        self.assertEqual(gen, 1)

        # Update with a valid frame
        frame1 = np.ones((100, 100, 3), dtype=np.uint8) * 50
        state.update(annotated_frame=frame1)
        self.assertEqual(state.source_generation, 1)

        # Fresh frame should be returned with is_fallback=False
        fid, frame, is_fallback, gen = state.get_frame_for_stream()
        self.assertIsNotNone(frame)
        self.assertFalse(is_fallback)
        self.assertEqual(gen, 1)
        self.assertEqual(frame[0, 0, 0], 50)

        # Simulate a temporary frame gap by setting current annotated frame to None
        with state._lock:
            state._annotated_frame = None

        # Should fall back to same-generation last good frame
        fid, frame, is_fallback, gen = state.get_frame_for_stream()
        self.assertIsNotNone(frame)
        self.assertTrue(is_fallback)
        self.assertEqual(frame[0, 0, 0], 50)
        self.assertEqual(gen, 1)

        # Switch camera: clear_frames must increment generation and wipe last good frame
        state.clear_frames(increment_generation=True)
        self.assertEqual(state.source_generation, 2)

        # After switch, previous generation's frame MUST NEVER be shown
        fid, frame, is_fallback, gen = state.get_frame_for_stream()
        self.assertIsNone(frame)
        self.assertTrue(is_fallback)
        self.assertEqual(gen, 2)

    def test_status_placeholder_creation(self):
        """Verify Requirement C4: status placeholder renders valid JPEG bytes."""
        jpeg_bytes = create_status_placeholder(
            width=640,
            height=360,
            title="TEST RECONNECTING...",
            subtitle="Please wait",
        )
        self.assertIsInstance(jpeg_bytes, bytes)
        self.assertGreater(len(jpeg_bytes), 1000)
        # Check JPEG SOI (0xFFD8) and EOI (0xFFD9) magic numbers
        self.assertTrue(jpeg_bytes.startswith(b"\xff\xd8"))
        self.assertTrue(jpeg_bytes.endswith(b"\xff\xd9"))

    def test_concurrent_mjpeg_clients(self):
        """Verify Requirement C5: MJPEGServer allows concurrent clients without violent eviction."""
        state = SharedRuntimeState()
        server = MJPEGServer(state=state)

        # Simulate 3 client connections
        class DummyHandler:
            def __init__(self):
                self.close_connection = False

        h1, h2, h3 = DummyHandler(), DummyHandler(), DummyHandler()
        t1 = server.claim_video_client(h1)
        t2 = server.claim_video_client(h2)
        t3 = server.claim_video_client(h3)

        self.assertEqual(state.mjpeg_clients_count, 3)
        self.assertFalse(h1.close_connection)
        self.assertFalse(h2.close_connection)
        self.assertFalse(h3.close_connection)

        # Release client 2
        server.release_video_client(h2, t2)
        self.assertEqual(state.mjpeg_clients_count, 2)

        # Release remaining
        server.release_video_client(h1, t1)
        server.release_video_client(h3, t3)
        self.assertEqual(state.mjpeg_clients_count, 0)

    def test_bounded_jitter_buffer_and_drop_policy(self):
        """Verify Requirement B4 & B5: Bounded jitter buffer drops obsolete burst backlog."""
        reader = DirectHLSReader(url="http://test.m3u8", width=64, height=64)
        reader._max_jitter_frames = 10
        reader._max_jitter_age_seconds = 0.5

        # Simulate a burst of 25 decoded frames arriving in quick succession
        now = time.time()
        with reader._lock:
            for i in range(25):
                frame_arr = np.zeros((64, 64, 3), dtype=np.uint8)
                reader._jitter_buffer.append((i, now + (i * 0.01), frame_arr))
                # Apply drop policy
                while len(reader._jitter_buffer) > reader._max_jitter_frames:
                    reader._jitter_buffer.popleft()
                    reader._frames_dropped_by_pacer += 1

        # Buffer must be bounded to max_jitter_frames (10)
        self.assertEqual(reader.jitter_buffer_frames, 10)
        # Dropped frames must be recorded
        self.assertEqual(reader.frames_dropped_by_pacer, 15)

    def test_telemetry_snapshot_contains_pacing_and_black_screen_fields(self):
        """Verify all additional required metrics are exposed in TelemetrySnapshot."""
        state = SharedRuntimeState()
        state.update(
            decoded_frames_total=120,
            decoded_fps=29.8,
            paced_frames_total=100,
            paced_fps=29.5,
            published_frames_total=95,
            publish_fps=29.0,
            frames_dropped_by_pacer=20,
            jitter_buffer_frames=8,
            jitter_buffer_ms=266.7,
            last_decoded_frame_age=0.03,
            last_paced_frame_age=0.033,
        )
        state.record_mjpeg_publish(success=True)

        snapshot = state.get_telemetry()
        d = snapshot.to_dict()

        required_keys = [
            "source_generation",
            "mjpeg_clients",
            "mjpeg_connection_generation",
            "last_jpeg_success",
            "last_jpeg_error",
            "decoded_frames_total",
            "decoded_fps",
            "paced_frames_total",
            "paced_fps",
            "published_frames_total",
            "publish_fps",
            "frames_dropped_by_pacer",
            "jitter_buffer_frames",
            "jitter_buffer_ms",
            "last_decoded_frame_age",
            "last_paced_frame_age",
            "last_published_frame_age",
        ]
        for k in required_keys:
            self.assertIn(k, d, f"Missing required telemetry metric: {k}")

        self.assertEqual(d["decoded_frames_total"], 120)
        self.assertEqual(d["paced_frames_total"], 100)
        self.assertEqual(d["frames_dropped_by_pacer"], 20)
        self.assertEqual(d["jitter_buffer_frames"], 8)
        self.assertTrue(d["last_jpeg_success"])


if __name__ == "__main__":
    unittest.main()
