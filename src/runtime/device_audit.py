"""Bounded, opt-in observations of already-instantiated production models.

No model initialization or inference is performed by this module. Timed wrappers
delegate identical arguments/results; no image, embedding or identity is retained.
"""
from collections import defaultdict, deque
import os
import sys
import threading
import time
import numpy as np

_lock = threading.Lock()
_samples = defaultdict(lambda: deque(maxlen=4096))
_inputs = {}


def _observe(obj, method, label, enabled):
    if obj is None or not enabled:
        return
    original = getattr(obj, method, None)
    if original is None or getattr(original, '_datt_device_audit', False):
        return
    def measured(*args, **kwargs):
        start = time.perf_counter()
        if method == 'run':
            feed = args[1] if len(args) > 1 else kwargs.get('input_feed', {})
            devices = sorted({str(getattr(v, 'device', 'CPU NumPy')) for v in feed.values()})
            with _lock:
                _inputs[label] = devices
        try:
            return original(*args, **kwargs)
        finally:
            with _lock:
                _samples[label].append((time.perf_counter() - start) * 1000.0)
    measured._datt_device_audit = True
    setattr(obj, method, measured)


def _providers(session):
    if session is None:
        return None
    return dict(providers=session.get_providers(), options=session.get_provider_options())


def snapshot(instrument=False):
    local = {}
    for frame in sys._current_frames().values():
        while frame:
            if frame.f_code.co_name == 'run_pipeline' and frame.f_globals.get('__name__') == 'app':
                local = dict(frame.f_locals)
                break
            frame = frame.f_back
        if local:
            break
    detector = local.get('detector')
    yolo_device = None
    if detector is not None:
        try:
            predictor = getattr(detector.model, 'predictor', None)
            active_model = getattr(getattr(predictor, 'model', None), 'model', None)
            yolo_device = str(next((active_model if active_model is not None else detector.model.model).parameters()).device)
        except (AttributeError, StopIteration):
            pass
    face_module = sys.modules.get('src.face.face_embedder')
    face = getattr(face_module, 'face_embedder', None)
    scrfd = getattr(getattr(face, '_det_model', None), 'session', None)
    matcher_module = sys.modules.get('src.recognition.target_matcher')
    matcher = getattr(matcher_module, 'target_matcher', None)
    adaface = getattr(getattr(getattr(matcher, 'face_pipeline', None), 'embedder', None), '_session', None)
    plate_module = sys.modules.get('src.ocr.plate_reader')
    reader = getattr(getattr(plate_module, 'plate_reader', None), '_reader', None)
    line_reader = getattr(getattr(plate_module, 'plate_reader', None), '_line_recognizer', None)
    line_session = getattr(line_reader, 'session', None)
    _observe(scrfd, 'run', 'scrfd_inference', instrument)
    _observe(adaface, 'run', 'adaface_inference', instrument)
    _observe(reader, 'readtext', 'ocr', instrument)
    _observe(line_session, 'run', 'plate_line_inference', instrument)
    with _lock:
        timings = {k:dict(count=len(v), p50_ms=float(np.percentile(v, 50)),
                         p95_ms=float(np.percentile(v, 95))) for k,v in _samples.items() if v}
        inputs = dict(_inputs)
    return dict(pid=os.getpid(), observed_at=time.time(), frame_id=local.get('curr_frame_id'),
        yolo_device=yolo_device, scrfd=_providers(scrfd), adaface=_providers(adaface),
        adaface_input_devices=inputs.get('adaface_inference'),
        ocr_device=str(reader.device) if reader is not None else None,
        plate_line_ocr=_providers(line_session),
        timings=timings, audit_only=os.environ.get('DATT_EVENT_AUDIT_ONLY')=='1')
