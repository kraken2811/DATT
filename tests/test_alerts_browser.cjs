const assert = require('node:assert/strict');
const {test} = require('node:test');
const fs = require('node:fs');
const vm = require('node:vm');
const flush = () => new Promise(resolve => setImmediate(resolve));

function harness() {
    const nodes = new Map(), requests = [], timers = new Map(); let nextTimer = 0;
    function node() { return {value: '', textContent: '', children: [], listeners: {}, hidden: false,
        addEventListener(name, fn) { this.listeners[name] = fn; },
        appendChild(child) { this.children.push(child); }, replaceChildren() { this.children = []; }}; }
    const document = {hidden: false, listeners: {}, createElement: node,
        getElementById(id) { if (!nodes.has(id)) nodes.set(id, node()); return nodes.get(id); },
        addEventListener(name, fn) { this.listeners[name] = fn; }};
    const context = {window: {}, document, AbortController, URLSearchParams, Date, console,
        setTimeout(fn, ms) { timers.set(++nextTimer, {fn, ms}); return nextTimer; },
        clearTimeout(id) { timers.delete(id); },
        fetch(url, options) { return new Promise(resolve => requests.push({url, options, resolve})); }};
    vm.runInNewContext(fs.readFileSync('src/ui/static/alerts.js', 'utf8'), context);
    const api = context.window.DattAlerts; api.init(x => x);
    return {api, nodes, document, requests, timers};
}
const row = (status = 'SENT') => ({id: 'notice', event_id: 'event', event_center_id: 'face:event',
    event_type: 'FACE_WATCHLIST_MATCH', camera_name: '<img onerror=bad>', camera_id: 'gate',
    recipient_email: 'to@example.invalid', status, created_at: '2026-10-02T00:00:00Z',
    sent_at: status === 'SENT' ? '2026-10-02T00:00:01Z' : null, retry_count: 0});
const response = data => ({ok: true, json: async () => data});

test('renders API delivery statuses and recipient as text, schedules one polling request', async () => {
    const h = harness(); h.api.setActive(true);
    h.requests.shift().resolve(response({alerts: ['SENT','PENDING','FAILED','SUPPRESSED'].map(row), total: 4})); await flush();
    const rows = h.nodes.get('alertsBody').children;
    assert.equal(rows[0].children[1].textContent, '<img onerror=bad>');
    assert.equal(rows[0].children[2].textContent, 'to@example.invalid');
    assert.deepEqual(rows.map(r => r.children[3].children[0].textContent), ['Đã gửi','Đang chờ gửi','Gửi thất bại','Không gửi (đã chặn)']);
    assert.equal(rows[1].children[4].textContent, '—');
    assert.equal([...h.timers.values()].filter(t => t.ms === 10000).length, 1);
    h.api.setActive(false); assert.equal(h.timers.size, 0);
});

test('navigation cancels requests and discards late response', async () => {
    const h = harness(); h.api.setActive(true); const pending = h.requests.shift();
    h.api.setActive(false); assert.equal(pending.options.signal.aborted, true);
    pending.resolve(response({alerts: [row()], total: 1})); await flush();
    assert.equal(h.nodes.has('alertsBody'), false); assert.equal(h.timers.size, 0);
});

test('filters reset pagination, detail fetch uses backend error and event link', async () => {
    const h = harness(); h.api.setActive(true);
    h.requests.shift().resolve(response({alerts: [row('FAILED')], total: 30})); await flush();
    h.nodes.get('alertsNext').listeners.click();
    assert.match(h.requests[0].url, /page=2/);
    h.requests.shift().resolve(response({alerts: [row('FAILED')], total: 30})); await flush();
    h.nodes.get('alertsStatus').value = 'FAILED';
    h.nodes.get('alertsFilters').listeners.submit({preventDefault() {}});
    assert.match(h.requests[0].url, /page=1/); assert.match(h.requests[0].url, /status=FAILED/);
    h.requests.shift().resolve(response({alerts: [row('FAILED')], total: 1})); await flush();
    h.nodes.get('alertsBody').children[0].children[6].children[0].listeners.click();
    assert.equal(h.requests[0].url, '/api/alerts/notice');
    h.requests.shift().resolve(response({alert: {...row('FAILED'), error_message: 'SMTP delivery timed out.'}})); await flush();
    assert.equal(h.nodes.get('alertDetailError').textContent, 'SMTP delivery timed out.');
    assert.equal(h.nodes.get('alertDetailStatus').textContent, 'Gửi thất bại');
    assert.equal(h.nodes.get('alertEventLink').href, '/events?id=face%3Aevent');
    h.nodes.get('alertDetailClose').listeners.click(); assert.equal(h.nodes.get('alertDetail').hidden, true);
});

test('failure is visible and hidden pages do not poll', async () => {
    const h = harness(); h.api.setActive(true);
    h.requests.shift().resolve({ok: false, status: 503}); await flush();
    assert.match(h.nodes.get('alertsFeedback').textContent, /Không tải được/);
    h.document.hidden = true;
    [...h.timers.values()].find(t => t.ms === 10000).fn();
    assert.equal(h.requests.length, 0);
});
