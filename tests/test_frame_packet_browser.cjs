const assert = require('node:assert/strict');
const {test} = require('node:test');
const fs = require('node:fs');
const vm = require('node:vm');

function harness(stream = false) {
    const source = fs.readFileSync('src/ui/static/app.js', 'utf8');
    const code = source.slice(source.indexOf('    let frameEpoch ='),
        source.indexOf('    function applyTelemetry(data)'));
    const requests = [], paints = [], timers = [], commits = [];
    let now = 0;
    const context = {
        state: {uiState: 'MONITORING'}, UI_STATE: {MONITORING: 'MONITORING'},
        DOM: {
            videoFeed: {width: 2, height: 2, dataset: {}, getContext: () => ({
                drawImage: image => commits.push(['image', image.id]), clearRect() {}
            })},
            videoErrorOverlay: {style: {}}, pingLatency: {}, metricStreamFps: {},
        },
        AbortController, performance: {now: () => now}, console, Uint8Array, DataView, TextDecoder, Blob,
        setTimeout: (fn, ms) => { timers.push([fn, ms]); return timers.length; },
        clearTimeout() {}, apiUrl: x => x,
        fetch: () => new Promise(resolve => requests.push(resolve)),
        createImageBitmap: async blob => ({id: blob.id ?? Number(await blob.text()), width: 2, height: 2, close() {}}),
        requestAnimationFrame: fn => paints.push(fn),
        applyTelemetry: data => commits.push(['metrics', data.frame_id]),
        handleTelemetryError() {},
    };
    vm.createContext(context);
    if (stream) vm.runInContext(fs.readFileSync('src/ui/static/frame_stream.js', 'utf8'), context);
    vm.runInContext(code, context);
    return {context, requests, paints, timers, commits, advance: ms => now += ms};
}

const flush = () => new Promise(resolve => setImmediate(resolve));
const response = id => ({ok: true, status: 200,
    headers: {get: () => JSON.stringify({source_generation: 1, frame_id: id})},
    blob: async () => ({id})});

test('image and matching metrics commit only in the same animation frame', async () => {
    const h = harness();
    h.context.startFramePackets();
    h.requests.shift()(response(7));
    await flush();
    assert.deepEqual(h.commits, []);
    assert.equal(h.requests.length, 0); // No overlapping fetch while decoding/painting.
    h.paints.shift()();
    await flush();
    assert.deepEqual(h.commits, [['image', 7], ['metrics', 7]]);
});

test('camera switch discards an already decoded response before painting', async () => {
    const h = harness();
    h.context.startFramePackets();
    h.requests.shift()(response(7));
    await flush();
    h.context.stopFramePackets();
    h.paints.shift()();
    await flush();
    assert.deepEqual(h.commits, []);
});

test('camera switch discards an old network response', async () => {
    const h = harness();
    h.context.startFramePackets();
    h.context.stopFramePackets();
    h.requests.shift()(response(7));
    await flush();
    assert.deepEqual(h.commits, []);
    assert.equal(h.paints.length, 0);
});

test('hidden tab pauses preview and returning discards the old response', async () => {
    const h = harness();
    let onVisibility;
    h.context.document = {hidden: false, addEventListener: (name, fn) => {
        assert.equal(name, 'visibilitychange'); onVisibility = fn;
    }};
    h.context.setupVideoStream();
    h.context.startFramePackets();
    const oldResponse = h.requests.shift();
    h.context.document.hidden = true; onVisibility();
    h.context.startFramePackets();
    assert.equal(h.requests.length, 0);
    h.context.document.hidden = false; onVisibility();
    assert.equal(h.requests.length, 1);
    oldResponse(response(1)); await flush();
    assert.deepEqual(h.commits, []);
    await paint(h, 2);
    assert.deepEqual(h.commits, [['image', 2], ['metrics', 2]]);
});

async function paint(h, id) {
    h.requests.shift()(response(id));
    await flush();
    h.paints.shift()();
    await flush();
}

test('one failed request preserves a fresh image, a stalled stream is exposed', async () => {
    const h = harness(); h.context.startFramePackets(); await paint(h, 1);
    h.advance(100); h.timers.at(-1)[0]();
    h.requests.shift()({ok: false, status: 503}); await flush();
    assert.equal(h.context.DOM.videoErrorOverlay.style.display, 'none');
    h.advance(3000); h.timers[0][0]();
    assert.equal(h.context.DOM.videoErrorOverlay.style.display, 'flex');
    assert.equal(h.context.DOM.metricStreamFps.textContent, '0.0');
});

test('duplicate packets cannot disguise a frozen camera; a new frame recovers it', async () => {
    const h = harness(); h.context.startFramePackets(); await paint(h, 1);
    h.advance(3100); h.timers[0][0]();
    h.timers.findLast(t => t[1] === 33)[0]();
    h.requests.shift()(response(1)); await flush();
    assert.equal(h.context.DOM.videoErrorOverlay.style.display, 'flex');
    h.timers.at(-1)[0](); await paint(h, 2);
    assert.equal(h.context.DOM.videoErrorOverlay.style.display, 'none');
});

test('stale publication-time images are not painted as live', async () => {
    const h = harness(); h.context.startFramePackets();
    const r = response(2);
    r.headers.get = () => JSON.stringify({frame_id: 2, source_generation: 1, frame_age_ms: 4000});
    h.requests.shift()(r); await flush();
    assert.equal(h.paints.length, 0);
    assert.deepEqual(h.commits, []);
});

test('display FPS measures painted frames instead of claimed capture FPS', async () => {
    const h = harness(); h.context.startFramePackets(); await paint(h, 1);
    h.advance(200); h.timers.at(-1)[0](); await paint(h, 2);
    assert.equal(h.context.DOM.metricStreamFps.textContent, '5.0');
});

test('stream paints multiple synchronized frames over one request and stops on camera switch', async () => {
    const h = harness(true), reads = [];
    let cancelled = 0;
    const reader = {read: () => new Promise(resolve => reads.push(resolve)), cancel: async () => cancelled++};
    const packet = id => {
        const meta = Buffer.from(JSON.stringify({frame_id: id, source_generation: 1}));
        const header = Buffer.alloc(8); header.writeUInt32BE(meta.length); header.writeUInt32BE(1, 4);
        return Buffer.concat([header, meta, Buffer.from(String(id))]);
    };
    h.context.startFramePackets();
    h.requests.shift()({ok: true, headers: {get: () => '1'}, body: {getReader: () => reader}});
    await flush();
    for (const id of [7, 8]) {
        reads.shift()({value: packet(id), done: false}); await flush();
        h.paints.shift()(); await flush();
    }
    assert.deepEqual(h.commits, [['image', 7], ['metrics', 7], ['image', 8], ['metrics', 8]]);
    assert.equal(h.requests.length, 0);
    h.context.stopFramePackets();
    reads.shift()({value: packet(9), done: false}); await flush();
    assert.equal(h.paints.length, 0);
    assert.equal(cancelled, 1);
});
