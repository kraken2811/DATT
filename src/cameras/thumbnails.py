"""Bounded, cached camera previews using the same isolated source probe."""
from collections import OrderedDict
import json,subprocess,sys,threading,time
from src.stream.thumbnail_service import CLEAN_PLACEHOLDER_SVG

_cache=OrderedDict()
_lock=threading.Lock()
_slots=threading.BoundedSemaphore(2)

def thumbnail_bytes(camera):
    if not camera['enabled']:return CLEAN_PLACEHOLDER_SVG,'image/svg+xml'
    key=(camera['id'],camera['source_type'],camera['source_url'])
    with _lock:
        old=_cache.get(key)
        if old and time.monotonic()-old[0]<90:return old[1],old[2]
    if not _slots.acquire(timeout=.1):return CLEAN_PLACEHOLDER_SVG,'image/svg+xml'
    try:
        data,kind=CLEAN_PLACEHOLDER_SVG,'image/svg+xml'
        result=subprocess.run([sys.executable,'-m','src.cameras.probe'],input=json.dumps({
            'type':camera['source_type'],'source':camera['source_url'],'thumbnail':True}).encode(),capture_output=True,timeout=10)
        if result.returncode==0 and result.stdout.startswith(b'\xff\xd8') and len(result.stdout)<=1024*1024:
            data,kind=result.stdout,'image/jpeg'
        with _lock:
            _cache[key]=(time.monotonic(),data,kind);_cache.move_to_end(key)
            while len(_cache)>128:_cache.popitem(last=False)
        return data,kind
    except (subprocess.TimeoutExpired,OSError):return CLEAN_PLACEHOLDER_SVG,'image/svg+xml'
    finally:_slots.release()
