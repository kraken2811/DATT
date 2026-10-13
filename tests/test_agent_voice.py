"""Unit and integration tests for DATT AI Voice Transcription (Groq Whisper Large V3 Turbo)."""

import io
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.agent.api.routes import router
from fastapi import FastAPI


@pytest.fixture
def test_app():
    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture
def client(test_app):
    return TestClient(test_app)


def test_transcribe_missing_auth_header(client, monkeypatch):
    """Transcription endpoint requires session or authorization header when strict auth is enabled."""
    monkeypatch.setenv("DATT_STRICT_AUTH", "1")
    audio_content = b"RIFF....WAVEfmt ...."
    files = {"file": ("recording.webm", io.BytesIO(audio_content), "audio/webm")}
    resp = client.post("/api/agent/transcribe", files=files)
    assert resp.status_code == 401
    assert "authentication token is required" in resp.json()["detail"].lower()


def test_transcribe_empty_file_rejected(client):
    """Uploading an empty file raises 400 Bad Request."""
    headers = {"X-Session-Id": "test_session_user_1"}
    files = {"file": ("recording.webm", io.BytesIO(b""), "audio/webm")}
    resp = client.post("/api/agent/transcribe", files=files, headers=headers)
    assert resp.status_code == 400
    assert "Empty audio" in resp.json()["detail"]


def test_transcribe_unsupported_audio_extension(client):
    """Uploading non-audio files is rejected."""
    headers = {"X-Session-Id": "test_session_user_1"}
    files = {"file": ("malicious.exe", io.BytesIO(b"binarycontent123"), "application/octet-stream")}
    resp = client.post("/api/agent/transcribe", files=files, headers=headers)
    assert resp.status_code == 400
    assert "Unsupported audio" in resp.json()["detail"]


def test_transcribe_file_too_large_rejected(client):
    """Audio files exceeding 25MB are rejected."""
    headers = {"X-Session-Id": "test_session_user_1"}
    large_audio = b"A" * (26 * 1024 * 1024)
    files = {"file": ("huge.webm", io.BytesIO(large_audio), "audio/webm")}
    resp = client.post("/api/agent/transcribe", files=files, headers=headers)
    assert resp.status_code == 413
    assert "exceeds" in resp.json()["detail"].lower()


def test_transcribe_successful_vietnamese_transcription(client):
    """Successful audio transcription returns recognized text."""
    headers = {"X-Session-Id": "test_session_user_1"}
    audio_content = b"valid_audio_bytes_12345"
    files = {"file": ("sample.webm", io.BytesIO(audio_content), "audio/webm")}

    mock_whisper_resp = MagicMock()
    mock_whisper_resp.text = "Kiểm tra tình trạng camera số 01"

    with patch("groq.Groq") as mock_groq_cls:
        client_mock = MagicMock()
        client_mock.audio.transcriptions.create.return_value = mock_whisper_resp
        mock_groq_cls.return_value = client_mock

        resp = client.post("/api/agent/transcribe", files=files, headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["text"] == "Kiểm tra tình trạng camera số 01"
        assert data["language"] == "vi"
        assert "duration_sec" in data


def test_transcribe_groq_api_error_returns_502(client):
    """When Groq Whisper service fails, a clean 502 Bad Gateway is returned."""
    headers = {"X-Session-Id": "test_session_user_1"}
    audio_content = b"audio_sample_bytes"
    files = {"file": ("sample.webm", io.BytesIO(audio_content), "audio/webm")}

    with patch("groq.Groq") as mock_groq_cls:
        client_mock = MagicMock()
        client_mock.audio.transcriptions.create.side_effect = Exception("503 Service Unavailable: Whisper quota exceeded")
        mock_groq_cls.return_value = client_mock

        resp = client.post("/api/agent/transcribe", files=files, headers=headers)
        assert resp.status_code == 502
        assert "Whisper transcription failed" in resp.json()["detail"]
