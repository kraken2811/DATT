const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const puppeteer = require('puppeteer-core');
const dist = path.resolve(__dirname, '../../src/ui/static/react_dist');
const seen = [];
let framePacket;
const server = http.createServer((req, res) => {
  const pathname = new URL(req.url, 'http://localhost').pathname;
  const json = (status, data) => { res.writeHead(status, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(data)); };
  if (pathname.startsWith('/api/') || pathname === '/video_sources') {
    const authorized = req.headers.authorization === 'Bearer browser-fixture:signature';
    seen.push({ path: pathname, authorized });
    if (!authorized) return json(401, { detail: 'Bearer token required' });
    if (pathname === '/api/agent/conversations') return json(200, { status: 'success', user_id: 'browser-fixture', conversations: [], count: 0 });
    if (pathname === '/api/telemetry') return json(200, { status: 'ok', camera_status: 'STOPPED', people_count: 0, car_count: 0, stream_alive: false });
    if (pathname === '/api/frame_stream') {
      res.writeHead(200, { 'Content-Type': 'application/octet-stream', 'X-DATT-Frame-Protocol': '1' });
      // The production frame stream stays open. Closing it immediately correctly
      // clears the canvas and cannot validate a persistent live frame.
      res.write(framePacket);
      return;
    }
    return json(200, { cameras: [], events: [], sources: [], primary_device: 'CUDA' });
  }
  const asset = path.resolve(dist, '.' + pathname);
  const file = asset.startsWith(dist + path.sep) && fs.existsSync(asset) && fs.statSync(asset).isFile() ? asset : path.join(dist, 'index.html');
  res.writeHead(200, { 'Content-Type': file.endsWith('.js') ? 'text/javascript' : file.endsWith('.css') ? 'text/css' : 'text/html' });
  res.end(fs.readFileSync(file));
});
(async () => {
  let browser;
  try {
    await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
    const executablePath = [process.env.CHROME_PATH, 'C:/Program Files/Google/Chrome/Application/chrome.exe', 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', '/usr/bin/chromium', '/usr/bin/google-chrome'].find(file => file && fs.existsSync(file));
    assert.ok(executablePath, 'Set CHROME_PATH to a browser executable');
    browser = await puppeteer.launch({ executablePath, headless: true, args: ['--no-sandbox'] });
    const page = await browser.newPage();
    const jpeg = Buffer.from(await page.evaluate(() => {
      const canvas = document.createElement('canvas');
      canvas.width = canvas.height = 1;
      const context = canvas.getContext('2d');
      context.fillStyle = '#ff0000'; context.fillRect(0, 0, 1, 1);
      return canvas.toDataURL('image/jpeg').split(',')[1];
    }), 'base64');
    const metadata = Buffer.from(JSON.stringify({ frame_id: 1, source_generation: 1, frame_age_ms: 0 }));
    const header = Buffer.alloc(8); header.writeUInt32BE(metadata.length); header.writeUInt32BE(jpeg.length, 4);
    framePacket = Buffer.concat([header, metadata, jpeg]);
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    const base = 'http://127.0.0.1:' + server.address().port;
    await page.goto(base + '/dashboard', { waitUntil: 'networkidle0' });
    await page.waitForSelector('#authenticationNotice');
    assert.equal(await page.$eval('#statPeopleCount', node => node.textContent.trim()), '—');
    const count = seen.filter(item => item.path === '/api/telemetry').length;
    // Prove polling stopped, rather than only checking the initial error text.
    await new Promise(resolve => setTimeout(resolve, 2400));
    assert.equal(seen.filter(item => item.path === '/api/telemetry').length, count);
    await page.click('#authenticationNotice a');
    await page.waitForSelector('#inputAuthToken');
    assert.equal(await page.$eval('#inputAuthToken', node => node.type), 'password');
    await page.type('#inputAuthToken', 'invalid:signature');
    await page.click('#btnAuthenticate');
    await page.waitForFunction(() => document.querySelector('#settingsAuthentication').textContent.includes('Token chưa được lưu'));
    assert.equal(await page.evaluate(() => localStorage.getItem('datt_auth_token')), null);
    await page.type('#inputAuthToken', 'browser-fixture:signature');
    await page.click('#btnAuthenticate');
    await page.waitForFunction(() => localStorage.getItem('datt_auth_token') === 'browser-fixture:signature');
    await page.waitForFunction(() => !document.querySelector('#authenticationNotice'));
    await page.goto(base + '/dashboard', { waitUntil: 'domcontentloaded' });
    await page.waitForFunction(() => document.querySelector('#statPeopleCount').textContent.trim() === '0');
    assert.ok(seen.some(item => item.path === '/api/telemetry' && item.authorized));
    assert.ok(seen.some(item => item.path === '/api/frame_stream' && item.authorized), 'Video sends authorization without a token URL');
    await page.waitForFunction(() => {
      const canvas = document.querySelector('#mainVideoStream');
      return canvas?.width === 1 && canvas.getContext('2d').getImageData(0, 0, 1, 1).data[0] > 200;
    });
    await page.goto(base + '/settings', { waitUntil: 'networkidle0' });
    assert.equal(await page.$eval('#inputAuthToken', node => node.value), '');
    await page.screenshot({ path: path.resolve(__dirname, '../../scratch/auth-settings-regression.png'), fullPage: true });
    assert.deepEqual(errors, []);
    console.log('Authentication browser regression PASS: denied polling pauses, unavailable differs from zero, invalid token not saved, valid account verified, polling resumes, video headers, masked empty input, no JS errors');
  } finally {
    if (browser) await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
