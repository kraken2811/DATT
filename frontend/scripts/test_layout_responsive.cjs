const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const puppeteer = require('puppeteer-core');

const dist = path.resolve(__dirname, '../../src/ui/static/react_dist');
const history = new Map([['test-thread', [{ type: 'human', content: 'Xin chào' }, { type: 'ai', content: 'Chào bạn, tôi là DATT AI Operations Assistant.' }]]]);
const conversationsMap = new Map([
  ['test-thread', {
    thread_id: 'test-thread',
    title: 'Tra cứu lưu lượng Camera 01',
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    last_message_at: new Date().toISOString(),
    status: 'active',
  }],
]);

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, 'http://localhost');
  const route = url.pathname.replace(/^\/remote/, '');
  const json = (status, data) => {
    res.writeHead(status, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify(data));
  };

  if (route.startsWith('/api/agent/conversations/')) {
    const thread = decodeURIComponent(route.split('/').at(-1));
    return json(200, { status: 'success', thread_id: thread, messages: history.get(thread) || [] });
  }

  if (route === '/api/agent/conversations') {
    return json(200, {
      status: 'success',
      conversations: Array.from(conversationsMap.values()),
      count: conversationsMap.size,
    });
  }

  if (route === '/telemetry') return json(200, { camera_status: 'RUNNING', stream_alive: true });
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
    const candidates = [
      process.env.CHROME_PATH,
      'C:/Program Files/Google/Chrome/Application/chrome.exe',
      'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
      '/usr/bin/chromium',
      '/usr/bin/google-chrome',
    ].filter(Boolean);
    const executablePath = candidates.find(file => fs.existsSync(file));
    assert.ok(executablePath, 'Browser executable not found');

    browser = await puppeteer.launch({ executablePath, headless: true, args: ['--no-sandbox'] });
    const page = await browser.newPage();

    await page.evaluateOnNewDocument(() => {
      localStorage.setItem('datt_agent_thread_id', 'test-thread');
    });

    const viewports = [
      { name: '1920x1080', width: 1920, height: 1080, isDesktop: true },
      { name: '1366x768', width: 1366, height: 768, isDesktop: true },
      { name: '768px (Tablet)', width: 768, height: 1024, isDesktop: false },
      { name: '390px (Mobile)', width: 390, height: 844, isDesktop: false },
    ];

    for (const vp of viewports) {
      await page.setViewport({ width: vp.width, height: vp.height });
      await page.goto(base + '/agent', { waitUntil: 'networkidle0' });
      await page.waitForSelector('#agentPage');

      const metrics = await page.evaluate((isDesktop) => {
        const body = document.body;
        const mainContent = document.querySelector('.main-content');
        const appSidebar = document.querySelector('.app-sidebar');
        const mainSidebarHeader = document.querySelector('.app-sidebar .sidebar-header');
        const appHeader = document.querySelector('.agent-page .app-header');
        const mainContainer = document.querySelector('.agent-main-container');
        const historySidebar = document.querySelector('.agent-history-sidebar');
        const chatLayout = document.querySelector('.agent-chat-layout');
        const threadHeader = document.querySelector('.chat-thread-header');
        const historyHeader = document.querySelector('.agent-history-sidebar .sidebar-header');

        const mainSidebarHeaderStyle = window.getComputedStyle(mainSidebarHeader);
        const appHeaderStyle = window.getComputedStyle(appHeader);
        const mainContainerStyle = window.getComputedStyle(mainContainer);
        const historySidebarStyle = window.getComputedStyle(historySidebar);
        const chatLayoutStyle = window.getComputedStyle(chatLayout);

        const historyRect = historySidebar ? historySidebar.getBoundingClientRect() : null;
        const chatRect = chatLayout ? chatLayout.getBoundingClientRect() : null;
        const containerRect = mainContainer ? mainContainer.getBoundingClientRect() : null;
        const appHeaderRect = appHeader ? appHeader.getBoundingClientRect() : null;

        const overflowing = Array.from(document.querySelectorAll('*'))
          .map(el => ({
            tag: el.tagName,
            id: el.id,
            className: el.className,
            right: el.getBoundingClientRect().right,
            width: el.getBoundingClientRect().width,
            scrollWidth: el.scrollWidth,
            clientWidth: el.clientWidth,
          }))
          .filter(x => x.right > body.clientWidth + 0.5);

        return {
          bodyScrollWidth: body.scrollWidth,
          bodyClientWidth: body.clientWidth,
          hasHorizontalScroll: body.scrollWidth > body.clientWidth,
          overflowing,
          mainSidebarHeaderHeight: parseFloat(mainSidebarHeaderStyle.height),
          appHeaderHeight: parseFloat(appHeaderStyle.height),
          appHeaderPaddingLeft: parseFloat(appHeaderStyle.paddingLeft),
          appHeaderPaddingRight: parseFloat(appHeaderStyle.paddingRight),
          mainContainerMarginLeft: parseFloat(mainContainerStyle.marginLeft),
          mainContainerMarginRight: parseFloat(mainContainerStyle.marginRight),
          mainContainerBorderRadius: mainContainerStyle.borderRadius,
          mainContainerOverflow: mainContainerStyle.overflow,
          historySidebarWidth: historyRect ? historyRect.width : 0,
          chatLayoutWidth: chatRect ? chatRect.width : 0,
          gapBetweenColumns: (historyRect && chatRect && isDesktop) ? (chatRect.left - historyRect.right) : 0,
          heightDifference: (historyRect && chatRect && isDesktop) ? Math.abs(historyRect.height - chatRect.height) : 0,
          isSidebarCollapsed: historySidebar ? historySidebar.classList.contains('collapsed') : true,
          historyHeaderHeight: historyHeader ? parseFloat(window.getComputedStyle(historyHeader).height) : 0,
          threadHeaderHeight: threadHeader ? parseFloat(window.getComputedStyle(threadHeader).height) : 0,
        };
      }, vp.isDesktop);

      if (metrics.hasHorizontalScroll) {
        console.error(`[OVERFLOW] Elements overflowing ${vp.name}:`, JSON.stringify(metrics.overflowing, null, 2));
      }

      console.log(`[PASS] Viewport ${vp.name}:`, JSON.stringify(metrics, null, 2));

      // 1. No unwanted horizontal scrollbar
      assert.equal(metrics.hasHorizontalScroll, false, `Viewport ${vp.name} must not have horizontal scrollbar`);

      // 2. Main sidebar header must be height 64px (var(--header-height))
      assert.equal(Math.round(metrics.mainSidebarHeaderHeight), 64, `Main sidebar header height must be 64px`);

      // 3. AI Assistant app header must be height 64px
      assert.equal(Math.round(metrics.appHeaderHeight), 64, `App header height must be 64px`);

      if (vp.isDesktop) {
        // 4. Desktop: gap between history sidebar and chat panel must be 0
        assert.ok(Math.abs(metrics.gapBetweenColumns) <= 1, `Desktop gap between columns must be 0px, got ${metrics.gapBetweenColumns}px`);

        // 5. Desktop: both columns must have matching heights
        assert.ok(metrics.heightDifference <= 1, `Desktop column heights must match, diff: ${metrics.heightDifference}px`);

        // 6. Desktop: conversation history width around 260-280px
        assert.ok(metrics.historySidebarWidth >= 260 && metrics.historySidebarWidth <= 285, `History sidebar width (${metrics.historySidebarWidth}) should be ~280px`);

        // 7. Desktop: app-header padding-left and main-container margin-left should align (both 32px)
        assert.equal(Math.round(metrics.appHeaderPaddingLeft), Math.round(metrics.mainContainerMarginLeft), `App header padding-left and main container margin-left must match`);

        // 8. Desktop: sub-headers in history and chat should share equal height
        assert.equal(Math.round(metrics.historyHeaderHeight), Math.round(metrics.threadHeaderHeight), `Sub-headers height must match`);
      }

      // 9. Combined workspace container must have rounded corners and overflow hidden
      assert.ok(metrics.mainContainerBorderRadius.includes('14px') || metrics.mainContainerBorderRadius.includes('var(--radius-lg)'), 'Container must have rounded corners');
      assert.equal(metrics.mainContainerOverflow, 'hidden', 'Container must have overflow: hidden');
    }

    // Test collapsing sidebar on desktop: chat should expand to fill workspace
    await page.setViewport({ width: 1366, height: 768 });
    await page.goto(base + '/agent', { waitUntil: 'networkidle0' });
    await page.waitForSelector('.sidebar-collapse-btn');
    await page.click('.sidebar-collapse-btn');
    await page.waitForFunction(() => document.querySelector('.agent-history-sidebar.collapsed'));

    const collapsedMetrics = await page.evaluate(() => {
      const historySidebar = document.querySelector('.agent-history-sidebar');
      const chatLayout = document.querySelector('.agent-chat-layout');
      const mainContainer = document.querySelector('.agent-main-container');
      const reopenBtn = document.querySelector('.sidebar-open-btn');
      return {
        isCollapsed: historySidebar.classList.contains('collapsed'),
        historyWidth: historySidebar.getBoundingClientRect().width,
        chatWidth: chatLayout.getBoundingClientRect().width,
        containerWidth: mainContainer.getBoundingClientRect().width,
        hasReopenBtn: Boolean(reopenBtn),
      };
    });

    console.log('[PASS] Collapsed Sidebar State:', JSON.stringify(collapsedMetrics, null, 2));
    assert.equal(collapsedMetrics.isCollapsed, true, 'Sidebar must have collapsed class');
    assert.equal(collapsedMetrics.historyWidth, 0, 'Collapsed sidebar width must be 0');
    assert.ok(collapsedMetrics.chatWidth >= collapsedMetrics.containerWidth - 4, 'Chat layout must expand to fill entire container');
    assert.equal(collapsedMetrics.hasReopenBtn, true, 'Reopen button must be visible when sidebar is collapsed');

    // Test reopening sidebar on desktop
    await page.click('.sidebar-open-btn');
    await page.waitForFunction(() => !document.querySelector('.agent-history-sidebar.collapsed'));
    const reopenedWidth = await page.evaluate(() => document.querySelector('.agent-history-sidebar').getBoundingClientRect().width);
    assert.ok(reopenedWidth >= 260, 'Reopened sidebar width must be restored to ~280px');

    console.log('\nAll Responsive Layout & Workspace Merge Tests PASSED successfully!');
  } finally {
    if (browser) await browser.close();
    server.close();
  }
})();
