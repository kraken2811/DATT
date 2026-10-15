/**
 * Independent, browser-side anti-spam gate for confirmed Watchlist events.
 *
 * Cooldown follows the existing email default (300 seconds), but does not
 * depend on SMTP configuration, delivery, retries, or notification status.
 * The gate is per identity AND camera, and persists across reloads/tabs.
 */
export const POPUP_COOLDOWN_MS = 300_000;
export const MAX_EVENT_AGE_MS = 120_000;
const MAX_FUTURE_SKEW_MS = 30_000;
const MAX_SEEN_EVENT_IDS = 1_000;
const MAX_COOLDOWN_KEYS = 500;

export function emptyWatchlistPopupState() {
  return { initialized: false, seenEventIds: [], lastShownByKey: {} };
}

export function watchlistPopupIdentity(event) {
  // Never alert on a normal detection or a provisional OCR/face hypothesis.
  if (!event || event.watchlist_match !== true) return null;
  const cameraId = String(event.camera_id || '').trim();
  if (!cameraId) return null;

  if (event.event_type === 'face') {
    const targetId = String(event.target_id || '').trim();
    const name = String(event.target_name || '').trim();
    if (!targetId || !name) return null;
    return {
      key: JSON.stringify(['face', targetId, cameraId]),
      label: `Người: ${name}`,
      camera: cameraId,
    };
  }

  if (event.event_type === 'plate') {
    const plate = String(event.plate || '').toUpperCase().replace(/[^A-Z0-9]/g, '');
    if (!plate) return null;
    return {
      key: JSON.stringify(['plate', plate, cameraId]),
      label: `Xe: ${plate}`,
      camera: cameraId,
    };
  }

  return null;
}

/**
 * Pure decision engine. Call it under a same-origin cross-tab lock, if available.
 * Incoming events are all marked seen (including cooldown-suppressed events).
 * Suppression never deletes recorded events or interferes with email delivery.
 */
export function evaluateWatchlistPopupBatch(
  previousState,
  incomingEvents,
  nowMs,
  { cooldownMs = POPUP_COOLDOWN_MS, maxEventAgeMs = MAX_EVENT_AGE_MS } = {},
) {
  const state = previousState && typeof previousState === 'object'
    ? previousState : emptyWatchlistPopupState();
  const initialized = state.initialized === true;
  const seen = new Set(Array.isArray(state.seenEventIds) ? state.seenEventIds : []);
  const prior = state.lastShownByKey && typeof state.lastShownByKey === 'object'
    ? state.lastShownByKey : {};
  const lastShownByKey = {};
  // Prune expired keys to avoid unbounded growth and obsolete cooldowns.
  for (const [key, value] of Object.entries(prior)) {
    if (Number.isFinite(value) && value <= nowMs && nowMs - value < cooldownMs) {
      lastShownByKey[key] = value;
    }
  }

  const alerts = [];
  const ordered = Array.isArray(incomingEvents)
    ? [...incomingEvents].sort((a, b) => {
      const t1 = Date.parse(a?.timestamp || '') || 0;
      const t2 = Date.parse(b?.timestamp || '') || 0;
      return t1 - t2;
    }) : [];

  for (const event of ordered) {
    const id = typeof event?.event_id === 'string' ? event.event_id : '';
    if (!id || seen.has(id)) continue;
    seen.add(id);

    // The very first snapshot is only a baseline: no flood of past alerts.
    if (!initialized) continue;

    const eventTime = Date.parse(event.timestamp || '');
    if (!Number.isFinite(eventTime) ||
      nowMs - eventTime > maxEventAgeMs ||
      eventTime - nowMs > MAX_FUTURE_SKEW_MS) continue;

    const identity = watchlistPopupIdentity(event);
    if (!identity) continue;
    const last = lastShownByKey[identity.key];
    if (Number.isFinite(last) && nowMs - last < cooldownMs) continue;

    lastShownByKey[identity.key] = nowMs;
    alerts.push({ ...identity, eventId: id });
  }

  return {
    state: {
      initialized: true,
      seenEventIds: [...seen].slice(-MAX_SEEN_EVENT_IDS),
      lastShownByKey: Object.fromEntries(
        Object.entries(lastShownByKey)
          .sort((a, b) => a[1] - b[1])
          .slice(-MAX_COOLDOWN_KEYS),
      ),
    },
    alerts,
  };
}
