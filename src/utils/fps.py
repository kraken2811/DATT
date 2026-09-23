"""FPS and Latency performance measurement utility."""

from collections import deque
import time


class FPSMeter:
    """Computes running frame rate over a sliding window of frame timestamps."""

    def __init__(self, window_size: int = 30, window_seconds: float = 1.0):
        self.window_size = window_size
        self.window_seconds = window_seconds
        self.timestamps: deque[float] = deque(maxlen=window_size)
        self.fps: float = 0.0
        self.last_update_time: float = time.perf_counter()

    def tick(self) -> bool:
        """Record one processed frame timestamp and update sliding window FPS.

        Returns True if a measurement interval (>= window_seconds) has passed for HUD logging,
        while maintaining a rolling sliding-window FPS across the last 30 frames:
        FPS = (number of frames - 1) / (time difference)
        """
        now = time.perf_counter()
        self.timestamps.append(now)

        if len(self.timestamps) >= 2:
            time_diff = self.timestamps[-1] - self.timestamps[0]
            if time_diff > 0:
                self.fps = (len(self.timestamps) - 1) / time_diff

        if now - self.last_update_time >= self.window_seconds:
            self.last_update_time = now
            return True
        return False
