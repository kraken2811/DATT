/**
 * Unified API Client with Request Deduplication, Abort Support, and In-Memory Caching.
 * Prevents redundant fetches, React StrictMode double-invocations, and slow tab switches.
 */

const inFlightRequests = new Map();
const memoryCache = new Map();

export function getBackendBaseUrl() {
  try {
    const saved = localStorage.getItem('datt_backend_url');
    if (saved && saved.trim()) return saved.trim().replace(/\/$/, '');
  } catch (e) {}
  return '';
}

/**
 * Execute an HTTP request with deduplication and caching support.
 *
 * @param {string} endpoint - API endpoint (e.g. '/api/cameras')
 * @param {object} options - Fetch options (method, headers, body, signal, cacheTtlMs, forceRefresh)
 */
export async function apiRequest(endpoint, options = {}) {
  const {
    method = 'GET',
    headers = {},
    body = null,
    signal = null,
    cacheTtlMs = 0,
    forceRefresh = false,
  } = options;

  const baseUrl = getBackendBaseUrl();
  const url = `${baseUrl}${endpoint}`;
  const isGet = method.toUpperCase() === 'GET';
  const cacheKey = `${method}:${url}`;

  // Check cache for GET requests
  if (isGet && cacheTtlMs > 0 && !forceRefresh) {
    const cached = memoryCache.get(cacheKey);
    if (cached && Date.now() - cached.timestamp < cacheTtlMs) {
      return cached.data;
    }
  }

  // Deduplicate in-flight GET requests
  if (isGet && inFlightRequests.has(cacheKey) && !signal) {
    return inFlightRequests.get(cacheKey);
  }

  let clientSessionId = '';
  let clientAuthToken = null;
  try {
    clientSessionId = localStorage.getItem('datt_agent_session_id');
    if (!clientSessionId) {
      clientSessionId = (typeof crypto !== 'undefined' && crypto.randomUUID)
        ? crypto.randomUUID()
        : `sess_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;
      localStorage.setItem('datt_agent_session_id', clientSessionId);
    }
    clientAuthToken = localStorage.getItem('datt_auth_token');
  } catch (e) {}

  const defaultHeaders = {
    'Accept': 'application/json',
  };
  if (clientSessionId) {
    defaultHeaders['X-Session-Id'] = clientSessionId;
  }
  if (clientAuthToken) {
    defaultHeaders['Authorization'] = `Bearer ${clientAuthToken}`;
  }
  if (body && typeof body === 'object' && !(body instanceof FormData)) {
    defaultHeaders['Content-Type'] = 'application/json';
  }

  const fetchPromise = (async () => {
    try {
      const response = await fetch(url, {
        method,
        headers: { ...defaultHeaders, ...headers },
        body: body instanceof FormData ? body : (body && typeof body === 'object' ? JSON.stringify(body) : body),
        signal,
      });

      if (!response.ok) {
        let errMessage = `HTTP ${response.status} ${response.statusText}`;
        try {
          const errJson = await response.json();
          errMessage = errJson.message || errJson.detail || errJson.error || errMessage;
        } catch (e) {}
        const error = new Error(errMessage);
        error.status = response.status;
        throw error;
      }

      const contentType = response.headers.get('content-type') || '';
      let data = null;
      if (contentType.includes('application/json')) {
        data = await response.json();
      } else {
        data = await response.text();
      }

      if (isGet && cacheTtlMs > 0) {
        memoryCache.set(cacheKey, {
          data,
          timestamp: Date.now(),
        });
      }

      return data;
    } finally {
      if (isGet) {
        inFlightRequests.delete(cacheKey);
      }
    }
  })();

  if (isGet && !signal) {
    inFlightRequests.set(cacheKey, fetchPromise);
  }

  return fetchPromise;
}

export function invalidateApiCache(prefix = '') {
  if (!prefix) {
    memoryCache.clear();
    return;
  }
  for (const key of memoryCache.keys()) {
    if (key.includes(prefix)) {
      memoryCache.delete(key);
    }
  }
}
