import { apiRequest } from './client.js';

export async function fetchTelemetry(signal = null) {
  try {
    return await apiRequest('/api/telemetry', {
      signal,
      cacheTtlMs: 0, // Never cache realtime telemetry
    });
  } catch (error) {
    if (error.name === 'AbortError') throw error;
    if (error.status === 401 || error.status === 403) throw error;
    // Disconnected fallback telemetry
    return {
      status: 'DISCONNECTED',
      camera_status: 'DISCONNECTED',
      stream_alive: false,
      people_count: null,
      car_count: null,
      stream_fps: null,
      processing_fps: null,
      yolo_latency_ms: null,
      pipeline_latency_ms: null,
      camera_name: 'Disconnected',
      error_message: error.message || 'Cannot reach AI telemetry service',
      is_fallback: true,
    };
  }
}
