import React, { useEffect, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  FiArrowLeft,
  FiCamera,
  FiCircle,
  FiMaximize2,
  FiRefreshCw,
  FiServer,
  FiVideoOff,
} from 'react-icons/fi';
import { AuthenticatedVideo } from '../components/AuthenticatedVideo';
import { fetchCameraDetail } from '../api/cameras';
import { useApp } from '../context/AppContext';
import { LoadingSpinner, ErrorState } from '../components/StatusStates';

const EMPTY = '—';

function valueOrDash(value) {
  return value === null || value === undefined || value === '' ? EMPTY : value;
}

export function CameraViewPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { telemetry, activeCamera, switchActiveCamera } = useApp();
  const [camera, setCamera] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [fullscreen, setFullscreen] = useState(false);
  const rootRef = useRef(null);
  const switchedCameraRef = useRef(null);

  useEffect(() => {
    let mounted = true;
    const controller = new AbortController();

    fetchCameraDetail(id, controller.signal)
      .then(async (resp) => {
        const detail = resp?.status === 'ok' ? resp.camera : null;
        if (!detail) throw new Error('Camera không tồn tại hoặc đã bị xóa');
        if (!mounted) return;
        setCamera(detail);
        if (switchedCameraRef.current !== detail.id) {
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
  }, [id, switchActiveCamera]);

  useEffect(() => {
    const onFullscreen = () => setFullscreen(document.fullscreenElement === rootRef.current);
    document.addEventListener('fullscreenchange', onFullscreen);
    return () => document.removeEventListener('fullscreenchange', onFullscreen);
  }, []);

  const toggleFullscreen = async () => {
    if (!rootRef.current) return;
    if (document.fullscreenElement === rootRef.current) {
      await document.exitFullscreen();
    } else {
      await rootRef.current.requestFullscreen();
    }
  };

  const live = Boolean(telemetry?.stream_alive);
  const fps = typeof telemetry?.processing_fps === 'number'
    ? telemetry.processing_fps.toFixed(1)
    : (typeof telemetry?.stream_fps === 'number' ? telemetry.stream_fps.toFixed(1) : EMPTY);
  const latency = typeof telemetry?.pipeline_latency_ms === 'number' && telemetry.pipeline_latency_ms > 0
    ? `${Math.round(telemetry.pipeline_latency_ms)} ms`
    : EMPTY;

  if (loading) {
    return <div className="monitor-page"><div className="monitor-card"><LoadingSpinner text="Đang tải camera…" /></div></div>;
  }
  if (error) {
    return <div className="monitor-page"><ErrorState message={error} onRetry={() => navigate('/cameras')} /></div>;
  }

  return (
    <div ref={rootRef} className={`monitor-page camera-view-page ${fullscreen ? 'is-fullscreen' : ''}`} id="cameraViewPage">
      {!fullscreen ? (
        <header className="monitor-page-header">
          <div className="camera-view-heading">
            <button type="button" className="icon-action" onClick={() => navigate('/cameras')} title="Quay lại Camera">
              <FiArrowLeft size={16} />
            </button>
            <div>
              <h1>{camera?.name || 'Camera'}</h1>
              <p>{camera?.zone || camera?.location || camera?.id}</p>
            </div>
          </div>
        </header>
      ) : null}

      <section className="camera-detail-layout">
        <div className="monitor-card camera-live-card">
          <div className="camera-live-surface">
            {live ? (
              <AuthenticatedVideo cameraId={id} label={camera?.name || 'Camera feed'} />
            ) : (
              <div className="offline-state large">
                <FiVideoOff size={42} />
                <strong>Camera Offline</strong>
                <span>{camera?.name || activeCamera?.name || id}</span>
                <button type="button" className="monitor-button primary" onClick={() => switchActiveCamera(camera)}>
                  <FiRefreshCw size={14} /> Reconnect
                </button>
              </div>
            )}

            <div className="vertical-video-toolbar" aria-label="Điều khiển video">
              <button type="button" className={`video-tool ${live ? 'active' : ''}`} title={live ? 'Đang phát' : 'Offline'}>
                <FiCircle size={15} />
              </button>
              <button type="button" className="video-tool" title={`Nguồn: ${camera?.source_type || EMPTY}`}>
                <FiServer size={15} />
              </button>
              <button type="button" className="video-tool" onClick={() => switchActiveCamera(camera)} title="Reconnect">
                <FiRefreshCw size={15} />
              </button>
              <button type="button" className="video-tool" onClick={toggleFullscreen} title="Fullscreen">
                <FiMaximize2 size={15} />
              </button>
            </div>

            {fullscreen ? (
              <div className="fullscreen-status-bar">
                <span><FiCamera size={13} /> {camera?.name || id}</span>
                <span>People {telemetry?.people_count ?? EMPTY}</span>
                <span>Vehicles {telemetry?.car_count ?? EMPTY}</span>
                <span>FPS {fps}</span>
              </div>
            ) : null}
          </div>
        </div>

        {!fullscreen ? (
          <aside className="monitor-card camera-info-panel">
            <div className="monitor-card-header">
              <div>
                <h2>System information</h2>
                <span>Dữ liệu backend hiện có</span>
              </div>
            </div>
            <dl className="camera-info-list">
              <div><dt>Camera name</dt><dd>{valueOrDash(camera?.name)}</dd></div>
              <div><dt>Source</dt><dd>{valueOrDash(camera?.source_type)}</dd></div>
              <div><dt>Status</dt><dd><span className={`monitor-badge ${live ? 'online' : 'offline'}`}>{telemetry?.camera_status || (live ? 'online' : 'offline')}</span></dd></div>
              <div><dt>People detected</dt><dd>{telemetry?.people_count ?? EMPTY}</dd></div>
              <div><dt>Vehicles detected</dt><dd>{telemetry?.car_count ?? EMPTY}</dd></div>
              <div><dt>Processing FPS</dt><dd>{fps}</dd></div>
              <div><dt>Pipeline latency</dt><dd>{latency}</dd></div>
              <div><dt>Resolution</dt><dd>{valueOrDash(telemetry?.resolution || camera?.resolution)}</dd></div>
              <div><dt>AI/GPU</dt><dd>{valueOrDash(telemetry?.gpu_status || telemetry?.ai_status || telemetry?.device)}</dd></div>
            </dl>
          </aside>
        ) : null}
      </section>
    </div>
  );
}
