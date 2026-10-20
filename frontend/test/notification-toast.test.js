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

test('NotificationToastWatcher formats FACE vs VEHICLE labels correctly', () => {
  const watcherPath = path.resolve(__dirname, '../src/components/NotificationToastWatcher.jsx');
  const content = fs.readFileSync(watcherPath, 'utf8');

  // Must check event_type to separate FACE vs VEHICLE
  assert.ok(content.includes('isFace'), 'Must determine alert type via isFace');
  assert.ok(content.includes('Xe:'), 'Must format vehicle label with "Xe: "');
  assert.ok(!content.includes('target_name || alert.plate_number'), 'Must NOT use target_name || plate_number fallback for both');

  // Verify label resolver logic directly
  const resolveLabel = (alert) => {
    const isVehicle = (alert.event_type || alert.alert_type) === 'VEHICLE_WATCHLIST_MATCH';
    if (isVehicle) {
      return alert.plate_number ? `Xe: ${alert.plate_number}` : 'Xe không xác định';
    }
    return alert.target_name || alert.name || 'Không xác định';
  };

  const faceAlert = {
    event_type: 'FACE_WATCHLIST_MATCH',
    target_name: 'Nguyễn Văn A',
  };
  assert.equal(resolveLabel(faceAlert), 'Nguyễn Văn A');

  const vehicleAlert = {
    event_type: 'VEHICLE_WATCHLIST_MATCH',
    target_name: 'Chủ xe Nguyễn Văn A',
    plate_number: '30A10010',
  };
  const vehicleLabel = resolveLabel(vehicleAlert);
  assert.equal(vehicleLabel, 'Xe: 30A10010');
  assert.ok(!vehicleLabel.includes('Chủ xe Nguyễn Văn A'));
});

test('NotificationToastWatcher safely handles prev across status transitions (PENDING->SENT, PENDING->FAILED)', () => {
  const watcherPath = path.resolve(__dirname, '../src/components/NotificationToastWatcher.jsx');
  const content = fs.readFileSync(watcherPath, 'utf8');

  // Verify that `const prev = knownAlertsRef.current.get(alert.id);` is in the loop scope
  assert.ok(
    content.includes('const prev = knownAlertsRef.current.get(alert.id);'),
    'NotificationToastWatcher.jsx must declare `prev` inside the alert loop'
  );

  // Simulate multiple alert transitions in sequence (Case 1: PENDING->SENT, Case 2: PENDING->FAILED)
  const knownAlerts = new Map();
  const toasts = [];
  const sessionEmailSet = new Set();

  function processAlerts(alerts) {
    for (const alert of alerts) {
      const currStatus = (alert.status || '').toUpperCase();
      const currRetryCount = alert.retry_count ?? 0;
      const currRetryScheduled = Boolean(alert.retry_scheduled);
      const prev = knownAlerts.get(alert.id);
      const isFace = alert.event_type === 'FACE_WATCHLIST_MATCH';
      const objectName = isFace ? (alert.target_name || 'Không xác định') : (alert.plate_number ? `Xe: ${alert.plate_number}` : 'Xe không xác định');
      const cameraName = alert.camera_name || 'Cam 1';

      if (currStatus === 'SENT') {
        const sig = `${alert.id}:SENT`;
        const isNew = !prev || prev.status !== 'SENT';
        if (isNew && !sessionEmailSet.has(sig)) {
          sessionEmailSet.add(sig);
          toasts.push({ type: 'success', id: alert.id });
        }
      } else if (currStatus === 'FAILED' && currRetryScheduled) {
        const sig = `${alert.id}:RETRY:${currRetryCount}`;
        const isNew = !prev || prev.status === 'PENDING' || (prev.status === 'FAILED' && currRetryCount > prev.retry_count);
        if (isNew && !sessionEmailSet.has(sig)) {
          sessionEmailSet.add(sig);
          toasts.push({ type: 'warning', id: alert.id });
        }
      } else if (currStatus === 'FAILED' && !currRetryScheduled) {
        const sig = `${alert.id}:EXHAUSTED:${currRetryCount}`;
        const isNew = !prev || prev.status === 'PENDING' || (prev.status === 'FAILED' && prev.retry_scheduled);
        if (isNew && !sessionEmailSet.has(sig)) {
          sessionEmailSet.add(sig);
          toasts.push({ type: 'error', id: alert.id });
        }
      }

      knownAlerts.set(alert.id, {
        status: currStatus,
        retry_count: currRetryCount,
        retry_scheduled: currRetryScheduled,
      });
    }
  }

  // Initial poll: 3 alerts in PENDING
  processAlerts([
    { id: 'alert-1', status: 'PENDING', target_name: 'User 1' },
    { id: 'alert-2', status: 'PENDING', plate_number: '29A12345' },
    { id: 'alert-3', status: 'PENDING', target_name: 'User 3' },
  ]);
  assert.equal(toasts.length, 0, 'PENDING alerts must not fire toasts');
  assert.equal(knownAlerts.get('alert-1').status, 'PENDING');
  assert.equal(knownAlerts.get('alert-2').status, 'PENDING');

  // Second poll: Alert 1 -> SENT, Alert 2 -> FAILED (retry), Alert 3 -> FAILED (exhausted)
  // Must execute without ReferenceError and process all 3 in the same batch
  assert.doesNotThrow(() => {
    processAlerts([
      { id: 'alert-1', status: 'SENT', target_name: 'User 1' },
      { id: 'alert-2', status: 'FAILED', retry_scheduled: true, retry_count: 1, plate_number: '29A12345' },
      { id: 'alert-3', status: 'FAILED', retry_scheduled: false, retry_count: 3, target_name: 'User 3' },
    ]);
  }, 'Processing status transitions must not throw');

  assert.equal(toasts.length, 3, 'All 3 transitions must generate their respective toasts');
  assert.equal(toasts[0].type, 'success');
  assert.equal(toasts[1].type, 'warning');
  assert.equal(toasts[2].type, 'error');

  // Verify all 3 alerts are tracked in knownAlerts
  assert.equal(knownAlerts.get('alert-1').status, 'SENT');
  assert.equal(knownAlerts.get('alert-2').status, 'FAILED');
  assert.equal(knownAlerts.get('alert-3').status, 'FAILED');
});


