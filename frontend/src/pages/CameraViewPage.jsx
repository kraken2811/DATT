import React, { useEffect, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  FiArrowLeft,
  FiCamera,
  FiMaximize2,
  FiPause,
  FiRefreshCw,
  FiUsers,
  FiVideo,
  FiZap,
} from 'react-icons/fi';
import { AuthenticatedVideo } from '../components/AuthenticatedVideo';
import { fetchCameraDetail } from '../api/cameras';
import { useApp } from '../context/AppContext';
import { LoadingSpinner, ErrorState } from '../components/StatusStates';

const EMPTY = '—';

function valueOrDash(value) {
  return value === null || value === undefined || value === '' ? EMPTY : value;
}

function MetricCard({ label, value, unit, icon: Icon }) {
  return (
    <div className="classic-monitor-metric">
      <div className="classic-monitor-metric-label">
        <span>{label}</span>
        <Icon size={15} />
      </div>
      <div className="classic-monitor-metric-value">
        {value}
        {value !== EMPTY && unit ? <small>{unit}</small> : null}
      </div>
    </div>
  );
}

export function CameraViewPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const {
    telemetry,
    activeCamera,
    switchActiveCamera,
    stopActiveCamera,
  } = useApp();

  const [camera, setCamera] = useState(id ? null : activeCamera);
  const [loading, setLoading] = useState(Boolean(id));
  const [error, setError] = useState(null);
  const [fullscreen, setFullscreen] = useState(false);
  const rootRef = useRef(null);
  const switchedCameraRef = useRef(null);

  useEffect(() => {
    if (!id) {
      setCamera(activeCamera);
      setLoading(false);
      return undefined;
    }

    let mounted = true;
    const controller = new AbortController();
    setLoading(true);
    setError(null);

    fetchCameraDetail(id, controller.signal)
      .then(async (resp) => {
        const detail = resp?.status === 'ok' ? resp.camera : null;
        if (!detail) throw new Error('Camera không tồn tại hoặc đã bị xóa');
        if (!mounted) return;
        setCamera(detail);
        if (switchedCameraRef.current !== detail.id && String(activeCamera?.id) !== String(detail.id)) {
          switchedCameraRef.current = detail.id;
          await switchActiveCamera(detail);
        }
      })
      .catch((err) => {
        if (mounted && err.name !== 'AbortError') setError(err.message);
      })
      .finally(() => {
        if (mounted) setLoading(false);
      });

    return () => {
      mounted = false;
      controller.abort();
    };
  }, [id, activeCamera, switchActiveCamera]);

  useEffect(() => {
    const onFullscreen = () => setFullscreen(document.fullscreenElement === rootRef.current);
    document.addEventListener('fullscreenchange', onFullscreen);
    return () => document.removeEventListener('fullscreenchange', onFullscreen);
  }, []);

  const toggleFullscreen = async () => {
    if (!rootRef.current) return;
    if (document.fullscreenElement === rootRef.current) await document.exitFullscreen();
    else await rootRef.current.requestFullscreen();
  };

  const currentCamera = camera || activeCamera || {};
  const cameraId = currentCamera.id || activeCamera?.id;
  const live = Boolean(telemetry?.stream_alive);
  const cameraStatus = String(telemetry?.camera_status || (live ? 'ONLINE' : 'OFFLINE')).toUpperCase();
  const fps = typeof telemetry?.processing_fps === 'number'
    ? telemetry.processing_fps.toFixed(1)
    : (typeof telemetry?.stream_fps === 'number' ? telemetry.stream_fps.toFixed(1) : EMPTY);
  const latency = typeof telemetry?.pipeline_latency_ms === 'number'
    ? Math.round(telemetry.pipeline_latency_ms)
    : EMPTY;

  if (loading) {
    return <div className="classic-monitor-page"><div className="classic-monitor-card"><LoadingSpinner text="Đang tải camera…" /></div></div>;
  }
  if (error) {
    return <div className="classic-monitor-page"><ErrorState message={error} onRetry={() => navigate('/')} /></div>;
  }

  return (
    <div ref={rootRef} className={`classic-monitor-page ${fullscreen ? 'is-fullscreen' : ''}`} id="cameraViewPage">
      {!fullscreen ? (
        <>
          <header className="classic-monitor-topbar">
            <div className="classic-monitor-title">
              <strong>{currentCamera.name || telemetry?.camera_name || 'Camera'}</strong>
              <span className={live ? 'online' : 'offline'}>{cameraStatus}</span>
            </div>
            <button type="button" className="classic-monitor-fullscreen-top" onClick={toggleFullscreen}>
              <FiMaximize2 size={15} /> Toàn màn hình
            </button>
          </header>

          <div className="classic-monitor-back-row">
            <button type="button" onClick={() => navigate('/')}>
              <FiArrowLeft size={13} /> Quay lại Dashboard
            </button>
          </div>

          <section className="classic-monitor-metrics">
            <MetricCard label="NGƯỜI TRONG KHUNG HÌNH" icon={FiUsers} value={telemetry?.people_count ?? 0} />
            <MetricCard label="PHƯƠNG TIỆN PHÁT HIỆN" icon={FiVideo} value={telemetry?.car_count ?? 0} />
            <MetricCard label="TỐC ĐỘ XỬ LÝ (FPS)" icon={FiRefreshCw} value={fps === EMPTY ? 0 : fps} unit="fps" />
            <MetricCard label="ĐỘ TRỄ PIPELINE" icon={FiZap} value={latency === EMPTY ? 0 : latency} unit="ms" />
          </section>
        </>
      ) : null}

      <section className={`classic-monitor-video-shell ${fullscreen ? 'fullscreen' : ''}`}>
        <div className="classic-monitor-video">
          {live ? (
            <AuthenticatedVideo cameraId={cameraId} label={currentCamera.name || 'Camera feed'} />
          ) : (
            <div className="classic-monitor-offline">
              <FiCamera size={31} />
              <strong>CAMERA OFFLINE</strong>
              <span>{currentCamera.name || telemetry?.camera_name || 'Nguồn hiện không khả dụng'}</span>
            </div>
          )}

          <div className="classic-monitor-video-badges">
            <span>{currentCamera.name || telemetry?.camera_name || 'Camera'}</span>
            <strong className={live ? 'online' : 'offline'}>{live ? 'ONLINE' : 'OFFLINE'}</strong>
          </div>

          <div className="classic-monitor-video-actions">
            <button type="button" onClick={stopActiveCamera}><FiPause size={13} /> Dừng</button>
            <button type="button" onClick={toggleFullscreen}><FiMaximize2 size={13} /> Toàn màn hình</button>
          </div>
        </div>
      </section>

      {!fullscreen ? (
        <section className="classic-monitor-tech-card">
          <h2><FiCamera size={15} /> Thông tin kỹ thuật Camera</h2>
          <div className="classic-monitor-tech-grid">
            <div><span>Mã Camera (ID):</span><strong>{valueOrDash(currentCamera.id)}</strong></div>
            <div><span>Khu vực / Vị trí:</span><strong>{valueOrDash(currentCamera.zone || currentCamera.location || (currentCamera.source_type === 'local' ? 'Local Storage' : null))}</strong></div>
            <div><span>Loại giao thức:</span><strong>{valueOrDash(currentCamera.source_type)}</strong></div>
            <div><span>Trạng thái luồng:</span><strong>{cameraStatus}</strong></div>
            <div><span>Giao thức phát hình:</span><strong>Authenticated Frame Stream</strong></div>
            <div><span>Độ trễ AI (YOLO):</span><strong>{telemetry?.yolo_latency_ms != null ? `${Math.round(telemetry.yolo_latency_ms)} ms` : EMPTY}</strong></div>
            <div className="wide"><span>Địa chỉ nguồn (ẩn mật khẩu):</span><strong>{valueOrDash(currentCamera.source_url || currentCamera.url)}</strong></div>
          </div>
        </section>
      ) : null}
    </div>
  );
}
