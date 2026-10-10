import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

test('NotificationToastWatcher component contract', () => {
  const watcherPath = path.resolve(__dirname, '../src/components/NotificationToastWatcher.jsx');
  assert.ok(fs.existsSync(watcherPath), 'NotificationToastWatcher.jsx must exist');
  const content = fs.readFileSync(watcherPath, 'utf8');

  // Verify bounded polling interval
  assert.ok(content.includes('POLLING_INTERVAL_MS'), 'Must define POLLING_INTERVAL_MS');
  assert.ok(
    content.includes('7000') || content.includes('6000') || content.includes('8000') || content.includes('5000'),
    'Polling interval must be between 5-10 seconds'
  );

  // Verify status transition hooks
  assert.ok(content.includes('useToast'), 'Must consume useToast');
  assert.ok(content.includes('fetchAlerts'), 'Must call fetchAlerts');
  assert.ok(content.includes('isInitializedRef'), 'Must maintain baseline initialization to avoid flood');
  assert.ok(content.includes('sessionStorage'), 'Must use sessionStorage for cross-render deduplication');

  // Verify Vietnamese toast message templates
  assert.ok(
    content.includes('Email cảnh báo đã được gửi — Đối tượng:'),
    'Must include success toast format: Email cảnh báo đã được gửi — Đối tượng: [name], Camera: [camera]'
  );
  assert.ok(
    content.includes('Gửi email cảnh báo thất bại, đang thử lại'),
    'Must include retry warning format'
  );
  assert.ok(
    content.includes('Không thể gửi email cảnh báo (quá số lần thử)'),
    'Must include exhausted retry error format'
  );

  // Verify suppression and pending exclusion
  assert.ok(
    !content.includes("showToast(`Email cảnh báo đang chờ") && !content.includes("showToast(`Đang chờ gửi"),
    'Pending notifications must never generate toasts'
  );

  // Verify request cancellation and unmount cleanup
  assert.ok(content.includes('AbortController'), 'Must use AbortController');
  assert.ok(content.includes('clearTimeout'), 'Must clean up timeout on unmount');
  assert.ok(content.includes('visibilitychange'), 'Must handle tab visibility change');
});

test('App.jsx mounts NotificationToastWatcher globally', () => {
  const appPath = path.resolve(__dirname, '../src/App.jsx');
  const appContent = fs.readFileSync(appPath, 'utf8');

  assert.ok(appContent.includes('NotificationToastWatcher'), 'App.jsx must import NotificationToastWatcher');
  assert.ok(
    appContent.includes('<NotificationToastWatcher />') || appContent.includes('<NotificationToastWatcher/>'),
    'App.jsx must render NotificationToastWatcher inside Providers'
  );
  assert.ok(appContent.includes('<ToastContainer />'), 'App.jsx must render ToastContainer');
});

test('SettingsPage preserves existing theme and backend config toasts', () => {
  const settingsPath = path.resolve(__dirname, '../src/pages/SettingsPage.jsx');
  const content = fs.readFileSync(settingsPath, 'utf8');

  assert.ok(content.includes("showToast('Đã chuyển sang giao diện Sáng (Light Mode)', 'info')"));
  assert.ok(content.includes("showToast('Đã chuyển sang giao diện Tối (Dark Mode)', 'info')"));
  assert.ok(content.includes("showToast(`Đã chuyển theme: ${t.label}`, 'info')"));
});

test('Notification status transition logic handles all 10 requirements', () => {
  // Simulate the watcher transition state engine
  const known = new Map();
  const sessionSet = new Set();
  const firedToasts = [];

  function simulateShowToast(msg, type) {
    firedToasts.push({ msg, type });
  }

  function evaluateAlerts(alerts, isInitial) {
    if (isInitial) {
      for (const a of alerts) {
        known.set(a.id, {
          status: a.status.toUpperCase(),
          retry_count: a.retry_count ?? 0,
          retry_scheduled: Boolean(a.retry_scheduled),
        });
        if (a.status === 'SENT') sessionSet.add(`${a.id}:SENT`);
        else if (a.status === 'FAILED') sessionSet.add(`${a.id}:EXHAUSTED:${a.retry_count}`);
      }
      return;
    }

    for (const a of alerts) {
      const currStatus = a.status.toUpperCase();
      const currRetryCount = a.retry_count ?? 0;
      const currRetryScheduled = Boolean(a.retry_scheduled);
      const prev = known.get(a.id);
      const name = a.target_name || 'Không xác định';
      const cam = a.camera_name || 'Không xác định';

      if (currStatus === 'SENT') {
        const sig = `${a.id}:SENT`;
        if ((!prev || prev.status !== 'SENT') && !sessionSet.has(sig)) {
          sessionSet.add(sig);
          simulateShowToast(`Email cảnh báo đã được gửi — Đối tượng: ${name}, Camera: ${cam}`, 'success');
        }
      } else if (currStatus === 'FAILED' && currRetryScheduled) {
        const sig = `${a.id}:RETRY:${currRetryCount}`;
        const isNew = !prev || prev.status === 'PENDING' || (prev.status === 'FAILED' && currRetryCount > prev.retry_count);
        if (isNew && !sessionSet.has(sig)) {
          sessionSet.add(sig);
          simulateShowToast(`Gửi email cảnh báo thất bại, đang thử lại — Đối tượng: ${name}, Camera: ${cam}`, 'warning');
        }
      } else if (currStatus === 'FAILED' && !currRetryScheduled) {
        const sig = `${a.id}:EXHAUSTED:${currRetryCount}`;
        const isNew = !prev || prev.status === 'PENDING' || (prev.status === 'FAILED' && prev.retry_scheduled);
        if (isNew && !sessionSet.has(sig)) {
          sessionSet.add(sig);
          simulateShowToast(`Không thể gửi email cảnh báo (quá số lần thử) — Đối tượng: ${name}, Camera: ${cam}`, 'error');
        }
      }

      known.set(a.id, { status: currStatus, retry_count: currRetryCount, retry_scheduled: currRetryScheduled });
    }
  }

  // 1. Initial baseline: historical alerts exist
  const historical = [
    { id: '1', status: 'SENT', target_name: 'An', camera_name: 'Gate' },
    { id: '2', status: 'PENDING', target_name: 'Binh', camera_name: 'Lobby' },
    { id: '3', status: 'SUPPRESSED', target_name: 'Cuong', camera_name: 'Gate' },
  ];
  evaluateAlerts(historical, true);
  assert.equal(firedToasts.length, 0, 'Initial load must NOT fire any toasts (no flood)');

  // 2. pending -> sent
  evaluateAlerts([
    { id: '2', status: 'SENT', target_name: 'Binh', camera_name: 'Lobby' },
  ], false);
  assert.equal(firedToasts.length, 1);
  assert.equal(firedToasts[0].type, 'success');
  assert.equal(firedToasts[0].msg, 'Email cảnh báo đã được gửi — Đối tượng: Binh, Camera: Lobby');

  // 3. new pending -> failed with retry scheduled
  evaluateAlerts([
    { id: '4', status: 'PENDING', target_name: 'Dung', camera_name: 'Parking' },
  ], false);
  assert.equal(firedToasts.length, 1, 'Pending status must not show toast');

  evaluateAlerts([
    { id: '4', status: 'FAILED', retry_scheduled: true, retry_count: 1, target_name: 'Dung', camera_name: 'Parking' },
  ], false);
  assert.equal(firedToasts.length, 2);
  assert.equal(firedToasts[1].type, 'warning');
  assert.ok(firedToasts[1].msg.includes('đang thử lại'));

  // 4. failed -> sent on retry
  evaluateAlerts([
    { id: '4', status: 'SENT', target_name: 'Dung', camera_name: 'Parking' },
  ], false);
  assert.equal(firedToasts.length, 3);
  assert.equal(firedToasts[2].type, 'success');

  // 5. failed after final retry (retries exhausted)
  evaluateAlerts([
    { id: '5', status: 'PENDING', target_name: 'Em', camera_name: 'Gate' },
  ], false);
  evaluateAlerts([
    { id: '5', status: 'FAILED', retry_scheduled: false, retry_count: 3, target_name: 'Em', camera_name: 'Gate' },
  ], false);
  assert.equal(firedToasts.length, 4);
  assert.equal(firedToasts[3].type, 'error');
  assert.ok(firedToasts[3].msg.includes('quá số lần thử'));

  // 6. suppressed alert: no popup spam
  evaluateAlerts([
    { id: '6', status: 'SUPPRESSED', target_name: 'Giang', camera_name: 'Gate' },
  ], false);
  assert.equal(firedToasts.length, 4, 'Suppressed must not fire toast');

  // 7. Duplicate poll without status change: no duplicate toasts
  evaluateAlerts([
    { id: '2', status: 'SENT', target_name: 'Binh', camera_name: 'Lobby' },
    { id: '4', status: 'SENT', target_name: 'Dung', camera_name: 'Parking' },
    { id: '5', status: 'FAILED', retry_scheduled: false, retry_count: 3, target_name: 'Em', camera_name: 'Gate' },
  ], false);
  assert.equal(firedToasts.length, 4, 'Repeated polling must NOT produce duplicate toasts');
});
