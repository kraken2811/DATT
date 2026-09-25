"""FPS and Latency performance measurement utility."""

from collections import deque
import time


class FPSMeter:
    """Computes running frame rate over a sliding window of frame timestamps."""

    def __init__(self, window_size: int = 90, window_seconds: float = 1.0):
        self.window_size = window_size
        self.window_seconds = window_seconds
        self.timestamps: deque[float] = deque(maxlen=window_size)
        self.fps: float = 0.0
        self.last_update_time: float = time.perf_counter()

    def tick(self) -> bool:
        """Record one processed frame timestamp and update sliding window FPS.

        Returns True if a measurement interval (>= window_seconds) has passed for HUD logging,
        while maintaining a rolling sliding-window FPS across the last 3 seconds:
        FPS = (number of frames - 1) / (time difference)
        """
        now = time.perf_counter()
        self.timestamps.append(now)

        cutoff = now - 3.0
        while len(self.timestamps) > 2 and self.timestamps[0] < cutoff:
            self.timestamps.popleft()

        if len(self.timestamps) >= 2:
            time_diff = self.timestamps[-1] - self.timestamps[0]
            if time_diff >= 0.5:
                self.fps = (len(self.timestamps) - 1) / time_diff

        if now - self.last_update_time >= self.window_seconds:
            self.last_update_time = now
            return True
        return False
