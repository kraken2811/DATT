import React, { useState, useEffect, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Header } from '../components/Header';
import {
  fetchTargets,
  registerTarget,
  deleteTarget,
  toggleTargetSelection,
  getTargetImageUrl,
  fetchVehicles,
  createVehicle,
  updateVehicle,
  deleteVehicle,
} from '../api/watchlists';
import { useToast } from '../context/ToastContext';
import { LoadingSpinner, EmptyState, ErrorState } from '../components/StatusStates';
import { AuthenticatedImage } from '../components/AuthenticatedImage';
import { FaceDetailModal } from '../components/FaceDetailModal';
import { VehicleDetailModal } from '../components/VehicleDetailModal';
import { DeleteConfirmModal } from '../components/DeleteConfirmModal';
import {
  Users,
  Car,
  Search,
  Plus,
  Trash2,
  Edit,
  Check,
  X,
  ChevronLeft,
  ChevronRight,
  Upload,
  Eye,
} from 'lucide-react';

export function WatchlistPage() {
  const { showToast } = useToast();
  const [searchParams, setSearchParams] = useSearchParams();

  // Tab synchronization with URL: /watchlist?type=face or /watchlist?type=vehicle
  const activeTab = searchParams.get('type') === 'vehicle' ? 'vehicle' : 'face';

  const setActiveTab = (type) => {
    setSearchParams({ type });
  };

  // ==========================================
  // FACE WATCHLIST STATE
  // ==========================================
  const [faceTargets, setFaceTargets] = useState([]);
  const [faceTotal, setFaceTotal] = useState(0);
  const [facePage, setFacePage] = useState(1);
  const [facePageSize, setFacePageSize] = useState(24);
  const [faceSearch, setFaceSearch] = useState('');
  const [faceDebouncedSearch, setFaceDebouncedSearch] = useState('');
  const [faceLoading, setFaceLoading] = useState(true);
  const [faceError, setFaceError] = useState(null);

  // Add Target Modal State
  const [isAddFaceModalOpen, setIsAddFaceModalOpen] = useState(false);
  const [faceName, setFaceName] = useState('');
  const [faceColor, setFaceColor] = useState('');
  const [faceThreshold, setFaceThreshold] = useState('0.45');
  const [faceFile, setFaceFile] = useState(null);
  const [faceSubmitting, setFaceSubmitting] = useState(false);

  // Debounce Face Search
  useEffect(() => {
    const timer = setTimeout(() => {
      setFaceDebouncedSearch(faceSearch);
      setFacePage(1);
    }, 350);
    return () => clearTimeout(timer);
  }, [faceSearch]);

  const loadFaceTargets = useCallback(async (signal) => {
    setFaceLoading(true);
    setFaceError(null);
    try {
      const resp = await fetchTargets(
        {
          page: facePage,
          page_size: facePageSize,
          search: faceDebouncedSearch,
        },
        signal
      );
      if (resp && resp.status === 'ok') {
        setFaceTargets(resp.targets || []);
        setFaceTotal(resp.total || 0);
      } else {
        throw new Error(resp?.message || 'Không thể tải danh sách khuôn mặt');
      }
    } catch (err) {
      if (err.name !== 'AbortError') {
        setFaceError(err.message);
      }
    } finally {
      setFaceLoading(false);
    }
  }, [facePage, facePageSize, faceDebouncedSearch]);

  useEffect(() => {
    if (activeTab === 'face') {
      const abortCtrl = new AbortController();
      loadFaceTargets(abortCtrl.signal);
      return () => abortCtrl.abort();
    }
  }, [activeTab, loadFaceTargets]);

  const handleAddFaceTarget = async (e) => {
    e.preventDefault();
    if (!faceName.trim()) {
      showToast('Vui lòng nhập tên đối tượng', 'warning');
      return;
    }
    if (!faceFile) {
      showToast('Vui lòng chọn hình ảnh khuôn mặt', 'warning');
      return;
    }

    setFaceSubmitting(true);
    try {
      const formData = new FormData();
      formData.append('name', faceName.trim());
      if (faceColor.trim()) formData.append('color', faceColor.trim());
      formData.append('threshold', faceThreshold);
      formData.append('face_image', faceFile);

      const resp = await registerTarget(formData);
      if (resp && resp.status === 'ok') {
        showToast(`Đã thêm đối tượng: ${faceName}`, 'success');
        setIsAddFaceModalOpen(false);
        setFaceName('');
        setFaceColor('');
        setFaceFile(null);
        loadFaceTargets();
      } else {
        throw new Error(resp?.message || 'Đăng ký không thành công');
      }
    } catch (err) {
      showToast(`Lỗi: ${err.message}`, 'error');
    } finally {
      setFaceSubmitting(false);
    }
  };

  // Delete Confirmation Modal State
  const [deleteTargetInfo, setDeleteTargetInfo] = useState(null);
  const [isDeleting, setIsDeleting] = useState(false);

  // Detail Modals State
  const [selectedFaceTarget, setSelectedFaceTarget] = useState(null);
  const [selectedVehicle, setSelectedVehicle] = useState(null);

  const handleDeleteFaceRequest = (id, name) => {
    setDeleteTargetInfo({ type: 'face', id, name });
  };

  const handleDeleteVehicleRequest = (id, plate) => {
    setDeleteTargetInfo({ type: 'vehicle', id, name: plate });
  };

  const handleConfirmDelete = async () => {
    if (!deleteTargetInfo) return;
    setIsDeleting(true);
    try {
      if (deleteTargetInfo.type === 'face') {
        await deleteTarget(deleteTargetInfo.id);
        showToast(`Đã xóa đối tượng: ${deleteTargetInfo.name}`, 'success');
        if (selectedFaceTarget?.id === deleteTargetInfo.id) {
          setSelectedFaceTarget(null);
        }
        loadFaceTargets();
      } else {
        await deleteVehicle(deleteTargetInfo.id);
        showToast(`Đã xóa phương tiện: ${deleteTargetInfo.name}`, 'success');
        if (selectedVehicle?.id === deleteTargetInfo.id) {
          setSelectedVehicle(null);
        }
        loadVehicles();
      }
      setDeleteTargetInfo(null);
    } catch (err) {
      showToast(`Lỗi xóa: ${err.message}`, 'error');
    } finally {
      setIsDeleting(false);
    }
  };

  const handleToggleFace = async (id, currentSelected) => {
    try {
      const resp = await toggleTargetSelection(id, !currentSelected);
      setFaceTargets((prev) =>
        prev.map((t) => (t.id === id ? { ...t, selected: resp.selected } : t))
      );
      if (selectedFaceTarget?.id === id) {
        setSelectedFaceTarget((prev) => (prev ? { ...prev, selected: resp.selected } : null));
      }
      showToast('Đã cập nhật trạng thái tìm kiếm', 'info');
    } catch (err) {
      showToast(`Lỗi: ${err.message}`, 'error');
    }
  };

  const getWatchlistStatus = () => {
    const currentLoading = activeTab === 'face' ? faceLoading : vehicleLoading;
    const currentError = activeTab === 'face' ? faceError : vehicleError;

    if (currentError) {
      const errStr = String(currentError).toLowerCase();
      if (errStr.includes('401') || errStr.includes('xác thực') || errStr.includes('unauthorized')) {
        return { className: 'disconnected', label: 'CẦN XÁC THỰC' };
      }
      if (errStr.includes('403') || errStr.includes('forbidden') || errStr.includes('quyền')) {
        return { className: 'disconnected', label: 'CHƯA CÓ QUYỀN' };
      }
      if (errStr.includes('500') || errStr.includes('503') || errStr.includes('database')) {
        return { className: 'disconnected', label: 'LỖI MÁY CHỦ' };
      }
      if (errStr.includes('network') || errStr.includes('failed to fetch')) {
        return { className: 'disconnected', label: 'MẤT KẾT NỐI' };
      }
      return { className: 'disconnected', label: 'KHÔNG THỂ TRUY XUẤT' };
    }

    if (currentLoading) {
      return { className: 'connecting', label: 'ĐANG TẢI...' };
    }

    return { className: 'live', label: 'ĐÃ KẾT NỐI' };
  };

  // ==========================================
  // VEHICLE WATCHLIST STATE
  // ==========================================
  const [vehicles, setVehicles] = useState([]);
  const [vehicleTotal, setVehicleTotal] = useState(0);
  const [vehiclePage, setVehiclePage] = useState(1);
  const [vehiclePageSize, setVehiclePageSize] = useState(25);
  const [vehicleSearch, setVehicleSearch] = useState('');
  const [vehicleDebouncedSearch, setVehicleDebouncedSearch] = useState('');
  const [vehicleTypeFilter, setVehicleTypeFilter] = useState('all');
  const [vehicleStatusFilter, setVehicleStatusFilter] = useState('all');
  const [vehicleLoading, setVehicleLoading] = useState(true);
  const [vehicleError, setVehicleError] = useState(null);

  // Add / Edit Vehicle Modal State
  const [isVehicleModalOpen, setIsVehicleModalOpen] = useState(false);
  const [editingVehicleId, setEditingVehicleId] = useState(null);
  const [vPlate, setVPlate] = useState('');
  const [vName, setVName] = useState('');
  const [vType, setVType] = useState('car');
  const [vColor, setVColor] = useState('black');
  const [vOwner, setVOwner] = useState('');
  const [vNotes, setVNotes] = useState('');
  const [vStatus, setVStatus] = useState('active');
  const [vSubmitting, setVSubmitting] = useState(false);

  // Debounce Vehicle Search
  useEffect(() => {
    const timer = setTimeout(() => {
      setVehicleDebouncedSearch(vehicleSearch);
      setVehiclePage(1);
    }, 350);
    return () => clearTimeout(timer);
  }, [vehicleSearch]);

  const loadVehicles = useCallback(async (signal) => {
    setVehicleLoading(true);
    setVehicleError(null);
    try {
      const resp = await fetchVehicles(
        {
          page: vehiclePage,
          page_size: vehiclePageSize,
          search: vehicleDebouncedSearch,
          vehicle_type: vehicleTypeFilter,
          status: vehicleStatusFilter,
        },
        signal
      );
      if (resp && resp.status === 'ok') {
        setVehicles(resp.vehicles || []);
        setVehicleTotal(resp.total || 0);
      } else {
        throw new Error(resp?.message || 'Không thể tải danh sách phương tiện');
      }
    } catch (err) {
      if (err.name !== 'AbortError') {
        setVehicleError(err.message);
      }
    } finally {
      setVehicleLoading(false);
    }
  }, [vehiclePage, vehiclePageSize, vehicleDebouncedSearch, vehicleTypeFilter, vehicleStatusFilter]);

  useEffect(() => {
    if (activeTab === 'vehicle') {
      const abortCtrl = new AbortController();
      loadVehicles(abortCtrl.signal);
      return () => abortCtrl.abort();
    }
  }, [activeTab, loadVehicles]);

  const openAddVehicleModal = () => {
    setEditingVehicleId(null);
    setVPlate('');
    setVName('');
    setVType('car');
    setVColor('black');
    setVOwner('');
    setVNotes('');
    setVStatus('active');
    setIsVehicleModalOpen(true);
  };

  const openEditVehicleModal = (veh) => {
    setEditingVehicleId(veh.id);
    setVPlate(veh.plate_number);
    setVName(veh.display_name || veh.name || '');
    setVType(veh.vehicle_type || 'car');
    setVColor(veh.vehicle_color || 'black');
    setVOwner(veh.owner_info || '');
    setVNotes(veh.notes || '');
    setVStatus(veh.status || 'active');
    setIsVehicleModalOpen(true);
  };

  const handleSaveVehicle = async (e) => {
    e.preventDefault();
    if (!vPlate.trim()) {
      showToast('Vui lòng nhập biển số xe', 'warning');
      return;
    }

    setVSubmitting(true);
    try {
      const payload = {
        plate_number: vPlate.trim(),
        name: vName.trim(),
        display_name: vName.trim(),
        vehicle_type: vType,
        vehicle_color: vColor,
        owner_info: vOwner.trim(),
        notes: vNotes.trim(),
        status: vStatus,
      };

      if (editingVehicleId) {
        await updateVehicle(editingVehicleId, payload);
        showToast('Đã cập nhật thông tin phương tiện', 'success');
      } else {
        await createVehicle(payload);
        showToast('Đã đăng ký phương tiện vào Watchlist', 'success');
      }
      setIsVehicleModalOpen(false);
      loadVehicles();
    } catch (err) {
      showToast(`Lỗi: ${err.message}`, 'error');
    } finally {
      setVSubmitting(false);
    }
  };

  const handleDeleteVehicle = async (id, plate) => {
    if (!window.confirm(`Bạn có chắc chắn muốn xóa phương tiện biển số "${plate}"?`)) return;
    try {
      await deleteVehicle(id);
      showToast(`Đã xóa phương tiện: ${plate}`, 'success');
      loadVehicles();
    } catch (err) {
      showToast(`Lỗi xóa: ${err.message}`, 'error');
    }
  };

  const faceTotalPages = Math.ceil(faceTotal / facePageSize) || 1;
  const vehicleTotalPages = Math.ceil(vehicleTotal / vehiclePageSize) || 1;

  return (
    <>
      <Header
        title="Danh sách Theo dõi (Watchlist)"
        status={getWatchlistStatus()}
      />

      <div className="page-container" id="watchlistPage">
        {/* Navigation Tabs Header */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '20px', flexWrap: 'wrap', gap: '12px' }}>
          <div style={{ display: 'flex', gap: '8px' }}>
            <button
              type="button"
              className={`btn ${activeTab === 'face' ? 'btn-primary' : 'btn-secondary'}`}
              onClick={() => setActiveTab('face')}
              id="tabFaceWatchlist"
            >
              <Users size={16} />
              <span>Khuôn mặt (Face Watchlist)</span>
            </button>
            <button
              type="button"
              className={`btn ${activeTab === 'vehicle' ? 'btn-primary' : 'btn-secondary'}`}
              onClick={() => setActiveTab('vehicle')}
              id="tabVehicleWatchlist"
            >
              <Car size={16} />
              <span>Phương tiện (Vehicle Watchlist)</span>
            </button>
          </div>

          <div>
            {activeTab === 'face' ? (
              <button
                type="button"
                className="btn btn-primary"
                onClick={() => setIsAddFaceModalOpen(true)}
                id="btnAddFaceTarget"
              >
                <Plus size={16} />
                <span>Thêm khuôn mặt</span>
              </button>
            ) : (
              <button
                type="button"
                className="btn btn-primary"
                onClick={openAddVehicleModal}
                id="btnAddVehicle"
              >
                <Plus size={16} />
                <span>Thêm phương tiện</span>
              </button>
            )}
          </div>
        </div>

        {/* ========================================== */}
        {/* TAB 1: FACE WATCHLIST                      */}
        {/* ========================================== */}
        {activeTab === 'face' && (
          <div>
            {/* Filter bar */}
            <div className="card" style={{ marginBottom: '20px' }}>
              <div className="filter-bar" style={{ margin: 0 }}>
                <div className="search-input-wrapper">
                  <Search size={16} className="search-input-icon" />
                  <input
                    type="text"
                    className="input-field with-icon"
                    placeholder="Tìm kiếm khuôn mặt theo tên, ID, màu áo..."
                    value={faceSearch}
                    onChange={(e) => setFaceSearch(e.target.value)}
                    id="faceSearchInput"
                  />
                </div>

                <div style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>
                  Tổng cộng: <strong>{faceLoading ? '—' : faceTotal}</strong> đối tượng
                </div>
              </div>
            </div>

            {faceLoading ? (
              <div className="card">
                <LoadingSpinner text="Đang tải danh sách khuôn mặt từ DB..." />
              </div>
            ) : faceError ? (
              <ErrorState message={faceError} onRetry={() => loadFaceTargets()} />
            ) : faceTargets.length === 0 ? (
              <div className="card">
                <EmptyState
                  icon={Users}
                  title="Chưa có đối tượng khuôn mặt nào"
                  message="Thêm khuôn mặt mới để hệ thống tự động nhận diện và cảnh báo."
                />
              </div>
            ) : (
              <div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: '16px', marginBottom: '20px' }}>
                  {faceTargets.map((t) => (
                    <div
                      key={t.id}
                      className="card"
                      style={{
                        padding: '16px',
                        display: 'flex',
                        flexDirection: 'column',
                        gap: '12px',
                        position: 'relative',
                      }}
                    >
                      <div style={{ display: 'flex', gap: '14px', alignItems: 'center' }}>
                        <AuthenticatedImage
                          src={getTargetImageUrl(t.id)}
                          alt={t.name}
                          style={{
                            width: '64px',
                            height: '64px',
                            objectFit: 'cover',
                            borderRadius: 'var(--radius-md)',
                            border: '2px solid var(--border-card)',
                            background: '#000',
                          }}
                        />

                        <div style={{ flex: 1, overflow: 'hidden' }}>
                          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '6px' }}>
                            <h4 style={{ fontSize: '0.95rem', fontWeight: 600, color: 'var(--text-primary)', textOverflow: 'ellipsis', overflow: 'hidden', whiteSpace: 'nowrap', margin: 0 }}>
                              {t.name}
                            </h4>
                            <span
                              className="tag-badge"
                              style={{
                                background: t.selected ? 'rgba(16, 185, 129, 0.15)' : 'var(--bg-hover)',
                                color: t.selected ? '#10b981' : 'var(--text-muted)',
                                fontSize: '0.68rem',
                                padding: '1px 5px',
                                flexShrink: 0,
                              }}
                            >
                              {t.selected ? 'THEO DÕI' : 'TẮT'}
                            </span>
                          </div>
                          <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '2px' }}>
                            ID: {t.id ? t.id.slice(0, 8) : 'N/A'}...
                          </div>
                          {t.clothing_color && (
                            <span className="tag-badge" style={{ background: 'var(--bg-hover)', color: 'var(--text-secondary)', marginTop: '4px' }}>
                              Áo: {t.clothing_color}
                            </span>
                          )}
                        </div>
                      </div>

                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderTop: '1px solid var(--border-subtle)', paddingTop: '10px' }}>
                        <button
                          type="button"
                          className="btn btn-secondary btn-sm"
                          style={{ fontSize: '0.8rem', padding: '6px 12px', display: 'flex', alignItems: 'center', gap: '6px' }}
                          onClick={() => setSelectedFaceTarget(t)}
                          id={`btnViewDetailFace-${t.id}`}
                        >
                          <Eye size={16} />
                          <span>Xem chi tiết</span>
                        </button>

                        <button
                          type="button"
                          className="btn btn-danger btn-icon"
                          onClick={() => handleDeleteFaceRequest(t.id, t.name)}
                          title={`Xóa đối tượng ${t.name}`}
                          aria-label={`Xóa đối tượng ${t.name}`}
                          id={`btnDeleteFace-${t.id}`}
                        >
                          <Trash2 size={18} />
                        </button>
                      </div>
                    </div>
                  ))}
                </div>

                {/* Face Pagination */}
                <div className="card pagination-container" style={{ padding: '12px 20px' }}>
                  <div>
                    Hiển thị {(facePage - 1) * facePageSize + 1} -{' '}
                    {Math.min(facePage * facePageSize, faceTotal)} / <strong>{faceTotal}</strong>
                  </div>
                  <div className="pagination-controls">
                    <button
                      type="button"
                      className="btn btn-secondary btn-sm"
                      disabled={facePage <= 1}
                      onClick={() => setFacePage((p) => Math.max(1, p - 1))}
                    >
                      <ChevronLeft size={14} />
                      <span>Trước</span>
                    </button>
                    <div style={{ display: 'flex', alignItems: 'center', padding: '0 8px', fontSize: '0.85rem' }}>
                      {facePage} / {faceTotalPages}
                    </div>
                    <button
                      type="button"
                      className="btn btn-secondary btn-sm"
                      disabled={facePage >= faceTotalPages}
                      onClick={() => setFacePage((p) => Math.min(faceTotalPages, p + 1))}
                    >
                      <span>Sau</span>
                      <ChevronRight size={14} />
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}

        {/* ========================================== */}
        {/* TAB 2: VEHICLE WATCHLIST                   */}
        {/* ========================================== */}
        {activeTab === 'vehicle' && (
          <div>
            {/* Filter Bar */}
            <div className="card" style={{ marginBottom: '20px' }}>
              <div className="filter-bar" style={{ margin: 0 }}>
                <div className="search-input-wrapper">
                  <Search size={16} className="search-input-icon" />
                  <input
                    type="text"
                    className="input-field with-icon"
                    placeholder="Tìm kiếm phương tiện (biển số, tên xe, chủ xe...)"
                    value={vehicleSearch}
                    onChange={(e) => setVehicleSearch(e.target.value)}
                    id="vehicleSearchInput"
                  />
                </div>

                <select
                  className="select-field"
                  value={vehicleTypeFilter}
                  onChange={(e) => {
                    setVehicleTypeFilter(e.target.value);
                    setVehiclePage(1);
                  }}
                >
                  <option value="all">Tất cả loại xe</option>
                  <option value="car">Ô tô (Car)</option>
                  <option value="motorbike">Xe máy (Motorbike)</option>
                  <option value="truck">Xe tải (Truck)</option>
                  <option value="bus">Xe buýt (Bus)</option>
                </select>

                <select
                  className="select-field"
                  value={vehicleStatusFilter}
                  onChange={(e) => {
                    setVehicleStatusFilter(e.target.value);
                    setVehiclePage(1);
                  }}
                >
                  <option value="all">Tất cả trạng thái</option>
                  <option value="active">Đang hoạt động (Active)</option>
                  <option value="disabled">Đã vô hiệu (Disabled)</option>
                </select>

                <div style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>
                  Tổng cộng: <strong>{vehicleLoading ? '—' : vehicleTotal}</strong> phương tiện
                </div>
              </div>
            </div>

            {vehicleLoading ? (
              <div className="card">
                <LoadingSpinner text="Đang tải danh sách phương tiện..." />
              </div>
            ) : vehicleError ? (
              <ErrorState message={vehicleError} onRetry={() => loadVehicles()} />
            ) : vehicles.length === 0 ? (
              <div className="card">
                <EmptyState
                  icon={Car}
                  title="Chưa có phương tiện nào trong Watchlist"
                  message="Thêm biển số xe cần theo dõi để kích hoạt nhận diện tự động."
                />
              </div>
            ) : (
              <div className="table-container">
                <table className="data-table" id="vehicleWatchlistTable">
                  <thead>
                    <tr>
                      <th>Biển số xe</th>
                      <th>Tên gợi nhớ</th>
                      <th>Loại xe</th>
                      <th>Màu xe</th>
                      <th>Chủ xe</th>
                      <th>Lần xuất hiện</th>
                      <th>Lần cuối</th>
                      <th>Trạng thái</th>
                      <th style={{ textAlign: 'center' }}>Thao tác</th>
                    </tr>
                  </thead>
                  <tbody>
                    {vehicles.map((veh) => (
                      <tr key={veh.id}>
                        <td>
                          <span
                            style={{
                              fontFamily: 'var(--font-mono)',
                              fontWeight: 700,
                              fontSize: '0.95rem',
                              color: 'var(--accent)',
                              background: 'var(--accent-surface)',
                              padding: '2px 8px',
                              borderRadius: 'var(--radius-sm)',
                              border: '1px solid var(--border-subtle)',
                            }}
                          >
                            {veh.plate_number}
                          </span>
                        </td>
                        <td>{veh.display_name || veh.name || '—'}</td>
                        <td>{veh.vehicle_type || 'car'}</td>
                        <td>{veh.vehicle_color || '—'}</td>
                        <td>{veh.owner_info || '—'}</td>
                        <td style={{ fontWeight: 600 }}>{veh.detection_count ?? 0}</td>
                        <td style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                          {veh.last_seen || 'Chưa thấy'}
                        </td>
                        <td>
                          <span
                            className="tag-badge"
                            style={{
                              background:
                                veh.status === 'active'
                                  ? 'rgba(16, 185, 129, 0.15)'
                                  : 'var(--bg-hover)',
                              color: veh.status === 'active' ? '#10b981' : 'var(--text-muted)',
                            }}
                          >
                            {veh.status === 'active' ? 'HOẠT ĐỘNG' : 'TẮT'}
                          </span>
                        </td>
                        <td style={{ textAlign: 'center' }}>
                          <div style={{ display: 'flex', gap: '8px', justifyContent: 'center', alignItems: 'center' }}>
                            <button
                              type="button"
                              className="btn btn-secondary btn-icon"
                              onClick={() => setSelectedVehicle(veh)}
                              title={`Xem chi tiết phương tiện ${veh.plate_number}`}
                              aria-label={`Xem chi tiết phương tiện ${veh.plate_number}`}
                              id={`btnViewDetailVehicle-${veh.id}`}
                            >
                              <Eye size={18} />
                            </button>
                            <button
                              type="button"
                              className="btn btn-secondary btn-icon"
                              onClick={() => openEditVehicleModal(veh)}
                              title={`Sửa thông tin phương tiện ${veh.plate_number}`}
                              aria-label={`Sửa thông tin phương tiện ${veh.plate_number}`}
                              id={`btnEditVehicle-${veh.id}`}
                            >
                              <Edit size={18} />
                            </button>
                            <button
                              type="button"
                              className="btn btn-danger btn-icon"
                              onClick={() => handleDeleteVehicleRequest(veh.id, veh.plate_number)}
                              title={`Xóa phương tiện ${veh.plate_number}`}
                              aria-label={`Xóa phương tiện ${veh.plate_number}`}
                              id={`btnDeleteVehicle-${veh.id}`}
                            >
                              <Trash2 size={18} />
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>

                {/* Vehicle Pagination */}
                <div className="pagination-container">
                  <div>
                    Hiển thị {(vehiclePage - 1) * vehiclePageSize + 1} -{' '}
                    {Math.min(vehiclePage * vehiclePageSize, vehicleTotal)} / <strong>{vehicleTotal}</strong>
                  </div>
                  <div className="pagination-controls">
                    <button
                      type="button"
                      className="btn btn-secondary btn-sm"
                      disabled={vehiclePage <= 1}
                      onClick={() => setVehiclePage((p) => Math.max(1, p - 1))}
                    >
                      <ChevronLeft size={14} />
                      <span>Trước</span>
                    </button>
                    <div style={{ display: 'flex', alignItems: 'center', padding: '0 8px', fontSize: '0.85rem' }}>
                      {vehiclePage} / {vehicleTotalPages}
                    </div>
                    <button
                      type="button"
                      className="btn btn-secondary btn-sm"
                      disabled={vehiclePage >= vehicleTotalPages}
                      onClick={() => setVehiclePage((p) => Math.min(vehicleTotalPages, p + 1))}
                    >
                      <span>Sau</span>
                      <ChevronRight size={14} />
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}

        {/* Modal: Add Face Target */}
        {isAddFaceModalOpen && (
          <div className="modal-overlay" onClick={() => setIsAddFaceModalOpen(false)}>
            <div className="modal-card" onClick={(e) => e.stopPropagation()}>
              <div className="modal-header">
                <h3 className="modal-title">Đăng ký Đối tượng Khuôn mặt mới</h3>
                <button
                  type="button"
                  className="btn btn-secondary btn-icon btn-sm"
                  onClick={() => setIsAddFaceModalOpen(false)}
                >
                  <X size={16} />
                </button>
              </div>

              <form onSubmit={handleAddFaceTarget}>
                <div className="modal-body">
                  <div>
                    <label style={{ display: 'block', fontSize: '0.85rem', marginBottom: '6px', color: 'var(--text-secondary)' }}>
                      Tên người cần nhận diện *
                    </label>
                    <input
                      type="text"
                      className="input-field"
                      placeholder="Ví dụ: Nguyễn Văn A"
                      value={faceName}
                      onChange={(e) => setFaceName(e.target.value)}
                      required
                    />
                  </div>

                  <div>
                    <label style={{ display: 'block', fontSize: '0.85rem', marginBottom: '6px', color: 'var(--text-secondary)' }}>
                      Màu trang phục nhận diện (Tùy chọn)
                    </label>
                    <input
                      type="text"
                      className="input-field"
                      placeholder="Ví dụ: red, black, blue..."
                      value={faceColor}
                      onChange={(e) => setFaceColor(e.target.value)}
                    />
                  </div>

                  <div>
                    <label style={{ display: 'block', fontSize: '0.85rem', marginBottom: '6px', color: 'var(--text-secondary)' }}>
                      Ngưỡng nhận diện (Threshold)
                    </label>
                    <input
                      type="number"
                      step="0.05"
                      min="0.2"
                      max="0.9"
                      className="input-field"
                      value={faceThreshold}
                      onChange={(e) => setFaceThreshold(e.target.value)}
                    />
                  </div>

                  <div>
                    <label style={{ display: 'block', fontSize: '0.85rem', marginBottom: '6px', color: 'var(--text-secondary)' }}>
                      Tải lên ảnh khuôn mặt *
                    </label>
                    <input
                      type="file"
                      accept="image/jpeg,image/png,image/webp"
                      onChange={(e) => setFaceFile(e.target.files?.[0] || null)}
                      required
                    />
                  </div>
                </div>

                <div className="modal-footer">
                  <button
                    type="button"
                    className="btn btn-secondary"
                    onClick={() => setIsAddFaceModalOpen(false)}
                  >
                    Hủy
                  </button>
                  <button
                    type="submit"
                    className="btn btn-primary"
                    disabled={faceSubmitting}
                  >
                    {faceSubmitting ? 'Đang lưu...' : 'Lưu đối tượng'}
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}

        {/* Modal: Add / Edit Vehicle */}
        {isVehicleModalOpen && (
          <div className="modal-overlay" onClick={() => setIsVehicleModalOpen(false)}>
            <div className="modal-card" onClick={(e) => e.stopPropagation()}>
              <div className="modal-header">
                <h3 className="modal-title">
                  {editingVehicleId ? 'Sửa thông tin phương tiện' : 'Thêm phương tiện vào Watchlist'}
                </h3>
                <button
                  type="button"
                  className="btn btn-secondary btn-icon btn-sm"
                  onClick={() => setIsVehicleModalOpen(false)}
                >
                  <X size={16} />
                </button>
              </div>

              <form onSubmit={handleSaveVehicle}>
                <div className="modal-body">
                  <div>
                    <label style={{ display: 'block', fontSize: '0.85rem', marginBottom: '6px', color: 'var(--text-secondary)' }}>
                      Biển số xe *
                    </label>
                    <input
                      type="text"
                      className="input-field"
                      placeholder="Ví dụ: 29A12345"
                      value={vPlate}
                      onChange={(e) => setVPlate(e.target.value)}
                      required
                    />
                  </div>

                  <div>
                    <label style={{ display: 'block', fontSize: '0.85rem', marginBottom: '6px', color: 'var(--text-secondary)' }}>
                      Tên gợi nhớ / Nhãn
                    </label>
                    <input
                      type="text"
                      className="input-field"
                      placeholder="Ví dụ: Xe Giám đốc, Xe Khách VIP"
                      value={vName}
                      onChange={(e) => setVName(e.target.value)}
                    />
                  </div>

                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                    <div>
                      <label style={{ display: 'block', fontSize: '0.85rem', marginBottom: '6px', color: 'var(--text-secondary)' }}>
                        Loại phương tiện
                      </label>
                      <select
                        className="select-field"
                        value={vType}
                        onChange={(e) => setVType(e.target.value)}
                        style={{ width: '100%' }}
                      >
                        <option value="car">Ô tô (Car)</option>
                        <option value="motorbike">Xe máy (Motorbike)</option>
                        <option value="truck">Xe tải (Truck)</option>
                        <option value="bus">Xe buýt (Bus)</option>
                        <option value="other">Khác</option>
                      </select>
                    </div>

                    <div>
                      <label style={{ display: 'block', fontSize: '0.85rem', marginBottom: '6px', color: 'var(--text-secondary)' }}>
                        Màu xe
                      </label>
                      <select
                        className="select-field"
                        value={vColor}
                        onChange={(e) => setVColor(e.target.value)}
                        style={{ width: '100%' }}
                      >
                        <option value="black">Đen (Black)</option>
                        <option value="white">Trắng (White)</option>
                        <option value="silver">Bạc (Silver)</option>
                        <option value="gray">Xám (Gray)</option>
                        <option value="red">Đỏ (Red)</option>
                        <option value="blue">Xanh (Blue)</option>
                        <option value="other">Khác</option>
                      </select>
                    </div>
                  </div>

                  <div>
                    <label style={{ display: 'block', fontSize: '0.85rem', marginBottom: '6px', color: 'var(--text-secondary)' }}>
                      Thông tin chủ sở hữu
                    </label>
                    <input
                      type="text"
                      className="input-field"
                      placeholder="Tên, số điện thoại hoặc phòng ban..."
                      value={vOwner}
                      onChange={(e) => setVOwner(e.target.value)}
                    />
                  </div>

                  <div>
                    <label style={{ display: 'block', fontSize: '0.85rem', marginBottom: '6px', color: 'var(--text-secondary)' }}>
                      Trạng thái kích hoạt
                    </label>
                    <select
                      className="select-field"
                      value={vStatus}
                      onChange={(e) => setVStatus(e.target.value)}
                      style={{ width: '100%' }}
                    >
                      <option value="active">Hoạt động (Active)</option>
                      <option value="disabled">Vô hiệu hóa (Disabled)</option>
                    </select>
                  </div>
                </div>

                <div className="modal-footer">
                  <button
                    type="button"
                    className="btn btn-secondary"
                    onClick={() => setIsVehicleModalOpen(false)}
                  >
                    Hủy
                  </button>
                  <button
                    type="submit"
                    className="btn btn-primary"
                    disabled={vSubmitting}
                  >
                    {vSubmitting ? 'Đang lưu...' : 'Lưu phương tiện'}
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}
        {/* Modal: Face Detail */}
        <FaceDetailModal
          target={selectedFaceTarget}
          isOpen={Boolean(selectedFaceTarget)}
          onClose={() => setSelectedFaceTarget(null)}
          onToggleActive={handleToggleFace}
          onDeleteRequest={handleDeleteFaceRequest}
        />

        {/* Modal: Vehicle Detail */}
        <VehicleDetailModal
          vehicle={selectedVehicle}
          isOpen={Boolean(selectedVehicle)}
          onClose={() => setSelectedVehicle(null)}
          onEdit={openEditVehicleModal}
          onDeleteRequest={handleDeleteVehicleRequest}
        />

        {/* Modal: Delete Confirmation */}
        <DeleteConfirmModal
          isOpen={Boolean(deleteTargetInfo)}
          title={`Xác nhận xóa ${deleteTargetInfo?.type === 'face' ? 'đối tượng khuôn mặt' : 'phương tiện'}`}
          message={`Bạn có chắc chắn muốn xóa "${deleteTargetInfo?.name}" khỏi Danh sách Theo dõi? Thao tác này không thể hoàn tác.`}
          onConfirm={handleConfirmDelete}
          onClose={() => setDeleteTargetInfo(null)}
          isDeleting={isDeleting}
        />
      </div>
    </>
  );
}
