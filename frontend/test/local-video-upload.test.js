import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

test('Local Video Upload UI and contract in DashboardPage', () => {
  const dashboardPath = path.resolve(__dirname, '../src/pages/DashboardPage.jsx');
  assert.ok(fs.existsSync(dashboardPath), 'DashboardPage.jsx must exist');
  const content = fs.readFileSync(dashboardPath, 'utf8');

  // 1. Dashboard imports uploadVideo from ../api/cameras
  assert.ok(
    content.includes("uploadVideo") && content.includes("from '../api/cameras'"),
    '1. Dashboard must import uploadVideo from ../api/cameras'
  );

  // 2. Local tab contains a file input
  assert.ok(
    content.includes('id="localVideoFileInput"'),
    '2. Local tab must contain file input with id="localVideoFileInput"'
  );
  assert.ok(
    content.includes('type="file"'),
    '2. Local tab must contain an input of type="file"'
  );

  // 3. File input accept list matches backend-supported formats (.mp4, .mov, .mkv, .avi)
  assert.ok(
    content.includes('accept=".mp4,.mov,.mkv,.avi"'),
    '3. File input accept attribute must match backend ALLOWED_VIDEO_EXTENSIONS (.mp4,.mov,.mkv,.avi)'
  );

  // 4. Upload action creates FormData with field 'file'
  assert.ok(
    content.includes('new FormData()'),
    '4. Upload action must instantiate new FormData()'
  );
  assert.ok(
    content.includes("formData.append('file',") || content.includes('formData.append("file",'),
    "4. Upload action must append file to FormData with field name 'file'"
  );

  // 5. uploadVideo(formData) is called
  assert.ok(
    content.includes('uploadVideo(formData)'),
    '5. uploadVideo(formData) must be called with the constructed FormData'
  );

  // 6. Successful upload refreshes video sources
  assert.ok(
    content.includes('await loadVideoSources()') || content.includes('loadVideoSources()'),
    '6. Successful upload must trigger loadVideoSources() to refresh video list without page reload'
  );

  // 7. Upload failure does not replace the video list
  assert.ok(
    content.includes('setUploadError'),
    '7. Upload failure must update error state without overwriting videoSources list'
  );

  // 8. Upload button is disabled while uploading
  assert.ok(
    content.includes('disabled={isUploading}'),
    '8. Upload controls must be disabled while isUploading is true'
  );
  assert.ok(
    content.includes('id="btnUploadLocalVideo"'),
    '8. Primary upload button id="btnUploadLocalVideo" must exist'
  );

  // 9. Existing local source selection still works
  assert.ok(
    content.includes('handleSelectSource(sourceObj)'),
    '9. Existing source card selection handleSelectSource must be preserved'
  );
  assert.ok(
    content.includes('category: \'local\'') && content.includes('source_type: \'local\''),
    '9. Local video source object schema must be preserved'
  );

  // 10. Upload does NOT directly activate the backend monitoring pipeline
  assert.ok(
    !content.includes('switchActiveCamera('),
    '10. Dashboard must never directly invoke switchActiveCamera'
  );
  assert.ok(
    !content.includes('handleLaunchMonitoring(sourceObj)') ||
      !content.slice(content.indexOf('handleFileChange'), content.indexOf('handleFileChange') + 1500).includes('handleLaunchMonitoring'),
    '10. File upload handler must not automatically trigger handleLaunchMonitoring or navigation'
  );
});
