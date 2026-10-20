import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

test('SettingsPage Crowd Alert Threshold UI contract', () => {
  const settingsPath = path.resolve(__dirname, '../src/pages/SettingsPage.jsx');
  assert.ok(fs.existsSync(settingsPath), 'SettingsPage.jsx must exist');
  const content = fs.readFileSync(settingsPath, 'utf8');

  // Verify UI element IDs
  assert.ok(content.includes('id="settingCardCrowdThreshold"'), 'Must contain settingCardCrowdThreshold container');
  assert.ok(content.includes('id="inputCrowdThreshold"'), 'Must contain inputCrowdThreshold input field');
  assert.ok(content.includes('id="btnSaveCrowdThreshold"'), 'Must contain btnSaveCrowdThreshold button');

  // Verify description text required by specification
  assert.ok(
    content.includes('Generate a crowd alert when the detected number of people reaches or exceeds this threshold.'),
    'Must display exact requirement description'
  );

  // Verify unit indicator
  assert.ok(content.includes('people'), 'Must display "people" unit label');

  // Verify API endpoint interactions
  assert.ok(content.includes("apiRequest('/api/settings')"), 'Must fetch current settings from /api/settings');
  assert.ok(content.includes("method: 'PATCH'"), 'Must update settings via PATCH request');
  assert.ok(content.includes('crowd_threshold'), 'Must send and receive crowd_threshold payload key');

  // Verify input constraints and validation
  assert.ok(content.includes('min="1"'), 'Must specify minimum threshold value of 1');
  assert.ok(content.includes('val < 1'), 'Must validate integer >= 1 before submission');
});
