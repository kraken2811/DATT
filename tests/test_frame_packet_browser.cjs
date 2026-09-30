const assert = require('node:assert/strict');
const {test} = require('node:test');
const fs = require('node:fs');
const vm = require('node:vm');

function harness() {
    const source = fs.readFileSync('src/ui/static/app.js', 'utf8');
    const code = source.slice(source.indexOf('    let frameEpoch ='),
        source.indexOf('    function applyTelemetry(data)'));
    const requests = [], paints = [], timers = [], commits = [];
    const context = {
        state: {uiState: 'MONITORING'}, UI_STATE: {MONITORING: 'MONITORING'},
        DOM: {
            videoFeed: {width: 2, height: 2, dataset: {}, getContext: () => ({
                drawImage: image => commits.push(['image', image.id]), clearRect() {}
            })},
            videoErrorOverlay: {style: {}}, pingLatency: {},
        },
        AbortController, performance, console,
        setTimeout: (fn, ms) => { timers.push([fn, ms]); return timers.length; },
        clearTimeout() {}, apiUrl: x => x,
        fetch: () => new Promise(resolve => requests.push(resolve)),
        createImageBitmap: async blob => ({id: blob.id, width: 2, height: 2, close() {}}),
        requestAnimationFrame: fn => paints.push(fn),
        applyTelemetry: data => commits.push(['metrics', data.frame_id]),
        handleTelemetryError() {},
    };
    vm.createContext(context);
    vm.runInContext(code, context);
    return {context, requests, paints, timers, commits};
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
