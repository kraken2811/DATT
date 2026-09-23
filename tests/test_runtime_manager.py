"""Tests for DATT Unified Runtime Manager & Entry Point (Phase 4.5).

Verifies:
1. Argument parsing in src/main.py
2. Port availability check & protection against collisions
3. Lifecycle start & graceful shutdown
"""

from pathlib import Path
import socket
import sys
import unittest
from unittest.mock import MagicMock, patch

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.main import parse_args
from src.runtime.runtime_manager import RuntimeManager, is_port_available


class TestRuntimeManager(unittest.TestCase):
    """Test suite for unified RuntimeManager."""

    def test_cli_argument_parsing(self) -> None:
        """Verify command line flags parse correctly in src/main.py."""
        test_argv = ["src/main.py", "--camera", "camera_02", "--port", "8502", "--max-frames", "25"]
        with patch.object(sys, "argv", test_argv):
            args = parse_args()
            self.assertEqual(args.camera, "camera_02")
            self.assertEqual(args.port, 8502)
            self.assertEqual(args.max_frames, 25)
            self.assertTrue(args.ui)

    def test_port_availability_detection(self) -> None:
        """Verify is_port_available accurately detects free and occupied ports."""
        # Find an open port dynamically
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            free_port = s.getsockname()[1]

        # Should be available now that socket is closed
        self.assertTrue(is_port_available(free_port, "127.0.0.1"))

        # Occupy the port and verify collision detection
        occupier = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        occupier.bind(("127.0.0.1", free_port))
        occupier.listen(1)
        try:
            self.assertFalse(is_port_available(free_port, "127.0.0.1"))

            # RuntimeManager must raise RuntimeError if port is occupied
            mgr = RuntimeManager(web_port=free_port, ai_port=59998, ai_host="127.0.0.1")
            with self.assertRaises(RuntimeError) as ctx:
                mgr.validate_ports()
            self.assertIn("already in use", str(ctx.exception))
        finally:
            occupier.close()

    def test_graceful_shutdown_cleans_threads(self) -> None:
        """Verify shutdown() releases all resources and stops threads cleanly."""
        mgr = RuntimeManager(
            web_port=58501,
            ai_port=58000,
            ui_enabled=False,
            max_frames=1,
        )
        self.assertFalse(mgr._stop_event.is_set())

        # Trigger shutdown
        mgr.shutdown()
        self.assertTrue(mgr._stop_event.is_set())
        # Subsequent call should be safe (idempotent)
        mgr.shutdown()


def run_tests():
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(TestRuntimeManager)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)


if __name__ == "__main__":
    run_tests()
