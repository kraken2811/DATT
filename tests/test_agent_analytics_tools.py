"""Unit tests for Gemini AI Agent analytical tools."""

import pytest
from src.agent.tools import (
    ALL_AGENT_TOOLS,
    get_historical_analytics,
    get_peak_traffic_hours,
    get_tomorrow_forecast,
    get_predictive_alerts,
)


def test_agent_tools_registration():
    tool_names = [t.name for t in ALL_AGENT_TOOLS]
    assert "get_historical_analytics" in tool_names
    assert "get_peak_traffic_hours" in tool_names
    assert "get_tomorrow_forecast" in tool_names
    assert "get_predictive_alerts" in tool_names


def test_get_historical_analytics_tool():
    # Invoke tool directly
    res = get_historical_analytics.invoke({
        "camera_id": "all",
        "time_range": "7_days",
        "group_by": "hour",
    })
    assert isinstance(res, dict)
    assert res.get("status") == "success"
    assert "metrics" in res
    assert "hourly_distribution" in res
    assert "weekday_comparison" in res


def test_get_peak_traffic_hours_tool():
    res = get_peak_traffic_hours.invoke({
        "camera_id": "all",
        "days_back": 7,
    })
    assert isinstance(res, dict)
    assert res.get("status") == "success"
    assert "typical_peak_hours" in res


def test_get_tomorrow_forecast_tool():
    res = get_tomorrow_forecast.invoke({
        "camera_id": "cam_gate",
    })
    assert isinstance(res, dict)
    assert "data_quality_status" in res
    assert "hourly_forecasts" in res or "message" in res
    # If no data, message should indicate lack of data in Vietnamese
    if res.get("data_quality_status") == "INSUFFICIENT_DATA":
        assert "Chưa đủ dữ liệu lịch sử" in res["message"]


def test_get_predictive_alerts_tool():
    res = get_predictive_alerts.invoke({
        "camera_id": "cam_gate",
    })
    assert isinstance(res, dict)
    assert res.get("status") == "success"
    assert "alerts" in res
