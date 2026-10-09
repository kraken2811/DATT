import React, { useState, useEffect, useRef } from 'react';
import { useApp } from '../context/AppContext';
import { Header } from '../components/Header';
import { AuthenticatedVideo } from '../components/AuthenticatedVideo';
import { fetchCameras, fetchPublicCameras, fetchVideoSources } from '../api/cameras';
import { fetchEvents } from '../api/events';
import {
  Users,
  Car,
  Zap,
  Gauge,
  Clock,
  Play,
  Square,
  RefreshCw,
  Search,
  ExternalLink,
  ShieldAlert,
} from 'lucide-react';

export function DashboardPage() {
  const { telemetry, activeCamera, switchActiveCamera, stopActiveCamera } = useApp();

  const [isFullscreen, setIsFullscreen] = useState(false);
  const streamContainerRef = useRef(null);

  // Quick camera selector drawer / state
  const [activeTab, setActiveTab] = useState('registered'); // 'registered' | 'cctv' | 'local' | 'custom'
  const [cameras, setCameras] = useState([]);
  const [cctvCameras, setCctvCameras] = useState([]);
  const [videoSources, setVideoSources] = useState([]);
  const [cctvProvider, setCctvProvider] = useState('caltrans');
  const [searchQuery, setSearchQuery] = useState('');
  const [recentEvents, setRecentEvents] = useState([]);
  const [isLoadingSources, setIsLoadingSources] = useState(false);

  // Custom stream input
  const [customUrl, setCustomUrl] = useState('');
  const [customName, setCustomName] = useState('');
  const [customType, setCustomType] = useState('direct_hls');

  // Handle Fullscreen & ESC key
  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key === 'Escape' && isFullscreen) {
        setIsFullscreen(false);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isFullscreen]);

  const toggleFullscreen = () => {
    setIsFullscreen((prev) => !prev);
  };

  // Load cameras & video sources in parallel (no sequential waterfall)
  useEffect(() => {
    let isMounted = true;
    const abortCtrl = new AbortController();

    const loadData = async () => {
      setIsLoadingSources(true);
      try {
        const [camsResp, sourcesResp, eventsResp] = await Promise.allSettled([
          fetchCameras({}, abortCtrl.signal),
          fetchVideoSources(abortCtrl.signal),
          fetchEvents({ page: 1, page_size: 5 }, abortCtrl.signal),
        ]);

        if (!isMounted) return;

        if (camsResp.status === 'fulfilled' && camsResp.value?.cameras) {
          setCameras(camsResp.value.cameras);
        }
        if (sourcesResp.status === 'fulfilled' && sourcesResp.value?.sources) {
          setVideoSources(sourcesResp.value.sources);
        }
        if (eventsResp.status === 'fulfilled' && eventsResp.value?.events) {
          setRecentEvents(eventsResp.value.events);
        }
      } finally {
        if (isMounted) setIsLoadingSources(false);
      }
    };

    loadData();

    return () => {
      isMounted = false;
      abortCtrl.abort();
    };
  }, []);

  // Fetch CCTV cameras when CCTV tab is selected
  useEffect(() => {
    if (activeTab !== 'cctv') return;
    let isMounted = true;
    const abortCtrl = new AbortController();

    const loadCctv = async () => {
      try {
        const resp = await fetchPublicCameras(
          { provider: cctvProvider, q: searchQuery },
          abortCtrl.signal
        );
        if (isMounted && resp?.cameras) {
          setCctvCameras(resp.cameras);
        }
      } catch (err) {
        if (err.name !== 'AbortError') console.error('Failed to load CCTV:', err);
      }
    };

    loadCctv();

    return () => {
      isMounted = false;
      abortCtrl.abort();
    };
  }, [activeTab, cctvProvider, searchQuery]);


  return (
    <>
      <Header
        title={activeCamera.name || 'AI Vision Monitor'}
        onToggleFullscreen={toggleFullscreen}
        isFullscreen={isFullscreen}
        isCameraContext={true}
      />

      <div className="page-container" id="dashboardPage">
        {/* Real Backend Statistics Bar */}
        <div className="stats-grid">
          <div className="stat-card" id="statPeopleCard">
            <div className="stat-header">
              <span>Người trong khung hình</span>
              <Users size={16} />
            </div>
            <div className="stat-value" id="statPeopleCount">
              {telemetry.people_count ?? '—'}
            </div>
          </div>

          <div className="stat-card" id="statVehicleCard">
            <div className="stat-header">
              <span>Phương tiện phát hiện</span>
              <Car size={16} />
            </div>
            <div className="stat-value" id="statVehicleCount">
              {telemetry.car_count ?? '—'}
            </div>
          </div>

          <div className="stat-card" id="statFpsCard">
            <div className="stat-header">
              <span>Tốc độ xử lý (FPS)</span>
              <Gauge size={16} />
            </div>
            <div className="stat-value" id="statFpsValue">
              {typeof telemetry.stream_fps === 'number'
                ? telemetry.stream_fps.toFixed(1)
                : '—'}
              <span className="stat-unit">fps</span>
            </div>
          </div>

          <div className="stat-card" id="statLatencyCard">
            <div className="stat-header">
              <span>Độ trễ Pipeline</span>
              <Zap size={16} />
            </div>
            <div className="stat-value" id="statLatencyValue">
              {typeof telemetry.pipeline_latency_ms === 'number' && telemetry.pipeline_latency_ms > 0
                ? `${telemetry.pipeline_latency_ms.toFixed(0)}`
                : 'N/A'}
              <span className="stat-unit">ms</span>
            </div>
          </div>
        </div>

        {/* Video Stream Monitor Frame */}
        <div
          ref={streamContainerRef}
          className={`stream-wrapper ${isFullscreen ? 'fullscreen' : ''}`}
          id="mainStreamWrapper"
        >
          <AuthenticatedVideo cameraId={activeCamera.id} id="mainVideoStream" label="AI Video Stream" />

          <div className="stream-overlay-top">
            <div className="stream-badges">
              <span className="stream-badge" id="badgeActiveCameraName">
                {activeCamera.name}
              </span>
              <span className="stream-badge" id="badgeCameraStatus">
                {telemetry.camera_status || 'LIVE'}
              </span>
            </div>
          </div>

          <div className="stream-controls">
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
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={toggleFullscreen}
              id="btnFullscreenInStream"
            >
              {isFullscreen ? 'Thu nhỏ' : 'Toàn màn hình'}
            </button>
          </div>
        </div>

        {/* Camera Source Selector Section */}
        <div className="card" style={{ marginTop: '24px' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px', flexWrap: 'wrap', gap: '12px' }}>
            <h2 style={{ fontSize: '1.1rem', fontWeight: 600 }}>Chuyển đổi Nguồn Camera</h2>
            <div style={{ display: 'flex', gap: '8px' }}>
              <button
                type="button"
                className={`btn btn-sm ${activeTab === 'registered' ? 'btn-primary' : 'btn-secondary'}`}
                onClick={() => setActiveTab('registered')}
                id="tabBtnRegistered"
              >
                Hệ thống ({cameras.length})
              </button>
              <button
                type="button"
                className={`btn btn-sm ${activeTab === 'cctv' ? 'btn-primary' : 'btn-secondary'}`}
                onClick={() => setActiveTab('cctv')}
                id="tabBtnCctv"
              >
                CCTV Công cộng
              </button>
              <button
                type="button"
                className={`btn btn-sm ${activeTab === 'local' ? 'btn-primary' : 'btn-secondary'}`}
                onClick={() => setActiveTab('local')}
                id="tabBtnLocal"
              >
                Video Tải lên ({videoSources.length})
              </button>
              <button
                type="button"
                className={`btn btn-sm ${activeTab === 'custom' ? 'btn-primary' : 'btn-secondary'}`}
                onClick={() => setActiveTab('custom')}
                id="tabBtnCustom"
              >
                Tùy chỉnh (URL)
              </button>
            </div>
          </div>

          {/* Tab 1: Registered Cameras */}
          {activeTab === 'registered' && (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))', gap: '12px' }}>
              {cameras.map((cam) => (
                <div
                  key={cam.id}
                  style={{
                    background: 'var(--bg-input)',
                    border: '1px solid var(--border-card)',
                    borderRadius: 'var(--radius-md)',
                    padding: '12px 14px',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '8px',
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span style={{ fontWeight: 600, fontSize: '0.9rem' }}>{cam.name}</span>
                    <span className="tag-badge" style={{ background: cam.status === 'online' ? 'rgba(16, 185, 129, 0.15)' : 'var(--bg-hover)', color: cam.status === 'online' ? '#10b981' : 'var(--text-muted)' }}>
                      {cam.status}
                    </span>
                  </div>
                  <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                    {cam.zone || 'Khu vực chung'} • {cam.source_type}
                  </div>
                  <button
                    type="button"
                    className="btn btn-primary btn-sm"
                    style={{ marginTop: '4px' }}
                    onClick={() => switchActiveCamera(cam)}
                  >
                    <Play size={12} />
                    <span>Chọn Camera</span>
                  </button>
                </div>
              ))}
            </div>
          )}

          {/* Tab 2: Public CCTV (Caltrans & Seattle) */}
          {activeTab === 'cctv' && (
            <div>
              <div style={{ display: 'flex', gap: '12px', marginBottom: '16px' }}>
                <select
                  className="select-field"
                  value={cctvProvider}
                  onChange={(e) => setCctvProvider(e.target.value)}
                >
                  <option value="caltrans">California Caltrans CCTV</option>
                  <option value="seattle">Seattle SDOT CCTV</option>
                </select>
                <div className="search-input-wrapper">
                  <Search size={16} className="search-input-icon" />
                  <input
                    type="text"
                    className="input-field with-icon"
                    placeholder="Tìm kiếm camera theo tên tuyến đường, quận..."
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                  />
                </div>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: '12px', maxHeight: '380px', overflowY: 'auto' }}>
                {cctvCameras.map((cam) => (
                  <div
                    key={cam.id}
                    style={{
                      background: 'var(--bg-input)',
                      border: '1px solid var(--border-card)',
                      borderRadius: 'var(--radius-md)',
                      padding: '12px',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: '8px',
                    }}
                  >
                    <div style={{ fontWeight: 600, fontSize: '0.85rem' }}>{cam.name}</div>
                    <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                      {cam.provider} • {cam.district || cam.city || 'Public'}
                    </div>
                    <button
                      type="button"
                      className="btn btn-secondary btn-sm"
                      onClick={() =>
                        switchActiveCamera({
                          name: cam.name,
                          source_url: cam.stream_url,
                          source_type: 'direct_hls',
                          provider: cam.provider,
                        })
                      }
                    >
                      <Play size={12} />
                      <span>Kết nối Luồng</span>
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Tab 3: Local Video Uploads */}
          {activeTab === 'local' && (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))', gap: '12px' }}>
              {videoSources.length === 0 ? (
                <div style={{ padding: '24px', textAlign: 'center', color: 'var(--text-muted)', gridColumn: '1 / -1' }}>
                  Chưa có video nội bộ nào được tải lên.
                </div>
              ) : (
                videoSources.map((v) => (
                  <div
                    key={v.id}
                    style={{
                      background: 'var(--bg-input)',
                      border: '1px solid var(--border-card)',
                      borderRadius: 'var(--radius-md)',
                      padding: '12px',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: '8px',
                    }}
                  >
                    <div style={{ fontWeight: 600, fontSize: '0.85rem' }}>{v.name}</div>
                    <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                      {v.file_path}
                    </div>
                    <button
                      type="button"
                      className="btn btn-primary btn-sm"
                      onClick={() =>
                        switchActiveCamera({
                          name: `Local: ${v.original_filename}`,
                          source_url: v.storage_path,
                          source_type: 'local',
                          video_source_id: v.id,
                          loop: true,
                        })
                      }
                    >
                      <Play size={12} />
                      <span>Phát Lặp lại</span>
                    </button>
                  </div>
                ))
              )}
            </div>
          )}

          {/* Tab 4: Custom URL (RTSP/HLS/YouTube) */}
          {activeTab === 'custom' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', maxWidth: '600px' }}>
              <div>
                <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '4px' }}>
                  Tên hiển thị
                </label>
                <input
                  type="text"
                  className="input-field"
                  placeholder="Ví dụ: Camera Cổng Chính"
                  value={customName}
                  onChange={(e) => setCustomName(e.target.value)}
                />
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '4px' }}>
                  Loại nguồn
                </label>
                <select
                  className="select-field"
                  value={customType}
                  onChange={(e) => setCustomType(e.target.value)}
                  style={{ width: '100%' }}
                >
                  <option value="direct_hls">Direct HLS (.m3u8)</option>
                  <option value="rtsp">RTSP Stream (rtsp://...)</option>
                  <option value="youtube">YouTube Live Video URL</option>
                </select>
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '4px' }}>
                  URL Luồng
                </label>
                <input
                  type="text"
                  className="input-field"
                  placeholder="https://... hoặc rtsp://..."
                  value={customUrl}
                  onChange={(e) => setCustomUrl(e.target.value)}
                />
              </div>

              <button
                type="button"
                className="btn btn-primary"
                style={{ alignSelf: 'flex-start' }}
                disabled={!customUrl.trim()}
                onClick={() => {
                  switchActiveCamera({
                    name: customName.trim() || 'Custom Stream',
                    source_url: customUrl.trim(),
                    source_type: customType,
                  });
                }}
              >
                <Play size={14} />
                <span>Kết nối Luồng Tùy chỉnh</span>
              </button>
            </div>
          )}
        </div>

        {/* Latest Events Summary */}
        <div className="card" style={{ marginTop: '24px' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <ShieldAlert size={18} style={{ color: 'var(--accent)' }} />
              <h2 style={{ fontSize: '1.1rem', fontWeight: 600 }}>Sự kiện gần nhất hôm nay</h2>
            </div>
            <a href="/events" className="btn btn-secondary btn-sm">
              <span>Xem tất cả sự kiện</span>
              <ExternalLink size={12} />
            </a>
          </div>

          <div className="table-container">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Thời gian</th>
                  <th>Loại sự kiện</th>
                  <th>Camera</th>
                  <th>Chi tiết</th>
                </tr>
              </thead>
              <tbody>
                {recentEvents.length === 0 ? (
                  <tr>
                    <td colSpan={4} style={{ textAlign: 'center', padding: '24px', color: 'var(--text-muted)' }}>
                      Chưa có sự kiện nào được ghi nhận.
                    </td>
                  </tr>
                ) : (
                  recentEvents.map((evt) => (
                    <tr key={evt.event_id || evt.id}>
                      <td style={{ whiteSpace: 'nowrap' }}>
                        {evt.timestamp ? new Date(evt.timestamp).toLocaleTimeString() : 'N/A'}
                      </td>
                      <td>
                        <span className="tag-badge" style={{ background: 'var(--accent-surface)', color: 'var(--accent)' }}>
                          {evt.semantic_type || evt.event_type}
                        </span>
                      </td>
                      <td>{evt.camera_id || 'N/A'}</td>
                      <td>
                        {evt.plate ? `Biển số: ${evt.plate}` : evt.target_id ? `Target ID: ${evt.target_id.slice(0, 8)}...` : 'Phát hiện đối tượng'}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </>
  );
}
