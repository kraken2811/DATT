import time
import httpx

client = httpx.Client(timeout=15.0)
req = client.build_request('GET', 'http://127.0.0.1:8501/video_feed')
resp = client.send(req, stream=True)
print('Video feed status:', resp.status_code)
print('Content-Type:', resp.headers.get('content-type'))

chunks = 0
bytes_read = 0
t0 = time.time()
for chunk in resp.iter_bytes():
    chunks += 1
    bytes_read += len(chunk)
    if chunks >= 20 or (time.time() - t0) > 4.0:
        break

print(f"Successfully received {chunks} MJPEG stream chunks ({bytes_read} bytes in {time.time()-t0:.2f}s)")
resp.close()
client.close()
