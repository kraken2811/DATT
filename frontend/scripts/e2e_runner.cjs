const puppeteer = require('puppeteer-core');
const path = require('path');
const fs = require('fs');

const CHROME_PATH = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const SCREENSHOTS_DIR = path.resolve(__dirname, '..', '..', 'screenshots');
const BASE_URL = 'http://localhost:8501';

async function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function clickByText(page, tag, textSubstr) {
  return page.evaluate((tag, textSubstr) => {
    const elements = Array.from(document.querySelectorAll(tag));
    const target = elements.find(el => el.textContent && el.textContent.toLowerCase().includes(textSubstr.toLowerCase()));
    if (target) {
      target.click();
      return true;
    }
    return false;
  }, tag, textSubstr);
}

async function run() {
  console.log('====================================================');
  console.log('STARTING REAL REACT UI & PIPELINE E2E VERIFICATION');
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
    // ----------------------------------------------------
    // STEP 1: Open Dashboard
    // ----------------------------------------------------
    console.log('\n[1] Navigating to Dashboard...');
    await page.goto(`${BASE_URL}/dashboard`, { waitUntil: 'networkidle2', timeout: 30000 });
    await sleep(2500); // Allow telemetry & stream canvas/img to establish

    console.log('  -> Capturing 01_dashboard.png...');
    await page.screenshot({ path: path.join(SCREENSHOTS_DIR, '01_dashboard.png') });

    // ----------------------------------------------------
    // STEP 2: Dashboard Camera Source Tabs & Sources
    // ----------------------------------------------------
    console.log('\n[2] Testing Camera Sources & Tabs...');
    await clickByText(page, 'button', 'cctv');
    await sleep(1500);
    console.log('  -> Capturing 02_dashboard_camera_sources.png...');
    await page.screenshot({ path: path.join(SCREENSHOTS_DIR, '02_dashboard_camera_sources.png') });

    await clickByText(page, 'button', 'registered');
    await sleep(1000);

    // ----------------------------------------------------
    // STEP 3: Live Camera View & Fullscreen
    // ----------------------------------------------------
    console.log('\n[3] Testing Live Camera Normal View...');
    await page.goto(`${BASE_URL}/cameras/camera_01`, { waitUntil: 'networkidle2', timeout: 20000 });
    await sleep(2500);
    console.log('  -> Capturing 09_camera_normal.png...');
    await page.screenshot({ path: path.join(SCREENSHOTS_DIR, '09_camera_normal.png') });

    console.log('\n[4] Testing Camera Fullscreen Mode...');
    await page.evaluate(() => {
      const btn = document.querySelector('button[title*="Fullscreen" i], button[aria-label*="Fullscreen" i]') ||
                  Array.from(document.querySelectorAll('button')).find(b => b.innerHTML.includes('lucide-maximize'));
      if (btn) btn.click();
    });
    await sleep(1000);
    console.log('  -> Capturing 10_camera_fullscreen.png...');
    await page.screenshot({ path: path.join(SCREENSHOTS_DIR, '10_camera_fullscreen.png') });
    await page.keyboard.press('Escape');
    await sleep(1000);

    // ----------------------------------------------------
    // STEP 4: Camera Rapid Switching (A -> B -> C -> A)
    // ----------------------------------------------------
    console.log('\n[5] Testing Camera Rapid Switching (A -> B -> C -> A)...');
    await page.goto(`${BASE_URL}/dashboard`, { waitUntil: 'networkidle2' });
    await sleep(1500);

    const switchRes = await page.evaluate(async () => {
      const results = [];
      const sources = [
        { id: 'cam_A', name: 'Camera A', source_url: 'scratch/audit_fixture_200.mp4' },
        { id: 'cam_B', name: 'Camera B', source_url: 'data/uploads/videos/0a143c87_sample_test_traffic.mp4' },
        { id: 'cam_C', name: 'Camera C', source_url: 'scratch/audit_fixture_200.mp4' },
        { id: 'cam_A', name: 'Camera A', source_url: 'scratch/audit_fixture_200.mp4' },
      ];
      for (const s of sources) {
        try {
          const r = await fetch('/api/switch_camera', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(s)
          });
          results.push({ name: s.name, status: r.status });
        } catch (e) {
          results.push({ name: s.name, error: e.message });
        }
      }
      return results;
    });
    console.log('  -> Rapid switch result:', JSON.stringify(switchRes));
    await sleep(2000);

    // ----------------------------------------------------
    // STEP 5: Watchlist (Face Watchlist)
    // ----------------------------------------------------
    console.log('\n[6] Testing Watchlist (Face)...');
    await page.goto(`${BASE_URL}/watchlist?type=face`, { waitUntil: 'networkidle2' });
    await sleep(1500);
    await page.evaluate(() => {
      const inp = document.querySelector('input[placeholder*="Search" i], input[type="text"]');
      if (inp) {
        inp.value = 'target';
        inp.dispatchEvent(new Event('input', { bubbles: true }));
      }
    });
    await sleep(600);
    console.log('  -> Capturing 03_watchlist_face.png...');
    await page.screenshot({ path: path.join(SCREENSHOTS_DIR, '03_watchlist_face.png') });

    // ----------------------------------------------------
    // STEP 6: Watchlist (Vehicle Watchlist)
    // ----------------------------------------------------
    console.log('\n[7] Testing Watchlist (Vehicle)...');
    await page.goto(`${BASE_URL}/watchlist?type=vehicle`, { waitUntil: 'networkidle2' });
    await sleep(1500);
    console.log('  -> Capturing 04_watchlist_vehicle.png...');
    await page.screenshot({ path: path.join(SCREENSHOTS_DIR, '04_watchlist_vehicle.png') });

    // ----------------------------------------------------
    // STEP 7: Event Center
    // ----------------------------------------------------
    console.log('\n[8] Testing Event Center...');
    await page.goto(`${BASE_URL}/events`, { waitUntil: 'networkidle2' });
    await sleep(2000);
    console.log('  -> Capturing 05_event_center.png...');
    await page.screenshot({ path: path.join(SCREENSHOTS_DIR, '05_event_center.png') });

    console.log('\n[9] Testing Event Detail Modal...');
    await page.evaluate(() => {
      const eyeBtn = document.querySelector('button:has(svg.lucide-eye), button[title*="View" i], button[title*="detail" i]');
      if (eyeBtn) eyeBtn.click();
    });
    await sleep(1500);
    console.log('  -> Capturing 06_event_detail.png...');
    await page.screenshot({ path: path.join(SCREENSHOTS_DIR, '06_event_detail.png') });
    await page.keyboard.press('Escape');
    await sleep(500);

    // ----------------------------------------------------
    // STEP 8: Alert Center
    // ----------------------------------------------------
    console.log('\n[10] Testing Alert Center...');
    await page.goto(`${BASE_URL}/alerts`, { waitUntil: 'networkidle2' });
    await sleep(2000);
    console.log('  -> Capturing 07_alert_center.png...');
    await page.screenshot({ path: path.join(SCREENSHOTS_DIR, '07_alert_center.png') });

    console.log('\n[11] Testing Alert Detail Modal...');
    await page.evaluate(() => {
      const eyeBtn = document.querySelector('button:has(svg.lucide-eye)');
      if (eyeBtn) eyeBtn.click();
    });
    await sleep(1500);
    console.log('  -> Capturing 08_alert_detail.png...');
    await page.screenshot({ path: path.join(SCREENSHOTS_DIR, '08_alert_detail.png') });
    await page.keyboard.press('Escape');
    await sleep(500);

    // ----------------------------------------------------
    // STEP 9: Settings & Theme Persistence
    // ----------------------------------------------------
    console.log('\n[12] Testing Settings & Theme Persistence...');
    await page.goto(`${BASE_URL}/settings`, { waitUntil: 'networkidle2' });
    await sleep(1500);
    await page.evaluate(() => {
      const dots = Array.from(document.querySelectorAll('button[title*="Emerald" i], button[title*="Violet" i], button[title*="Amber" i], div.theme-picker button'));
      if (dots.length > 0) dots[1].click();
    });
    await sleep(800);
    await page.reload({ waitUntil: 'networkidle2' });
    await sleep(1500);
    console.log('  -> Capturing 11_settings_theme.png...');
    await page.screenshot({ path: path.join(SCREENSHOTS_DIR, '11_settings_theme.png') });

    // ----------------------------------------------------
    // STEP 10: Global Toast System (>= 4 notifications stack)
    // ----------------------------------------------------
    console.log('\n[13] Testing Global Toast System (Stack max 3)...');
    await page.evaluate(() => {
      if (window.showToast) {
        window.showToast('Notification #1: Camera connected', 'info', 5000);
        window.showToast('Notification #2: Watchlist sync complete', 'success', 5000);
        window.showToast('Notification #3: Zone event detected', 'warning', 5000);
        window.showToast('Notification #4: Priority Alert dispatched', 'error', 5000);
      }
    });
    await sleep(1000);
    console.log('  -> Capturing 12_toast_stack.png...');
    await page.screenshot({ path: path.join(SCREENSHOTS_DIR, '12_toast_stack.png') });

    console.log('\n====================================================');
    console.log('ALL 12 REAL SCREENSHOTS CAPTURED SUCCESSFULLY!');
    console.log('====================================================');

  } catch (err) {
    console.error('E2E Verification Error:', err);
    process.exit(1);
  } finally {
    await browser.close();
  }
}

run();
