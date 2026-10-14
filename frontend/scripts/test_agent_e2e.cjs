const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const puppeteer = require('puppeteer-core');
const dist = path.resolve(__dirname, '../../src/ui/static/react_dist');
const requests = [];
const history = new Map([['restored-thread', [{ type: 'human', content: 'Previous question' }, { type: 'ai', content: 'Restored answer' }]]]);
const conversationsMap = new Map([
  ['restored-thread', {
    thread_id: 'restored-thread',
    title: 'Previous question',
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    last_message_at: new Date().toISOString(),
    status: 'active',
  }],
]);

let mode = 'success';
const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, 'http://localhost');
  requests.push({ method: req.method, path: url.pathname, session: req.headers['x-session-id'] });
  const route = url.pathname.replace(/^\/remote/, '');
  const json = (status, data) => { res.writeHead(status, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(data)); };

  if (route.startsWith('/api/agent/conversations/')) {
    const thread = decodeURIComponent(route.split('/').at(-1));
    if (req.method === 'DELETE') {
      history.delete(thread);
      conversationsMap.delete(thread);
      return json(200, { status: 'success', message: 'deleted' });
    }
    if (req.method === 'PATCH') {
      let body = ''; for await (const chunk of req) body += chunk;
      const payload = JSON.parse(body);
      const conv = conversationsMap.get(thread) || { thread_id: thread, title: payload.title };
      conv.title = payload.title;
      conversationsMap.set(thread, conv);
      return json(200, { status: 'success', conversation: conv });
    }
    return json(200, { status: 'success', thread_id: thread, messages: history.get(thread) || [] });
  }

  if (route === '/api/agent/conversations') {
    if (req.method === 'POST') {
      let body = ''; for await (const chunk of req) body += chunk;
      let payload = {};
      try { payload = JSON.parse(body); } catch (e) {}
      const threadId = payload.thread_id || `thread_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`;
      const conv = {
        thread_id: threadId,
        title: payload.title || 'Cuộc trò chuyện mới',
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        last_message_at: new Date().toISOString(),
        status: 'active',
      };
      conversationsMap.set(threadId, conv);
      return json(200, { status: 'success', conversation: conv });
    }
    return json(200, {
      status: 'success',
      conversations: Array.from(conversationsMap.values()),
      count: conversationsMap.size,
    });
  }

  if (route === '/api/agent/chat') {
    let body = ''; for await (const chunk of req) body += chunk;
    const payload = JSON.parse(body);
    if (mode === 'http-error') return json(404, { detail: 'Agent route unavailable' });
    if (mode === 'llm-error') return json(200, { status: 'llm_unavailable', reply: 'Mock provider unavailable' });
    if (mode === 'slow') {
      await new Promise(r => setTimeout(r, 2500));
    }
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
    browser = await puppeteer.launch({ executablePath, headless: true, args: ['--no-sandbox', '--window-size=1280,800'] });
    const page = await browser.newPage();
    await page.setViewport({ width: 1280, height: 800 });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.evaluateOnNewDocument(() => {
      if (!localStorage.getItem('datt_agent_thread_id')) localStorage.setItem('datt_agent_thread_id', 'restored-thread');
    });
    await page.goto(base + '/agent', { waitUntil: 'networkidle0' });
    await page.waitForFunction(() => document.querySelector('#chatMessages').textContent.includes('Restored answer'));
    assert.ok(await page.$('#agentPage .header-right button'), 'New conversation action is visible');
    assert.equal(await page.$eval('#headerStatusBadge', el => el.textContent.trim()), 'AGENT API ONLINE');

    // Verify decorative sparkles and per-message model badges are removed
    assert.equal(await page.$('.provider-model-badge'), null, 'Per-message model badges must be removed');
    assert.equal(await page.$('.quick-prompts-label svg'), null, 'Sparkles icon removed from quick prompts label');

    const send = async (text) => {
      await page.type('#agentMessageInput', text);
      await page.click('#btnSendAgentMessage');
      await page.waitForFunction(() => !document.querySelector('.loading-row'));
    };
    await send('Hello');
    await page.waitForFunction(() => document.querySelector('#chatMessages').textContent.includes('Mock reply'));
    await page.reload({ waitUntil: 'networkidle0' });
    assert.ok(await page.$eval('#chatMessages', el => el.textContent.includes('Mock reply')), 'Sent messages restored after reload');

    // TEST PHASE 2, 3, 4, 5, 6: ACTIVE INPUT, STOP BUTTON, VOICE AVAILABILITY & RE-SEND
    mode = 'slow';
    await page.type('#agentMessageInput', 'Question A slow');
    await page.click('#btnSendAgentMessage');

    // Immediately verify processing state
    await page.waitForSelector('#btnSendAgentMessage.is-stopping');
    const stopAriaLabel = await page.$eval('#btnSendAgentMessage', el => el.getAttribute('aria-label'));
    assert.equal(stopAriaLabel, 'Dừng phản hồi', 'Stop button accessible aria-label');
    const stopBtnText = await page.$eval('#btnSendAgentMessage', el => el.textContent.trim());
    assert.equal(stopBtnText, '', 'Stop button must be icon-only without visible text');
    const inputDisabled = await page.$eval('#agentMessageInput', el => el.disabled);
    assert.equal(inputDisabled, false, 'Text input MUST remain editable while agent is processing');
    const micDisabled = await page.$eval('#btnVoiceInput', el => el.disabled);
    assert.equal(micDisabled, false, 'Microphone MUST remain enabled while agent is processing');

    // Type Question B draft while agent is still processing Question A
    await page.type('#agentMessageInput', 'Question B draft');
    const typedDraft = await page.$eval('#agentMessageInput', el => el.value);
    assert.equal(typedDraft, 'Question B draft', 'Typed draft preserved while processing');

    // Click Stop button to interrupt active request safely
    await page.click('#btnSendAgentMessage');
    await page.waitForFunction(() => !document.querySelector('.loading-row'));

    // Verify after stop state
    const afterStopAria = await page.$eval('#btnSendAgentMessage', el => el.getAttribute('aria-label'));
    assert.equal(afterStopAria, 'Gửi tin nhắn', 'Button reverts to Send icon after stop');
    const preservedDraft = await page.$eval('#agentMessageInput', el => el.value);
    assert.equal(preservedDraft, 'Question B draft', 'Current draft preserved after stopping response');

    // Now submit Question B successfully
    mode = 'success';
    await page.click('#btnSendAgentMessage');
    await page.waitForFunction(() => document.querySelector('#chatMessages').textContent.includes('Question B draft'));
    await page.waitForFunction(() => !document.querySelector('.loading-row'));

    mode = 'http-error';
    await send('Trigger HTTP error');
    await page.waitForFunction(() => [...document.querySelectorAll('.toast-item.error')].some(el => el.textContent.includes('Agent route unavailable')));
    assert.equal(await page.$eval('#headerStatusBadge', el => el.textContent.trim()), 'AGENT API OFFLINE');
    mode = 'llm-error';
    await send('Trigger provider error');
    await page.waitForFunction(() => [...document.querySelectorAll('.toast-item.error')].some(el => el.textContent.includes('Mock provider unavailable')));
    assert.equal(await page.$eval('#headerStatusBadge', el => el.textContent.trim()), 'AGENT API ONLINE');

    // Test creating a new conversation (MUST NEVER CALL DELETE)
    const previous = await page.evaluate(() => localStorage.getItem('datt_agent_thread_id'));
    // Toasts occupy the top-right corner; dismiss them before clicking the header action.
    await page.$$eval('.toast-close-btn', buttons => buttons.forEach(button => button.click()));
    await page.waitForFunction(() => !document.querySelector('#agentPage .header-right button').disabled);

    // Test Draft Preservation across conversation switching
    await page.type('#agentMessageInput', 'Draft in previous conversation');
    await page.click('#agentPage .header-right button');
    await page.waitForFunction(old => localStorage.getItem('datt_agent_thread_id') !== old, {}, previous);
    await page.waitForSelector('.toast-item.info');

    // In new conversation, input is empty
    const newConvInput = await page.$eval('#agentMessageInput', el => el.value);
    assert.equal(newConvInput, '', 'New conversation has clean input');

    // Switch back to previous conversation in sidebar
    await page.click('.conversation-item:not(.active)');
    await page.waitForFunction(prevId => localStorage.getItem('datt_agent_thread_id') === prevId, {}, previous);
    const restoredDraft = await page.$eval('#agentMessageInput', el => el.value);
    assert.equal(restoredDraft, 'Draft in previous conversation', 'Draft correctly preserved when switching conversations');
    await page.$eval('#agentMessageInput', el => { el.value = ''; el.dispatchEvent(new Event('input', { bubbles: true })); });

    // Switch back to the newly created conversation
    await page.click('.conversation-item:not(.active)');
    await page.waitForFunction(prevId => localStorage.getItem('datt_agent_thread_id') !== prevId, {}, previous);

    // FEATURE B Requirement: Creating a new conversation must NEVER invoke DELETE
    assert.equal(requests.some(req => req.method === 'DELETE' && req.path.endsWith(previous)), false, 'New conversation must NEVER call DELETE');
    assert.equal(history.has(previous), true, 'Previous conversation history MUST be preserved in history');

    mode = 'success';
    await send('New conversation');
    const current = await page.evaluate(() => localStorage.getItem('datt_agent_thread_id'));
    assert.equal(history.get(current).length, 2);

    // Verify explicit deletion works only when explicitly requested
    await page.evaluate(threadToDelete => {
      const sessionId = localStorage.getItem('datt_agent_session_id') || 'test-session';
      return fetch(`/api/agent/conversations/${encodeURIComponent(threadToDelete)}`, {
        method: 'DELETE',
        headers: { 'X-Session-Id': sessionId },
      });
    }, previous);
    assert.ok(requests.some(req => req.method === 'DELETE' && req.path.endsWith(previous)), 'Explicit delete endpoint callable');

    await page.evaluate(baseUrl => localStorage.setItem('datt_backend_url', baseUrl + '/remote/'), base);
    await page.reload({ waitUntil: 'networkidle0' });
    assert.ok(requests.some(req => req.path.startsWith('/remote/api/agent/conversations')), 'Saved API base URL is honored');
    assert.ok(requests.filter(req => req.path.includes('/api/agent/')).every(req => req.session), 'Stable session header accompanies Agent requests');
    assert.deepEqual(errors, [], 'No uncaught JavaScript errors');
    console.log('Agent browser regressions PASS: active input while processing, icon-only stop, draft preservation across switching, mic availability, sparkles/model badges removal, history, error toasts, multi-thread continuity');
  } finally {
    if (browser) await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
