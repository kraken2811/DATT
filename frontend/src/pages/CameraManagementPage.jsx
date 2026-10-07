import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { Header } from '../components/Header';
import {
  fetchCameras,
  createCamera,
  updateCamera,
  deleteCamera,
  toggleCameraStatus,
  testCameraConnection,
} from '../api/cameras';
import { useApp } from '../context/AppContext';
import { useToast } from '../context/ToastContext';
import { LoadingSpinner, EmptyState, ErrorState } from '../components/StatusStates';
import {
  Camera,
  Plus,
  Search,
  Play,
  Edit,
  Trash2,
  Power,
  CheckCircle,
  AlertTriangle,
  X,
  Radio,
} from 'lucide-react';

export function CameraManagementPage() {
  const navigate = useNavigate();
  const { switchActiveCamera } = useApp();
  const { showToast } = useToast();

  const [cameras, setCameras] = useState([]);
  const [total, setTotal] = useState(0);
  const [summary, setSummary] = useState({ online: 0, offline: 0, disabled: 0 });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Filters
  const [searchTerm, setSearchTerm] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [zoneFilter, setZoneFilter] = useState('all');

  // Modal: Add / Edit Camera
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingCameraId, setEditingCameraId] = useState(null);
  const [camName, setCamName] = useState('');
  const [camType, setCamType] = useState('rtsp');
  const [camUrl, setCamUrl] = useState('');
  const [camZone, setCamZone] = useState('');
  const [camDesc, setCamDesc] = useState('');
  const [testingConnection, setTestingConnection] = useState(false);
  const [testResult, setTestResult] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  // Debounce search
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearch(searchTerm);
    }, 350);
    return () => clearTimeout(timer);
  }, [searchTerm]);

  const loadCameras = useCallback(async (signal) => {
    setLoading(true);
    setError(null);
    try {
      const resp = await fetchCameras(
        {
          search: debouncedSearch,
          status: statusFilter,
          zone: zoneFilter,
        },
        signal
      );
      if (resp && resp.status === 'ok') {
        setCameras(resp.cameras || []);
        setTotal(resp.total || 0);
        if (resp.summary) setSummary(resp.summary);
      } else {
        throw new Error(resp?.detail || 'Không thể tải danh sách camera');
      }
    } catch (err) {
      if (err.name !== 'AbortError') setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [debouncedSearch, statusFilter, zoneFilter]);

  useEffect(() => {
    const abortCtrl = new AbortController();
    loadCameras(abortCtrl.signal);
    return () => abortCtrl.abort();
  }, [loadCameras]);

  const openAddModal = () => {
    setEditingCameraId(null);
    setCamName('');
    setCamType('rtsp');
    setCamUrl('');
    setCamZone('');
    setCamDesc('');
    setTestResult(null);
    setIsModalOpen(true);
  };

  const openEditModal = (cam) => {
    setEditingCameraId(cam.id);
    setCamName(cam.name);
    setCamType(cam.source_type || 'rtsp');
    setCamUrl(cam.source_url || cam.url || '');
    setCamZone(cam.zone || cam.location || '');
    setCamDesc(cam.description || '');
    setTestResult(null);
    setIsModalOpen(true);
  };

  const handleTestConnection = async () => {
    if (!camUrl.trim()) {
      showToast('Vui lòng nhập URL nguồn stream để kiểm tra', 'warning');
      return;
    }
    setTestingConnection(true);
    setTestResult(null);
    try {
      const resp = await testCameraConnection(camType, camUrl.trim());
      setTestResult(resp);
      if (resp.status === 'ok' || resp.reachable) {
        showToast('Kết nối thành công tới nguồn stream!', 'success');
      } else {
        showToast(`Không thể kết nối: ${resp.detail || 'Lỗi kết nối'}`, 'error');
      }
    } catch (err) {
      setTestResult({ status: 'error', detail: err.message });
      showToast(`Lỗi kiểm tra: ${err.message}`, 'error');
    } finally {
      setTestingConnection(false);
    }
  };

  const handleSaveCamera = async (e) => {
    e.preventDefault();
    if (!camName.trim() || !camUrl.trim()) {
      showToast('Vui lòng nhập tên và URL camera', 'warning');
      return;
    }

    setSubmitting(true);
    try {
      const payload = {
        name: camName.trim(),
        source_type: camType,
        source_url: camUrl.trim(),
        location: camZone.trim(),
        description: camDesc.trim(),
      };

      if (editingCameraId) {
        await updateCamera(editingCameraId, payload);
        showToast(`Đã cập nhật camera: ${camName}`, 'success');
      } else {
        await createCamera(payload);
        showToast(`Đã thêm camera mới: ${camName}`, 'success');
      }
      setIsModalOpen(false);
      loadCameras();
    } catch (err) {
      showToast(`Lỗi: ${err.message}`, 'error');
    } finally {
      setSubmitting(false);
    }
  };

  const handleDeleteCamera = async (id, name) => {
    if (!window.confirm(`Bạn có chắc chắn muốn xóa camera "${name}"?`)) return;
    try {
      await deleteCamera(id);
      showToast(`Đã xóa camera: ${name}`, 'success');
      loadCameras();
    } catch (err) {
      showToast(`Lỗi: ${err.message}`, 'error');
    }
  };

  const handleToggleStatus = async (id, currentEnabled) => {
    try {
      await toggleCameraStatus(id, !currentEnabled);
      showToast(`Đã ${!currentEnabled ? 'kích hoạt' : 'vô hiệu'} camera`, 'info');
      loadCameras();
    } catch (err) {
      showToast(`Lỗi: ${err.message}`, 'error');
    }
  };

  const handleLaunchMonitoring = (cam) => {
    switchActiveCamera(cam);
    navigate('/');
  };

  return (
    <>
      <Header title="Quản lý Camera (Camera Management)" />

      <div className="page-container" id="cameraManagementPage">
        {/* Header Action & Summary Cards */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px', flexWrap: 'wrap', gap: '12px' }}>
          <div style={{ display: 'flex', gap: '12px' }}>
            <div className="stat-card" style={{ padding: '10px 16px', minWidth: '130px' }}>
              <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Tổng camera</span>
              <span style={{ fontSize: '1.3rem', fontWeight: 700 }}>{summary.total ?? total}</span>
            </div>
            <div className="stat-card" style={{ padding: '10px 16px', minWidth: '130px' }}>
              <span style={{ fontSize: '0.75rem', color: 'var(--status-online)' }}>Trực tuyến</span>
              <span style={{ fontSize: '1.3rem', fontWeight: 700, color: 'var(--status-online)' }}>{summary.online ?? 0}</span>
            </div>
            <div className="stat-card" style={{ padding: '10px 16px', minWidth: '130px' }}>
              <span style={{ fontSize: '0.75rem', color: 'var(--status-danger)' }}>Ngoại tuyến / Tắt</span>
              <span style={{ fontSize: '1.3rem', fontWeight: 700, color: 'var(--text-muted)' }}>{(summary.offline ?? 0) + (summary.disabled ?? 0)}</span>
            </div>
          </div>

          <button
            type="button"
            className="btn btn-primary"
            onClick={openAddModal}
            id="btnAddCamera"
          >
            <Plus size={16} />
            <span>Thêm Camera Mới</span>
          </button>
        </div>

        {/* Filter Bar */}
        <div className="card" style={{ marginBottom: '20px' }}>
          <div className="filter-bar" style={{ margin: 0 }}>
            <div className="search-input-wrapper">
              <Search size={16} className="search-input-icon" />
              <input
                type="text"
                className="input-field with-icon"
                placeholder="Tìm kiếm camera theo tên, khu vực, mô tả..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                id="cameraSearchInput"
              />
            </div>

            <select
              className="select-field"
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              id="cameraStatusFilter"
            >
              <option value="all">Tất cả trạng thái</option>
              <option value="online">Trực tuyến (Online)</option>
              <option value="offline">Ngoại tuyến (Offline)</option>
              <option value="disabled">Đã tắt (Disabled)</option>
            </select>
          </div>
        </div>

        {/* Camera List Table */}
        {loading ? (
          <div className="card">
            <LoadingSpinner text="Đang tải danh sách camera..." />
          </div>
        ) : error ? (
          <ErrorState message={error} onRetry={() => loadCameras()} />
        ) : cameras.length === 0 ? (
          <div className="card">
            <EmptyState
              icon={Camera}
              title="Không tìm thấy camera nào"
              message="Thêm camera mới hoặc thay đổi bộ lọc tìm kiếm."
            />
          </div>
        ) : (
          <div className="table-container">
            <table className="data-table" id="cameraManagementTable">
              <thead>
                <tr>
                  <th>Tên Camera</th>
                  <th>Loại luồng</th>
                  <th>Khu vực (Zone)</th>
                  <th>Địa chỉ nguồn</th>
                  <th>Trạng thái</th>
                  <th style={{ textAlign: 'center' }}>Hành động</th>
                </tr>
              </thead>
              <tbody>
                {cameras.map((cam) => (
                  <tr key={cam.id}>
                    <td>
                      <div style={{ fontWeight: 600 }}>{cam.name}</div>
                      {cam.description && (
                        <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>{cam.description}</div>
                      )}
                    </td>
                    <td>
                      <span className="tag-badge" style={{ background: 'var(--accent-surface)', color: 'var(--accent)' }}>
                        {cam.source_type}
                      </span>
                    </td>
                    <td>{cam.zone || cam.location || 'Mặc định'}</td>
                    <td>
                      <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.78rem', color: 'var(--text-secondary)' }}>
                        {cam.source_url ? (cam.source_url.length > 40 ? `${cam.source_url.slice(0, 37)}...` : cam.source_url) : '—'}
                      </span>
                    </td>
                    <td>
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
                    </td>
                    <td style={{ textAlign: 'center' }}>
                      <div style={{ display: 'flex', gap: '6px', justifyContent: 'center' }}>
                        <button
                          type="button"
                          className="btn btn-primary btn-sm"
                          onClick={() => handleLaunchMonitoring(cam)}
                          title="Xem luồng trực tiếp"
                        >
                          <Play size={13} />
                          <span>Giám sát</span>
                        </button>
                        <button
                          type="button"
                          className="btn btn-secondary btn-icon btn-sm"
                          onClick={() => openEditModal(cam)}
                          title="Sửa cấu hình"
                        >
                          <Edit size={14} />
                        </button>
                        <button
                          type="button"
                          className="btn btn-secondary btn-icon btn-sm"
                          onClick={() => handleToggleStatus(cam.id, cam.enabled)}
                          title={cam.enabled ? 'Tắt camera' : 'Bật camera'}
                        >
                          <Power size={14} style={{ color: cam.enabled ? '#10b981' : '#94a3b8' }} />
                        </button>
                        <button
                          type="button"
                          className="btn btn-danger btn-icon btn-sm"
                          onClick={() => handleDeleteCamera(cam.id, cam.name)}
                          title="Xóa camera"
                        >
                          <Trash2 size={14} />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Modal: Add / Edit Camera */}
        {isModalOpen && (
          <div className="modal-overlay" onClick={() => setIsModalOpen(false)}>
            <div className="modal-card" onClick={(e) => e.stopPropagation()}>
              <div className="modal-header">
                <h3 className="modal-title">
                  {editingCameraId ? 'Chỉnh sửa Camera' : 'Thêm Camera Mới vào Hệ thống'}
                </h3>
                <button
                  type="button"
                  className="btn btn-secondary btn-icon btn-sm"
                  onClick={() => setIsModalOpen(false)}
                >
                  <X size={16} />
                </button>
              </div>

              <form onSubmit={handleSaveCamera}>
                <div className="modal-body">
                  <div>
                    <label style={{ display: 'block', fontSize: '0.85rem', marginBottom: '6px', color: 'var(--text-secondary)' }}>
                      Tên Camera *
                    </label>
                    <input
                      type="text"
                      className="input-field"
                      placeholder="Ví dụ: Camera Cổng Bắc, Sảnh Tầng 1..."
                      value={camName}
                      onChange={(e) => setCamName(e.target.value)}
                      required
                    />
                  </div>

                  <div>
                    <label style={{ display: 'block', fontSize: '0.85rem', marginBottom: '6px', color: 'var(--text-secondary)' }}>
                      Loại nguồn video
                    </label>
                    <select
                      className="select-field"
                      value={camType}
                      onChange={(e) => setCamType(e.target.value)}
                      style={{ width: '100%' }}
                    >
                      <option value="rtsp">RTSP (rtsp://...)</option>
                      <option value="direct_hls">Direct HLS (.m3u8)</option>
                      <option value="http">HTTP MJPEG stream</option>
                      <option value="youtube">YouTube Live Stream</option>
                    </select>
                  </div>

                  <div>
                    <label style={{ display: 'block', fontSize: '0.85rem', marginBottom: '6px', color: 'var(--text-secondary)' }}>
                      Địa chỉ nguồn (Stream URL) *
                    </label>
                    <div style={{ display: 'flex', gap: '8px' }}>
                      <input
                        type="text"
                        className="input-field"
                        placeholder="rtsp://... hoặc https://.../playlist.m3u8"
                        value={camUrl}
                        onChange={(e) => setCamUrl(e.target.value)}
                        required
                        style={{ flex: 1 }}
                      />
                      <button
                        type="button"
                        className="btn btn-secondary btn-sm"
                        onClick={handleTestConnection}
                        disabled={testingConnection || !camUrl.trim()}
                      >
                        <Radio size={14} />
                        <span>{testingConnection ? 'Kiểm tra...' : 'Test kết nối'}</span>
                      </button>
                    </div>

                    {testResult && (
                      <div
                        style={{
                          marginTop: '8px',
                          fontSize: '0.8rem',
                          padding: '8px 12px',
                          borderRadius: 'var(--radius-sm)',
                          background: testResult.status === 'ok' ? 'rgba(16, 185, 129, 0.1)' : 'rgba(239, 68, 68, 0.1)',
                          color: testResult.status === 'ok' ? '#10b981' : '#ef4444',
                        }}
                      >
                        {testResult.status === 'ok'
                          ? 'Đã kiểm tra: Nguồn video sẵn sàng kết nối.'
                          : `Kết nối thất bại: ${testResult.detail || testResult.message}`}
                      </div>
                    )}
                  </div>

                  <div>
                    <label style={{ display: 'block', fontSize: '0.85rem', marginBottom: '6px', color: 'var(--text-secondary)' }}>
                      Khu vực / Tòa nhà (Zone)
                    </label>
                    <input
                      type="text"
                      className="input-field"
                      placeholder="Ví dụ: Tòa nhà A, Bãi đỗ xe..."
                      value={camZone}
                      onChange={(e) => setCamZone(e.target.value)}
                    />
                  </div>

                  <div>
                    <label style={{ display: 'block', fontSize: '0.85rem', marginBottom: '6px', color: 'var(--text-secondary)' }}>
                      Ghi chú / Mô tả
                    </label>
                    <textarea
                      className="input-field"
                      rows={2}
                      placeholder="Mô tả vị trí hoặc mục đích giám sát..."
                      value={camDesc}
                      onChange={(e) => setCamDesc(e.target.value)}
                    />
                  </div>
                </div>

                <div className="modal-footer">
                  <button
                    type="button"
                    className="btn btn-secondary"
                    onClick={() => setIsModalOpen(false)}
                  >
                    Hủy
                  </button>
                  <button
                    type="submit"
                    className="btn btn-primary"
                    disabled={submitting}
                  >
                    {submitting ? 'Đang lưu...' : 'Lưu Camera'}
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}
      </div>
    </>
  );
}
