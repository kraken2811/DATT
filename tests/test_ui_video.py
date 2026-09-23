from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.ui import mjpeg_client as _client


def test_mjpeg_parser_rejects_non_multipart():
    class Headers:
        def get(self, name, default=""):
            return "image/jpeg"
    class Response:
        headers = Headers()
    try:
        next(_client.iter_jpegs(Response()))
    except ValueError as exc:
        assert "multipart" in str(exc)
    else:
        raise AssertionError("invalid content type was accepted")


def test_reader_has_explicit_endpoint_and_diagnostics():
    reader = _client.MJPEGReader("http://localhost:8000/video_feed")
    assert reader.endpoint.endswith("/video_feed")
    assert reader.poll()[1:] == (None, None)
    reader.close()
