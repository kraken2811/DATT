// Existing DATT frame_stream protocol: bounded JSON metadata followed by JPEG bytes.
export class FrameStreamParser {
  constructor() { this.pending = new Uint8Array(0); }
  push(chunk) {
    const bytes = new Uint8Array(this.pending.length + chunk.length);
    bytes.set(this.pending); bytes.set(chunk, this.pending.length);
    let offset = 0, latest = null;
    while (bytes.length - offset >= 8) {
      const view = new DataView(bytes.buffer, bytes.byteOffset + offset, 8);
      const metadataLength = view.getUint32(0), jpegLength = view.getUint32(4);
      if (!metadataLength || metadataLength > 65536 || jpegLength > 4 * 1024 * 1024) {
        throw new Error('Invalid frame stream lengths');
      }
      const end = offset + 8 + metadataLength + jpegLength;
      if (end > bytes.length) break;
      const metrics = JSON.parse(new TextDecoder().decode(bytes.subarray(offset + 8, offset + 8 + metadataLength)));
      if (jpegLength) latest = { metrics, blob: new Blob([bytes.slice(offset + 8 + metadataLength, end)], { type: 'image/jpeg' }) };
      offset = end;
    }
    this.pending = bytes.slice(offset);
    return latest;
  }
}
