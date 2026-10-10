import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useParams, useNavigate, useLocation } from 'react-router-dom';
import { Header } from '../components/Header';
import { AuthenticatedVideo } from '../components/AuthenticatedVideo';
import { fetchCameraDetail } from '../api/cameras';
import { useApp } from '../context/AppContext';
import { LoadingSpinner, ErrorState } from '../components/StatusStates';
import {
  ArrowLeft,
  Square,
  Play,
  Maximize,
  Minimize,
  Users,
  Car,
  Gauge,
  Zap,
  Camera,
  AlertTriangle,
  Info,
  RefreshCw,
} from 'lucide-react';

function sanitizeStreamUrl(url) {
  if (!url) return '—';
  try {
    return url.replace(/:\/\/([^@/]+)@/, '://***:***@');
  } catch {
    return url;
  }
}

export function CameraViewPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const location = useLocation();

  const {
    telemetry,
    activeCamera,
    switchActiveCamera,
    stopActiveCamera,
  } = useApp();

  const [camera, setCamera] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [missingSourceState, setMissingSourceState] = useState(false);

  const streamContainerRef = useRef(null);
  const autoSwitchRef = useRef(null);

  // Source object passed via navigation state (e.g. from Dashboard or Camera Management)
  const transientSource = location.state?.source || null;
  const cameFromCameras = location.state?.from === '/cameras';

  // Toggle fullscreen
  const toggleFullscreen = () => {
    setIsFullscreen((prev) => !prev);
  };

  // Handle ESC key for exiting fullscreen
  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key === 'Escape' && isFullscreen) {
        setIsFullscreen(false);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isFullscreen]);

  // Resolve camera source & trigger activation exactly once
  useEffect(() => {
    let isMounted = true;
    const abortCtrl = new AbortController();

    const resolveAndActivate = async () => {
      setLoading(true);
      setError(null);
      setMissingSourceState(false);

      try {
        let resolvedCamera = null;

        if (id) {
          // Case 1: Route is /cameras/:id (registered camera)
          if (transientSource && (transientSource.id === id || transientSource.camera_id === id)) {
            resolvedCamera = transientSource;
          } else {
            const resp = await fetchCameraDetail(id, abortCtrl.signal);
            if (resp?.status === 'ok' && resp.camera) {
              resolvedCamera = resp.camera;
            } else {
              throw new Error(resp?.detail || 'Camera không tồn tại hoặc đã bị xóa');
            }
          }
        } else {
          // Case 2: Route is /monitor (transient source e.g. CCTV, local video, custom URL)
          if (transientSource) {
            resolvedCamera = transientSource;
          } else {
            // Missing source state after page reload or direct visit
            if (isMounted) {
              setMissingSourceState(true);
              setLoading(false);
            }
            return;
          }
        }

        if (!isMounted || !resolvedCamera) return;

        setCamera(resolvedCamera);

        // Generate a switch key to prevent duplicate calls
        const switchKey = resolvedCamera.id
          ? `id:${resolvedCamera.id}`
          : `src:${resolvedCamera.source_type}:${resolvedCamera.source_url || resolvedCamera.video_source_id}`;

        if (autoSwitchRef.current !== switchKey) {
          autoSwitchRef.current = switchKey;
          await switchActiveCamera(resolvedCamera);
        }
      } catch (err) {
        if (err.name !== 'AbortError' && isMounted) {
          setError(err.message || 'Không thể kết nối tới nguồn camera');
        }
      } finally {
        if (isMounted) setLoading(false);
      }
    };

    resolveAndActivate();

    return () => {
      isMounted = false;
      abortCtrl.abort();
    };
  }, [id, transientSource, switchActiveCamera]);

  // Restart camera if currently stopped
  const handleRestart = async () => {
    const src = camera || transientSource;
    if (src) {
      await switchActiveCamera(src);
    }
  };

  const displayName = camera?.name || transientSource?.name || activeCamera.name || 'AI Vision Monitor';

  // Determine stream display status text & badge style
  const isStopped = telemetry.camera_status === 'STOPPED';
  const isConnecting = telemetry.camera_status === 'CONNECTING';
  const isRunning = telemetry.camera_status === 'RUNNING' || telemetry.stream_alive;
  const isError = telemetry.camera_status === 'ERROR';

  let statusBadgeText = 'OFFLINE';
  let statusBadgeStyle = { background: 'var(--bg-hover)', color: 'var(--text-muted)' };

  if (isStopped) {
    statusBadgeText = 'ĐÃ DỪNG';
    statusBadgeStyle = { background: 'rgba(245, 158, 11, 0.15)', color: '#f59e0b' };
  } else if (isConnecting) {
    statusBadgeText = 'ĐANG KẾT NỐI';
    statusBadgeStyle = { background: 'rgba(59, 130, 246, 0.15)', color: '#3b82f6' };
  } else if (isRunning) {
    statusBadgeText = 'TRỰC TIẾP';
    statusBadgeStyle = { background: 'rgba(16, 185, 129, 0.15)', color: '#10b981' };
  } else if (isError) {
    statusBadgeText = 'LỖI KẾT NỐI';
    statusBadgeStyle = { background: 'rgba(239, 68, 68, 0.15)', color: '#ef4444' };
  }

  return (
    <>
      <Header
        title={displayName}
        onToggleFullscreen={toggleFullscreen}
        isFullscreen={isFullscreen}
        isCameraContext={true}
      />

      <div className="page-container" id="cameraMonitoringPage">
        {/* Navigation Bar: Quay lại Dashboard */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            marginBottom: '16px',
            flexWrap: 'wrap',
            gap: '10px',
          }}
        >
          <div style={{ display: 'flex', gap: '8px' }}>
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={() => navigate('/')}
              id="btnBackToDashboard"
            >
              <ArrowLeft size={16} />
              <span>Quay lại Dashboard</span>
            </button>

            {cameFromCameras && (
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={() => navigate('/cameras')}
                id="btnBackToCameras"
              >
                <span>Quay lại Quản lý Camera</span>
              </button>
            )}
          </div>
        </div>

        {/* Missing Source State (e.g. Browser reload on /monitor without saved history state) */}
        {missingSourceState ? (
          <div
            className="card"
            style={{
              textAlign: 'center',
              padding: '48px 24px',
              maxWidth: '600px',
              margin: '30px auto',
            }}
            id="missingSourceCard"
          >
            <div
              style={{
                width: '56px',
                height: '56px',
                borderRadius: '50%',
                background: 'var(--accent-surface)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                margin: '0 auto 16px',
                color: 'var(--accent)',
              }}
            >
              <Camera size={28} />
            </div>
            <h2 style={{ fontSize: '1.25rem', fontWeight: 600, marginBottom: '8px' }}>
              Chưa chọn nguồn camera
            </h2>
            <p
              style={{
                color: 'var(--text-muted)',
                fontSize: '0.9rem',
                marginBottom: '24px',
                lineHeight: 1.5,
              }}
            >
              Không tìm thấy thông tin nguồn camera hoặc phiên làm việc đã kết thúc. Vui lòng chọn
              một nguồn camera từ Dashboard để bắt đầu theo dõi trực tiếp.
            </p>
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => navigate('/')}
              id="btnSelectSourceFromDashboard"
            >
              <ArrowLeft size={16} />
              <span>Quay lại Dashboard chọn nguồn</span>
            </button>
          </div>
        ) : loading ? (
          <div className="card">
            <LoadingSpinner text="Đang kết nối luồng camera..." />
          </div>
        ) : error ? (
          <ErrorState
            message={error}
            onRetry={() => {
              if (id) {
                navigate(0); // Reload current page
              } else {
                navigate('/');
              }
            }}
          />
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
            {/* Top Section: Live Real Telemetry Statistic Cards */}
            <div className="stats-grid" id="monitoringStatsGrid">
              {/* Stat 1: People Count */}
              <div className="stat-card" id="statPeopleCard">
                <div className="stat-header">
                  <span>Người trong khung hình</span>
                  <Users size={16} />
                </div>
                <div className="stat-value" id="statPeopleCount">
                  {typeof telemetry.people_count === 'number' ? telemetry.people_count : '—'}
                </div>
              </div>

              {/* Stat 2: Vehicles Detected */}
              <div className="stat-card" id="statVehicleCard">
                <div className="stat-header">
                  <span>Phương tiện phát hiện</span>
                  <Car size={16} />
                </div>
                <div className="stat-value" id="statVehicleCount">
                  {typeof telemetry.car_count === 'number' ? telemetry.car_count : '—'}
                </div>
              </div>

              {/* Stat 3: Processing FPS */}
              <div className="stat-card" id="statFpsCard">
                <div className="stat-header">
                  <span>Tốc độ xử lý (FPS)</span>
                  <Gauge size={16} />
                </div>
                <div className="stat-value" id="statFpsValue">
                  {typeof telemetry.processing_fps === 'number'
                    ? telemetry.processing_fps.toFixed(1)
                    : typeof telemetry.stream_fps === 'number'
                    ? telemetry.stream_fps.toFixed(1)
                    : '—'}
                  <span className="stat-unit">fps</span>
                </div>
              </div>

              {/* Stat 4: Pipeline Latency (ms) */}
              <div className="stat-card" id="statLatencyCard">
                <div className="stat-header">
                  <span>Độ trễ Pipeline</span>
                  <Zap size={16} />
                </div>
                <div className="stat-value" id="statLatencyValue">
                  {typeof telemetry.pipeline_latency_ms === 'number'
                    ? `${telemetry.pipeline_latency_ms.toFixed(0)}`
                    : '—'}
                  <span className="stat-unit">ms</span>
                </div>
              </div>
            </div>

            {/* Main Section: 16:9 Authenticated Video Monitoring Player */}
            <div
              ref={streamContainerRef}
              className={`stream-wrapper ${isFullscreen ? 'fullscreen' : ''}`}
              id="mainStreamWrapper"
            >
              <AuthenticatedVideo
                cameraId={activeCamera.id || camera?.id}
                id="mainVideoStream"
                label={displayName}
              />

              {/* Overlay Top Badges */}
              <div className="stream-overlay-top">
                <div className="stream-badges">
                  <span className="stream-badge" id="badgeActiveCameraName">
                    {displayName}
                  </span>
                  <span
                    className="stream-badge"
                    id="badgeCameraStatus"
                    style={statusBadgeStyle}
                  >
                    {statusBadgeText}
                  </span>
                </div>
              </div>

              {/* Meaningful Idle Overlay if Stream is stopped */}
              {isStopped && (
                <div className="stream-idle-overlay" id="streamIdleOverlay">
                  <Square size={36} style={{ color: '#f59e0b' }} />
                  <div style={{ fontSize: '1.1rem', fontWeight: 600 }}>Luồng video đã dừng</div>
                  <p style={{ fontSize: '0.85rem', color: 'var(--text-muted)', maxWidth: '380px' }}>
                    Camera đang ở trạng thái dừng xử lý. Nhấn nút bên dưới để khởi động lại luồng.
                  </p>
                  <button
                    type="button"
                    className="btn btn-primary btn-sm"
                    onClick={handleRestart}
                    id="btnRestartCamera"
                  >
                    <Play size={14} />
                    <span>Phát lại camera</span>
                  </button>
                </div>
              )}

              {/* Stream Controls */}
              <div className="stream-controls">
                {isStopped ? (
                  <button
                    type="button"
                    className="btn btn-primary btn-sm"
                    onClick={handleRestart}
                    id="btnStartCamera"
                    title="Phát lại camera"
                  >
                    <Play size={14} />
                    <span>Phát</span>
                  </button>
                ) : (
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    onClick={stopActiveCamera}
                    id="btnStopCamera"
                    title="Dừng luồng video"
                  >
                    <Square size={14} />
                    <span>Dừng</span>
                  </button>
                )}

                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  onClick={toggleFullscreen}
                  id="btnFullscreenInStream"
                  title={isFullscreen ? 'Thu nhỏ' : 'Toàn màn hình'}
                >
                  {isFullscreen ? <Minimize size={14} /> : <Maximize size={14} />}
                  <span>{isFullscreen ? 'Thu nhỏ' : 'Toàn màn hình'}</span>
                </button>
              </div>
            </div>

            {/* Additional Information: Technical Metadata Panel */}
            <div className="card" id="cameraTechnicalDetailsCard">
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '14px' }}>
                <Info size={18} style={{ color: 'var(--accent)' }} />
                <h3 style={{ fontSize: '1.05rem', fontWeight: 600 }}>
                  Thông tin kỹ thuật Camera
                </h3>
              </div>

              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
                  gap: '16px',
                  fontSize: '0.85rem',
                }}
              >
                <div>
                  <span style={{ color: 'var(--text-muted)' }}>Mã Camera (ID):</span>
                  <div style={{ fontWeight: 600, fontFamily: 'var(--font-mono)' }} id="techMetaId">
                    {camera?.id || activeCamera.id || 'Nguồn vãng lai'}
                  </div>
                </div>

                <div>
                  <span style={{ color: 'var(--text-muted)' }}>Khu vực / Vị trí:</span>
                  <div style={{ fontWeight: 600 }} id="techMetaLocation">
                    {camera?.zone ||
                      camera?.location ||
                      camera?.district ||
                      transientSource?.location ||
                      'Mặc định'}
                  </div>
                </div>

                <div>
                  <span style={{ color: 'var(--text-muted)' }}>Loại giao thức:</span>
                  <div style={{ fontWeight: 600 }} id="techMetaType">
                    {camera?.source_type || transientSource?.source_type || activeCamera.source_type || '—'}
                  </div>
                </div>

                <div>
                  <span style={{ color: 'var(--text-muted)' }}>Trạng thái luồng:</span>
                  <div style={{ fontWeight: 600 }} id="techMetaStatus">
                    {telemetry.camera_status || 'IDLE'}
                  </div>
                </div>

                <div>
                  <span style={{ color: 'var(--text-muted)' }}>Giao thức phát hình:</span>
                  <div style={{ fontWeight: 600 }}>Authenticated Frame Stream (JPEG Canvas v1)</div>
                </div>

                <div>
                  <span style={{ color: 'var(--text-muted)' }}>Độ trễ AI (YOLO):</span>
                  <div style={{ fontWeight: 600 }} id="techMetaYoloLatency">
                    {typeof telemetry.yolo_latency_ms === 'number'
                      ? `${telemetry.yolo_latency_ms.toFixed(0)} ms`
                      : '—'}
                  </div>
                </div>

                <div>
                  <span style={{ color: 'var(--text-muted)' }}>Địa chỉ nguồn (ẩn mật khẩu):</span>
                  <div
                    style={{
                      fontFamily: 'var(--font-mono)',
                      fontSize: '0.78rem',
                      color: 'var(--text-secondary)',
                      wordBreak: 'break-all',
                    }}
                    id="techMetaSourceUrl"
                  >
                    {sanitizeStreamUrl(camera?.source_url || camera?.url || transientSource?.source_url)}
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </>
  );
}
