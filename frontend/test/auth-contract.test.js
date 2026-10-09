import test, { beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import { apiRequest } from '../src/api/client.js';
import { fetchTelemetry } from '../src/api/telemetry.js';
import { readConnection, saveAuthToken, clearAuthToken, setBackendBaseUrl, AUTH_REJECTED } from '../src/api/connection.js';
import { verifyAndSaveAuthToken } from '../src/api/auth.js';
import { FrameStreamParser } from '../src/api/frameStream.js';

beforeEach(() => {
  const storage = new Map();
  globalThis.localStorage = { getItem: key => storage.get(key) ?? null,
    setItem: (key, value) => storage.set(key, String(value)), removeItem: key => storage.delete(key) };
  globalThis.location = { origin: 'https://ui.example.test' };
  globalThis.window = new EventTarget();
});
const json = (data, status = 200) => new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } });

test('scoped token and stable session accompany operational requests', async () => {
  saveAuthToken('Bearer test-user:signature');
  let seen;
  globalThis.fetch = async (url, options) => { seen = { url, options }; return json({ ok: true }); };
  await apiRequest('/api/telemetry');
  assert.equal(seen.options.headers.get('Authorization'), 'Bearer test-user:signature');
  assert.equal(seen.options.headers.get('X-Session-Id'), localStorage.getItem('datt_agent_session_id'));
  assert.equal(seen.url, '/api/telemetry');
  assert.ok(!seen.url.includes('signature'));
});

for (const status of [401, 403]) test(`telemetry preserves ${status} as authentication failure`, async () => {
  globalThis.fetch = async () => json({ detail: 'Denied' }, status);
  let reported;
  window.addEventListener(AUTH_REJECTED, event => { reported = event.detail; });
  await assert.rejects(fetchTelemetry(), error => error.status === status);
  assert.deepEqual(reported, { status });
});

test('unavailable telemetry is null; verified zero remains zero', async () => {
  globalThis.fetch = async () => { throw new TypeError('Network unavailable'); };
  const unavailable = await fetchTelemetry();
  assert.equal(unavailable.people_count, null);
  assert.equal(unavailable.car_count, null);
  assert.equal(unavailable.is_fallback, true);
  globalThis.fetch = async () => json({ people_count: 0, car_count: 0 });
  assert.deepEqual(await fetchTelemetry(), { people_count: 0, car_count: 0 });
});

test('cache works within one account but does not cross account changes', async () => {
  let calls = 0;
  globalThis.fetch = async (_, options) => { calls++; return json({ user: options.headers.get('Authorization') }); };
  saveAuthToken('user-a:signature');
  const a = await apiRequest('/api/private', { cacheTtlMs: 60000 });
  assert.deepEqual(await apiRequest('/api/private', { cacheTtlMs: 60000 }), a);
  assert.equal(calls, 1);
  saveAuthToken('user-b:signature');
  assert.equal((await apiRequest('/api/private', { cacheTtlMs: 60000 })).user, 'Bearer user-b:signature');
  assert.equal(calls, 2);
});

test('anonymous session changes and logout invalidate private cached data', async () => {
  let calls = 0;
  globalThis.fetch = async (_, options) => { calls++; return json({ session: options.headers.get('X-Session-Id') }); };
  await apiRequest('/api/private', { cacheTtlMs: 60000 });
  localStorage.setItem('datt_agent_session_id', 'another-session');
  assert.equal((await apiRequest('/api/private', { cacheTtlMs: 60000 })).session, 'another-session');
  assert.equal(calls, 2);
  saveAuthToken('user-a:signature');
  await apiRequest('/api/private', { cacheTtlMs: 60000 });
  clearAuthToken();
  await apiRequest('/api/private', { cacheTtlMs: 60000 });
  assert.equal(calls, 4);
});

test('old in-flight account response cannot populate a new account cache', async () => {
  saveAuthToken('user-a:signature');
  let finish;
  globalThis.fetch = () => new Promise(resolve => { finish = resolve; });
  const stale = apiRequest('/api/private', { cacheTtlMs: 60000 });
  saveAuthToken('user-b:signature');
  finish(json({ private: 'account-a' }));
  await assert.rejects(stale, error => error.name === 'AbortError');
  globalThis.fetch = async () => json({ private: 'account-b' });
  assert.deepEqual(await apiRequest('/api/private', { cacheTtlMs: 60000 }), { private: 'account-b' });
});

test('token is never forwarded to a different backend; legacy tokens stay on this origin', async () => {
  localStorage.setItem('datt_auth_token', 'legacy:signature');
  assert.equal(readConnection().token, 'legacy:signature');
  setBackendBaseUrl('https://other.example.test');
  assert.equal(readConnection().token, '');
  saveAuthToken('other:signature');
  assert.equal(readConnection().token, 'other:signature');
  setBackendBaseUrl('https://third.example.test');
  assert.equal(readConnection().token, '');
});

test('verification stores only a server-confirmed account and scopes its token', async () => {
  let seen;
  globalThis.fetch = async (_, options) => { seen = options.headers.get('Authorization'); return json({ status: 'success', user_id: 'verified-user' }); };
  assert.equal(await verifyAndSaveAuthToken('Bearer verified-user:signature'), 'verified-user');
  assert.equal(seen, 'Bearer verified-user:signature');
  assert.equal(localStorage.getItem('datt_auth_token_scope'), location.origin);
  assert.equal(readConnection().token, 'verified-user:signature');
});

for (const status of [401, 403, 503]) test(`failed verification (${status}) does not replace the current token`, async () => {
  saveAuthToken('old-user:signature');
  globalThis.fetch = async () => json({ detail: 'Rejected' }, status);
  let eventCount = 0;
  window.addEventListener(AUTH_REJECTED, () => { eventCount++; });
  await assert.rejects(verifyAndSaveAuthToken('candidate:signature'));
  assert.equal(readConnection().token, 'old-user:signature');
  assert.equal(eventCount, 0);
});

test('HTTP 200 without verified user is not a successful login', async () => {
  globalThis.fetch = async () => json({ status: 'success' });
  await assert.rejects(verifyAndSaveAuthToken('candidate:signature'));
  assert.equal(localStorage.getItem('datt_auth_token'), null);
});

test('insecure remote token destination is refused before transmission', async () => {
  setBackendBaseUrl('http://remote.example.test');
  globalThis.fetch = () => assert.fail('Never transmit a token on remote HTTP');
  await assert.rejects(verifyAndSaveAuthToken('user:signature'), /HTTPS/);
  assert.equal(readConnection().token, '');
});

test('storage failure cannot rebind an old token to another server', () => {
  saveAuthToken('old:signature');
  setBackendBaseUrl('https://other.example.test');
  const set = localStorage.setItem;
  localStorage.setItem = (key, value) => { if (key === 'datt_auth_token') throw new Error('Storage full'); set(key, value); };
  assert.throws(() => saveAuthToken('new:signature'), /Storage full/);
  assert.equal(readConnection().token, '');
});

test('unsafe backend URL forms are rejected', () => {
  for (const value of ['javascript:alert(1)', 'https://user:password@example.test', 'https://example.test?secret=x', 'https://example.test#secret']) {
    assert.throws(() => setBackendBaseUrl(value));
  }
});

function packet(id, jpeg = new Uint8Array([id])) {
  const metadata = new TextEncoder().encode(JSON.stringify({ frame_id: id }));
  const bytes = new Uint8Array(8 + metadata.length + jpeg.length);
  new DataView(bytes.buffer).setUint32(0, metadata.length);
  new DataView(bytes.buffer).setUint32(4, jpeg.length);
  bytes.set(metadata, 8); bytes.set(jpeg, 8 + metadata.length);
  return bytes;
}

test('existing stream protocol handles fragmentation and retains the latest JPEG', async () => {
  const parser = new FrameStreamParser();
  const first = packet(1), second = packet(2);
  assert.equal(parser.push(first.slice(0, 7)), null);
  const remaining = new Uint8Array(first.length - 7 + second.length);
  remaining.set(first.slice(7)); remaining.set(second, first.length - 7);
  const latest = parser.push(remaining);
  assert.equal(latest.metrics.frame_id, 2);
  assert.deepEqual(new Uint8Array(await latest.blob.arrayBuffer()), new Uint8Array([2]));
  assert.equal(parser.pending.length, 0);
});

test('stream heartbeat has no image; oversized packets are rejected', () => {
  const parser = new FrameStreamParser();
  assert.equal(parser.push(packet(0, new Uint8Array())), null);
  const invalid = new Uint8Array(8);
  new DataView(invalid.buffer).setUint32(0, 65537);
  assert.throws(() => parser.push(invalid), /lengths/);
});
