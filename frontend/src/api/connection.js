export const CONNECTION_CHANGED = 'datt-connection-changed';
export const AUTH_REJECTED = 'datt-auth-rejected';

export function getBackendBaseUrl() {
  try {
    return (localStorage.getItem('datt_backend_url') || '').trim().replace(/\/$/, '');
  } catch { return ''; }
}

function backendIdentity(base = getBackendBaseUrl()) {
  const origin = globalThis.location?.origin || 'http://localhost';
  const url = new URL(base || origin, origin);
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash) {
    throw new Error('Địa chỉ backend phải là HTTP/HTTPS, không chứa thông tin đăng nhập, query hoặc fragment.');
  }
  return url.href.replace(/\/$/, '');
}

function allowedTokenDestination(identity) {
  const url = new URL(identity);
  return url.protocol === 'https:' || ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname);
}

export function readConnection() {
  const baseUrl = getBackendBaseUrl();
  const identity = backendIdentity(baseUrl);
  let token = '';
  try {
    const stored = localStorage.getItem('datt_auth_token') || '';
    const scope = localStorage.getItem('datt_auth_token_scope');
    // Legacy tokens are usable on this origin only; never forward one to a new server.
    const sameOrigin = new URL(identity).origin === (globalThis.location?.origin || 'http://localhost');
    if (allowedTokenDestination(identity) && (scope === identity || (!scope && sameOrigin))) token = stored;
  } catch { /* Storage unavailable: do not claim an authenticated connection. */ }
  return { baseUrl, identity, token };
}

export function notifyConnectionChanged() {
  globalThis.window?.dispatchEvent(new Event(CONNECTION_CHANGED));
}

export function setBackendBaseUrl(value) {
  const identity = backendIdentity(value.trim());
  localStorage.setItem('datt_backend_url', identity);
  notifyConnectionChanged();
}

export function normalizeAuthToken(value) {
  const token = value.trim().replace(/^Bearer\s+/i, '');
  if (!token || /\s/.test(token)) throw new Error('Nhập Bearer token của tài khoản đã được cấp quyền.');
  return token;
}

export function saveAuthToken(value) {
  const token = normalizeAuthToken(value);
  const { identity } = readConnection();
  if (!allowedTokenDestination(identity)) throw new Error('Dùng HTTPS để gửi token; HTTP chỉ được dùng trên localhost.');
  // Remove the old token before changing its recipient. Failed writes fail closed.
  localStorage.removeItem('datt_auth_token');
  try {
    localStorage.setItem('datt_auth_token_scope', identity);
    localStorage.setItem('datt_auth_token', token);
  } finally { notifyConnectionChanged(); }
}

export function clearAuthToken() {
  localStorage.removeItem('datt_auth_token');
  localStorage.removeItem('datt_auth_token_scope');
  notifyConnectionChanged();
}

export function assertSecureTokenDestination() {
  if (!allowedTokenDestination(readConnection().identity)) {
    throw new Error('Dùng HTTPS để gửi token; HTTP chỉ được dùng trên localhost.');
  }
}
