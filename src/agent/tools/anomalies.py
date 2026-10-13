"""LangGraph Anomaly Detection tools for DATT AI Assistant."""

from typing import Any
from langchain_core.tools import tool

from src.agent.config import agent_config
from src.analytics.anomalies import TrafficAnomalyDetector


@tool
def detect_traffic_anomalies(
    time_window_hours: int = 2,
    camera_id: str | None = None,
    zone_id: str | None = None,
    anomaly_types: list[str] | None = None,
    sensitivity: str = "normal",
) -> dict[str, Any]:
    """Detect statistical operational and traffic anomalies across the camera fleet.

    Deterministically compares recent traffic metrics against historical baselines
    (same hour of day and day of week from past weeks).
    Detects:
    - TRAFFIC_SPIKE: Traffic significantly exceeding baseline (e.g. > +50%).
    - TRAFFIC_DROP: Traffic dropping drastically below expected baseline (e.g. > -50%).
    - SUSTAINED_HIGH_TRAFFIC: Continuous high congestion over consecutive intervals.
    - UNUSUAL_OFF_HOURS_ACTIVITY: Uncharacteristic traffic during late night / off-hours (23:00 - 05:00).
    - CAMERA_AVAILABILITY_ANOMALY: Camera downtime, dropped frames, or low coverage ratio (< 60%).
    - ABNORMAL_ALERT_FREQUENCY: Spike in security watchlist match alerts.

    Args:
        time_window_hours: Evaluation window in hours (1-48, default: 2).
        camera_id: Optional camera identifier to scope analysis to a single camera.
        zone_id: Optional zone identifier.
        anomaly_types: Optional list of anomaly types to check (default: all).
        sensitivity: Sensitivity threshold level: 'low', 'normal', or 'high' (default: 'normal').

    Returns:
        Structured anomalies with observed values, baselines, deviation percentages,
        severity (CRITICAL, HIGH, MEDIUM, LOW), explanations, and actionable recommendations.
    """
    db = agent_config.get_database()
    try:
        detector = TrafficAnomalyDetector(db=db)
        return detector.detect_anomalies(
            time_window_hours=time_window_hours,
            camera_id=camera_id,
            zone_id=zone_id,
            anomaly_types=anomaly_types,
            sensitivity=sensitivity,
        )
    finally:
        db.dispose()
