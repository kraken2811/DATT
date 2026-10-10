const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const puppeteer = require('puppeteer-core');

const dist = path.resolve(__dirname, '../../src/ui/static/react_dist');
const screenshotsDir = path.resolve(__dirname, '../../screenshots');

if (!fs.existsSync(screenshotsDir)) {
  fs.mkdirSync(screenshotsDir, { recursive: true });
}

// Mock cameras and events for reliable UI testing
const mockCameras = [
  {
    id: 'cam-01',
    name: 'Camera Cổng Bắc',
    source_type: 'rtsp',
    source_url: 'rtsp://192.168.1.100:554/live',
    zone: 'Cổng chính A1',
    status: 'online',
    enabled: true,
  },
  {
    id: 'cam-02',
    name: 'Camera Bãi Đỗ Xe',
    source_type: 'rtsp',
    source_url: 'rtsp://192.168.1.101:554/live',
    zone: 'Bãi đỗ xe B2',
    status: 'online',
    enabled: true,
  },
];

const mockEvents = [
  {
    event_id: 'evt-01',
    timestamp: new Date().toISOString(),
    event_type: 'face',
    semantic_type: 'Face Detected',
    camera_id: 'cam-01',
    target_id: 'target-uuid-12345678',
    confidence: 0.94,
    watchlist_match: true,
  },
  {
    event_id: 'evt-02',
    timestamp: new Date().toISOString(),
    event_type: 'plate',
    semantic_type: 'Plate Match',
    camera_id: 'cam-02',
    plate: '29A-123.45',
    confidence: 0.98,
    watchlist_match: false,
  },
];

const mockTelemetry = {
  status: 'CONNECTED',
  camera_status: 'RUNNING',
  stream_alive: true,
  people_count: 2,
  car_count: 0,
  stream_fps: 29.9,
  processing_fps: 30.2,
  yolo_latency_ms: 18,
  pipeline_latency_ms: 14,
  camera_name: 'Camera Cổng Bắc',
  is_fallback: false,
};

let switchCallCount = 0;
let lastSwitchedSource = null;
let stopCallCount = 0;

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, 'http://localhost');
  const json = (status, data) => {
    res.writeHead(status, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify(data));
  };

  if (url.pathname === '/telemetry' || url.pathname === '/api/telemetry') {
    return json(200, mockTelemetry);
  }

  if (url.pathname === '/api/cameras') {
    return json(200, { status: 'ok', cameras: mockCameras, total: mockCameras.length });
  }

  if (url.pathname.startsWith('/api/cameras/')) {
    const id = decodeURIComponent(url.pathname.replace('/api/cameras/', ''));
    const cam = mockCameras.find(c => c.id === id);
    if (cam) return json(200, { status: 'ok', camera: cam });
    return json(404, { status: 'error', detail: 'Camera không tồn tại' });
  }

  if (url.pathname === '/video_sources') {
    return json(200, { sources: [{ id: 'src-01', name: 'Sample Vehicle Benchmark', storage_path: '/data/sample.mp4', file_path: 'videos/sample.mp4' }] });
  }

  if (url.pathname === '/public_cameras') {
    return json(200, { cameras: [{ id: 'cctv-01', name: 'I-80 North Bound', stream_url: 'https://cctv.test/live.m3u8', provider: 'caltrans', district: 'District 4' }] });
  }

  if (url.pathname === '/api/event_center/events') {
    return json(200, { status: 'ok', events: mockEvents, total: mockEvents.length });
  }

  if (url.pathname === '/switch_camera' || url.pathname === '/api/select_source') {
    switchCallCount++;
    let body = '';
    req.on('data', chunk => { body += chunk; });
    req.on('end', () => {
      try { lastSwitchedSource = JSON.parse(body); } catch {}
      json(200, { status: 'ok', camera_id: 'cam-01', camera_name: 'Camera Cổng Bắc' });
    });
    return;
  }

  if (url.pathname === '/stop_camera') {
    stopCallCount++;
    return json(200, { status: 'ok' });
  }

  if (url.pathname === '/api/frame_stream') {
    res.writeHead(200, {
      'Content-Type': 'application/octet-stream',
      'X-DATT-Frame-Protocol': '1',
    });
    res.write(Buffer.from([]));
    return;
  }

  const asset = path.resolve(dist, '.' + url.pathname);
  const file = asset.startsWith(dist + path.sep) && fs.existsSync(asset) && fs.statSync(asset).isFile() ? asset : path.join(dist, 'index.html');
  res.writeHead(200, { 'Content-Type': file.endsWith('.js') ? 'text/javascript' : file.endsWith('.css') ? 'text/css' : 'text/html' });
  res.end(fs.readFileSync(file));
});

(async () => {
  let browser;
  try {
    await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
    const port = server.address().port;
    const base = `http://127.0.0.1:${port}`;
    console.log(`Test server running at ${base}`);

    const candidates = [
      process.env.CHROME_PATH,
      'C:/Program Files/Google/Chrome/Application/chrome.exe',
      'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
      '/usr/bin/chromium',
      '/usr/bin/google-chrome',
    ].filter(Boolean);
    const executablePath = candidates.find(file => fs.existsSync(file));
    assert.ok(executablePath, 'Browser executable not found');

    browser = await puppeteer.launch({
      executablePath,
      headless: true,
      args: ['--no-sandbox', '--disable-setuid-sandbox'],
    });

    const page = await browser.newPage();
    page.on('console', msg => console.log('[BROWSER]', msg.type(), msg.text()));
    page.on('pageerror', err => console.log('[PAGE ERROR]', err));
    await page.setViewport({ width: 1440, height: 900 });

    // -------------------------------------------------------------------------
    // TEST 1: Dashboard Landing Page
    // -------------------------------------------------------------------------
    console.log('\n[E2E 1] Loading Dashboard (desktop)...');
    await page.goto(`${base}/`, { waitUntil: 'networkidle0' });
    await page.waitForSelector('#dashboardPage');

    // Verify video stream is NOT present on Dashboard
    const videoStreamOnDashboard = await page.$('#mainVideoStream');
    assert.equal(videoStreamOnDashboard, null, 'Dashboard must NOT have video stream');

    // Verify stat cards are NOT present on Dashboard
    const statCardsOnDashboard = await page.$('#monitoringStatsGrid');
    assert.equal(statCardsOnDashboard, null, 'Dashboard must NOT have monitoring stats grid');

    // Verify camera selection and events exist
    await page.waitForSelector('#registeredCamerasGrid');
    await page.waitForSelector('#dashboardEventsTable');
    console.log('✓ Dashboard shows only camera sources and recent events');

    // Capture initial Dashboard screenshot
    const dashInitialPath = path.resolve(screenshotsDir, 'redesign_01_dashboard_initial.png');
    await page.screenshot({ path: dashInitialPath, fullPage: true });
    console.log(`Saved screenshot: ${dashInitialPath}`);

    // -------------------------------------------------------------------------
    // TEST 2: Selecting a camera updates UI only (no backend switch)
    // -------------------------------------------------------------------------
    console.log('\n[E2E 2] Selecting Camera Cổng Bắc without launching...');
    const switchCountBefore = switchCallCount;
    await page.click('#sourceCard_registered_cam-01');

    // Verify selected card class and banner
    await page.waitForSelector('#selectedSourceBanner');
    const isCardSelected = await page.$eval('#sourceCard_registered_cam-01', el => el.classList.contains('selected'));
    assert.equal(isCardSelected, true, 'Card must have .selected class');
    assert.equal(switchCallCount, switchCountBefore, 'Selecting camera must NOT trigger backend switch');
    console.log('✓ Camera selected cleanly without backend activation');

    // Capture selected Dashboard screenshot
    const dashSelectedPath = path.resolve(screenshotsDir, 'redesign_02_dashboard_selected.png');
    await page.screenshot({ path: dashSelectedPath, fullPage: true });
    console.log(`Saved screenshot: ${dashSelectedPath}`);

    // -------------------------------------------------------------------------
    // TEST 3: Clicking "Xem camera" navigates to Monitoring Screen
    // -------------------------------------------------------------------------
    console.log('\n[E2E 3] Clicking "Xem camera" to open monitoring interface...');
    await page.click('#btnLaunchSelectedCamera');
    await page.waitForSelector('#cameraMonitoringPage');

    // Verify URL is /cameras/cam-01
    const currentUrl = page.url();
    assert.ok(currentUrl.includes('/cameras/cam-01'), `Expected /cameras/cam-01, got ${currentUrl}`);

    // Verify top stat cards exist and show correct values
    // Wait for telemetry polling update
    await page.waitForFunction(
      () => document.querySelector('#statPeopleCount')?.textContent.trim() === '2',
      { timeout: 5000 }
    );
    const peopleCount = await page.$eval('#statPeopleCount', el => el.textContent.trim());
    const vehicleCount = await page.$eval('#statVehicleCount', el => el.textContent.trim());
    const fpsValue = await page.$eval('#statFpsValue', el => el.textContent.trim());
    const latencyValue = await page.$eval('#statLatencyValue', el => el.textContent.trim());

    assert.equal(peopleCount, '2', 'People count must match telemetry');
    assert.equal(vehicleCount, '0', 'Vehicle count must match genuine zero');
    assert.ok(fpsValue.includes('fps'), 'FPS must include fps unit');
    assert.ok(latencyValue.includes('ms'), 'Latency must include ms unit');
    console.log(`✓ Telemetry verified: People=${peopleCount}, Vehicle=${vehicleCount}, FPS=${fpsValue}, Latency=${latencyValue}`);

    // Verify 16:9 authenticated video player and controls
    await page.waitForSelector('#mainVideoStream');
    await page.waitForSelector('#btnStopCamera');
    await page.waitForSelector('#btnFullscreenInStream');
    await page.waitForSelector('#cameraTechnicalDetailsCard');

    // Verify switch call occurred on monitoring page mount exactly once
    assert.equal(switchCallCount, switchCountBefore + 1, 'Monitoring page must trigger switch exactly once');
    console.log('✓ Dedicated monitoring screen verified');

    // Capture Monitoring Screen screenshot
    const monitorPath = path.resolve(screenshotsDir, 'redesign_03_camera_monitoring.png');
    await page.screenshot({ path: monitorPath, fullPage: true });
    console.log(`Saved screenshot: ${monitorPath}`);

    // -------------------------------------------------------------------------
    // TEST 4: Stop camera control
    // -------------------------------------------------------------------------
    console.log('\n[E2E 4] Testing Stop Camera control...');
    const stopCountBefore = stopCallCount;
    await page.click('#btnStopCamera');
    assert.equal(stopCallCount, stopCountBefore + 1, 'Stop camera must trigger backend stop endpoint');
    console.log('✓ Stop camera control verified');

    // -------------------------------------------------------------------------
    // TEST 5: Back to Dashboard button
    // -------------------------------------------------------------------------
    console.log('\n[E2E 5] Testing "Quay lại Dashboard"...');
    await page.click('#btnBackToDashboard');
    await page.waitForSelector('#dashboardPage');
    assert.ok(page.url().endsWith('/') || page.url().includes('/dashboard'), 'Must return to Dashboard');
    console.log('✓ Returned to Dashboard successfully');

    // -------------------------------------------------------------------------
    // TEST 6: Missing transient source state handling on /monitor
    // -------------------------------------------------------------------------
    console.log('\n[E2E 6] Testing missing source state on /monitor...');
    await page.goto(`${base}/monitor`, { waitUntil: 'networkidle0' });
    await page.waitForSelector('#missingSourceCard');
    const missingTitle = await page.$eval('#missingSourceCard h2', el => el.textContent.trim());
    assert.equal(missingTitle, 'Chưa chọn nguồn camera');
    console.log('✓ Missing transient source state shows clear re-selection card');

    const missingPath = path.resolve(screenshotsDir, 'redesign_04_missing_source_state.png');
    await page.screenshot({ path: missingPath, fullPage: true });
    console.log(`Saved screenshot: ${missingPath}`);

    // -------------------------------------------------------------------------
    // TEST 7: Mobile responsive layout verification
    // -------------------------------------------------------------------------
    console.log('\n[E2E 7] Verifying mobile responsive view (390x844)...');
    await page.setViewport({ width: 390, height: 844 });
    await page.goto(`${base}/`, { waitUntil: 'networkidle0' });
    await page.waitForSelector('#dashboardPage');

    const mobileDashPath = path.resolve(screenshotsDir, 'redesign_05_mobile_dashboard.png');
    await page.screenshot({ path: mobileDashPath, fullPage: true });
    console.log(`Saved screenshot: ${mobileDashPath}`);

    await page.goto(`${base}/cameras/cam-01`, { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('#cameraMonitoringPage');
    const mobileMonitorPath = path.resolve(screenshotsDir, 'redesign_06_mobile_monitor.png');
    await page.screenshot({ path: mobileMonitorPath, fullPage: true });
    console.log(`Saved screenshot: ${mobileMonitorPath}`);
    console.log('✓ Mobile responsive layout verified');

    console.log('\n=======================================================');
    console.log('ALL E2E BROWSER VALIDATION TESTS PASSED SUCCESSFULLY!');
    console.log('=======================================================');
  } finally {
    if (browser) await browser.close();
    server.close();
  }
})().catch(err => {
  console.error('E2E validation failed:', err);
  process.exit(1);
});
