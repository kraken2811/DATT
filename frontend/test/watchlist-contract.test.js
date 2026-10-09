import test, { beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

test('CSS rules enforce 40x40px click target and scope AI Assistant classes', () => {
  const cssPath = path.resolve(__dirname, '../src/index.css');
  const cssContent = fs.readFileSync(cssPath, 'utf8');

  // Verify global .btn-icon definition has minimum 40px dimensions
  assert.ok(cssContent.includes('.btn-icon {'), 'Global .btn-icon must exist');
  assert.ok(cssContent.includes('min-width: 40px;'), '.btn-icon must have min-width 40px');
  assert.ok(cssContent.includes('min-height: 40px;'), '.btn-icon must have min-height 40px');
  assert.ok(cssContent.includes('width: 18px;'), '.btn-icon svg must have 18px size');

  // Verify AI Assistant .btn-icon is strictly scoped
  assert.ok(
    cssContent.includes('.agent-history-sidebar .btn-icon') ||
    cssContent.includes('.agent-container .sidebar-collapse-btn'),
    'AI Assistant icon buttons must be scoped to prevent overriding Watchlist'
  );

  // Verify AI Assistant .btn-danger is strictly scoped
  assert.ok(
    cssContent.includes('.modal-actions .btn-danger') ||
    cssContent.includes('.agent-modal .btn-danger'),
    'AI Assistant danger buttons must be scoped to prevent overriding Watchlist'
  );

  // Verify dedicated .btn-danger.btn-icon
  assert.ok(cssContent.includes('.btn-danger.btn-icon'), '.btn-danger.btn-icon styling must be defined');
});

test('Header component decouples camera stream from operational API connection', () => {
  const headerPath = path.resolve(__dirname, '../src/components/Header.jsx');
  const headerContent = fs.readFileSync(headerPath, 'utf8');

  // Must accept isCameraContext
  assert.ok(headerContent.includes('isCameraContext = false'), 'Header must default isCameraContext to false');

  // Must only derive CAMERA OFFLINE / LIVE in camera context
  assert.ok(headerContent.includes('else if (isCameraContext)'), 'Header must separate camera context');

  // Must support clear Vietnamese labels
  assert.ok(headerContent.includes('ĐÃ KẾT NỐI'), 'Header must support ĐÃ KẾT NỐI label');
  assert.ok(headerContent.includes('CẦN XÁC THỰC'), 'Header must support CẦN XÁC THỰC label');
  assert.ok(headerContent.includes('CHƯA CÓ QUYỀN'), 'Header must support CHƯA CÓ QUYỀN label');
  assert.ok(headerContent.includes('CAMERA OFFLINE') || headerContent.includes('CAMERA NGOẠI TUYẾN'), 'Header must support CAMERA OFFLINE label');
});

test('Face Watchlist card replaces active toggle button with Xem chi tiết', () => {
  const watchlistPath = path.resolve(__dirname, '../src/pages/WatchlistPage.jsx');
  const content = fs.readFileSync(watchlistPath, 'utf8');

  // Must include 'Xem chi tiết' button on face card
  assert.ok(content.includes('Xem chi tiết'), 'WatchlistPage must feature Xem chi tiết button');
  assert.ok(content.includes('btnViewDetailFace-'), 'Face card must have view detail button with unique ID');

  // Must render FaceDetailModal and VehicleDetailModal
  assert.ok(content.includes('<FaceDetailModal'), 'WatchlistPage must render FaceDetailModal');
  assert.ok(content.includes('<VehicleDetailModal'), 'WatchlistPage must render VehicleDetailModal');
  assert.ok(content.includes('<DeleteConfirmModal'), 'WatchlistPage must render DeleteConfirmModal');

  // Delete button must have 18px icon and accessible aria-label
  assert.ok(content.includes('Trash2 size={18}'), 'Delete button must use 18px Trash2 icon');
  assert.ok(content.includes('aria-label='), 'Delete buttons must have accessible aria-label');

  // Total counter must not show 0 during loading
  assert.ok(content.includes("faceLoading ? '—' : faceTotal"), 'Total count must show placeholder while loading');
  assert.ok(content.includes("vehicleLoading ? '—' : vehicleTotal"), 'Vehicle count must show placeholder while loading');
});

test('FaceDetailModal contract preserves toggle control without leaking raw embedding vectors', () => {
  const modalPath = path.resolve(__dirname, '../src/components/FaceDetailModal.jsx');
  const content = fs.readFileSync(modalPath, 'utf8');

  // Toggle control inside modal
  assert.ok(content.includes('btnToggleFaceActiveInModal'), 'Modal must have toggle control inside');
  assert.ok(content.includes('onToggleActive'), 'Modal must support onToggleActive callback');

  // Must show required metadata fields
  assert.ok(content.includes('UUID:'), 'Modal must show Target UUID');
  assert.ok(content.includes('Thời gian đăng ký'), 'Modal must show registration time');
  assert.ok(content.includes('Ngưỡng nhận diện (Threshold)'), 'Modal must show recognition threshold');
  assert.ok(content.includes('Màu trang phục nhận diện'), 'Modal must show clothing color');
  assert.ok(content.includes('Véc-tơ đặc trưng khuôn mặt'), 'Modal must show embedding status');
  assert.ok(content.includes('Xem lịch sử sự kiện'), 'Modal must provide link to Event Center');

  // Must NOT expose raw vectors
  assert.ok(!content.includes('raw_embedding'), 'Modal must not expose raw embedding floats');
  assert.ok(!content.includes('embedding.join'), 'Modal must not serialize raw embedding vector');
});
