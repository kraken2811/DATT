import { apiRequest } from './client';

export async function fetchEvents(params = {}, signal = null) {
  const query = new URLSearchParams();
  if (params.page) query.set('page', params.page);
  if (params.page_size) query.set('page_size', params.page_size);
  if (params.limit) query.set('limit', params.limit);
  if (params.search) query.set('search', params.search);
  if (params.q) query.set('q', params.q);
  if (params.event_type && params.event_type !== 'all') query.set('event_type', params.event_type);
  if (params.camera_id && params.camera_id !== 'all') query.set('camera_id', params.camera_id);
  if (params.watchlist_match !== undefined && params.watchlist_match !== 'all') {
    query.set('watchlist_match', params.watchlist_match);
  }
  if (params.plate) query.set('plate', params.plate);
  if (params.notification_status && params.notification_status !== 'all') {
    query.set('notification_status', params.notification_status);
  }
  if (params.from) query.set('from', params.from);
  if (params.to) query.set('to', params.to);
  if (params.sort) query.set('sort', params.sort);

  const qs = query.toString();
  return apiRequest(`/api/event_center/events${qs ? `?${qs}` : ''}`, {
    signal,
    cacheTtlMs: 2000,
  });
}

export async function fetchEventDetail(eventId, signal = null) {
  return apiRequest(`/api/event_center/events/${encodeURIComponent(eventId)}`, {
    signal,
    cacheTtlMs: 10000,
  });
}

export function getEventEvidenceUrl(eventId) {
  return `/api/event_center/events/${encodeURIComponent(eventId)}/evidence`;
}
