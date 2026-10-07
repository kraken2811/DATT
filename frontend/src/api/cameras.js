import { apiRequest, invalidateApiCache } from './client';

export async function fetchCameras(params = {}, signal = null) {
  const query = new URLSearchParams();
  if (params.search) query.set('search', params.search);
  if (params.q) query.set('q', params.q);
  if (params.status && params.status !== 'all') query.set('status', params.status);
  if (params.zone && params.zone !== 'all') query.set('zone', params.zone);
  if (params.source_type && params.source_type !== 'all') query.set('source_type', params.source_type);
  if (params.page) query.set('page', params.page);
  if (params.page_size) query.set('page_size', params.page_size);

  const qs = query.toString();
  return apiRequest(`/api/cameras${qs ? `?${qs}` : ''}`, {
    signal,
    cacheTtlMs: 5000,
  });
}

export async function fetchCameraDetail(id, signal = null) {
  return apiRequest(`/api/cameras/${encodeURIComponent(id)}`, {
    signal,
    cacheTtlMs: 5000,
  });
}

export async function switchCamera(payload, signal = null) {
  invalidateApiCache('/api/cameras');
  invalidateApiCache('/telemetry');
  return apiRequest('/switch_camera', {
    method: 'POST',
    body: payload,
    signal,
  });
}

export async function stopCamera(signal = null) {
  invalidateApiCache('/telemetry');
  return apiRequest('/stop_camera', {
    method: 'POST',
    signal,
  });
}

export async function fetchPublicCameras(params = {}, signal = null) {
  const query = new URLSearchParams();
  if (params.q) query.set('q', params.q);
  if (params.provider) query.set('provider', params.provider);
  const qs = query.toString();
  return apiRequest(`/public_cameras${qs ? `?${qs}` : ''}`, {
    signal,
    cacheTtlMs: 30000, // Cache public cameras for 30s
  });
}

export async function fetchVideoSources(signal = null) {
  return apiRequest('/video_sources', {
    signal,
    cacheTtlMs: 5000,
  });
}

export async function uploadVideo(formData, signal = null) {
  invalidateApiCache('/video_sources');
  return apiRequest('/upload_video', {
    method: 'POST',
    body: formData,
    signal,
  });
}

export async function testCameraConnection(sourceType, sourceUrl) {
  return apiRequest('/api/camera_management/test_connection', {
    method: 'POST',
    body: { source_type: sourceType, source_url: sourceUrl },
  });
}

export async function createCamera(cameraData) {
  invalidateApiCache('/api/cameras');
  return apiRequest('/api/cameras', {
    method: 'POST',
    body: cameraData,
  });
}

export async function updateCamera(id, cameraData) {
  invalidateApiCache('/api/cameras');
  return apiRequest(`/api/cameras/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    body: cameraData,
  });
}

export async function deleteCamera(id) {
  invalidateApiCache('/api/cameras');
  return apiRequest(`/api/cameras/${encodeURIComponent(id)}`, {
    method: 'DELETE',
  });
}

export async function toggleCameraStatus(id, enabled) {
  invalidateApiCache('/api/cameras');
  return apiRequest(`/api/cameras/${encodeURIComponent(id)}/${enabled ? 'enable' : 'disable'}`, {
    method: 'POST',
  });
}
