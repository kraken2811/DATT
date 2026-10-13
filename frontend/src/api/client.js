/**
 * Unified API Client with Request Deduplication, Abort Support, and In-Memory Caching.
 * Prevents redundant fetches, React StrictMode double-invocations, and slow tab switches.
 */

import { readConnection, AUTH_REJECTED } from './connection.js';
export { getBackendBaseUrl } from './connection.js';

const inFlightRequests = new Map();
const memoryCache = new Map();
let connectionRevision = 0;
let previousIdentity = null;
let previousToken = null;
let previousSession = null;

function currentConnection() {
  const connection = readConnection();
  let sessionId = '';
  try {
    sessionId = localStorage.getItem('datt_agent_session_id');
    if (!sessionId) {
      sessionId = globalThis.crypto?.randomUUID?.() || `sess_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;
      localStorage.setItem('datt_agent_session_id', sessionId);
    }
  } catch { /* No persistent browser session available. */ }
  if (connection.identity !== previousIdentity || connection.token !== previousToken || sessionId !== previousSession) {
    previousIdentity = connection.identity;
    previousToken = connection.token;
    previousSession = sessionId;
    connectionRevision += 1;
    memoryCache.clear();
    inFlightRequests.clear();
  }
  return { ...connection, sessionId, revision: connectionRevision };
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
    staleTtlMs: customStaleTtlMs,
    swr = true,
    forceRefresh = false,
    responseType = 'auto',
    reportAuthFailure = true,
  } = options;

  const connection = currentConnection();
  const { baseUrl } = connection;
  const url = `${baseUrl}${endpoint}`;
  const isGet = method.toUpperCase() === 'GET';
  const explicitAuth = new Headers(headers).has('Authorization') || new Headers(headers).has('X-Session-Id');
  const canReuse = isGet && responseType === 'auto' && !explicitAuth;
  const cacheKey = `${connection.revision}:${method}:${url}`;

  const staleTtlMs = customStaleTtlMs ?? (cacheTtlMs > 0 ? Math.max(cacheTtlMs * 10, 60000) : 60000);
  const defaultHeaders = {
    'Accept': 'application/json',
  };
  if (connection.sessionId) {
    defaultHeaders['X-Session-Id'] = connection.sessionId;
  }
  if (connection.token) {
    defaultHeaders['Authorization'] = `Bearer ${connection.token}`;
  }
  if (body && typeof body === 'object' && !(body instanceof FormData)) {
    defaultHeaders['Content-Type'] = 'application/json';
  }

  const requestHeaders = new Headers(defaultHeaders);
  new Headers(headers).forEach((value, name) => requestHeaders.set(name, value));

  // Check cache and SWR for GET requests
  if (canReuse && !forceRefresh) {
    const cached = memoryCache.get(cacheKey);
    if (cached) {
      const age = Date.now() - cached.timestamp;
      // 1. Fresh cache hit: return immediately
      if (cacheTtlMs > 0 && age < cacheTtlMs) {
        return cached.data;
      }
      // 2. Stale cache hit (within stale window): return stale data immediately and revalidate in background
      if (swr && age < staleTtlMs) {
        if (!inFlightRequests.has(cacheKey)) {
          const bgHeaders = new Headers(requestHeaders);
          const bgPromise = (async () => {
            try {
              const bgResp = await fetch(url, {
                method,
                headers: bgHeaders,
              });
              if (bgResp.ok && currentConnection().revision === connection.revision) {
                const ct = bgResp.headers.get('content-type') || '';
                const bgData = ct.includes('application/json') ? await bgResp.json() : await bgResp.text();
                memoryCache.set(cacheKey, { data: bgData, timestamp: Date.now() });
              }
            } catch {
              // Ignore background refresh errors
            } finally {
              inFlightRequests.delete(cacheKey);
            }
          })();
          inFlightRequests.set(cacheKey, bgPromise);
        }
        return cached.data;
      }
    }
  }

  // Deduplicate in-flight GET requests
  if (canReuse && inFlightRequests.has(cacheKey) && !signal) {
    return inFlightRequests.get(cacheKey);
  }

  const fetchPromise = (async () => {
    try {
      const response = await fetch(url, {
        method,
        headers: requestHeaders,
        body: body instanceof FormData ? body : (body && typeof body === 'object' ? JSON.stringify(body) : body),
        signal,
      });

      if (!response.ok) {
        let errMessage = `HTTP ${response.status} ${response.statusText}`;
        try {
          const errJson = await response.json();
          errMessage = errJson.message || errJson.detail || errJson.error || errMessage;
        } catch {}
        const error = new Error(errMessage);
        error.status = response.status;
        if ((response.status === 401 || response.status === 403) && reportAuthFailure
            && currentConnection().revision === connection.revision) {
          globalThis.window?.dispatchEvent(new CustomEvent(AUTH_REJECTED, { detail: { status: response.status } }));
        }
        throw error;
      }

      if (currentConnection().revision !== connection.revision) {
        throw new DOMException('Connection changed', 'AbortError');
      }
      if (responseType === 'response') return response;
      const contentType = response.headers.get('content-type') || '';
      let data = null;
      if (contentType.includes('application/json')) {
        data = await response.json();
      } else {
        data = await response.text();
      }

      if (currentConnection().revision !== connection.revision) {
        throw new DOMException('Connection changed', 'AbortError');
      }
      if (canReuse && (cacheTtlMs > 0 || (swr && staleTtlMs > 0))) {
        memoryCache.set(cacheKey, {
          data,
          timestamp: Date.now(),
        });
      }

      return data;
    } finally {
      if (canReuse) {
        inFlightRequests.delete(cacheKey);
      }
    }
  })();

  if (canReuse && !signal) {
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

/**
 * Upload voice recording to backend speech-to-text service (Whisper).
 * @param {Blob|File} audioBlob - Recorded audio blob
 * @returns {Promise<{status: string, text: string, duration?: number, language?: string}>}
 */
export async function transcribeAudio(audioBlob) {
  const formData = new FormData();
  formData.append('file', audioBlob, 'recording.webm');
  return apiRequest('/api/agent/transcribe', {
    method: 'POST',
    body: formData,
  });
}
