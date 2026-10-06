const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const context = {Uint8Array, DataView, TextDecoder, Blob};
vm.createContext(context);
vm.runInContext(fs.readFileSync('src/ui/static/frame_stream.js', 'utf8') + '\nthis.Parser = DattFrameStreamParser;', context);
function packet(id, body = 'jpeg') {
    const metadata = Buffer.from(JSON.stringify({frame_id: id, source_generation: 1}));
    const header = Buffer.alloc(8);
    header.writeUInt32BE(metadata.length); header.writeUInt32BE(body.length, 4);
    return Buffer.concat([header, metadata, Buffer.from(body)]);
}
test('all possible network splits preserve JPEG and its exact metadata', async () => {
    const bytes = packet(12);
    for (let split = 1; split < bytes.length; split++) {
        const parser = new context.Parser();
        assert.equal(parser.push(bytes.subarray(0, split)), null);
        const result = parser.push(bytes.subarray(split));
        assert.equal(result.metrics.frame_id, 12);
        assert.equal(await result.blob.text(), 'jpeg');
        assert.equal(parser.pending.length, 0);
    }
});
test('batched network frames keep only latest image and ignore trailing heartbeat', async () => {
    const parser = new context.Parser();
    const result = parser.push(Buffer.concat([packet(1, 'old'), packet(2, 'new'), packet(3, '')]));
    assert.equal(result.metrics.frame_id, 2);
    assert.equal(await result.blob.text(), 'new');
});
test('partial next frame is retained without retaining already consumed frames', () => {
    const parser = new context.Parser(), next = packet(2);
    assert.equal(parser.push(Buffer.concat([packet(1), next.subarray(0, 5)])).metrics.frame_id, 1);
    assert.equal(parser.pending.length, 5);
    assert.equal(parser.push(next.subarray(5)).metrics.frame_id, 2);
});
test('oversized corrupt lengths are rejected before buffering a payload', () => {
    const header = Buffer.alloc(8); header.writeUInt32BE(1); header.writeUInt32BE(0xffffffff, 4);
    assert.throws(() => new context.Parser().push(header), /lengths/);
});
