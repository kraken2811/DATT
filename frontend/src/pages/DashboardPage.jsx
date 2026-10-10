import React, { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  FiActivity,
  FiCamera,
  FiChevronRight,
  FiExternalLink,
  FiRefreshCw,
  FiUsers,
  FiVideo,
  FiVideoOff,
  FiZap,
} from 'react-icons/fi';
import { AuthenticatedVideo } from '../components/AuthenticatedVideo';
import { useApp } from '../context/AppContext';
import { useToast } from '../context/ToastContext';
import {
  fetchCameras,
  fetchPublicCameras,
  fetchVideoSources,
  testCameraConnection,
} from '../api/cameras';

const EMPTY = '—';

function normalizeStatus(value) {
  const status = String(value || '').toLowerCase();
  if (['online', 'running', 'live', 'connected', 'active'].includes(status)) return 'online';
  if (['connecting', 'loading', 'starting'].includes(status)) return 'connecting';
  if (['offline', 'stopped', 'error', 'disconnected', 'disabled'].includes(status)) return 'offline';
  return status || 'unknown';
}

function MetricCard({ label, value, unit, icon: Icon }) {
  return (
    <div className="monitor-metric-card">
      <div className="monitor-metric-label">
        <span>{label}</span>
        <Icon size={16} aria-hidden="true" />
      </div>
      <div className="monitor-metric-value">
        {value}
        {value !== EMPTY && unit ? <span>{unit}</span> : null}
      </div>
    </div>
  );
}

export function DashboardPage() {
  const navigate = useNavigate();
  const { showToast } = useToast();
  const { telemetry, activeCamera, switchActiveCamera } = useApp();

  const [cameras, setCameras] = useState([]);
  const [videoSources, setVideoSources] = useState([]);
  const [publicSources, setPublicSources] = useState([]);
  const [loading, setLoading] = useState(true);
  const [sourcePanel, setSourcePanel] = useState(null);
  const [selectedVideoId, setSelectedVideoId] = useState('');
  const [selectedPublicId, setSelectedPublicId] = useState('');
  const [publicProvider, setPublicProvider] = useState('caltrans');
  const [customUrl, setCustomUrl] = useState('');
  const [customName, setCustomName] = useState('');
  const [customType, setCustomType] = useState('direct_hls');
  const [testingSource, setTestingSource] = useState(false);

  useEffect(() => {
    let mounted = true;
    const controller = new AbortController();

    Promise.allSettled([
      fetchCameras({}, controller.signal),
      fetchVideoSources(controller.signal),
    ]).then(([cameraResult, sourceResult]) => {
      if (!mounted) return;
      if (cameraResult.status === 'fulfilled') {
        setCameras(cameraResult.value?.cameras || []);
      }
      if (sourceResult.status === 'fulfilled') {
        setVideoSources(sourceResult.value?.sources || []);
      }
      setLoading(false);
    });

    return () => {
      mounted = false;
      controller.abort();
    };
  }, []);

  useEffect(() => {
    if (sourcePanel?.mode !== 'public') return undefined;
    let mounted = true;
    const controller = new AbortController();

    fetchPublicCameras({ provider: publicProvider }, controller.signal)
      .then((resp) => {
        if (mounted) setPublicSources(resp?.cameras || []);
      })
      .catch((error) => {
        if (error.name !== 'AbortError' && mounted) {
          setPublicSources([]);
          showToast(`Không tải được CCTV công cộng: ${error.message}`, 'error');
        }
      });

    return () => {
      mounted = false;
      controller.abort();
    };
  }, [sourcePanel?.mode, publicProvider, showToast]);

  const activeRegisteredCamera = useMemo(
    () => cameras.find((camera) => String(camera.id) === String(activeCamera?.id)),
    [cameras, activeCamera?.id],
  );

  const activeStatus = normalizeStatus(telemetry?.camera_status);
  const isLive = Boolean(telemetry?.stream_alive) && activeStatus !== 'offline';

  const metricForCamera = (camera, field, formatter) => {
    if (String(camera.id) !== String(activeCamera?.id)) return EMPTY;
    const value = telemetry?.[field];
    if (value === null || value === undefined || Number.isNaN(value)) return EMPTY;
    return formatter ? formatter(value) : value;
  };

  const handleRegisteredSwitch = async (camera) => {
    await switchActiveCamera(camera);
  };

  const openSourceMode = async (camera, mode) => {
    if (mode === 'stream') {
      await handleRegisteredSwitch(camera);
      setSourcePanel(null);
      return;
    }
    if (mode === 'local' && camera?.source_type === 'local') {
      await handleRegisteredSwitch(camera);
      setSourcePanel(null);
      return;
    }
    setSelectedVideoId('');
    setSelectedPublicId('');
    setCustomUrl('');
    setCustomName(camera?.name || '');
    setSourcePanel({ camera, mode });
  };

  const applyAlternateSource = async () => {
    if (!sourcePanel) return;
    const { camera, mode } = sourcePanel;

    if (mode === 'local' || mode === 'uploaded') {
      const source = videoSources.find((item) => String(item.id) === String(selectedVideoId));
      if (!source) {
        showToast('Chọn một video có thật từ hệ thống trước khi chuyển nguồn.', 'warning');
        return;
      }
      await switchActiveCamera({
        name: source.name || source.original_filename || camera.name,
        source_url: source.storage_path || source.file_path,
        source_type: 'local',
        video_source_id: source.id,
        loop: true,
      });
      setSourcePanel(null);
      return;
    }

    if (mode === 'public') {
      const source = publicSources.find((item) => String(item.id) === String(selectedPublicId));
      if (!source?.stream_url) {
        showToast('Chọn một camera CCTV công cộng hợp lệ.', 'warning');
        return;
      }
      await switchActiveCamera({
        name: source.name || camera.name,
        source_url: source.stream_url,
        source_type: 'direct_hls',
        provider: source.provider || publicProvider,
      });
      setSourcePanel(null);
      return;
    }

    if (mode === 'custom') {
      if (!customUrl.trim()) {
        showToast('Nhập URL nguồn trước khi kết nối.', 'warning');
        return;
      }
      await switchActiveCamera({
        name: customName.trim() || camera.name || 'Custom source',
        source_url: customUrl.trim(),
        source_type: customType,
      });
      setSourcePanel(null);
    }
  };

  const handleTestSource = async () => {
    const camera = sourcePanel?.camera || activeRegisteredCamera;
    const sourceType = sourcePanel?.mode === 'custom' ? customType : camera?.source_type;
    const sourceUrl = sourcePanel?.mode === 'custom'
      ? customUrl.trim()
      : (camera?.source_url || camera?.url);

    if (!sourceType || !sourceUrl) {
      showToast('Backend không cung cấp đủ source type/URL để kiểm tra nguồn này.', 'warning');
      return;
    }

    setTestingSource(true);
    try {
      const result = await testCameraConnection(sourceType, sourceUrl);
      const ok = result?.status === 'ok' || result?.success === true || result?.reachable === true;
      showToast(ok ? 'Nguồn camera phản hồi bình thường.' : 'Backend chưa xác nhận nguồn camera hoạt động.', ok ? 'success' : 'warning');
    } catch (error) {
      showToast(`Kiểm tra nguồn thất bại: ${error.message}`, 'error');
    } finally {
      setTestingSource(false);
    }
  };

  const sourceOptions = [
    ['stream', 'Stream'],
    ['local', 'Local'],
    ['public', 'Public/CCTV'],
    ['uploaded', 'Uploaded video'],
    ['custom', 'Custom URL'],
  ];

  return (
    <div className="monitor-page dashboard-monitor" id="dashboardPage">
      <header className="monitor-page-header">
        <div>
          <h1>Dashboard</h1>
          <p>Giám sát camera và telemetry AI theo dữ liệu backend hiện tại.</p>
        </div>
        <div className={`monitor-connection-pill ${isLive ? 'online' : 'offline'}`}>
          <FiActivity size={14} aria-hidden="true" />
          <span>{isLive ? 'Monitoring online' : 'Monitoring unavailable'}</span>
        </div>
      </header>

      <section className="monitor-metrics-grid" aria-label="Telemetry camera đang chọn">
        <MetricCard label="People" icon={FiUsers} value={telemetry?.people_count ?? EMPTY} />
        <MetricCard label="Vehicles" icon={FiVideo} value={telemetry?.car_count ?? EMPTY} />
        <MetricCard
          label="Processing FPS"
          icon={FiActivity}
          value={typeof telemetry?.processing_fps === 'number'
            ? telemetry.processing_fps.toFixed(1)
            : (typeof telemetry?.stream_fps === 'number' ? telemetry.stream_fps.toFixed(1) : EMPTY)}
          unit="fps"
        />
        <MetricCard
          label="Pipeline latency"
          icon={FiZap}
          value={typeof telemetry?.pipeline_latency_ms === 'number' && telemetry.pipeline_latency_ms > 0
            ? Math.round(telemetry.pipeline_latency_ms)
            : EMPTY}
          unit="ms"
        />
      </section>

      <section className="dashboard-workspace-grid">
        <div className="monitor-card camera-table-card">
          <div className="monitor-card-header">
            <div>
              <h2>Camera</h2>
              <span>{loading ? 'Đang tải…' : `${cameras.length} camera đăng ký`}</span>
            </div>
          </div>

          <div className="monitor-table-wrap">
            <table className="monitor-table camera-dashboard-table">
              <thead>
                <tr>
                  <th>Camera</th>
                  <th>Status</th>
                  <th>Source</th>
                  <th>People</th>
                  <th>Vehicles</th>
                  <th>FPS</th>
                  <th>Latency</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {!loading && cameras.length === 0 ? (
                  <tr>
                    <td colSpan={8} className="monitor-empty-cell">Không có camera từ backend.</td>
                  </tr>
                ) : cameras.map((camera) => {
                  const isActive = String(camera.id) === String(activeCamera?.id);
                  const status = isActive ? activeStatus : normalizeStatus(camera.status);
                  return (
                    <tr key={camera.id} className={isActive ? 'is-active-row' : ''}>
                      <td>
                        <div className="camera-name-cell">
                          <FiCamera size={15} aria-hidden="true" />
                          <div>
                            <strong>{camera.name || camera.id}</strong>
                            <span>{camera.zone || camera.location || camera.id}</span>
                          </div>
                        </div>
                      </td>
                      <td><span className={`monitor-badge ${status}`}>{status}</span></td>
                      <td>
                        <select
                          className="monitor-select compact"
                          value={sourcePanel?.camera?.id === camera.id ? sourcePanel.mode : 'stream'}
                          onChange={(event) => openSourceMode(camera, event.target.value)}
                          aria-label={`Chọn nguồn cho ${camera.name || camera.id}`}
                        >
                          {sourceOptions.map(([value, label]) => (
                            <option key={value} value={value}>{label}</option>
                          ))}
                        </select>
                      </td>
                      <td>{metricForCamera(camera, 'people_count')}</td>
                      <td>{metricForCamera(camera, 'car_count')}</td>
                      <td>{metricForCamera(camera, 'processing_fps', (value) => Number(value).toFixed(1))}</td>
                      <td>{metricForCamera(camera, 'pipeline_latency_ms', (value) => `${Math.round(Number(value))} ms`)}</td>
                      <td>
                        <div className="monitor-row-actions">
                          <button type="button" className="icon-action" onClick={() => handleRegisteredSwitch(camera)} title="Chọn camera">
                            <FiChevronRight size={15} />
                          </button>
                          <button type="button" className="icon-action" onClick={() => navigate(`/cameras/${encodeURIComponent(camera.id)}`)} title="Xem camera">
                            <FiExternalLink size={15} />
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {sourcePanel ? (
            <div className="source-inline-panel">
              <div className="source-inline-heading">
                <div>
                  <strong>{sourcePanel.camera?.name || sourcePanel.camera?.id}</strong>
                  <span>Chọn nguồn: {sourcePanel.mode}</span>
                </div>
                <button type="button" className="text-button" onClick={() => setSourcePanel(null)}>Đóng</button>
              </div>

              {(sourcePanel.mode === 'local' || sourcePanel.mode === 'uploaded') ? (
                <select className="monitor-select" value={selectedVideoId} onChange={(e) => setSelectedVideoId(e.target.value)}>
                  <option value="">Chọn video đã có trên backend</option>
                  {videoSources.map((source) => (
                    <option key={source.id} value={source.id}>
                      {source.name || source.original_filename || source.id}
                    </option>
                  ))}
                </select>
              ) : null}

              {sourcePanel.mode === 'public' ? (
                <div className="source-panel-grid">
                  <select className="monitor-select" value={publicProvider} onChange={(e) => setPublicProvider(e.target.value)}>
                    <option value="caltrans">Caltrans CCTV</option>
                    <option value="seattle">Seattle SDOT CCTV</option>
                  </select>
                  <select className="monitor-select" value={selectedPublicId} onChange={(e) => setSelectedPublicId(e.target.value)}>
                    <option value="">Chọn camera công cộng</option>
                    {publicSources.map((source) => (
                      <option key={source.id} value={source.id}>{source.name || source.id}</option>
                    ))}
                  </select>
                </div>
              ) : null}

              {sourcePanel.mode === 'custom' ? (
                <div className="source-panel-grid custom-source-grid">
                  <input className="monitor-input" value={customName} onChange={(e) => setCustomName(e.target.value)} placeholder="Tên hiển thị" />
                  <select className="monitor-select" value={customType} onChange={(e) => setCustomType(e.target.value)}>
                    <option value="direct_hls">HLS</option>
                    <option value="rtsp">RTSP</option>
                    <option value="youtube">YouTube</option>
                  </select>
                  <input className="monitor-input span-2" value={customUrl} onChange={(e) => setCustomUrl(e.target.value)} placeholder="URL nguồn thực tế" />
                </div>
              ) : null}

              <div className="source-panel-actions">
                {(sourcePanel.mode === 'custom' || sourcePanel.mode === 'local') ? (
                  <button type="button" className="monitor-button secondary" onClick={handleTestSource} disabled={testingSource}>
                    <FiRefreshCw size={14} />
                    {testingSource ? 'Đang kiểm tra…' : 'Test Source'}
                  </button>
                ) : null}
                <button type="button" className="monitor-button primary" onClick={applyAlternateSource}>
                  Áp dụng nguồn
                </button>
              </div>
            </div>
          ) : null}
        </div>

        <div className="monitor-card preview-card">
          <div className="monitor-card-header">
            <div>
              <h2>Monitoring preview</h2>
              <span>{activeCamera?.name || 'Chưa chọn camera'}</span>
            </div>
            <span className={`monitor-badge ${isLive ? 'online' : 'offline'}`}>{isLive ? 'online' : 'offline'}</span>
          </div>

          <div className="dashboard-preview">
            {isLive ? (
              <AuthenticatedVideo cameraId={activeCamera?.id} id="mainVideoStream" label={activeCamera?.name || 'Camera feed'} />
            ) : (
              <div className="offline-state">
                <FiVideoOff size={34} aria-hidden="true" />
                <strong>Camera Offline</strong>
                <span>{activeCamera?.name || telemetry?.camera_name || 'Chưa có nguồn camera hoạt động'}</span>
                <div className="offline-actions">
                  {activeRegisteredCamera ? (
                    <button type="button" className="monitor-button primary" onClick={() => handleRegisteredSwitch(activeRegisteredCamera)}>
                      <FiRefreshCw size={14} /> Reconnect
                    </button>
                  ) : null}
                  <button type="button" className="monitor-button secondary" onClick={handleTestSource} disabled={testingSource}>
                    Test Source
                  </button>
                </div>
              </div>
            )}
          </div>

          <div className="preview-status-strip">
            <span><strong>Camera</strong>{activeCamera?.name || EMPTY}</span>
            <span><strong>People</strong>{telemetry?.people_count ?? EMPTY}</span>
            <span><strong>Vehicles</strong>{telemetry?.car_count ?? EMPTY}</span>
            <span><strong>FPS</strong>{typeof telemetry?.processing_fps === 'number' ? telemetry.processing_fps.toFixed(1) : EMPTY}</span>
          </div>
        </div>
      </section>
    </div>
  );
}
