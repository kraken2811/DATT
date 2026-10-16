import { useEffect, useRef } from 'react';
import { useToast } from '../context/ToastContext';
import { fetchAlerts } from '../api/alerts';

const WATCHLIST_STORAGE_KEY = 'datt_notified_watchlist_events';
const EMAIL_STORAGE_KEY = 'datt_notified_email_alerts';
const COOLDOWN_STORAGE_KEY = 'datt_watchlist_cooldowns';
const POLLING_INTERVAL_MS = 2000; // 2 seconds for 1-3s end-to-end popup delivery
const COOLDOWN_MS = 300 * 1000; // 5 minutes (300 seconds) project standard cooldown

function getStoredSet(key) {
  try {
    const raw = sessionStorage.getItem(key);
    return raw ? new Set(JSON.parse(raw)) : new Set();
  } catch {
    return new Set();
  }
}

function persistToSet(key, item, maxSize = 300) {
  try {
    const set = getStoredSet(key);
    set.add(item);
    const arr = Array.from(set);
    if (arr.length > maxSize) arr.splice(0, arr.length - maxSize);
    sessionStorage.setItem(key, JSON.stringify(arr));
  } catch {}
}

function getStoredCooldowns() {
  try {
    const raw = sessionStorage.getItem(COOLDOWN_STORAGE_KEY);
    return raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}

function persistCooldown(cooldownKey, timestamp) {
  try {
    const map = getStoredCooldowns();
    map[cooldownKey] = timestamp;
    // Evict entries older than 1 hour to prevent indefinite growth
    const now = Date.now();
    for (const [k, ts] of Object.entries(map)) {
      if (now - ts > 3600 * 1000) {
        delete map[k];
      }
    }
    sessionStorage.setItem(COOLDOWN_STORAGE_KEY, JSON.stringify(map));
  } catch {}
}

export function NotificationToastWatcher() {
  const { showToast } = useToast();
  const knownAlertsRef = useRef(new Map());
  const isInitializedRef = useRef(false);
  const inFlightRef = useRef(false);
  const abortControllerRef = useRef(null);

  useEffect(() => {
    let timerId = null;
    let isMounted = true;

    async function checkNotificationUpdates() {
      if (inFlightRef.current || !isMounted) return;
      if (document.hidden) return; // Pause polling when document tab is hidden

      inFlightRef.current = true;
      const controller = new AbortController();
      abortControllerRef.current = controller;

      try {
        const resp = await fetchAlerts({ page: 1, page_size: 20 }, controller.signal, {
          cacheTtlMs: 0,
          forceRefresh: true,
        });

        if (!isMounted || !resp || !Array.isArray(resp.alerts)) {
          return;
        }

        const alerts = resp.alerts;
        const frontendReceivedAt = Date.now();

        // Baseline initialization: Absorb all historical records without firing toasts
        if (!isInitializedRef.current) {
          isInitializedRef.current = true;
          for (const alert of alerts) {
            const status = (alert.status || '').toUpperCase();
            const retryCount = alert.retry_count ?? 0;
            const retryScheduled = Boolean(alert.retry_scheduled);
            knownAlertsRef.current.set(alert.id, {
              status,
              retry_count: retryCount,
              retry_scheduled: retryScheduled,
            });

            // Mark existing watchlist events and email states as already acknowledged
            if (alert.event_id) {
              persistToSet(WATCHLIST_STORAGE_KEY, alert.event_id);
            }
            if (status === 'SENT') {
              persistToSet(EMAIL_STORAGE_KEY, `${alert.id}:SENT`);
            } else if (status === 'FAILED') {
              if (retryScheduled) {
                persistToSet(EMAIL_STORAGE_KEY, `${alert.id}:RETRY:${retryCount}`);
              } else {
                persistToSet(EMAIL_STORAGE_KEY, `${alert.id}:EXHAUSTED:${retryCount}`);
              }
            }
          }
          return;
        }

        // Subsequent polls: Process Watchlist match events and Email status transitions
        const notifiedEventsSet = getStoredSet(WATCHLIST_STORAGE_KEY);
        const notifiedEmailSet = getStoredSet(EMAIL_STORAGE_KEY);
        const cooldownMap = getStoredCooldowns();
        const now = Date.now();

        for (const alert of alerts) {
          const currStatus = (alert.status || '').toUpperCase();
          const currRetryCount = alert.retry_count ?? 0;
          const currRetryScheduled = Boolean(alert.retry_scheduled);
          const prev = knownAlertsRef.current.get(alert.id);

          const objectName = alert.target_name || alert.plate_number || 'Không xác định';
          const cameraName = alert.camera_name || alert.camera_id || 'Không xác định';
          const isFace = alert.event_type === 'FACE_WATCHLIST_MATCH' || (alert.event_center_id && alert.event_center_id.startsWith('face:'));

          // =========================================================================
          // LUỒNG B: IMMEDIATE WATCHLIST WARNING POPUP (Independent of email delivery)
          // =========================================================================
          if (alert.event_id && !notifiedEventsSet.has(alert.event_id)) {
            const targetKey = alert.target_id || alert.plate_number || objectName;
            const cooldownKey = `${alert.event_type || 'WATCHLIST'}:${targetKey}:${alert.camera_id}`;
            const lastCooldownTime = cooldownMap[cooldownKey] || 0;

            const isCoolingDown = (now - lastCooldownTime) < COOLDOWN_MS;

            if (!isCoolingDown) {
              const popupRenderedAt = Date.now();

              // Calculate milestone latencies
              const confirmedTime = alert.event_confirmed_at
                ? new Date(alert.event_confirmed_at).getTime()
                : (alert.created_at ? new Date(alert.created_at).getTime() : frontendReceivedAt);
              const persistedTime = alert.event_persisted_at
                ? new Date(alert.event_persisted_at).getTime()
                : (alert.created_at ? new Date(alert.created_at).getTime() : frontendReceivedAt);

              const confirmToPersistMs = Math.max(0, persistedTime - confirmedTime);
              const persistToReceivedMs = Math.max(0, frontendReceivedAt - persistedTime);
              const receivedToRenderedMs = Math.max(0, popupRenderedAt - frontendReceivedAt);
              const totalLatencyMs = Math.max(0, popupRenderedAt - confirmedTime);

              // Structured latency measurement log
              console.info('[LATENCY_MEASUREMENT]', {
                event_id: alert.event_id,
                event_type: alert.event_type,
                target_name: objectName,
                camera_id: alert.camera_id,
                camera_name: cameraName,
                event_confirmed_at: alert.event_confirmed_at || alert.created_at,
                event_persisted_at: alert.event_persisted_at || alert.created_at,
                alert_available_at: alert.alert_available_at || new Date().toISOString(),
                frontend_received_at: new Date(frontendReceivedAt).toISOString(),
                popup_rendered_at: new Date(popupRenderedAt).toISOString(),
                latencies: {
                  confirm_to_persist_ms: Math.round(confirmToPersistMs),
                  persist_to_received_ms: Math.round(persistToReceivedMs),
                  received_to_rendered_ms: Math.round(receivedToRenderedMs),
                  total_latency_ms: Math.round(totalLatencyMs),
                },
              });

              // Trigger Immediate Warning Popup
              const alertPrefix = isFace ? 'Face Watchlist' : 'Vehicle Watchlist';
              showToast(
                `🚨 Cảnh báo ${alertPrefix}: Phát hiện đối tượng "${objectName}" tại Camera "${cameraName}"`,
                'error',
                8000
              );

              persistCooldown(cooldownKey, now);
              cooldownMap[cooldownKey] = now;
            }

            // Mark this specific event_id as acknowledged in memory & storage
            persistToSet(WATCHLIST_STORAGE_KEY, alert.event_id);
            notifiedEventsSet.add(alert.event_id);
          }

          // =========================================================================
          // EXTERNAL NOTIFICATION STATUS TOASTS (Email transport progress / failure)
          // =========================================================================
          // 1. Transition to SENT
          if (currStatus === 'SENT') {
            const signature = `${alert.id}:SENT`;
            const isNewTransition = !prev || prev.status !== 'SENT';

            if (isNewTransition && !notifiedEmailSet.has(signature)) {
              persistToSet(EMAIL_STORAGE_KEY, signature);
              notifiedEmailSet.add(signature);
              showToast(
                `Email cảnh báo đã được gửi — Đối tượng: ${objectName}, Camera: ${cameraName}`,
                'success'
              );
            }
          }
          // 2. Transition to FAILED with retry still scheduled -> Warning Toast
          else if (currStatus === 'FAILED' && currRetryScheduled) {
            const signature = `${alert.id}:RETRY:${currRetryCount}`;
            const isNewTransition = !prev || prev.status === 'PENDING' || (prev.status === 'FAILED' && currRetryCount > prev.retry_count);

            if (isNewTransition && !notifiedEmailSet.has(signature)) {
              persistToSet(EMAIL_STORAGE_KEY, signature);
              notifiedEmailSet.add(signature);
              const maxRetries = alert.max_retries || 3;
              const retryLabel = currRetryCount > 0 ? `lần ${currRetryCount}/${maxRetries}` : 'hệ thống đang thử lại';
              showToast(
                `Gửi email cảnh báo thất bại, đang thử lại (${retryLabel}) — Đối tượng: ${objectName}, Camera: ${cameraName}`,
                'warning'
              );
            }
          }
          // 3. Transition to FAILED with retries exhausted (or not retryable) -> Error Toast
          else if (currStatus === 'FAILED' && !currRetryScheduled) {
            const signature = `${alert.id}:EXHAUSTED:${currRetryCount}`;
            const isNewTransition = !prev || prev.status === 'PENDING' || (prev.status === 'FAILED' && prev.retry_scheduled);

            if (isNewTransition && !notifiedEmailSet.has(signature)) {
              persistToSet(EMAIL_STORAGE_KEY, signature);
              notifiedEmailSet.add(signature);
              showToast(
                `Không thể gửi email cảnh báo (quá số lần thử) — Đối tượng: ${objectName}, Camera: ${cameraName}`,
                'error'
              );
            }
          }

          // Update tracking map
          knownAlertsRef.current.set(alert.id, {
            status: currStatus,
            retry_count: currRetryCount,
            retry_scheduled: currRetryScheduled,
          });
        }
      } catch (err) {
        // Silently handle 401, 403, 503, network errors without displaying false toasts
        if (err.name !== 'AbortError') {
          // Polling will safely retry on next cycle without losing unhandled events
        }
      } finally {
        inFlightRef.current = false;
        abortControllerRef.current = null;
      }
    }

    // Schedule regular polling with 2000ms cadence
    function scheduleNext() {
      timerId = setTimeout(async () => {
        if (!isMounted) return;
        await checkNotificationUpdates();
        if (isMounted) scheduleNext();
      }, POLLING_INTERVAL_MS);
    }

    // Run initial baseline check immediately on mount
    checkNotificationUpdates().then(() => {
      if (isMounted) scheduleNext();
    });

    // Re-check when document tab becomes visible
    function handleVisibilityChange() {
      if (!document.hidden && isMounted) {
        checkNotificationUpdates();
      }
    }
    document.addEventListener('visibilitychange', handleVisibilityChange);

    return () => {
      isMounted = false;
      if (timerId) clearTimeout(timerId);
      document.removeEventListener('visibilitychange', handleVisibilityChange);
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
    };
  }, [showToast]);

  return null;
}

