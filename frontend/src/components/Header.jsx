import React from 'react';
import { Maximize, Activity } from 'lucide-react';
import { useApp } from '../context/AppContext';

export function Header({
  title,
  subtitle,
  onToggleFullscreen,
  isFullscreen,
  actions,
  status,
  isCameraContext = false,
}) {
  const { telemetry, activeCamera, authenticationStatus, apiStatus } = useApp();

  let statusClass = 'disconnected';
  let statusText = 'MẤT KẾT NỐI';

  if (status) {
    statusClass = status.className || 'live';
    statusText = status.label || 'ĐÃ KẾT NỐI';
  } else if (isCameraContext) {
    const isLive = telemetry.stream_alive || telemetry.camera_status === 'RUNNING';
    const isConnecting = telemetry.camera_status === 'CONNECTING';
    if (isLive) {
      statusClass = 'live';
      statusText = 'TRỰC TIẾP';
    } else if (isConnecting) {
      statusClass = 'connecting';
      statusText = 'ĐANG KẾT NỐI';
    } else {
      statusClass = 'warning';
      statusText = 'CAMERA OFFLINE';
    }
  } else {
    // Operational context default (Watchlist, Event Center, Alert Center, Settings, etc.)
    if (authenticationStatus === 401) {
      statusClass = 'disconnected';
      statusText = 'CẦN XÁC THỰC';
    } else if (authenticationStatus === 403) {
      statusClass = 'disconnected';
      statusText = 'CHƯA CÓ QUYỀN';
    } else if (apiStatus === 'connected' || !telemetry.is_fallback) {
      statusClass = 'live';
      statusText = 'ĐÃ KẾT NỐI';
    } else if (apiStatus === 'connecting') {
      statusClass = 'connecting';
      statusText = 'ĐANG TẢI...';
    } else {
      statusClass = 'disconnected';
      statusText = 'MẤT KẾT NỐI';
    }
  }

  // Ensure global auth failure overrides if no explicit page status was passed
  if (authenticationStatus && !status) {
    statusClass = 'disconnected';
    statusText = authenticationStatus === 403 ? 'CHƯA CÓ QUYỀN' : 'CẦN XÁC THỰC';
  }

  return (
    <header className="app-header">
      <div className="header-left">
        <h1 className="header-title">{title || activeCamera.name}</h1>
        <div className={`header-status-badge ${statusClass}`} id="headerStatusBadge">
          <Activity size={14} />
          <span>{statusText}</span>
        </div>
      </div>

      <div className="header-right">
        {actions}
        {onToggleFullscreen && (
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={onToggleFullscreen}
            id="btnToggleFullscreen"
            title={isFullscreen ? 'Thoát toàn màn hình' : 'Toàn màn hình'}
          >
            <Maximize size={16} />
            <span>{isFullscreen ? 'Thu nhỏ' : 'Toàn màn hình'}</span>
          </button>
        )}
      </div>
    </header>
  );
}
