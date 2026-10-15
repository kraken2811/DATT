import test from 'node:test';
import assert from 'node:assert/strict';
import {
  emptyWatchlistPopupState, evaluateWatchlistPopupBatch, watchlistPopupIdentity,
  POPUP_COOLDOWN_MS,
} from '../src/utils/watchlistPopupPolicy.js';

const NOW = Date.parse('2026-10-15T04:00:00Z');
function plate(id, number='30A10010', camera='CAM01', at=NOW) {
  return { event_id: id, event_type: 'plate', watchlist_match: true,
    plate: number, camera_id: camera, timestamp: new Date(at).toISOString() };
}
function face(id, name='Long', target='target-1', camera='CAM01', at=NOW) {
  return { event_id: id, event_type: 'face', watchlist_match: true,
    target_name: name, target_id: target, camera_id: camera,
    timestamp: new Date(at).toISOString() };
}
function step(state, events, now=NOW) {
  return evaluateWatchlistPopupBatch(state, events, now);
}
test('initial backlog establishes baseline without notifications', () => {
  const r=step(emptyWatchlistPopupState(),[plate('old'),face('old2')]);
  assert.equal(r.alerts.length,0);
  assert.equal(r.state.initialized,true);
});
test('same vehicle same camera is suppressed for five minutes even with distinct event ids', () => {
  const first=step(step(emptyWatchlistPopupState(),[]).state,[plate('1')]);
  assert.equal(first.alerts.length,1);
  assert.equal(first.alerts[0].label,'Xe: 30A10010');
  const again=step(first.state,[plate('2','30A-100.10','CAM01',NOW+10_000)],NOW+10_000);
  assert.equal(again.alerts.length,0);
  assert.equal(step(again.state,[plate('2')],NOW+11_000).alerts.length,0);
  const after=step(again.state,[plate('3','30A10010','CAM01',NOW+POPUP_COOLDOWN_MS)],NOW+POPUP_COOLDOWN_MS);
  assert.equal(after.alerts.length,1);
});
test('different plates and different cameras do not block each other', () => {
  const initialized=step(emptyWatchlistPopupState(),[]).state;
  const r=step(initialized,[plate('1'),plate('2','30A10011'),plate('3','30A10010','CAM02')]);
  assert.equal(r.alerts.length,3);
});
test('same face target suppresses same camera, independent faces are not suppressed', () => {
  const state=step(emptyWatchlistPopupState(),[]).state;
  const first=step(state,[face('1')]);
  assert.equal(first.alerts[0].label,'Người: Long');
  const second=step(first.state,[face('2','Long','target-1'),face('3','Mai','target-2')]);
  assert.equal(second.alerts.length,1);
  assert.equal(second.alerts[0].label,'Người: Mai');
});
test('reload preserves cooldown, stale events and unconfirmed matches do not notify', () => {
  let r=step(step(emptyWatchlistPopupState(),[]).state,[plate('1')]);
  const reloaded=JSON.parse(JSON.stringify(r.state));
  const stale=plate('stale','35A12345','CAM01',NOW-300_000);
  const unmatched={...plate('unmatched','35A12345'),watchlist_match:false};
  r=step(reloaded,[plate('2'),stale,unmatched]);
  assert.equal(r.alerts.length,0);
  assert.equal(r.state.seenEventIds.includes('2'),true);
});
test('invalid face without ID or plate without value does not alert', () => {
  assert.equal(watchlistPopupIdentity({...face('1'),target_id:null}),null);
  assert.equal(watchlistPopupIdentity({...plate('1'),plate:''}),null);
});
