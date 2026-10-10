import { apiRequest } from './client';

export async function fetchAlerts(params = {}, signal = null, options = {}) {
  const query = new URLSearchParams();
  if (params.search) query.set('search', params.search);
  if (params.q) query.set('q', params.q);
  if (params.status && params.status !== 'all') query.set('status', params.status);
  if (params.event_type && params.event_type !== 'all') query.set('event_type', params.event_type);
  if (params.camera_id && params.camera_id !== 'all') query.set('camera_id', params.camera_id);
  if (params.page) query.set('page', params.page);
  if (params.page_size) query.set('page_size', params.page_size);

  const qs = query.toString();
  return apiRequest(`/api/alerts${qs ? `?${qs}` : ''}`, {
    signal,
    cacheTtlMs: options.cacheTtlMs ?? 5000,
    staleWhileRevalidateMs: options.staleWhileRevalidateMs ?? 30000,
    forceRefresh: options.forceRefresh ?? false,
  });
}

export async function fetchAlertDetail(alertId, signal = null) {
  return apiRequest(`/api/alerts/${encodeURIComponent(alertId)}`, {
    signal,
    cacheTtlMs: 10000,
    staleWhileRevalidateMs: 30000,
  });
}
