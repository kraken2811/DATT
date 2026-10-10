import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

test('1 & 2: Dashboard initially shows only source selection and recent events (no video stream or stat cards)', () => {
  const dashboardPath = path.resolve(__dirname, '../src/pages/DashboardPage.jsx');
  const content = fs.readFileSync(dashboardPath, 'utf8');

  // Must NOT import or mount AuthenticatedVideo
  assert.ok(!content.includes('AuthenticatedVideo'), 'DashboardPage must not mount AuthenticatedVideo');
  assert.ok(!content.includes('/api/frame_stream'), 'DashboardPage must not request /api/frame_stream');

  // Must NOT include the live telemetry stat cards
  assert.ok(!content.includes('statPeopleCard'), 'DashboardPage must not have statPeopleCard');
  assert.ok(!content.includes('statVehicleCard'), 'DashboardPage must not have statVehicleCard');
  assert.ok(!content.includes('statFpsCard'), 'DashboardPage must not have statFpsCard');
  assert.ok(!content.includes('statLatencyCard'), 'DashboardPage must not have statLatencyCard');

  // Must NOT include stop camera or stream fullscreen controls
  assert.ok(!content.includes('stopActiveCamera'), 'DashboardPage must not provide camera stop controls');
  assert.ok(!content.includes('isFullscreen'), 'DashboardPage must not contain stream fullscreen controls');

  // Must display clear heading
  assert.ok(
    content.includes('Bảng điều khiển (Dashboard)') || content.includes('title="Dashboard"'),
    'DashboardPage must have clear heading'
  );

  // Must feature Camera Source Selection with 4 tabs
  assert.ok(content.includes('Lựa chọn nguồn Camera'), 'DashboardPage must have Camera Source Selection header');
  assert.ok(content.includes('tabBtnRegistered'), 'DashboardPage must have registered cameras tab');
  assert.ok(content.includes('tabBtnCctv'), 'DashboardPage must have CCTV tab');
  assert.ok(content.includes('tabBtnLocal'), 'DashboardPage must have local videos tab');
  assert.ok(content.includes('tabBtnCustom'), 'DashboardPage must have custom stream tab');

  // Must feature Recent Events with "Sự kiện gần nhất" and "Xem tất cả sự kiện"
  assert.ok(content.includes('Sự kiện gần nhất'), 'DashboardPage must feature "Sự kiện gần nhất" section');
  assert.ok(content.includes('Xem tất cả sự kiện'), 'DashboardPage must feature "Xem tất cả sự kiện" navigation');
});

test('3 & 4: Selecting a camera updates selection state only; clicking "Xem camera" navigates to monitor', () => {
  const dashboardPath = path.resolve(__dirname, '../src/pages/DashboardPage.jsx');
  const content = fs.readFileSync(dashboardPath, 'utf8');

  // Pure frontend selection state
  assert.ok(content.includes('setSelectedSource('), 'DashboardPage must maintain selectedSource state');
  assert.ok(!content.includes('switchActiveCamera('), 'DashboardPage must NEVER trigger switchActiveCamera directly');

  // Obvious "Xem camera" action on selected source
  assert.ok(content.includes('btnLaunchSelectedCamera'), 'DashboardPage must feature prominent Xem camera banner action');
  assert.ok(content.includes('Xem camera'), 'DashboardPage must display "Xem camera" label');

  // Navigation logic
  assert.ok(
    content.includes("navigate(`/cameras/${src.id}`") || content.includes("navigate('/cameras/' + src.id"),
    'Registered cameras navigate to /cameras/:id'
  );
  assert.ok(
    content.includes("navigate('/monitor'"),
    'Transient cameras navigate to /monitor'
  );
  assert.ok(content.includes('state: { source: src'), 'Navigation must pass source via state without exposing secrets in query string');
});

test('5, 6, 7 & 8: All four source categories (registered, CCTV, local video, custom URL) are supported', () => {
  const dashboardPath = path.resolve(__dirname, '../src/pages/DashboardPage.jsx');
  const content = fs.readFileSync(dashboardPath, 'utf8');

  // 1. Registered cameras
  assert.ok(content.includes('registeredCamerasGrid'), 'Registered cameras grid must exist');
  assert.ok(content.includes('loadCameras'), 'Must fetch registered cameras');

  // 2. Public CCTV
  assert.ok(content.includes('cctvCamerasGrid'), 'CCTV cameras grid must exist');
  assert.ok(content.includes('cctvProviderSelect'), 'Provider selector must exist');
  assert.ok(content.includes('cctvSearchInput'), 'CCTV search input must exist');

  // 3. Local video upload
  assert.ok(content.includes('localVideosGrid'), 'Local videos grid must exist');
  assert.ok(content.includes('loadVideoSources'), 'Must fetch uploaded video sources');

  // 4. Custom URL (RTSP / HLS / YouTube)
  assert.ok(content.includes('customSourceForm'), 'Custom stream form must exist');
  assert.ok(content.includes('customSourceTypeSelect'), 'Must support direct_hls, rtsp, youtube options');
  assert.ok(content.includes('customSourceUrlInput'), 'Must accept stream URL');
});

test('9 & 10: Monitoring page owns activation without duplicates and displays correct telemetry values', () => {
  const monitorPath = path.resolve(__dirname, '../src/pages/CameraViewPage.jsx');
  const content = fs.readFileSync(monitorPath, 'utf8');

  // Owns switchActiveCamera activation with deduplication ref
  assert.ok(content.includes('autoSwitchRef'), 'Must use ref to prevent duplicate camera switches');
  assert.ok(content.includes('switchActiveCamera('), 'Monitoring page must trigger switchActiveCamera');

  // Displays genuine 0 vs — for telemetry values
  assert.ok(
    content.includes("typeof telemetry.people_count === 'number' ? telemetry.people_count : '—'"),
    'People count must show 0 when 0 and — when unavailable'
  );
  assert.ok(
    content.includes("typeof telemetry.car_count === 'number' ? telemetry.car_count : '—'"),
    'Vehicle count must show 0 when 0 and — when unavailable'
  );
  assert.ok(
    content.includes("telemetry.processing_fps") && content.includes("statFpsValue"),
    'Must display processing or stream FPS'
  );
  assert.ok(
    content.includes("typeof telemetry.pipeline_latency_ms === 'number'") && content.includes("'—'"),
    'Pipeline latency must show — when unavailable and value when number'
  );
});

test('11 & 12: Monitoring page has stop, fullscreen, and "Quay lại Dashboard" controls', () => {
  const monitorPath = path.resolve(__dirname, '../src/pages/CameraViewPage.jsx');
  const content = fs.readFileSync(monitorPath, 'utf8');

  // Stop camera button
  assert.ok(content.includes('btnStopCamera'), 'Must have btnStopCamera');
  assert.ok(content.includes('stopActiveCamera'), 'Must wire up stopActiveCamera');

  // Fullscreen controls
  assert.ok(content.includes('btnFullscreenInStream'), 'Must have btnFullscreenInStream');
  assert.ok(content.includes('toggleFullscreen'), 'Must have toggleFullscreen');

  // Quay lại Dashboard button
  assert.ok(content.includes('btnBackToDashboard'), 'Must have btnBackToDashboard');
  assert.ok(content.includes('Quay lại Dashboard'), 'Must show text "Quay lại Dashboard"');
});

test('13 & 14: Handles missing transient state gracefully without silently playing another camera', () => {
  const monitorPath = path.resolve(__dirname, '../src/pages/CameraViewPage.jsx');
  const content = fs.readFileSync(monitorPath, 'utf8');

  assert.ok(content.includes('missingSourceState'), 'Must track missing source state');
  assert.ok(content.includes('missingSourceCard'), 'Must render dedicated missing source card');
  assert.ok(content.includes('Chưa chọn nguồn camera'), 'Must inform user that no camera source is selected');
  assert.ok(content.includes('btnSelectSourceFromDashboard'), 'Must provide button to return to Dashboard');
  assert.ok(content.includes('sanitizeStreamUrl'), 'Must sanitize and mask credentials from source URLs');
});

test('15: App routes configure /monitor and preserve all existing routes', () => {
  const appPath = path.resolve(__dirname, '../src/App.jsx');
  const content = fs.readFileSync(appPath, 'utf8');

  assert.ok(content.includes('<Route path="/" element={<DashboardPage />} />'), 'Route / must be DashboardPage');
  assert.ok(content.includes('<Route path="/dashboard" element={<DashboardPage />} />'), 'Route /dashboard must be DashboardPage');
  assert.ok(content.includes('<Route path="/monitor" element={<CameraViewPage />} />'), 'Route /monitor must be CameraViewPage');
  assert.ok(content.includes('<Route path="/cameras/:id" element={<CameraViewPage />} />'), 'Route /cameras/:id must be CameraViewPage');
  assert.ok(content.includes('<Route path="/cameras" element={<CameraManagementPage />} />'), 'Route /cameras must remain CameraManagementPage');
  assert.ok(content.includes('<Route path="/watchlist" element={<WatchlistPage />} />'), 'Route /watchlist must remain WatchlistPage');
  assert.ok(content.includes('<Route path="/events" element={<EventCenterPage />} />'), 'Route /events must remain EventCenterPage');
  assert.ok(content.includes('<Route path="/alerts" element={<AlertCenterPage />} />'), 'Route /alerts must remain AlertCenterPage');
});

test('16: CameraManagementPage "Giám sát" navigates to monitoring screen instead of old dashboard', () => {
  const camMgmtPath = path.resolve(__dirname, '../src/pages/CameraManagementPage.jsx');
  const content = fs.readFileSync(camMgmtPath, 'utf8');

  assert.ok(
    content.includes("navigate(`/cameras/${cam.id}`"),
    'CameraManagementPage must navigate to /cameras/:id for monitoring'
  );
});
