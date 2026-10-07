import { apiRequest, invalidateApiCache } from './client';

// ==========================================
// Face Watchlist (Targets)
// ==========================================

export async function fetchTargets(params = {}, signal = null) {
  const query = new URLSearchParams();
  if (params.search) query.set('search', params.search);
  if (params.q) query.set('q', params.q);
  if (params.page) query.set('page', params.page);
  if (params.page_size) query.set('page_size', params.page_size);
  const qs = query.toString();

  return apiRequest(`/api/targets${qs ? `?${qs}` : ''}`, {
    signal,
    cacheTtlMs: 3000,
  });
}

export async function registerTarget(formData) {
  invalidateApiCache('/api/targets');
  return apiRequest('/api/register_target', {
    method: 'POST',
    body: formData,
  });
}

export async function deleteTarget(targetId) {
  invalidateApiCache('/api/targets');
  return apiRequest(`/api/targets/${encodeURIComponent(targetId)}`, {
    method: 'DELETE',
  });
}

export async function toggleTargetSelection(targetId, selected) {
  invalidateApiCache('/api/targets');
  return apiRequest(`/api/targets/${encodeURIComponent(targetId)}/select`, {
    method: 'POST',
    body: { selected },
  });
}

export function getTargetImageUrl(targetId) {
  return `/api/targets/${encodeURIComponent(targetId)}/image`;
}

// ==========================================
// Vehicle Watchlist
// ==========================================

export async function fetchVehicles(params = {}, signal = null) {
  const query = new URLSearchParams();
  if (params.search) query.set('search', params.search);
  if (params.q) query.set('q', params.q);
  if (params.status && params.status !== 'all') query.set('status', params.status);
  if (params.vehicle_type && params.vehicle_type !== 'all') query.set('vehicle_type', params.vehicle_type);
  if (params.page) query.set('page', params.page);
  if (params.page_size) query.set('page_size', params.page_size);
  const qs = query.toString();

  return apiRequest(`/api/watchlist/vehicles${qs ? `?${qs}` : ''}`, {
    signal,
    cacheTtlMs: 3000,
  });
}

export async function fetchVehicleDetail(vehicleId, signal = null) {
  return apiRequest(`/api/watchlist/vehicles/${encodeURIComponent(vehicleId)}`, {
    signal,
    cacheTtlMs: 5000,
  });
}

export async function createVehicle(vehicleData) {
  invalidateApiCache('/api/watchlist/vehicles');
  return apiRequest('/api/watchlist/vehicles', {
    method: 'POST',
    body: vehicleData,
  });
}

export async function updateVehicle(vehicleId, vehicleData) {
  invalidateApiCache('/api/watchlist/vehicles');
  return apiRequest(`/api/watchlist/vehicles/${encodeURIComponent(vehicleId)}`, {
    method: 'PATCH',
    body: vehicleData,
  });
}

export async function deleteVehicle(vehicleId) {
  invalidateApiCache('/api/watchlist/vehicles');
  return apiRequest(`/api/watchlist/vehicles/${encodeURIComponent(vehicleId)}`, {
    method: 'DELETE',
  });
}

export async function fetchVehicleDetections(vehicleId, signal = null) {
  return apiRequest(`/api/watchlist/vehicles/${encodeURIComponent(vehicleId)}/detections`, {
    signal,
    cacheTtlMs: 5000,
  });
}
