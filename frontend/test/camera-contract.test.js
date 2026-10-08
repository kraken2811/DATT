import assert from 'node:assert/strict';
import test from 'node:test';
import { cameraSwitchRequest } from '../src/api/cameraContract.js';

test('registered camera uses the switch_camera contract', () => {
  assert.deepEqual(cameraSwitchRequest({ id: 'camera-uuid', name: 'Entrance' }), {
    endpoint: '/switch_camera',
    body: { camera_id: 'camera-uuid' },
  });
});

test('local source uses the select_source contract', () => {
  assert.deepEqual(cameraSwitchRequest({
    storage_path: '/data/input.mp4',
    original_filename: 'input.mp4',
    source_type: 'local',
    video_source_id: 'video-uuid',
  }), {
    endpoint: '/api/select_source',
    body: {
      source: '/data/input.mp4',
      source_type: 'local',
      name: 'Camera',
      loop: true,
      video_source_id: 'video-uuid',
    },
  });
});

test('stream source normalizes hls to direct_hls', () => {
  const request = cameraSwitchRequest({
    source_url: 'https://example.invalid/live.m3u8',
    source_type: 'hls',
    name: 'Stream',
  });
  assert.equal(request.endpoint, '/api/select_source');
  assert.equal(request.body.source_type, 'direct_hls');
});

test('source switch rejects incomplete payloads before making a request', () => {
  assert.throws(() => cameraSwitchRequest({ source_type: 'local' }), /source and source type/);
});
