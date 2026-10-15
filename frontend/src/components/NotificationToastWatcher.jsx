import { useEffect, useRef } from 'react';
import { useToast } from '../context/ToastContext';
import { fetchEvents } from '../api/events';
import {
  emptyWatchlistPopupState,
  evaluateWatchlistPopupBatch,
} from '../utils/watchlistPopupPolicy';

const STORAGE_KEY = 'datt_watchlist_popup_gate_v2';
const POLLING_INTERVAL_MS = 2000;
const CROSS_TAB_LOCK = 'datt-watchlist-popup-gate';

// Persist the cooldown and event-id state across navigation, reloads and tabs.
function readStoredState() {
  try {
    const text = localStorage.getItem(STORAGE_KEY);
    return text ? JSON.parse(text) : null;
  } catch {
    return null;
  }
}

function writeStoredState(state) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch {
    // In-memory fallback if the browser denies storage access.
  }
}

export function NotificationToastWatcher() {
  const { showToast } = useToast();
  const inFlightRef = useRef(false);
  const fallbackStateRef = useRef(emptyWatchlistPopupState());

  useEffect(() => {
    let active = true;
    let timer = null;
    let controller = null;

    function deliverNewEvents(events) {
      if (!active) return;
      // Read inside the lock: another tab may have notified during our fetch.
      const stored = readStoredState();
      const previous = stored ?? fallbackStateRef.current;
      const { state, alerts } = evaluateWatchlistPopupBatch(
        previous, events, Date.now(),
      );
      fallbackStateRef.current = state;
      writeStoredState(state);

      for (const alert of alerts) {
        if (!active) return;
        showToast(
          `Phát hiện Watchlist — ${alert.label}, Camera: ${alert.camera}`,
          'warning',
        );
      }
    }

    async function checkNotificationUpdates() {
      if (!active || inFlightRef.current || document.hidden) return;
      inFlightRef.current = true;
      controller = new AbortController();
      try {
        const response = await fetchEvents({
          page: 1,
          page_size: 50,
          watchlist_match: 'true',
          include_total: false,
          sort: 'desc',
        }, controller.signal, {
          cacheTtlMs: 0,
          forceRefresh: true,
        });
        if (!active || !Array.isArray(response?.events)) return;

        // Web Locks serialize the read-check-write gate across same-origin tabs.
        if (typeof navigator !== 'undefined' && navigator.locks?.request) {
          await navigator.locks.request(CROSS_TAB_LOCK, { mode: 'exclusive' }, () => {
            deliverNewEvents(response.events);
          });
        } else {
          // On older browsers we retain localStorage + stable-event dedupe,
          // but cross-tab atomicity requires Web Locks support.
          deliverNewEvents(response.events);
        }
      } catch (error) {
        if (error.name !== 'AbortError') {
          // Do not treat a failed fetch as an empty list or reset cooldown.
        }
      } finally {
        inFlightRef.current = false;
        controller = null;
      }
    }

    async function poll() {
      await checkNotificationUpdates();
      if (active) timer = setTimeout(poll, POLLING_INTERVAL_MS);
    }

    poll();
    const onVisibilityChange = () => {
      if (!document.hidden) checkNotificationUpdates();
    };
    document.addEventListener('visibilitychange', onVisibilityChange);
    return () => {
      active = false;
      if (timer) clearTimeout(timer);
      document.removeEventListener('visibilitychange', onVisibilityChange);
      controller?.abort();
    };
  }, [showToast]);

  return null;
}
