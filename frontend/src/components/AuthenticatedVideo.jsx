import React, { useEffect, useRef } from 'react';
import { apiRequest } from '../api/client';
import { FrameStreamParser } from '../api/frameStream';
import { useApp } from '../context/AppContext';

// Fetch can attach Bearer headers; an img src cannot. Never put credentials in URLs.
export function AuthenticatedVideo({ cameraId, id, label }) {
  const canvasRef = useRef(null);
  const { connectionRevision, authenticationStatus } = useApp();
  useEffect(() => {
    const controller = new AbortController();
    let active = true, timer = null;
    const canvas = canvasRef.current;
    const clear = () => canvas?.getContext('2d')?.clearRect(0, 0, canvas.width, canvas.height);
    clear();
    if (authenticationStatus) return () => { active = false; controller.abort(); };
    const stream = async () => {
      let reader;
      try {
        const response = await apiRequest('/api/frame_stream', { responseType: 'response', signal: controller.signal });
        if (response.headers.get('X-DATT-Frame-Protocol') !== '1' || !response.body) throw new Error('Frame stream unavailable');
        reader = response.body.getReader();
        const parser = new FrameStreamParser();
        let paintedAt = 0;
        while (active) {
          const { value, done } = await reader.read();
          if (done) break;
          const packet = parser.push(value);
          if (!packet) {
            if (paintedAt && Date.now() - paintedAt > 3000 && active) clear();
            continue;
          }
          if (Number(packet.metrics.frame_age_ms) > 3000) { if (active) clear(); continue; }
          const image = await createImageBitmap(packet.blob);
          try {
            if (!active) break;
            canvas.width = image.width; canvas.height = image.height;
            canvas.getContext('2d').drawImage(image, 0, 0);
            paintedAt = Date.now();
          } finally { image.close(); }
        }
        if (active) clear();
        if (active) timer = setTimeout(stream, 1000);
      } catch (error) {
        if (active) clear();
        if (active && error.name !== 'AbortError' && error.status !== 401 && error.status !== 403) {
          timer = setTimeout(stream, 1000);
        }
      } finally {
        if (reader) { await reader.cancel().catch(() => {}); reader.releaseLock(); }
      }
    };
    stream();
    return () => { active = false; clearTimeout(timer); controller.abort(); clear(); };
  }, [cameraId, connectionRevision, authenticationStatus]);
  return <canvas ref={canvasRef} id={id} className="stream-img" role="img" aria-label={label} />;
}
