export function cameraSwitchRequest(camera) {
  const cameraId = camera?.camera_id || camera?.id;
  if (cameraId) {
    return { endpoint: '/switch_camera', body: { camera_id: String(cameraId) } };
  }

  const source = camera?.source_url || camera?.url || camera?.source || camera?.storage_path;
  const sourceType = camera?.source_type || camera?.type;
  if (!source || !sourceType) {
    throw new Error('Camera source and source type are required');
  }
  return {
    endpoint: '/api/select_source',
    body: {
      source,
      source_type: sourceType === 'hls' ? 'direct_hls' : sourceType,
      name: camera.name || camera.camera_name || 'Camera',
      loop: camera.loop ?? true,
      ...(camera.provider ? { provider: camera.provider } : {}),
      ...(camera.video_source_id ? { video_source_id: camera.video_source_id } : {}),
    },
  };
}
