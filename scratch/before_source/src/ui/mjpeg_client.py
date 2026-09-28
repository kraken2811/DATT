"""Server-side MJPEG reader; no Streamlit or inference dependencies."""

import base64
from email.message import Message
import threading
import time
import urllib.error
import urllib.request


MAX_FRAME_BYTES = 8 * 1024 * 1024


def iter_jpegs(response):
    """Read bounded multipart frames, including partial network reads."""
    content_type = Message()
    content_type['content-type'] = response.headers.get('Content-Type', '')
    boundary = content_type.get_param('boundary')
    if content_type.get_content_type() != 'multipart/x-mixed-replace' or not boundary:
        raise ValueError('Expected multipart/x-mixed-replace with a boundary')
    marker = b'--' + boundary.encode('ascii')
    while True:
        line = response.readline(8193)
        if not line:
            raise EOFError('MJPEG stream closed')
        if len(line) > 8192:
            raise ValueError('Multipart line exceeds limit')
        if line.strip() == marker + b'--':
            raise EOFError('MJPEG stream ended')
        if line.strip() != marker:
            continue
        headers = Message()
        for _ in range(32):
            line = response.readline(8193)
            if not line or len(line) > 8192:
                raise ValueError('Invalid multipart headers')
            if line in (b'\r\n', b'\n'):
                break
            key, value = line.decode('ascii').split(':', 1)
            headers[key] = value.strip()
        else:
            raise ValueError('Too many multipart headers')
        if headers.get_content_type() != 'image/jpeg':
            raise ValueError('Expected image/jpeg frame')
        size = int(headers.get('Content-Length', '0'))
        if not 0 < size <= MAX_FRAME_BYTES:
            raise ValueError('Invalid JPEG Content-Length')
        frame = bytearray()
        while len(frame) < size:
            chunk = response.read(size - len(frame))
            if not chunk:
                raise EOFError('Incomplete JPEG frame')
            frame.extend(chunk)
        if not frame.startswith(b'\xff\xd8') or not frame.endswith(b'\xff\xd9'):
            raise ValueError('Invalid JPEG markers')
        yield bytes(frame)


class MJPEGReader:
    """One latest frame per session, with retries and idle connection cleanup.

    The worker never calls Streamlit. Polling renews its lease; abandoned sessions
    stop within idle_timeout + socket timeout, without a global resource cache.
    """

    def __init__(self, endpoint, timeout=5.0, idle_timeout=30.0, retry_delay=1.0):
        self.endpoint = endpoint
        self.timeout = timeout
        self.idle_timeout = idle_timeout
        self.retry_delay = retry_delay
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._last_poll = time.monotonic()
        self._image = None
        self._status = None
        self._error = None

    def poll(self):
        with self._lock:
            self._last_poll = time.monotonic()
            if self._thread is None or not self._thread.is_alive():
                self._stop.clear()
                self._thread = threading.Thread(target=self._run, daemon=True,
                                                name='DashboardMJPEG')
                self._thread.start()
            return self._image, self._status, self._error

    def close(self):
        self._stop.set()

    def _active(self):
        with self._lock:
            return (not self._stop.is_set() and
                    time.monotonic() - self._last_poll < self.idle_timeout)

    def _run(self):
        while self._active():
            status = None
            try:
                request = urllib.request.Request(
                    self.endpoint, headers={'User-Agent': 'DATT-Dashboard'})
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    status = response.status
                    if status != 200:
                        raise ValueError(f'Expected HTTP 200, received {status}')
                    for frame in iter_jpegs(response):
                        if not self._active():
                            return
                        image = 'data:image/jpeg;base64,' + base64.b64encode(frame).decode('ascii')
                        with self._lock:
                            self._image, self._status, self._error = image, status, None
            except Exception as exc:
                if isinstance(exc, urllib.error.HTTPError):
                    status = exc.code
                    exc.close()
                with self._lock:
                    self._image = None
                    self._status = status
                    self._error = f'{type(exc).__name__}: {exc}'
            if self._stop.wait(self.retry_delay):
                return
