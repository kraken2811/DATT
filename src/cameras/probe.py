"""Bounded source decoder probe, isolated from backend and model processes."""
import json
import subprocess
import sys
import time
from .service import TYPES, validate_source


def probe(kind,source,timeout=10):
    start=time.monotonic()
    try:
        kind=TYPES[kind.lower()];validate_source(kind,source)
    except (ValueError,KeyError,AttributeError):
        return dict(status='error',success=False,code='INVALID_SOURCE',latency_ms=0)
    try:
        result=subprocess.run([sys.executable,'-m','src.cameras.probe'],input=json.dumps({'type':kind,'source':source}),
            capture_output=True,text=True,timeout=timeout)
        success=result.returncode==0
        code='FRAME_READ' if success else 'SOURCE_UNREADABLE'
    except subprocess.TimeoutExpired: success=False;code='TIMEOUT'
    except OSError: success=False;code='PROBE_UNAVAILABLE'
    return dict(status='ok' if success else 'error',success=success,code=code,
                latency_ms=round((time.monotonic()-start)*1000))


def main():
    data=json.load(sys.stdin);source=data['source'];kind=data['type']
    try:
        if kind=='file':
            from src.storage import get_storage
            source=str(get_storage().materialize(source))
        if kind=='youtube':
            import yt_dlp
            with yt_dlp.YoutubeDL({'quiet':True,'no_warnings':True,'socket_timeout':5,'format':'best[ext=mp4]/best'}) as ydl:
                source=ydl.extract_info(source,download=False)['url']
        if kind=='cctv':
            import requests,io
            from PIL import Image
            with requests.get(source,timeout=5,stream=True) as response:
                response.raise_for_status()
                if response.headers.get('Content-Type','').startswith('image/'):
                    blob=response.raw.read(5*1024*1024+1)
                    if len(blob)>5*1024*1024: return 1
                    image=Image.open(io.BytesIO(blob));image.load()
                    if data.get('thumbnail'):
                        image=image.convert('RGB');image.thumbnail((320,180));out=io.BytesIO();image.save(out,format='JPEG');sys.stdout.buffer.write(out.getvalue())
                    return 0
        import cv2
        reader=cv2.VideoCapture(source)
        try:
            ok,frame=reader.read()
            if not ok or frame is None:return 1
            if data.get('thumbnail'):
                frame=cv2.resize(frame,(320,180));encoded,blob=cv2.imencode('.jpg',frame)
                if not encoded:return 1
                sys.stdout.buffer.write(blob.tobytes())
            return 0
        finally: reader.release()
    except Exception: return 1


if __name__=='__main__': sys.exit(main())
