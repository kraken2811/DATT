import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const watcher = fs.readFileSync(path.join(root,'src/components/NotificationToastWatcher.jsx'), 'utf8');
const events = fs.readFileSync(path.join(root,'src/api/events.js'), 'utf8');
const app = fs.readFileSync(path.join(root,'src/App.jsx'), 'utf8');

test('watchlist alerts must not wait for SMTP', () => {
  assert.match(watcher, /fetchEvents/);
  assert.match(watcher, /watchlist_match: 'true'/);
  assert.doesNotMatch(watcher, /fetchAlerts|currStatus === 'SENT'/);
  assert.match(watcher, /POLLING_INTERVAL_MS = 2000/);
});
test('face names and vehicle plates are rendered independently', () => {
  assert.match(watcher, /event\.event_type === 'face'/);
  assert.match(watcher, /event\.target_name/);
  assert.match(watcher, /event\.event_type === 'plate'/);
  assert.match(watcher, /event\.plate/);
  assert.match(watcher, /Người:/);
  assert.match(watcher, /Xe:/);
  assert.doesNotMatch(watcher, /target_name \|\|.*plate/);
});
test('fresh polling bypasses API cache', () => {
  assert.match(events, /forceRefresh: options\.forceRefresh \?\? false/);
  assert.match(watcher, /forceRefresh: true/);
});
test('deduplication and historical baseline remain active', () => {
  assert.match(watcher, /localStorage/);
  assert.match(watcher, /navigator.locks.request/);
  assert.match(watcher, /evaluateWatchlistPopupBatch/);
  assert.match(watcher, /initializedRef/);
  assert.match(watcher, /seen\.has/);
  assert.match(watcher, /AbortController/);
  assert.match(watcher, /visibilitychange/);
});
test('global watcher is mounted', () => {
  assert.match(app, /<NotificationToastWatcher\s*\/>/);
  assert.match(app, /<ToastContainer\s*\/>/);
});
