const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const puppeteer = require('puppeteer-core');
const dist = path.resolve(__dirname, '../../src/ui/static/react_dist');
const requests = [];
const history = new Map([['restored-thread', [{ type: 'human', content: 'Previous question' }, { type: 'ai', content: 'Restored answer' }]]]);
let mode = 'success';
const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, 'http://localhost');
  requests.push({ method: req.method, path: url.pathname, session: req.headers['x-session-id'] });
  const route = url.pathname.replace(/^\/remote/, '');
  const json = (status, data) => { res.writeHead(status, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(data)); };
  if (route.startsWith('/api/agent/conversations/')) {
    const thread = decodeURIComponent(route.split('/').at(-1));
    if (req.method === 'DELETE') { history.delete(thread); return json(200, { status: 'success' }); }
    return json(200, { status: 'success', messages: history.get(thread) || [] });
  }
  if (route === '/api/agent/chat') {
    let body = ''; for await (const chunk of req) body += chunk;
    const payload = JSON.parse(body);
    if (mode === 'http-error') return json(404, { detail: 'Agent route unavailable' });
    if (mode === 'llm-error') return json(200, { status: 'llm_unavailable', reply: 'Mock provider unavailable' });
    history.set(payload.thread_id, [...(history.get(payload.thread_id) || []), { type: 'human', content: payload.message }, { type: 'ai', content: 'Mock reply' }]);
    return json(200, { status: 'success', reply: 'Mock reply', thread_id: payload.thread_id });
  }
  if (route === '/telemetry') return json(200, { camera_status: 'DISCONNECTED', stream_alive: false });
  if (route === '/cameras' || route.startsWith('/api/')) return json(200, { cameras: [], status: 'ok' });
  const asset = path.resolve(dist, '.' + url.pathname);
  const file = asset.startsWith(dist + path.sep) && fs.existsSync(asset) && fs.statSync(asset).isFile() ? asset : path.join(dist, 'index.html');
  res.writeHead(200, { 'Content-Type': file.endsWith('.js') ? 'text/javascript' : file.endsWith('.css') ? 'text/css' : 'text/html' });
  res.end(fs.readFileSync(file));
});
(async () => {
  let browser;
  try {
    await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
    const base = `http://127.0.0.1:${server.address().port}`;
    const candidates = [process.env.CHROME_PATH, 'C:/Program Files/Google/Chrome/Application/chrome.exe', 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', '/usr/bin/chromium', '/usr/bin/google-chrome'].filter(Boolean);
    const executablePath = candidates.find(file => fs.existsSync(file));
    assert.ok(executablePath, 'Set CHROME_PATH to a browser executable');
    browser = await puppeteer.launch({ executablePath, headless: true, args: ['--no-sandbox'] });
    const page = await browser.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.evaluateOnNewDocument(() => {
      if (!localStorage.getItem('datt_agent_thread_id')) localStorage.setItem('datt_agent_thread_id', 'restored-thread');
    });
    await page.goto(base + '/agent', { waitUntil: 'networkidle0' });
    await page.waitForFunction(() => document.querySelector('#chatMessages').textContent.includes('Restored answer'));
    assert.ok(await page.$('#agentPage .header-right button'), 'New conversation action is visible');
    assert.equal(await page.$eval('#headerStatusBadge', el => el.textContent.trim()), 'AGENT API ONLINE');
    const send = async (text) => {
      await page.type('#agentMessageInput', text);
      await page.click('#btnSendAgentMessage');
      await page.waitForFunction(() => !document.querySelector('#agentMessageInput').disabled);
    };
    await send('Hello');
    await page.waitForFunction(() => document.querySelector('#chatMessages').textContent.includes('Mock reply'));
    await page.reload({ waitUntil: 'networkidle0' });
    assert.ok(await page.$eval('#chatMessages', el => el.textContent.includes('Mock reply')), 'Sent messages restored after reload');
    mode = 'http-error';
    await send('Trigger HTTP error');
    await page.waitForFunction(() => [...document.querySelectorAll('.toast-item.error')].some(el => el.textContent.includes('Agent route unavailable')));
    assert.equal(await page.$eval('#headerStatusBadge', el => el.textContent.trim()), 'AGENT API OFFLINE');
    mode = 'llm-error';
    await send('Trigger provider error');
    await page.waitForFunction(() => [...document.querySelectorAll('.toast-item.error')].some(el => el.textContent.includes('Mock provider unavailable')));
    assert.equal(await page.$eval('#headerStatusBadge', el => el.textContent.trim()), 'AGENT API ONLINE');
    const previous = await page.evaluate(() => localStorage.getItem('datt_agent_thread_id'));
    // Toasts occupy the top-right corner; dismiss them before clicking the header action.
    await page.$$eval('.toast-close-btn', buttons => buttons.forEach(button => button.click()));
    await page.waitForFunction(() => !document.querySelector('#agentPage .header-right button').disabled);
    await page.click('#agentPage .header-right button');
    await page.waitForFunction(old => localStorage.getItem('datt_agent_thread_id') !== old, {}, previous);
    await page.waitForSelector('.toast-item.info');
    assert.ok(requests.some(req => req.method === 'DELETE' && req.path.endsWith(previous)));
    assert.equal(history.has(previous), false);
    mode = 'success';
    await send('New conversation');
    const current = await page.evaluate(() => localStorage.getItem('datt_agent_thread_id'));
    assert.equal(history.get(current).length, 2);
    await page.evaluate(baseUrl => localStorage.setItem('datt_backend_url', baseUrl + '/remote/'), base);
    await page.reload({ waitUntil: 'networkidle0' });
    assert.ok(requests.some(req => req.path.startsWith('/remote/api/agent/conversations/')), 'Saved API base URL is honored');
    assert.ok(requests.filter(req => req.path.includes('/api/agent/')).every(req => req.session), 'Stable session header accompanies Agent requests');
    assert.deepEqual(errors, [], 'No uncaught JavaScript errors');
    console.log('Agent browser regressions PASS: history, chat, HTTP/provider error toasts, reset/new thread, API status, base URL, session headers');
  } finally {
    if (browser) await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
