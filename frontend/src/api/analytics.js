import { apiRequest } from './client';

export async function fetchHistoricalAnalytics(params = {}, signal = null) {
  const query = new URLSearchParams();
  if (params.camera_id && params.camera_id !== 'all') query.set('camera_id', params.camera_id);
  if (params.zone_id && params.zone_id !== 'all') query.set('zone_id', params.zone_id);
  if (params.object_type && params.object_type !== 'all') query.set('object_type', params.object_type);
  if (params.vehicle_class && params.vehicle_class !== 'all') query.set('vehicle_class', params.vehicle_class);
  if (params.direction && params.direction !== 'all') query.set('direction', params.direction);
  if (params.time_range) query.set('time_range', params.time_range);
  if (params.from_time) query.set('from_time', params.from_time);
  if (params.to_time) query.set('to_time', params.to_time);
  if (params.group_by) query.set('group_by', params.group_by);
  if (params.compare_with) query.set('compare_with', params.compare_with);

  const qs = query.toString();
  return apiRequest(`/api/analytics/historical${qs ? `?${qs}` : ''}`, { signal, cacheTtlMs: 20000, staleTtlMs: 300000 });
}

export async function fetchPeakHours(params = {}, signal = null) {
  const query = new URLSearchParams();
  if (params.camera_id && params.camera_id !== 'all') query.set('camera_id', params.camera_id);
  if (params.zone_id && params.zone_id !== 'all') query.set('zone_id', params.zone_id);
  if (params.object_type && params.object_type !== 'all') query.set('object_type', params.object_type);
  if (params.days_back) query.set('days_back', params.days_back);

  const qs = query.toString();
  return apiRequest(`/api/analytics/peak_hours${qs ? `?${qs}` : ''}`, { signal, cacheTtlMs: 30000, staleTtlMs: 300000 });
}

export async function fetchTomorrowForecast(params = {}, signal = null) {
  const query = new URLSearchParams();
  if (params.camera_id) query.set('camera_id', params.camera_id);
  if (params.target_date) query.set('target_date', params.target_date);
  if (params.zone_id && params.zone_id !== 'all') query.set('zone_id', params.zone_id);
  if (params.object_type && params.object_type !== 'all') query.set('object_type', params.object_type);

  const qs = query.toString();
  return apiRequest(`/api/analytics/forecast${qs ? `?${qs}` : ''}`, { signal, cacheTtlMs: 30000, staleTtlMs: 300000 });
}

export async function generateDailyForecast(signal = null) {
  return apiRequest('/api/analytics/forecast/generate', {
    method: 'POST',
    signal,
    forceRefresh: true,
  });
}

export async function fetchForecastAlerts(params = {}, signal = null) {
  const query = new URLSearchParams();
  if (params.camera_id && params.camera_id !== 'all') query.set('camera_id', params.camera_id);
  if (params.target_date) query.set('target_date', params.target_date);
  if (params.status && params.status !== 'all') query.set('status', params.status);
  if (params.page) query.set('page', params.page);
  if (params.page_size) query.set('page_size', params.page_size);

  const qs = query.toString();
  return apiRequest(`/api/analytics/alerts${qs ? `?${qs}` : ''}`, { signal, cacheTtlMs: 20000, staleTtlMs: 300000 });
}

export async function fetchCameraAnalyticsConfig(cameraId, signal = null) {
  return apiRequest(`/api/analytics/config?camera_id=${encodeURIComponent(cameraId)}`, { signal, cacheTtlMs: 30000, staleTtlMs: 300000 });
}

export async function saveCameraAnalyticsConfig(payload, signal = null) {
  return apiRequest('/api/analytics/config', {
    method: 'POST',
    body: JSON.stringify(payload),
    headers: { 'Content-Type': 'application/json' },
    signal,
    forceRefresh: true,
  });
}

export function getExportCsvUrl(params = {}) {
  const query = new URLSearchParams();
  if (params.camera_id && params.camera_id !== 'all') query.set('camera_id', params.camera_id);
  if (params.time_range) query.set('time_range', params.time_range);
  const qs = query.toString();
  return `/api/analytics/export${qs ? `?${qs}` : ''}`;
}
