"""Integration tests for Analytics REST API Router."""

import pytest
from fastapi.testclient import TestClient
from src.ui.web_server import app


@pytest.fixture
def client():
    return TestClient(app)


def test_get_historical_analytics_endpoint(client):
    response = client.get("/api/analytics/historical?time_range=today")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "metrics" in data
    assert "hourly_distribution" in data


def test_get_peak_hours_endpoint(client):
    response = client.get("/api/analytics/peak_hours?days_back=7")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "typical_peak_hours" in data


def test_get_forecast_endpoint(client):
    response = client.get("/api/analytics/forecast?camera_id=test_cam_01")
    assert response.status_code == 200
    data = response.json()
    assert "data_quality_status" in data
    assert "target_date" in data


def test_get_forecast_alerts_endpoint(client):
    response = client.get("/api/analytics/alerts")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "alerts" in data


def test_camera_analytics_config_endpoints(client):
    cam_id = "test_cam_cfg_01"

    # 1. Get default config
    get_res = client.get(f"/api/analytics/config?camera_id={cam_id}")
    assert get_res.status_code == 200
    cfg = get_res.json()
    assert cfg["camera_id"] == cam_id
    assert cfg["enabled"] is True

    # 2. Update config
    post_res = client.post(
        "/api/analytics/config",
        json={
            "camera_id": cam_id,
            "enabled": True,
            "capacity": 250,
            "in_direction": "reverse",
        },
    )
    assert post_res.status_code == 200
    updated = post_res.json()
    assert updated["status"] == "success"
    assert updated["config"]["capacity"] == 250


def test_export_csv_endpoint(client):
    response = client.get("/api/analytics/export?time_range=today")
    assert response.status_code == 200
    assert "text/csv" in response.headers.get("content-type", "")
    assert "Khung_gio" in response.text
