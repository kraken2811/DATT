const puppeteer = require('puppeteer-core');
const path = require('path');
const fs = require('fs');

const CHROME_PATH = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const SCREENSHOTS_DIR = path.resolve(__dirname, '..', '..', 'screenshots');
const BASE_URL = 'http://localhost:8501';

async function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function getThemeState(page) {
  return page.evaluate(() => {
    return {
      themeAttr: document.documentElement.getAttribute('data-theme'),
      themeDataset: document.documentElement.dataset.theme,
      accentAttr: document.documentElement.getAttribute('data-accent'),
      accentDataset: document.documentElement.dataset.accent,
      localStorageTheme: localStorage.getItem('datt_theme'),
      localStorageAccent: localStorage.getItem('datt_accent_color'),
      computedBg: window.getComputedStyle(document.body).backgroundColor,
      computedColor: window.getComputedStyle(document.body).color,
    };
  });
}

async function run() {
  console.log('====================================================');
  console.log('STARTING DATT REACT LIGHT / DARK THEME E2E TESTS');
  console.log('====================================================');

  if (!fs.existsSync(SCREENSHOTS_DIR)) {
    fs.mkdirSync(SCREENSHOTS_DIR, { recursive: true });
  }

  const browser = await puppeteer.launch({
    executablePath: CHROME_PATH,
    headless: 'new',
    defaultViewport: { width: 1920, height: 1080 },
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--window-size=1920,1080'],
  });

  const page = await browser.newPage();

  page.on('console', (msg) => {
    if (msg.type() === 'error') {
      console.log(`[Browser Console Error] ${msg.text()}`);
    }
  });

  try {
    // -------------------------------------------------------------------------
    // TEST 1: Fresh browser with no saved preference -> Default LIGHT
    // -------------------------------------------------------------------------
    console.log('\n[TEST 1] Fresh browser verification (no saved preference)...');
    await page.goto(`${BASE_URL}/settings`, { waitUntil: 'networkidle2' });
    await page.evaluate(() => {
      localStorage.removeItem('datt_theme');
      localStorage.removeItem('datt_accent_color');
    });
    await page.reload({ waitUntil: 'networkidle2' });
    await sleep(1000);

    let state = await getThemeState(page);
    console.log('  State after fresh load:', state);
    if (state.themeDataset !== 'light') {
      throw new Error(`TEST 1 FAILED: Expected default theme 'light', got '${state.themeDataset}'`);
    }
    console.log('  -> PASS: Default theme is LIGHT');
    await page.screenshot({ path: path.join(SCREENSHOTS_DIR, 'theme_01_fresh_light.png') });

    // -------------------------------------------------------------------------
    // TEST 2: Switch Light -> Dark -> immediate DARK
    // -------------------------------------------------------------------------
    console.log('\n[TEST 2] Switching Light -> Dark...');
    await page.click('#btnThemeDark');
    await sleep(500);

    state = await getThemeState(page);
    console.log('  State after selecting Dark:', state);
    if (state.themeDataset !== 'dark' || state.localStorageTheme !== 'dark') {
      throw new Error(`TEST 2 FAILED: Expected immediate 'dark', got '${state.themeDataset}'`);
    }
    console.log('  -> PASS: Immediate switch to DARK');
    await page.screenshot({ path: path.join(SCREENSHOTS_DIR, 'theme_02_switch_dark.png') });

    // -------------------------------------------------------------------------
    // TEST 3: Refresh -> remains DARK
    // -------------------------------------------------------------------------
    console.log('\n[TEST 3] Refreshing while DARK...');
    await page.reload({ waitUntil: 'networkidle2' });
    await sleep(1000);

    state = await getThemeState(page);
    console.log('  State after refresh:', state);
    if (state.themeDataset !== 'dark' || state.localStorageTheme !== 'dark') {
      throw new Error(`TEST 3 FAILED: Expected retained 'dark' after reload, got '${state.themeDataset}'`);
    }
    console.log('  -> PASS: Theme persistence verified: remains DARK across reload');

    // -------------------------------------------------------------------------
    // TEST 4: Switch Dark -> Light -> immediate LIGHT
    // -------------------------------------------------------------------------
    console.log('\n[TEST 4] Switching Dark -> Light...');
    await page.click('#btnThemeLight');
    await sleep(500);

    state = await getThemeState(page);
    console.log('  State after selecting Light:', state);
    if (state.themeDataset !== 'light' || state.localStorageTheme !== 'light') {
      throw new Error(`TEST 4 FAILED: Expected immediate 'light', got '${state.themeDataset}'`);
    }
    console.log('  -> PASS: Immediate switch to LIGHT');
    await page.screenshot({ path: path.join(SCREENSHOTS_DIR, 'theme_03_switch_light.png') });

    // -------------------------------------------------------------------------
    // TEST 5: Refresh -> remains LIGHT
    // -------------------------------------------------------------------------
    console.log('\n[TEST 5] Refreshing while LIGHT...');
    await page.reload({ waitUntil: 'networkidle2' });
    await sleep(1000);

    state = await getThemeState(page);
    console.log('  State after refresh:', state);
    if (state.themeDataset !== 'light' || state.localStorageTheme !== 'light') {
      throw new Error(`TEST 5 FAILED: Expected retained 'light' after reload, got '${state.themeDataset}'`);
    }
    console.log('  -> PASS: Theme persistence verified: remains LIGHT across reload');

    // -------------------------------------------------------------------------
    // TEST 6: Change Accent Color while LIGHT -> Theme remains LIGHT
    // -------------------------------------------------------------------------
    console.log('\n[TEST 6] Changing Accent Color to Emerald while LIGHT...');
    await page.click('#btnThemeemerald');
    await sleep(500);

    state = await getThemeState(page);
    console.log('  State after accent change in LIGHT:', state);
    if (state.themeDataset !== 'light') {
      throw new Error(`TEST 6 FAILED: Theme changed when setting accent! Expected 'light', got '${state.themeDataset}'`);
    }
    if (state.accentDataset !== 'emerald' || state.localStorageAccent !== 'emerald') {
      throw new Error(`TEST 6 FAILED: Accent color was not set to 'emerald'`);
    }
    console.log('  -> PASS: Accent changed to Emerald; Theme remains LIGHT independently');

    // -------------------------------------------------------------------------
    // TEST 7: Change Accent Color while DARK -> Theme remains DARK
    // -------------------------------------------------------------------------
    console.log('\n[TEST 7] Switching to DARK and changing Accent Color to Violet...');
    await page.click('#btnThemeDark');
    await sleep(500);
    await page.click('#btnThemeviolet');
    await sleep(500);

    state = await getThemeState(page);
    console.log('  State after accent change in DARK:', state);
    if (state.themeDataset !== 'dark') {
      throw new Error(`TEST 7 FAILED: Theme changed when setting accent! Expected 'dark', got '${state.themeDataset}'`);
    }
    if (state.accentDataset !== 'violet' || state.localStorageAccent !== 'violet') {
      throw new Error(`TEST 7 FAILED: Accent color was not set to 'violet'`);
    }
    console.log('  -> PASS: Accent changed to Violet; Theme remains DARK independently');

    // Reset accent back to blue
    await page.click('#btnThemeblue');
    await sleep(300);

    // -------------------------------------------------------------------------
    // TEST 8: Full Navigation Consistency (Dark & Light)
    // -------------------------------------------------------------------------
    console.log('\n[TEST 8] Navigating all pages under DARK mode...');
    const pagesToTest = [
      { name: 'Dashboard', selector: '#navItemDashboard', directUrl: `${BASE_URL}/dashboard` },
      { name: 'Camera', selector: '#navItemCameras', directUrl: `${BASE_URL}/cameras` },
      { name: 'Live View', directUrl: `${BASE_URL}/cameras/camera_01` },
      { name: 'Watchlist', selector: '#navItemWatchlist', directUrl: `${BASE_URL}/watchlist` },
      { name: 'Event Center', selector: '#navItemEvents', directUrl: `${BASE_URL}/events` },
      { name: 'Alerts', selector: '#navItemAlerts', directUrl: `${BASE_URL}/alerts` },
      { name: 'Analytics', clientRoute: '/analytics' },
      { name: 'Settings', selector: '#navItemSettings', directUrl: `${BASE_URL}/settings` },
    ];

    for (const p of pagesToTest) {
      if (p.selector) {
        await page.click(p.selector);
      } else if (p.clientRoute) {
        await page.evaluate((r) => {
          window.history.pushState({}, '', r);
          window.dispatchEvent(new PopStateEvent('popstate'));
        }, p.clientRoute);
      } else if (p.directUrl) {
        await page.goto(p.directUrl, { waitUntil: 'networkidle2' });
      }
      await sleep(600);
      const st = await getThemeState(page);
      if (st.themeDataset !== 'dark') {
        throw new Error(`TEST 8 FAILED: Page ${p.name} lost dark theme! Got '${st.themeDataset}'`);
      }
      console.log(`  -> Page ${p.name}: verified dark theme consistent.`);
    }
    await page.screenshot({ path: path.join(SCREENSHOTS_DIR, 'theme_04_dark_dashboard.png') });

    // Switch to LIGHT and test navigation consistency
    console.log('\n[TEST 8b] Navigating all pages under LIGHT mode...');
    await page.click('#navItemSettings');
    await sleep(500);
    await page.click('#btnThemeLight');
    await sleep(500);

    for (const p of pagesToTest) {
      if (p.selector) {
        await page.click(p.selector);
      } else if (p.clientRoute) {
        await page.evaluate((r) => {
          window.history.pushState({}, '', r);
          window.dispatchEvent(new PopStateEvent('popstate'));
        }, p.clientRoute);
      } else if (p.directUrl) {
        await page.goto(p.directUrl, { waitUntil: 'networkidle2' });
      }
      await sleep(600);
      const st = await getThemeState(page);
      if (st.themeDataset !== 'light') {
        throw new Error(`TEST 8b FAILED: Page ${p.name} lost light theme! Got '${st.themeDataset}'`);
      }
      console.log(`  -> Page ${p.name}: verified light theme consistent.`);
    }
    await page.screenshot({ path: path.join(SCREENSHOTS_DIR, 'theme_05_light_dashboard.png') });

    // -------------------------------------------------------------------------
    // TEST 9: Components (Modal, Dropdown, Table, Toast, Fullscreen Camera)
    // -------------------------------------------------------------------------
    console.log('\n[TEST 9] Testing Component Rendering in Light & Dark modes...');

    // 9a: Tables & Toasts in Light Mode
    await page.goto(`${BASE_URL}/events`, { waitUntil: 'networkidle2' });
    await sleep(1000);
    console.log('  -> Capturing Light Table & Modal...');
    // Open Event Detail Modal in Light Mode
    await page.evaluate(() => {
      const btn = document.querySelector('button:has(svg.lucide-eye)');
      if (btn) btn.click();
    });
    await sleep(800);
    await page.screenshot({ path: path.join(SCREENSHOTS_DIR, 'theme_06_light_modal.png') });
    await page.keyboard.press('Escape');
    await sleep(500);

    // 9b: Switch to Dark Mode, Table & Modal in Dark Mode
    await page.goto(`${BASE_URL}/settings`, { waitUntil: 'networkidle2' });
    await page.click('#btnThemeDark');
    await sleep(500);

    await page.goto(`${BASE_URL}/events`, { waitUntil: 'networkidle2' });
    await sleep(1000);
    console.log('  -> Capturing Dark Table & Modal...');
    await page.evaluate(() => {
      const btn = document.querySelector('button:has(svg.lucide-eye)');
      if (btn) btn.click();
    });
    await sleep(800);
    await page.screenshot({ path: path.join(SCREENSHOTS_DIR, 'theme_07_dark_modal.png') });
    await page.keyboard.press('Escape');
    await sleep(500);

    // 9c: Fullscreen Camera in Dark Mode
    await page.goto(`${BASE_URL}/cameras/camera_01`, { waitUntil: 'networkidle2' });
    await sleep(1500);
    await page.evaluate(() => {
      const btn = document.querySelector('button#btnToggleFullscreen');
      if (btn) btn.click();
    });
    await sleep(1000);
    console.log('  -> Capturing Dark Fullscreen Camera...');
    await page.screenshot({ path: path.join(SCREENSHOTS_DIR, 'theme_08_dark_fullscreen.png') });
    await page.keyboard.press('Escape');
    await sleep(500);

    // 9d: Fullscreen Camera in Light Mode
    await page.goto(`${BASE_URL}/settings`, { waitUntil: 'networkidle2' });
    await page.click('#btnThemeLight');
    await sleep(500);

    await page.goto(`${BASE_URL}/cameras/camera_01`, { waitUntil: 'networkidle2' });
    await sleep(1500);
    await page.evaluate(() => {
      const btn = document.querySelector('button#btnToggleFullscreen');
      if (btn) btn.click();
    });
    await sleep(1000);
    console.log('  -> Capturing Light Fullscreen Camera...');
    await page.screenshot({ path: path.join(SCREENSHOTS_DIR, 'theme_09_light_fullscreen.png') });
    await page.keyboard.press('Escape');
    await sleep(500);

    console.log('\n====================================================');
    console.log('ALL LIGHT / DARK THEME E2E TESTS PASSED SUCCESSFULLY!');
    console.log('====================================================');

    await browser.close();
    process.exit(0);
  } catch (err) {
    console.error('Theme E2E Test Failure:', err);
    if (browser) await browser.close();
    process.exit(1);
  }
}

run();
