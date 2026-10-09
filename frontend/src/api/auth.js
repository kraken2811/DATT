import { apiRequest } from './client.js';
import { assertSecureTokenDestination, normalizeAuthToken, saveAuthToken } from './connection.js';

export async function verifyAndSaveAuthToken(value) {
  assertSecureTokenDestination();
  const token = normalizeAuthToken(value);
  const response = await apiRequest('/api/agent/conversations?limit=1', {
    headers: { Authorization: `Bearer ${token}` },
    reportAuthFailure: false,
  });
  if (response?.status !== 'success' || !response.user_id) {
    throw new Error('Máy chủ chưa xác nhận tài khoản; token chưa được lưu.');
  }
  saveAuthToken(token);
  return response.user_id;
}
