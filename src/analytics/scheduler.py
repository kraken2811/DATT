"""Daily Background Forecast Scheduler for DATT.

Executes daily traffic forecasting and predictive alert evaluation across all
enabled cameras at the configured hour (default: 18:00 Asia/Ho_Chi_Minh).
Runs as a supervised background daemon thread with duplicate execution prevention,
error recovery, and manual on-demand trigger support.
"""

from datetime import datetime, timezone, timedelta
import logging
import os
import threading
import time
from typing import Any

from src.db.database import Database
from src.analytics.alerts import PredictiveAlertService, get_tomorrow_date_local

logger = logging.getLogger("datt.analytics.scheduler")
LOCAL_TZ = timezone(timedelta(hours=7))  # Asia/Ho_Chi_Minh (UTC+7)


class DailyForecastScheduler:
    """Supervised daily scheduler for traffic forecasting and predictive alerts."""

    def __init__(self, db: Database | None = None, target_hour_ict: int | None = None) -> None:
        self.db = db or Database()
        self.target_hour_ict = (
            target_hour_ict
            if target_hour_ict is not None
            else int(os.environ.get("DATT_FORECAST_SCHEDULE_HOUR", "18"))
        )
        self.last_run_date: str | None = None
        self.last_run_time: datetime | None = None
        self.last_run_result: dict[str, Any] | None = None
        self.last_error: str | None = None
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def run_forecast_job(self) -> dict[str, Any]:
        """Execute daily forecast and alert evaluation across all enabled cameras."""
        with self._lock:
            try:
                alert_service = PredictiveAlertService(db=self.db)
                result = alert_service.generate_all_tomorrow_forecasts_and_alerts()
                now_utc = datetime.now(timezone.utc)
                self.last_run_time = now_utc
                self.last_run_date = result.get("target_date")
                self.last_run_result = result
                self.last_error = None
                logger.info(
                    "[FORECAST-SCHEDULER] Daily forecast job executed successfully for target date %s (%d cameras processed, %d alerts generated)",
                    self.last_run_date,
                    result.get("cameras_processed", 0),
                    result.get("total_alerts_generated", 0),
                )
                return result
            except Exception as exc:
                self.last_error = str(exc)
                logger.error("[FORECAST-SCHEDULER] Daily forecast job failed: %s", exc, exc_info=True)
                return {"status": "error", "error": str(exc)}

    def trigger_now(self) -> dict[str, Any]:
        """Manually trigger immediate execution of the daily forecast job."""
        return self.run_forecast_job()

    def get_status(self) -> dict[str, Any]:
        """Return scheduler status and metadata."""
        now_local = datetime.now(timezone.utc).astimezone(LOCAL_TZ)
        today_str = now_local.strftime("%Y-%m-%d")
        is_alive = self._thread is not None and self._thread.is_alive()
        return {
            "running": is_alive,
            "target_hour_ict": self.target_hour_ict,
            "current_time_ict": now_local.strftime("%Y-%m-%d %H:%M:%S"),
            "today_date_ict": today_str,
            "last_run_date": self.last_run_date,
            "last_run_time": self.last_run_time.isoformat() if self.last_run_time else None,
            "has_run_today": (self.last_run_date == today_str),
            "last_error": self.last_error,
            "last_cameras_processed": self.last_run_result.get("cameras_processed", 0) if self.last_run_result else 0,
            "last_alerts_generated": self.last_run_result.get("total_alerts_generated", 0) if self.last_run_result else 0,
        }

    def start(self) -> None:
        """Start scheduler background daemon thread."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                logger.info("[FORECAST-SCHEDULER] Thread already running")
                return

            self._stop_event.clear()

            def _loop() -> None:
                logger.info(
                    "[FORECAST-SCHEDULER] Background worker started (daily execution configured at %02d:00 ICT)",
                    self.target_hour_ict,
                )
                while not self._stop_event.is_set():
                    try:
                        now_local = datetime.now(timezone.utc).astimezone(LOCAL_TZ)
                        today_str = now_local.strftime("%Y-%m-%d")

                        # Trigger if hour matches and hasn't run yet today
                        if now_local.hour >= self.target_hour_ict and self.last_run_date != today_str:
                            logger.info(
                                "[FORECAST-SCHEDULER] Triggering scheduled forecast generation at %s ICT",
                                now_local.strftime("%H:%M:%S"),
                            )
                            self.run_forecast_job()
                    except Exception as exc:
                        logger.error("[FORECAST-SCHEDULER] Loop exception: %s", exc)

                    # Check stop event every 5 seconds
                    self._stop_event.wait(5.0)
                logger.info("[FORECAST-SCHEDULER] Background worker stopped")

            self._thread = threading.Thread(
                target=_loop,
                name="DailyForecastSchedulerWorker",
                daemon=True,
            )
            self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        """Stop scheduler background worker."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)


# Global singleton instance
daily_forecast_scheduler = DailyForecastScheduler()
