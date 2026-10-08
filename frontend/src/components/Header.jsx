import React from 'react';
import { Maximize, Activity } from 'lucide-react';
import { useApp } from '../context/AppContext';

export function Header({ title, onToggleFullscreen, isFullscreen, actions, status }) {
  const { telemetry, activeCamera } = useApp();

  const isLive = telemetry.stream_alive || telemetry.camera_status === 'RUNNING';
  const isConnecting = telemetry.camera_status === 'CONNECTING';

  let statusClass = 'disconnected';
  let statusText = 'MẤT KẾT NỐI';
  if (isLive) {
    statusClass = 'live';
    statusText = 'TRỰC TIẾP';
  } else if (isConnecting) {
    statusClass = 'connecting';
    statusText = 'ĐANG KẾT NỐI';
  }

  if (status) {
    statusClass = status.className;
    statusText = status.label;
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
