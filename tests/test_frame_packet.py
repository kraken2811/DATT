import threading

import numpy as np

from src.runtime.shared_state import SharedRuntimeState


def publish(state, frame_id, count=None):
    state.update(
        frame_id=frame_id,
        annotated_frame=np.zeros((2, 2, 3), dtype=np.uint8),
        jpeg_bytes=str(frame_id).encode(),
        people_count=frame_id,
        detection_count=count,
        camera_id="camera-a",
    )


def test_packet_keeps_publication_metrics_when_new_frames_arrive():
    state = SharedRuntimeState()
    publish(state, 1, 3)
    jpeg, metrics = state.get_frame_packet()
    publish(state, 2, None)
    assert jpeg == b"1"
    assert metrics["frame_id"] == metrics["people_count"] == 1
    assert metrics["detection_count"] == 3
    assert state.get_frame_packet()[1]["detection_count"] is None


def test_packet_never_pairs_different_frames_under_concurrent_publication():
    state = SharedRuntimeState()
    publish(state, 1)
    def writer():
        for frame_id in range(2, 300):
            publish(state, frame_id)
    thread = threading.Thread(target=writer)
    thread.start()
    for _ in range(300):
        jpeg, metrics = state.get_frame_packet()
        assert int(jpeg) == metrics["frame_id"] == metrics["people_count"]
    thread.join(timeout=3)
    assert not thread.is_alive()


def test_clear_frames_does_not_serve_previous_camera_packet():
    state = SharedRuntimeState()
    publish(state, 8)
    state.clear_frames()
    assert state.get_frame_packet() is None
    state.set_camera("camera-b", "B")
    state.update(frame_id=1, annotated_frame=np.zeros((2, 2, 3)),
                 jpeg_bytes=b"new", people_count=0, camera_id="camera-b")
    jpeg, metrics = state.get_frame_packet()
    assert jpeg == b"new"
    assert metrics["people_count"] == 0
    assert metrics["camera_id"] == "camera-b"


def test_http_packet_header_and_body_survive_publication_during_send():
    import io
    import json
    from src.ui.video_stream import StreamRequestHandler

    state = SharedRuntimeState()
    publish(state, 1, 3)
    handler = object.__new__(StreamRequestHandler)
    handler.state = state
    handler.wfile = io.BytesIO()
    headers = {}
    handler.send_response = lambda code: headers.update(status=code)
    handler.send_header = lambda key, value: headers.update({key: value})
    handler.end_headers = lambda: publish(state, 2, 9)
    handler.handle_frame_packet()
    metrics = json.loads(headers["X-Frame-Telemetry"])
    assert headers["status"] == 200
    assert handler.wfile.getvalue() == b"1"
    assert metrics["people_count"] == 1
    assert metrics["detection_count"] == 3


def test_proxy_preserves_packet_metadata_and_jpeg(monkeypatch):
    import asyncio
    import httpx
    from types import SimpleNamespace
    from src.ui import web_server

    async def get(url, **kwargs):
        assert url == "http://backend/frame_packet"
        return httpx.Response(200, content=b"jpeg", headers={
            "X-Frame-Telemetry": '{"frame_id":12,"people_count":4}'})

    monkeypatch.setattr(web_server, "get_backend_url", lambda request: "http://backend")
    monkeypatch.setattr(web_server, "get_backend_http_client", lambda: SimpleNamespace(get=get))
    response = asyncio.run(web_server.frame_packet(None))
    assert response.body == b"jpeg"
    assert response.headers["x-frame-telemetry"] == '{"frame_id":12,"people_count":4}'
