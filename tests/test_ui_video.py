"""UI relay regression tests."""
import importlib.util
from pathlib import Path
import types
import sys

_pkg = types.ModuleType("src.ui")
_pkg.__path__ = []
sys.modules.setdefault("src.ui", _pkg)
_spec = importlib.util.spec_from_file_location("src.ui.mjpeg_client", Path(__file__).parents[1] / "src/ui/mjpeg_client.py")
_client = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_client)


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
