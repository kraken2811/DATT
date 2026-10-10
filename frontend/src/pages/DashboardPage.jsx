import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { Header } from '../components/Header';
import { fetchCameras, fetchPublicCameras, fetchVideoSources } from '../api/cameras';
import { fetchEvents } from '../api/events';
import { LoadingSpinner, EmptyState, ErrorState } from '../components/StatusStates';
import {
  Play,
  Search,
  ExternalLink,
  ShieldAlert,
  Camera,
  Video,
  Globe,
  Sliders,
  CheckCircle2,
  AlertCircle,
  Film,
} from 'lucide-react';

export function DashboardPage() {
  const navigate = useNavigate();

  // Tab state: 'registered' | 'cctv' | 'local' | 'custom'
  const [activeTab, setActiveTab] = useState('registered');

  // Source selection state (pure frontend selection - does NOT trigger backend pipeline)
  const [selectedSource, setSelectedSource] = useState(null);

  // Registered system cameras
  const [cameras, setCameras] = useState([]);
  const [isLoadingCameras, setIsLoadingCameras] = useState(true);
  const [camerasError, setCamerasError] = useState(null);

  // Local uploaded videos
  const [videoSources, setVideoSources] = useState([]);
  const [isLoadingSources, setIsLoadingSources] = useState(true);
  const [sourcesError, setSourcesError] = useState(null);

  // Public CCTV cameras
  const [cctvCameras, setCctvCameras] = useState([]);
  const [cctvProvider, setCctvProvider] = useState('caltrans');
  const [searchQuery, setSearchQuery] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [isLoadingCctv, setIsLoadingCctv] = useState(false);
  const [cctvError, setCctvError] = useState(null);

  // Custom stream input
  const [customName, setCustomName] = useState('');
  const [customType, setCustomType] = useState('direct_hls');
  const [customUrl, setCustomUrl] = useState('');

  // Recent events (Event Center API)
  const [recentEvents, setRecentEvents] = useState([]);
  const [isLoadingEvents, setIsLoadingEvents] = useState(true);
  const [eventsError, setEventsError] = useState(null);

  // Debounce CCTV search input
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearch(searchQuery);
    }, 350);
    return () => clearTimeout(timer);
  }, [searchQuery]);

  // 1. Fetch Registered Cameras independently
  const loadCameras = useCallback(async (signal) => {
    setIsLoadingCameras(true);
    setCamerasError(null);
    try {
      const resp = await fetchCameras({}, signal);
      if (resp && resp.status === 'ok') {
        setCameras(resp.cameras || []);
      } else {
        throw new Error(resp?.detail || 'Không thể tải danh sách camera hệ thống');
      }
    } catch (err) {
      if (err.name !== 'AbortError') {
        setCamerasError(err.message || 'Lỗi tải camera hệ thống');
      }
    } finally {
      setIsLoadingCameras(false);
    }
  }, []);

  // 2. Fetch Video Sources independently
  const loadVideoSources = useCallback(async (signal) => {
    setIsLoadingSources(true);
    setSourcesError(null);
    try {
      const resp = await fetchVideoSources(signal);
      if (resp && resp.sources) {
        setVideoSources(resp.sources || []);
      }
    } catch (err) {
      if (err.name !== 'AbortError') {
        setSourcesError(err.message || 'Lỗi tải video tải lên');
      }
    } finally {
      setIsLoadingSources(false);
    }
  }, []);

  // 3. Fetch Recent Events independently
  const loadRecentEvents = useCallback(async (signal) => {
    setIsLoadingEvents(true);
    setEventsError(null);
    try {
      const resp = await fetchEvents({ page: 1, page_size: 5 }, signal);
      if (resp && resp.status === 'ok') {
        setRecentEvents(resp.events || []);
      } else {
        throw new Error(resp?.detail || 'Không thể tải danh sách sự kiện gần nhất');
      }
    } catch (err) {
      if (err.name !== 'AbortError') {
        setEventsError(err.message || 'Lỗi tải sự kiện gần đây');
      }
    } finally {
      setIsLoadingEvents(false);
    }
  }, []);

  // 4. Fetch Public CCTV when tab is active or provider/search changes
  useEffect(() => {
    if (activeTab !== 'cctv') return;
    let isMounted = true;
    const abortCtrl = new AbortController();

    const loadCctv = async () => {
      setIsLoadingCctv(true);
      setCctvError(null);
      try {
        const resp = await fetchPublicCameras(
          { provider: cctvProvider, q: debouncedSearch },
          abortCtrl.signal
        );
        if (isMounted && resp?.cameras) {
          setCctvCameras(resp.cameras);
        }
      } catch (err) {
        if (err.name !== 'AbortError' && isMounted) {
          setCctvError(err.message || 'Không thể tải camera CCTV');
        }
      } finally {
        if (isMounted) setIsLoadingCctv(false);
      }
    };

    loadCctv();
    return () => {
      isMounted = false;
      abortCtrl.abort();
    };
  }, [activeTab, cctvProvider, debouncedSearch]);

  // Initial independent loads
  useEffect(() => {
    const abortCtrl = new AbortController();
    loadCameras(abortCtrl.signal);
    loadVideoSources(abortCtrl.signal);
    loadRecentEvents(abortCtrl.signal);
    return () => abortCtrl.abort();
  }, [loadCameras, loadVideoSources, loadRecentEvents]);

  // Handle source selection (frontend state ONLY, no backend switch triggered)
  const handleSelectSource = (source) => {
    setSelectedSource(source);
  };

  // Launch monitoring interface: Navigate without triggering backend switch from Dashboard
  // CameraViewPage will own activation once mounted
  const handleLaunchMonitoring = (sourceToLaunch) => {
    const src = sourceToLaunch || selectedSource;
    if (!src) return;

    if (src.category === 'registered' && src.id) {
      navigate(`/cameras/${src.id}`, { state: { source: src, from: '/dashboard' } });
    } else {
      navigate('/monitor', { state: { source: src, from: '/dashboard' } });
    }
  };

  // Quick helper to check if a source matches currently selected
  const isSelected = (source) => {
    if (!selectedSource || !source) return false;
    if (source.category === 'registered' && selectedSource.category === 'registered') {
      return source.id === selectedSource.id;
    }
    if (source.category === 'local' && selectedSource.category === 'local') {
      return source.video_source_id === selectedSource.video_source_id;
    }
    if (source.category === 'cctv' && selectedSource.category === 'cctv') {
      return source.source_url === selectedSource.source_url;
    }
    if (source.category === 'custom' && selectedSource.category === 'custom') {
      return source.source_url === selectedSource.source_url;
    }
    return false;
  };

  return (
    <>
      <Header
        title="Bảng điều khiển (Dashboard)"
        subtitle="Chọn nguồn camera và xem sự kiện gần nhất"
        isCameraContext={false}
      />

      <div className="page-container" id="dashboardPage">
        {/* Selected Source Banner: Obvious "Xem camera" action */}
        {selectedSource && (
          <div className="source-selection-banner" id="selectedSourceBanner">
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
              <div
                style={{
                  width: '42px',
                  height: '42px',
                  borderRadius: 'var(--radius-md)',
                  background: 'var(--accent)',
                  color: '#ffffff',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  flexShrink: 0,
                }}
              >
                <CheckCircle2 size={22} />
              </div>
              <div>
                <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                  Nguồn camera đã chọn:
                </div>
                <div style={{ fontWeight: 700, fontSize: '1.05rem', color: 'var(--text-primary)' }}>
                  {selectedSource.name}{' '}
                  <span
                    style={{
                      fontSize: '0.8rem',
                      fontWeight: 600,
                      color: 'var(--accent)',
                      textTransform: 'uppercase',
                      marginLeft: '6px',
                    }}
                  >
                    ({selectedSource.source_type || selectedSource.type})
                  </span>
                </div>
                {(selectedSource.zone || selectedSource.location) && (
                  <div style={{ fontSize: '0.78rem', color: 'var(--text-secondary)' }}>
                    Vị trí: {selectedSource.zone || selectedSource.location}
                  </div>
                )}
              </div>
            </div>

            <button
              type="button"
              className="btn btn-primary"
              id="btnLaunchSelectedCamera"
              onClick={() => handleLaunchMonitoring(selectedSource)}
              style={{ padding: '10px 22px', fontSize: '0.95rem' }}
            >
              <Play size={16} />
              <span>Xem camera</span>
            </button>
          </div>
        )}

        {/* Section A: Camera Source Selection */}
        <div className="card" style={{ marginBottom: '24px' }}>
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              marginBottom: '18px',
              flexWrap: 'wrap',
              gap: '12px',
            }}
          >
            <div>
              <h2 style={{ fontSize: '1.15rem', fontWeight: 700, marginBottom: '2px' }}>
                Lựa chọn nguồn Camera
              </h2>
              <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                Chọn một nguồn từ danh sách bên dưới rồi nhấn &quot;Xem camera&quot; để mở màn hình giám sát.
              </p>
            </div>

            <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
              <button
                type="button"
                className={`btn btn-sm ${activeTab === 'registered' ? 'btn-primary' : 'btn-secondary'}`}
                onClick={() => setActiveTab('registered')}
                id="tabBtnRegistered"
              >
                <Camera size={14} />
                <span>Hệ thống ({cameras.length})</span>
              </button>
              <button
                type="button"
                className={`btn btn-sm ${activeTab === 'cctv' ? 'btn-primary' : 'btn-secondary'}`}
                onClick={() => setActiveTab('cctv')}
                id="tabBtnCctv"
              >
                <Globe size={14} />
                <span>CCTV Công cộng</span>
              </button>
              <button
                type="button"
                className={`btn btn-sm ${activeTab === 'local' ? 'btn-primary' : 'btn-secondary'}`}
                onClick={() => setActiveTab('local')}
                id="tabBtnLocal"
              >
                <Film size={14} />
                <span>Video Tải lên ({videoSources.length})</span>
              </button>
              <button
                type="button"
                className={`btn btn-sm ${activeTab === 'custom' ? 'btn-primary' : 'btn-secondary'}`}
                onClick={() => setActiveTab('custom')}
                id="tabBtnCustom"
              >
                <Sliders size={14} />
                <span>Tùy chỉnh (URL)</span>
              </button>
            </div>
          </div>

          {/* TAB 1: Registered Cameras */}
          {activeTab === 'registered' && (
            <div>
              {isLoadingCameras ? (
                <LoadingSpinner text="Đang tải danh sách camera hệ thống..." />
              ) : camerasError ? (
                <ErrorState message={camerasError} onRetry={() => loadCameras()} />
              ) : cameras.length === 0 ? (
                <EmptyState
                  icon={Camera}
                  title="Chưa có camera nào trong hệ thống"
                  message="Thêm camera mới trong mục Quản lý Camera."
                />
              ) : (
                <div
                  style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))',
                    gap: '14px',
                  }}
                  id="registeredCamerasGrid"
                >
                  {cameras.map((cam) => {
                    const sourceObj = {
                      category: 'registered',
                      id: cam.id,
                      name: cam.name,
                      source_type: cam.source_type || 'rtsp',
                      source_url: cam.source_url || cam.url || '',
                      zone: cam.zone || cam.location || 'Khu vực chung',
                      status: cam.status,
                      enabled: cam.enabled,
                    };
                    const selected = isSelected(sourceObj);

                    return (
                      <div
                        key={cam.id}
                        className={`source-card ${selected ? 'selected' : ''}`}
                        onClick={() => handleSelectSource(sourceObj)}
                        id={`sourceCard_registered_${cam.id}`}
                      >
                        <div
                          style={{
                            display: 'flex',
                            justifyContent: 'space-between',
                            alignItems: 'center',
                          }}
                        >
                          <span style={{ fontWeight: 600, fontSize: '0.92rem' }}>{cam.name}</span>
                          <span
                            className="tag-badge"
                            style={{
                              background:
                                cam.status === 'online'
                                  ? 'rgba(16, 185, 129, 0.15)'
                                  : cam.status === 'disabled'
                                  ? 'rgba(239, 68, 68, 0.15)'
                                  : 'var(--bg-hover)',
                              color:
                                cam.status === 'online'
                                  ? '#10b981'
                                  : cam.status === 'disabled'
                                  ? '#ef4444'
                                  : 'var(--text-muted)',
                            }}
                          >
                            {cam.status}
                          </span>
                        </div>

                        <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>
                          {cam.zone || 'Khu vực chung'} • {cam.source_type}
                        </div>

                        <div
                          style={{
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'space-between',
                            marginTop: '4px',
                          }}
                        >
                          {selected ? (
                            <button
                              type="button"
                              className="btn btn-primary btn-sm"
                              onClick={(e) => {
                                e.stopPropagation();
                                handleLaunchMonitoring(sourceObj);
                              }}
                              id={`btnViewCam_${cam.id}`}
                            >
                              <Play size={13} />
                              <span>Xem camera</span>
                            </button>
                          ) : (
                            <button
                              type="button"
                              className="btn btn-secondary btn-sm"
                              onClick={(e) => {
                                e.stopPropagation();
                                handleSelectSource(sourceObj);
                              }}
                              id={`btnSelectCam_${cam.id}`}
                            >
                              <span>Chọn nguồn</span>
                            </button>
                          )}

                          {selected && (
                            <span
                              style={{
                                fontSize: '0.72rem',
                                color: 'var(--accent)',
                                fontWeight: 600,
                              }}
                            >
                              ĐÃ CHỌN
                            </span>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          )}

          {/* TAB 2: Public CCTV */}
          {activeTab === 'cctv' && (
            <div>
              <div
                style={{
                  display: 'flex',
                  gap: '12px',
                  marginBottom: '16px',
                  flexWrap: 'wrap',
                }}
              >
                <select
                  className="select-field"
                  value={cctvProvider}
                  onChange={(e) => setCctvProvider(e.target.value)}
                  style={{ minWidth: '220px' }}
                  id="cctvProviderSelect"
                >
                  <option value="caltrans">California Caltrans CCTV</option>
                  <option value="seattle">Seattle SDOT CCTV</option>
                </select>

                <div className="search-input-wrapper">
                  <Search size={16} className="search-input-icon" />
                  <input
                    type="text"
                    className="input-field with-icon"
                    placeholder="Tìm kiếm camera theo tên tuyến đường, địa điểm..."
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    id="cctvSearchInput"
                  />
                </div>
              </div>

              {isLoadingCctv ? (
                <LoadingSpinner text="Đang tìm kiếm luồng CCTV công cộng..." />
              ) : cctvError ? (
                <ErrorState message={cctvError} />
              ) : cctvCameras.length === 0 ? (
                <EmptyState
                  icon={Globe}
                  title="Không tìm thấy camera CCTV nào"
                  message="Thử đổi từ khóa tìm kiếm hoặc chọn nhà cung cấp khác."
                />
              ) : (
                <div
                  style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))',
                    gap: '14px',
                    maxHeight: '420px',
                    overflowY: 'auto',
                    paddingRight: '4px',
                  }}
                  id="cctvCamerasGrid"
                >
                  {cctvCameras.map((cam, idx) => {
                    const sourceObj = {
                      category: 'cctv',
                      name: cam.name,
                      source_url: cam.stream_url,
                      source_type: 'direct_hls',
                      provider: cam.provider,
                      location: cam.district || cam.city || 'Public',
                    };
                    const selected = isSelected(sourceObj);

                    return (
                      <div
                        key={cam.id || `cctv_${idx}`}
                        className={`source-card ${selected ? 'selected' : ''}`}
                        onClick={() => handleSelectSource(sourceObj)}
                        id={`sourceCard_cctv_${idx}`}
                      >
                        <div style={{ fontWeight: 600, fontSize: '0.88rem' }}>{cam.name}</div>
                        <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                          {cam.provider} • {cam.district || cam.city || 'Public'}
                        </div>

                        <div
                          style={{
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'space-between',
                            marginTop: '4px',
                          }}
                        >
                          {selected ? (
                            <button
                              type="button"
                              className="btn btn-primary btn-sm"
                              onClick={(e) => {
                                e.stopPropagation();
                                handleLaunchMonitoring(sourceObj);
                              }}
                              id={`btnViewCctv_${idx}`}
                            >
                              <Play size={13} />
                              <span>Xem camera</span>
                            </button>
                          ) : (
                            <button
                              type="button"
                              className="btn btn-secondary btn-sm"
                              onClick={(e) => {
                                e.stopPropagation();
                                handleSelectSource(sourceObj);
                              }}
                              id={`btnSelectCctv_${idx}`}
                            >
                              <span>Chọn nguồn</span>
                            </button>
                          )}

                          {selected && (
                            <span
                              style={{
                                fontSize: '0.72rem',
                                color: 'var(--accent)',
                                fontWeight: 600,
                              }}
                            >
                              ĐÃ CHỌN
                            </span>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          )}

          {/* TAB 3: Local Video Uploads */}
          {activeTab === 'local' && (
            <div>
              {isLoadingSources ? (
                <LoadingSpinner text="Đang tải danh sách video nội bộ..." />
              ) : sourcesError ? (
                <ErrorState message={sourcesError} onRetry={() => loadVideoSources()} />
              ) : videoSources.length === 0 ? (
                <EmptyState
                  icon={Film}
                  title="Chưa có video nội bộ nào được tải lên"
                  message="Tải video lên từ máy để phát kiểm thử hoặc benchmark."
                />
              ) : (
                <div
                  style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))',
                    gap: '14px',
                  }}
                  id="localVideosGrid"
                >
                  {videoSources.map((v) => {
                    const sourceObj = {
                      category: 'local',
                      name: `Local: ${v.original_filename || v.name}`,
                      source_url: v.storage_path,
                      source_type: 'local',
                      video_source_id: v.id,
                      loop: true,
                      file_path: v.file_path,
                      location: 'Local Storage',
                    };
                    const selected = isSelected(sourceObj);

                    return (
                      <div
                        key={v.id}
                        className={`source-card ${selected ? 'selected' : ''}`}
                        onClick={() => handleSelectSource(sourceObj)}
                        id={`sourceCard_local_${v.id}`}
                      >
                        <div style={{ fontWeight: 600, fontSize: '0.88rem' }}>
                          {v.name || v.original_filename}
                        </div>
                        <div
                          style={{
                            fontSize: '0.75rem',
                            color: 'var(--text-muted)',
                            fontFamily: 'var(--font-mono)',
                            wordBreak: 'break-all',
                          }}
                        >
                          {v.file_path || v.storage_path}
                        </div>

                        <div
                          style={{
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'space-between',
                            marginTop: '4px',
                          }}
                        >
                          {selected ? (
                            <button
                              type="button"
                              className="btn btn-primary btn-sm"
                              onClick={(e) => {
                                e.stopPropagation();
                                handleLaunchMonitoring(sourceObj);
                              }}
                              id={`btnViewLocal_${v.id}`}
                            >
                              <Play size={13} />
                              <span>Xem camera</span>
                            </button>
                          ) : (
                            <button
                              type="button"
                              className="btn btn-secondary btn-sm"
                              onClick={(e) => {
                                e.stopPropagation();
                                handleSelectSource(sourceObj);
                              }}
                              id={`btnSelectLocal_${v.id}`}
                            >
                              <span>Chọn nguồn</span>
                            </button>
                          )}

                          {selected && (
                            <span
                              style={{
                                fontSize: '0.72rem',
                                color: 'var(--accent)',
                                fontWeight: 600,
                              }}
                            >
                              ĐÃ CHỌN
                            </span>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          )}

          {/* TAB 4: Custom URL (RTSP / HLS / YouTube) */}
          {activeTab === 'custom' && (
            <div
              style={{
                display: 'flex',
                flexDirection: 'column',
                gap: '14px',
                maxWidth: '640px',
              }}
              id="customSourceForm"
            >
              <div>
                <label
                  style={{
                    display: 'block',
                    fontSize: '0.82rem',
                    color: 'var(--text-secondary)',
                    marginBottom: '6px',
                  }}
                >
                  Tên hiển thị nguồn
                </label>
                <input
                  type="text"
                  className="input-field"
                  placeholder="Ví dụ: Camera Cổng Chính, YouTube Live Stream..."
                  value={customName}
                  onChange={(e) => setCustomName(e.target.value)}
                  id="customSourceNameInput"
                />
              </div>

              <div>
                <label
                  style={{
                    display: 'block',
                    fontSize: '0.82rem',
                    color: 'var(--text-secondary)',
                    marginBottom: '6px',
                  }}
                >
                  Loại giao thức nguồn
                </label>
                <select
                  className="select-field"
                  value={customType}
                  onChange={(e) => setCustomType(e.target.value)}
                  style={{ width: '100%' }}
                  id="customSourceTypeSelect"
                >
                  <option value="direct_hls">Direct HLS (.m3u8)</option>
                  <option value="rtsp">RTSP Stream (rtsp://...)</option>
                  <option value="youtube">YouTube Live Stream URL</option>
                </select>
              </div>

              <div>
                <label
                  style={{
                    display: 'block',
                    fontSize: '0.82rem',
                    color: 'var(--text-secondary)',
                    marginBottom: '6px',
                  }}
                >
                  Địa chỉ URL luồng *
                </label>
                <input
                  type="text"
                  className="input-field"
                  placeholder="rtsp://... hoặc https://.../playlist.m3u8 hoặc https://youtube.com/watch?v=..."
                  value={customUrl}
                  onChange={(e) => setCustomUrl(e.target.value)}
                  id="customSourceUrlInput"
                />
              </div>

              <div style={{ display: 'flex', gap: '10px', marginTop: '6px' }}>
                <button
                  type="button"
                  className="btn btn-primary"
                  disabled={!customUrl.trim()}
                  onClick={() => {
                    const customSource = {
                      category: 'custom',
                      name: customName.trim() || 'Custom Stream',
                      source_url: customUrl.trim(),
                      source_type: customType,
                      location: 'Custom URL',
                    };
                    handleSelectSource(customSource);
                    handleLaunchMonitoring(customSource);
                  }}
                  id="btnLaunchCustomStream"
                >
                  <Play size={14} />
                  <span>Xem camera</span>
                </button>
              </div>
            </div>
          )}
        </div>

        {/* Section B: Recent Events (Event Center API) */}
        <div className="card" id="recentEventsSection">
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              marginBottom: '16px',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <ShieldAlert size={18} style={{ color: 'var(--accent)' }} />
              <h2 style={{ fontSize: '1.1rem', fontWeight: 600 }}>Sự kiện gần nhất</h2>
            </div>

            <Link to="/events" className="btn btn-secondary btn-sm" id="btnViewAllEvents">
              <span>Xem tất cả sự kiện</span>
              <ExternalLink size={12} />
            </Link>
          </div>

          {isLoadingEvents ? (
            <LoadingSpinner text="Đang tải các sự kiện gần nhất..." />
          ) : eventsError ? (
            <ErrorState message={eventsError} onRetry={() => loadRecentEvents()} />
          ) : recentEvents.length === 0 ? (
            <EmptyState
              icon={ShieldAlert}
              title="Chưa có sự kiện nào"
              message="Chưa có sự kiện nhận diện nào được ghi nhận gần đây."
            />
          ) : (
            <div className="table-container">
              <table className="data-table" id="dashboardEventsTable">
                <thead>
                  <tr>
                    <th>Thời gian</th>
                    <th>Loại sự kiện</th>
                    <th>Camera</th>
                    <th>Chi tiết nhận diện</th>
                    <th>Watchlist</th>
                  </tr>
                </thead>
                <tbody>
                  {recentEvents.map((evt) => {
                    const isMatch = evt.watchlist_match;
                    const eventKey = evt.event_id || evt.id;

                    return (
                      <tr key={eventKey}>
                        <td
                          style={{
                            whiteSpace: 'nowrap',
                            fontSize: '0.82rem',
                            color: 'var(--text-secondary)',
                          }}
                        >
                          {evt.timestamp
                            ? new Date(evt.timestamp).toLocaleTimeString()
                            : 'N/A'}
                        </td>
                        <td>
                          <span
                            className="tag-badge"
                            style={{
                              background:
                                evt.event_type === 'face'
                                  ? 'rgba(59, 130, 246, 0.15)'
                                  : evt.event_type === 'plate'
                                  ? 'rgba(16, 185, 129, 0.15)'
                                  : 'var(--accent-surface)',
                              color:
                                evt.event_type === 'face'
                                  ? '#3b82f6'
                                  : evt.event_type === 'plate'
                                  ? '#10b981'
                                  : 'var(--accent)',
                            }}
                          >
                            {evt.semantic_type || evt.event_type}
                          </span>
                        </td>
                        <td style={{ fontSize: '0.82rem' }}>{evt.camera_id || 'N/A'}</td>
                        <td>
                          {evt.plate ? (
                            <span style={{ fontWeight: 600 }}>Biển số: {evt.plate}</span>
                          ) : evt.target_id ? (
                            <span>Target: {evt.target_id.slice(0, 8)}...</span>
                          ) : (
                            <span style={{ color: 'var(--text-secondary)' }}>
                              {evt.object_type || 'Phát hiện đối tượng'}
                            </span>
                          )}
                          {typeof evt.confidence === 'number' && (
                            <span
                              style={{
                                fontSize: '0.75rem',
                                color: 'var(--text-muted)',
                                marginLeft: '8px',
                              }}
                            >
                              ({(evt.confidence * 100).toFixed(0)}%)
                            </span>
                          )}
                        </td>
                        <td>
                          {isMatch ? (
                            <span
                              className="tag-badge"
                              style={{
                                background: 'rgba(239, 68, 68, 0.15)',
                                color: '#ef4444',
                              }}
                            >
                              TRÙNG KHỚP
                            </span>
                          ) : (
                            <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                              —
                            </span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </>
  );
}
