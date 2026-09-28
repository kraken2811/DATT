"""Regression checks for bounded event and dashboard update rates."""
from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_event_policy_constants_and_snapshot_cap_are_present():
    source = (ROOT / "src/events/event_manager.py").read_text(encoding="utf-8")
    assert "EVENT_REPORT_INTERVAL = 300.0" in source
    assert "SIGNIFICANT_CHANGE = 5" in source
    assert "STABLE_TIME_SECONDS = 5.0" in source
    assert "SNAPSHOT_INTERVAL_SECONDS = 60.0" in source


def test_dashboard_refreshes_metadata_at_bounded_rates():
    source = (ROOT / "src/ui/dashboard.py").read_text(encoding="utf-8")
    assert "value=2" in source
    assert "limit=5" in source
    assert "last_event_fetch" in source
    assert ">= 10.0" in source
