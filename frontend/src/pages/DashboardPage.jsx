import React, { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  FiCamera,
  FiCheckCircle,
  FiExternalLink,
  FiGlobe,
  FiPlay,
  FiSettings,
  FiShield,
  FiSliders,
  FiUploadCloud,
} from 'react-icons/fi';
import { useApp } from '../context/AppContext';
import { useToast } from '../context/ToastContext';
import {
  fetchCameras,
  fetchPublicCameras,
  fetchVideoSources,
} from '../api/cameras';
import { fetchEvents } from '../api/events';

const EMPTY = '—';

function normalizeStatus(value) {
  const status = String(value || '').toLowerCase();
  if (['online', 'running', 'live', 'connected', 'active'].includes(status)) return 'online';
  if (['connecting', 'loading', 'starting'].includes(status)) return 'connecting';
  if (['offline', 'stopped', 'error', 'disconnected', 'disabled'].includes(status)) return 'offline';
  return status || 'offline';
}

function formatTime(value) {
  if (!value) return EMPTY;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleTimeString();
}

function eventRecognition(event) {
  const plate = event.plate || event.plate_number || event.plate_text;
  if (plate) {
    const confidence = event.confidence != null ? ` (${Math.round(Number(event.confidence) * (Number(event.confidence) <= 1 ? 100 : 1))}%)` : '';
    return `Biển số: ${plate}${confidence}`;
  }
  return event.target_name || event.person_name || event.vehicle_type || EMPTY;
}

function sourceSubtitle(source) {
  return source.zone || source.location || source.source_type || source.provider || EMPTY;
}

function SourceCard({ source, active, onSelect, actionLabel = 'Chọn nguồn' }) {
  return (
    <article className={`classic-source-card ${active ? 'active' : ''}`}>
      <div className="classic-source-card-head">
        <strong>{source.name || source.original_filename || source.id || 'Nguồn camera'}</strong>
        {source.status ? <span className={`classic-status-pill ${normalizeStatus(source.status)}`}>{normalizeStatus(source.status)}</span> : null}
      </div>
      <div className="classic-source-card-subtitle">{sourceSubtitle(source)}</div>
      <div className="classic-source-card-footer">
        <button type="button" className={`classic-small-button ${active ? 'primary' : ''}`} onClick={() => onSelect(source)}>
          {active ? <FiPlay size={13} /> : null}
          {active ? 'Xem camera' : actionLabel}
        </button>
        {active ? <span className="classic-selected-label">ĐÃ CHỌN</span> : null}
      </div>
    </article>
  );
}

export function DashboardPage() {
  const navigate = useNavigate();
  const { showToast } = useToast();
  const { apiStatus, activeCamera, switchActiveCamera } = useApp();

  const [tab, setTab] = useState('system');
  const [cameras, setCameras] = useState([]);
  const [videoSources, setVideoSources] = useState([]);
  const [publicSources, setPublicSources] = useState([]);
  const [events, setEvents] = useState([]);
  const [customUrl, setCustomUrl] = useState('');
  const [customName, setCustomName] = useState('Custom Camera');
  const [customType, setCustomType] = useState('direct_hls');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;
    const controller = new AbortController();
    Promise.allSettled([
      fetchCameras({}, controller.signal),
      fetchVideoSources(controller.signal),
      fetchEvents({ page: 1, page_size: 5, sort: 'desc' }, controller.signal),
    ]).then(([cameraResult, sourceResult, eventResult]) => {
      if (!mounted) return;
      if (cameraResult.status === 'fulfilled') setCameras(cameraResult.value?.cameras || []);
      if (sourceResult.status === 'fulfilled') setVideoSources(sourceResult.value?.sources || []);
      if (eventResult.status === 'fulfilled') setEvents(eventResult.value?.events || []);
      setLoading(false);
    });
    return () => {
      mounted = false;
      controller.abort();
    };
  }, []);

  useEffect(() => {
    if (tab !== 'public') return undefined;
    let mounted = true;
    const controller = new AbortController();
    fetchPublicCameras({ provider: 'all' }, controller.signal)
      .then((response) => {
        if (mounted) setPublicSources(response?.cameras || []);
      })
      .catch((error) => {
        if (mounted && error.name !== 'AbortError') showToast(`Không tải được CCTV công cộng: ${error.message}`, 'error');
      });
    return () => {
      mounted = false;
      controller.abort();
    };
  }, [tab, showToast]);

  const selectedSource = useMemo(() => {
    const candidates = [...cameras, ...videoSources];
    return candidates.find((item) => String(item.id) === String(activeCamera?.id)) || activeCamera;
  }, [cameras, videoSources, activeCamera]);

  const selectRegistered = async (source) => {
    await switchActiveCamera(source);
  };

  const selectVideo = async (source) => {
    await switchActiveCamera({
      id: source.id,
      name: source.name || source.original_filename || 'Uploaded video',
      source_url: source.storage_path || source.file_path,
      source_type: 'local',
      video_source_id: source.id,
      loop: true,
    });
  };

  const selectPublic = async (source) => {
    if (!source.stream_url) {
      showToast('Nguồn CCTV này không có stream URL hợp lệ.', 'warning');
      return;
    }
    await switchActiveCamera({
      id: source.id,
      name: source.name || source.id,
      source_url: source.stream_url,
      source_type: 'direct_hls',
      provider: source.provider,
    });
  };

  const selectCustom = async () => {
    if (!customUrl.trim()) {
      showToast('Nhập URL nguồn camera.', 'warning');
      return;
    }
    await switchActiveCamera({
      name: customName.trim() || 'Custom Camera',
      source_url: customUrl.trim(),
      source_type: customType,
    });
  };

  const openMonitor = () => navigate('/monitor');
  const hasSelected = activeCamera?.name && !String(activeCamera.name).toLowerCase().includes('initializing');

  const tabs = [
    ['system', FiCamera, `Hệ thống (${cameras.length})`],
    ['public', FiGlobe, 'CCTV Công cộng'],
    ['uploaded', FiUploadCloud, `Video Tải lên (${videoSources.length})`],
    ['custom', FiSliders, 'Tùy chỉnh (URL)'],
  ];

  return (
    <div className="classic-dashboard-page" id="dashboardPage">
      <header className="classic-dashboard-header">
        <h1>Bảng điều khiển (Dashboard)</h1>
        <span className={`classic-connection-badge ${apiStatus === 'connected' ? 'online' : 'offline'}`}>
          <FiCheckCircle size={13} />
          {apiStatus === 'connected' ? 'ĐÃ KẾT NỐI' : 'MẤT KẾT NỐI'}
        </span>
      </header>

      {hasSelected ? (
        <section className="classic-selected-source">
          <div className="classic-selected-icon"><FiCheckCircle size={19} /></div>
          <div className="classic-selected-copy">
            <span>Nguồn camera đã chọn:</span>
            <strong>{activeCamera.name} <em>({String(activeCamera.source_type || 'source').toUpperCase()})</em></strong>
            <small>Vị trí: {selectedSource?.location || selectedSource?.zone || (activeCamera.source_type === 'local' ? 'Local Storage' : EMPTY)}</small>
          </div>
          <button type="button" className="classic-view-button" onClick={openMonitor}>
            <FiPlay size={15} /> Xem camera
          </button>
        </section>
      ) : null}

      <section className="classic-panel classic-source-panel">
        <div className="classic-panel-topline">
          <div>
            <h2>Lựa chọn nguồn Camera</h2>
            <p>Chọn một nguồn từ danh sách bên dưới rồi nhấn “Xem camera” để mở màn hình giám sát.</p>
          </div>
          <div className="classic-source-tabs">
            {tabs.map(([value, Icon, label]) => (
              <button key={value} type="button" className={tab === value ? 'active' : ''} onClick={() => setTab(value)}>
                <Icon size={13} /> {label}
              </button>
            ))}
          </div>
        </div>

        {loading ? <div className="classic-loading">Đang tải nguồn camera…</div> : null}

        {!loading && tab === 'system' ? (
          <div className="classic-source-grid">
            {cameras.map((camera) => (
              <SourceCard
                key={camera.id}
                source={camera}
                active={String(camera.id) === String(activeCamera?.id)}
                onSelect={async (source) => {
                  if (String(source.id) === String(activeCamera?.id)) openMonitor();
                  else await selectRegistered(source);
                }}
              />
            ))}
          </div>
        ) : null}

        {!loading && tab === 'uploaded' ? (
          <div className="classic-source-grid uploaded-grid">
            {videoSources.map((source) => (
              <SourceCard
                key={source.id}
                source={{ ...source, name: source.name || source.original_filename, source_type: 'local' }}
                active={String(source.id) === String(activeCamera?.id)}
                onSelect={async (item) => {
                  if (String(item.id) === String(activeCamera?.id)) openMonitor();
                  else await selectVideo(source);
                }}
              />
            ))}
          </div>
        ) : null}

        {tab === 'public' ? (
          <div className="classic-source-grid">
            {publicSources.length ? publicSources.slice(0, 12).map((source) => (
              <SourceCard key={`${source.provider}-${source.id}`} source={source} active={String(source.id) === String(activeCamera?.id)} onSelect={selectPublic} />
            )) : <div className="classic-empty">Không có CCTV công cộng phù hợp.</div>}
          </div>
        ) : null}

        {tab === 'custom' ? (
          <div className="classic-custom-source">
            <input value={customName} onChange={(e) => setCustomName(e.target.value)} placeholder="Tên camera" />
            <select value={customType} onChange={(e) => setCustomType(e.target.value)}>
              <option value="direct_hls">HLS / HTTP Stream</option>
              <option value="rtsp">RTSP</option>
              <option value="youtube">YouTube</option>
            </select>
            <input className="url" value={customUrl} onChange={(e) => setCustomUrl(e.target.value)} placeholder="Nhập URL nguồn camera" />
            <button type="button" onClick={selectCustom}><FiSettings size={14} /> Chọn nguồn</button>
          </div>
        ) : null}
      </section>

      <section className="classic-panel classic-events-panel">
        <div className="classic-events-heading">
          <h2><FiShield size={15} /> Sự kiện gần nhất</h2>
          <button type="button" onClick={() => navigate('/events')}>Xem tất cả sự kiện <FiExternalLink size={12} /></button>
        </div>
        <div className="classic-events-table-wrap">
          <table className="classic-events-table">
            <thead>
              <tr>
                <th>THỜI GIAN</th>
                <th>LOẠI SỰ KIỆN</th>
                <th>CAMERA</th>
                <th>CHI TIẾT NHẬN DIỆN</th>
                <th>WATCHLIST</th>
              </tr>
            </thead>
            <tbody>
              {events.length ? events.map((event) => (
                <tr key={event.event_id || event.id}>
                  <td>{formatTime(event.timestamp || event.created_at)}</td>
                  <td><span className="classic-event-type">{event.event_type || event.type || EMPTY}</span></td>
                  <td>{event.camera_name || event.camera_id || EMPTY}</td>
                  <td>{eventRecognition(event)}</td>
                  <td>{event.watchlist_match ? <span className="classic-watchlist-match">TRÙNG KHỚP</span> : EMPTY}</td>
                </tr>
              )) : (
                <tr><td colSpan={5} className="classic-empty-row">Chưa có sự kiện gần đây.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
