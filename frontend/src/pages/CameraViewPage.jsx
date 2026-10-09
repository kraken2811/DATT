import React, { useState, useEffect, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Header } from '../components/Header';
import { AuthenticatedVideo } from '../components/AuthenticatedVideo';
import { fetchCameraDetail } from '../api/cameras';
import { useApp } from '../context/AppContext';
import { LoadingSpinner, ErrorState } from '../components/StatusStates';
import { ArrowLeft, Play, Square, Maximize } from 'lucide-react';

export function CameraViewPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { telemetry, switchActiveCamera, stopActiveCamera } = useApp();

  const [camera, setCamera] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const autoSwitchIdRef = useRef(null);

  useEffect(() => {
    let isMounted = true;
    const abortCtrl = new AbortController();

    const load = async () => {
      setLoading(true);
      setError(null);
      try {
        const resp = await fetchCameraDetail(id, abortCtrl.signal);
        const camData = resp?.status === 'ok' ? resp.camera : null;

        if (camData) {
          if (isMounted) {
            setCamera(camData);
            if (autoSwitchIdRef.current !== camData.id) {
              autoSwitchIdRef.current = camData.id;
              await switchActiveCamera(camData);
            }
          }
        } else {
          throw new Error('Camera không tồn tại hoặc đã bị xóa');
        }
      } catch (err) {
        if (err.name !== 'AbortError' && isMounted) {
          setError(err.message);
        }
      } finally {
        if (isMounted) setLoading(false);
      }
    };

    load();

    return () => {
      isMounted = false;
      abortCtrl.abort();
    };
  }, [id, switchActiveCamera]);

  const toggleFullscreen = () => {
    setIsFullscreen((prev) => !prev);
  };

  return (
    <>
      <Header
        title={camera ? camera.name : 'Chi tiết Camera'}
        onToggleFullscreen={toggleFullscreen}
        isFullscreen={isFullscreen}
      />

      <div className="page-container" id="cameraViewPage">
        <div style={{ marginBottom: '16px' }}>
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={() => navigate('/cameras')}
            id="btnBackToCameras"
          >
            <ArrowLeft size={16} />
            <span>Quay lại Quản lý Camera</span>
          </button>
        </div>

        {loading ? (
          <div className="card">
            <LoadingSpinner text="Đang tải thông tin camera..." />
          </div>
        ) : error ? (
          <ErrorState message={error} onRetry={() => navigate('/cameras')} />
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
            {/* Stream Player */}
            <div
              className={`stream-wrapper ${isFullscreen ? 'fullscreen' : ''}`}
              id="cameraViewStreamWrapper"
            >
              <AuthenticatedVideo cameraId={id} label={camera?.name || 'Camera Feed'} />

              <div className="stream-overlay-top">
                <div className="stream-badges">
                  <span className="stream-badge">{camera?.name}</span>
                  <span className="stream-badge">{telemetry.camera_status || 'RUNNING'}</span>
                </div>
              </div>

              <div className="stream-controls">
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  onClick={stopActiveCamera}
                >
                  <Square size={14} />
                  <span>Dừng</span>
                </button>
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  onClick={toggleFullscreen}
                >
                  <Maximize size={14} />
                  <span>{isFullscreen ? 'Thu nhỏ' : 'Toàn màn hình'}</span>
                </button>
              </div>
            </div>

            {/* Camera Details Card */}
            <div className="card">
              <h3 style={{ fontSize: '1.05rem', fontWeight: 600, marginBottom: '14px' }}>
                Thông tin kỹ thuật Camera
              </h3>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '16px', fontSize: '0.85rem' }}>
                <div>
                  <span style={{ color: 'var(--text-muted)' }}>Mã Camera (ID):</span>
                  <div style={{ fontWeight: 600 }}>{camera?.id}</div>
                </div>
                <div>
                  <span style={{ color: 'var(--text-muted)' }}>Khu vực:</span>
                  <div style={{ fontWeight: 600 }}>{camera?.zone || camera?.location || 'Mặc định'}</div>
                </div>
                <div>
                  <span style={{ color: 'var(--text-muted)' }}>Loại giao thức:</span>
                  <div style={{ fontWeight: 600 }}>{camera?.source_type}</div>
                </div>
                <div>
                  <span style={{ color: 'var(--text-muted)' }}>Địa chỉ nguồn:</span>
                  <div style={{ fontFamily: 'var(--font-mono)', fontSize: '0.8rem', wordBreak: 'break-all' }}>
                    {camera?.source_url || camera?.url}
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
