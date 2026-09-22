"""FPS and Latency performance measurement utility."""

import time


class FPSMeter:
    """Computes running frame rate and latency over sliding time windows."""

    def __init__(self, window_seconds: float = 1.0):
        self.window_seconds = window_seconds
        self.frame_count: int = 0
        self.window_start: float = time.perf_counter()
        self.fps: float = 0.0

    def tick(self) -> bool:
        """Record one processed frame.

        Returns True if a measurement window completed and fps was updated.
        """
        self.frame_count += 1
        now = time.perf_counter()
        elapsed = now - self.window_start
        if elapsed >= self.window_seconds:
            self.fps = self.frame_count / elapsed
            self.frame_count = 0
            self.window_start = now
            return True
        return False
