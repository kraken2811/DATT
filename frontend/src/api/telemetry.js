import { apiRequest } from './client';

export async function fetchTelemetry(signal = null) {
  try {
    return await apiRequest('/api/telemetry', {
      signal,
      cacheTtlMs: 0, // Never cache realtime telemetry
    });
  } catch (error) {
    if (error.name === 'AbortError') throw error;
    // Disconnected fallback telemetry
    return {
      status: 'DISCONNECTED',
      camera_status: 'DISCONNECTED',
      stream_alive: false,
      people_count: 0,
      car_count: 0,
      stream_fps: 0,
      processing_fps: 0,
      yolo_latency_ms: 0,
      pipeline_latency_ms: 0,
      camera_name: 'Disconnected',
      error_message: error.message || 'Cannot reach AI telemetry service',
      is_fallback: true,
    };
  }
}
