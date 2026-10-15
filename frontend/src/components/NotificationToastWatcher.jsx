import { useEffect, useRef } from 'react';
import { useToast } from '../context/ToastContext';
import { fetchEvents } from '../api/events';

const STORAGE_KEY = 'datt_realtime_watchlist_event_ids';
const POLLING_INTERVAL_MS = 2000;
const MAX_SEEN = 500;

function readSeen() {
  try { return new Set(JSON.parse(sessionStorage.getItem(STORAGE_KEY) || '[]')); }
  catch { return new Set(); }
}
function saveSeen(seen) {
  try { sessionStorage.setItem(STORAGE_KEY, JSON.stringify([...seen].slice(-MAX_SEEN))); }
  catch { /* storage is optional */ }
}
function alertLabel(event) {
  if (event.event_type === 'face') {
    return event.target_name ? `Người: ${event.target_name}` : null;
  }
  if (event.event_type === 'plate') {
    const plate = String(event.plate || '').trim().toUpperCase().replace(/[^A-Z0-9]/g, '');
    return plate ? `Xe: ${plate}` : null;
  }
  return null;
}

export function NotificationToastWatcher() {
  const { showToast } = useToast();
  const initializedRef = useRef(false);
  const seenRef = useRef(readSeen());
  const inFlightRef = useRef(false);
  useEffect(() => {
    let active = true;
    let timer;
    let controller;
    async function checkEvents() {
      if (!active || inFlightRef.current || document.hidden) return;
      inFlightRef.current = true;
      controller = new AbortController();
      try {
        const resp = await fetchEvents({
          page: 1, page_size: 50, watchlist_match: 'true',
          include_total: false, sort: 'desc',
        }, controller.signal, { cacheTtlMs: 0, forceRefresh: true });
        if (!active || !Array.isArray(resp?.events)) return;
        const events = resp.events;
        const seen = seenRef.current;
        if (!initializedRef.current) {
          events.forEach(evt => seen.add(evt.event_id));
          initializedRef.current = true;
          saveSeen(seen);
          return;
        }
        const fresh = events.filter(evt => !seen.has(evt.event_id));
        // All event ids are acknowledged once observed; never re-alert on missing labels.
        for (const evt of fresh) seen.add(evt.event_id);
        saveSeen(seen);
        for (const evt of fresh.reverse()) {
          const label = alertLabel(evt);
          if (!label) continue;
          const camera = evt.camera_id || 'Không xác định';
          showToast(`Phát hiện Watchlist — ${label}, Camera: ${camera}`, 'warning');
        }
      } catch (error) {
        if (error.name !== 'AbortError') {
          // Preserve the last baseline and retry without false positives.
        }
      } finally {
        inFlightRef.current = false;
        controller = null;
      }
    }
    async function tick() {
      await checkEvents();
      if (active) timer = setTimeout(tick, POLLING_INTERVAL_MS);
    }
    tick();
    const visible = () => { if (!document.hidden) checkEvents(); };
    document.addEventListener('visibilitychange', visible);
    return () => {
      active = false;
      clearTimeout(timer);
      document.removeEventListener('visibilitychange', visible);
      controller?.abort();
    };
  }, [showToast]);
  return null;
}
