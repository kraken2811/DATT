import { useEffect, useRef } from 'react';
import { useToast } from '../context/ToastContext';
import { fetchAlerts } from '../api/alerts';

const STORAGE_KEY = 'datt_notified_email_alerts';
const POLLING_INTERVAL_MS = 7000; // 7 seconds (bounded between 5-10s)

function getStoredSignatures() {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    return raw ? new Set(JSON.parse(raw)) : new Set();
  } catch {
    return new Set();
  }
}

function persistSignature(signature) {
  try {
    const set = getStoredSignatures();
    set.add(signature);
    // Keep bounded to last 150 entries to prevent memory growth
    const arr = Array.from(set);
    if (arr.length > 150) arr.splice(0, arr.length - 150);
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(arr));
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

            // Mark existing completed/failed states in session storage as already acknowledged
            if (status === 'SENT') {
              persistSignature(`${alert.id}:SENT`);
            } else if (status === 'FAILED') {
              if (retryScheduled) {
                persistSignature(`${alert.id}:RETRY:${retryCount}`);
              } else {
                persistSignature(`${alert.id}:EXHAUSTED:${retryCount}`);
              }
            }
          }
          return;
        }

        // Subsequent polls: Detect relevant status transitions
        const notifiedSet = getStoredSignatures();

        for (const alert of alerts) {
          const currStatus = (alert.status || '').toUpperCase();
          const currRetryCount = alert.retry_count ?? 0;
          const currRetryScheduled = Boolean(alert.retry_scheduled);
          const prev = knownAlertsRef.current.get(alert.id);

          const objectName = alert.target_name || alert.plate_number || 'Không xác định';
          const cameraName = alert.camera_name || alert.camera_id || 'Không xác định';

          // 1. Transition to SENT (from PENDING, FAILED, or newly created in session)
          if (currStatus === 'SENT') {
            const signature = `${alert.id}:SENT`;
            const isNewTransition = !prev || prev.status !== 'SENT';

            if (isNewTransition && !notifiedSet.has(signature)) {
              persistSignature(signature);
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

            if (isNewTransition && !notifiedSet.has(signature)) {
              persistSignature(signature);
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

            if (isNewTransition && !notifiedSet.has(signature)) {
              persistSignature(signature);
              showToast(
                `Không thể gửi email cảnh báo (quá số lần thử) — Đối tượng: ${objectName}, Camera: ${cameraName}`,
                'error'
              );
            }
          }
          // 4. PENDING or SUPPRESSED: Do not show toast (as required)

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
          // Polling will safely retry on next cycle
        }
      } finally {
        inFlightRef.current = false;
        abortControllerRef.current = null;
      }
    }

    // Schedule regular polling
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
