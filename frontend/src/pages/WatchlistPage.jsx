import React, { useCallback, useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  FiCamera,
  FiCheck,
  FiChevronLeft,
  FiChevronRight,
  FiEdit2,
  FiEye,
  FiPlus,
  FiSearch,
  FiTrash2,
  FiTruck,
  FiUpload,
  FiUsers,
  FiX,
} from 'react-icons/fi';
import {
  createVehicle,
  deleteTarget,
  deleteVehicle,
  fetchTargetDetail,
  fetchTargets,
  fetchVehicleDetections,
  fetchVehicles,
  getTargetImageUrl,
  registerTarget,
  toggleTargetSelection,
  updateVehicle,
} from '../api/watchlists';
import { AuthenticatedImage } from '../components/AuthenticatedImage';
import { EmptyState, ErrorState, LoadingSpinner } from '../components/StatusStates';
import { DeleteConfirmModal } from '../components/DeleteConfirmModal';
import { useToast } from '../context/ToastContext';

const EMPTY = '—';

function formatTime(value) {
  if (!value) return EMPTY;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function DetailRow({ label, value }) {
  if (value === null || value === undefined || value === '') return null;
  return <div className="detail-row"><span>{label}</span><strong>{String(value)}</strong></div>;
}

export function WatchlistPage() {
  const { showToast } = useToast();
  const [searchParams, setSearchParams] = useSearchParams();
  const activeTab = searchParams.get('type') === 'vehicle' ? 'vehicle' : 'face';

  const [search, setSearch] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const [faces, setFaces] = useState([]);
  const [faceTotal, setFaceTotal] = useState(0);
  const [facePage, setFacePage] = useState(1);
  const [facePageSize] = useState(20);

  const [vehicles, setVehicles] = useState([]);
  const [vehicleTotal, setVehicleTotal] = useState(0);
  const [vehiclePage, setVehiclePage] = useState(1);
  const [vehiclePageSize] = useState(25);
  const [vehicleType, setVehicleType] = useState('all');
  const [vehicleStatus, setVehicleStatus] = useState('all');

  const [faceModalOpen, setFaceModalOpen] = useState(false);
  const [faceName, setFaceName] = useState('');
  const [faceColor, setFaceColor] = useState('');
  const [faceThreshold, setFaceThreshold] = useState('0.45');
  const [faceFile, setFaceFile] = useState(null);
  const [faceSubmitting, setFaceSubmitting] = useState(false);

  const [vehicleModalOpen, setVehicleModalOpen] = useState(false);
  const [editingVehicle, setEditingVehicle] = useState(null);
  const [vehiclePlate, setVehiclePlate] = useState('');
  const [vehicleKind, setVehicleKind] = useState('car');
  const [vehicleColor, setVehicleColor] = useState('black');
  const [vehicleNotes, setVehicleNotes] = useState('');
  const [vehicleEnabled, setVehicleEnabled] = useState('active');
  const [vehicleSubmitting, setVehicleSubmitting] = useState(false);

  const [detail, setDetail] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [deleteInfo, setDeleteInfo] = useState(null);
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearch(search.trim());
      if (activeTab === 'face') setFacePage(1);
      else setVehiclePage(1);
    }, 300);
    return () => clearTimeout(timer);
  }, [search, activeTab]);

  const loadFaces = useCallback(async (signal) => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetchTargets({
        page: facePage,
        page_size: facePageSize,
        search: debouncedSearch,
      }, signal);
      if (response?.status !== 'ok') throw new Error(response?.message || 'Không tải được Face Watchlist');
      setFaces(response.targets || []);
      setFaceTotal(response.total || 0);
    } catch (err) {
      if (err.name !== 'AbortError') setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [facePage, facePageSize, debouncedSearch]);

  const loadVehicles = useCallback(async (signal) => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetchVehicles({
        page: vehiclePage,
        page_size: vehiclePageSize,
        search: debouncedSearch,
        vehicle_type: vehicleType,
        status: vehicleStatus,
      }, signal);
      if (response?.status !== 'ok') throw new Error(response?.message || 'Không tải được Vehicle Watchlist');
      setVehicles(response.vehicles || []);
      setVehicleTotal(response.total || 0);
    } catch (err) {
      if (err.name !== 'AbortError') setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [vehiclePage, vehiclePageSize, debouncedSearch, vehicleType, vehicleStatus]);

  useEffect(() => {
    const controller = new AbortController();
    if (activeTab === 'face') loadFaces(controller.signal);
    else loadVehicles(controller.signal);
    return () => controller.abort();
  }, [activeTab, loadFaces, loadVehicles]);

  const changeTab = (type) => {
    setSearchParams({ type });
    setSearch('');
    setError(null);
  };

  const submitFace = async (event) => {
    event.preventDefault();
    if (!faceName.trim() || !faceFile) {
      showToast('Nhập tên và chọn ảnh khuôn mặt.', 'warning');
      return;
    }
    setFaceSubmitting(true);
    try {
      const form = new FormData();
      form.append('name', faceName.trim());
      if (faceColor.trim()) form.append('color', faceColor.trim());
      form.append('threshold', faceThreshold);
      form.append('face_image', faceFile);
      const response = await registerTarget(form);
      if (response?.status !== 'ok') throw new Error(response?.message || 'Không thể thêm khuôn mặt');
      showToast('Đã thêm khuôn mặt vào Watchlist.', 'success');
      setFaceModalOpen(false);
      setFaceName('');
      setFaceColor('');
      setFaceFile(null);
      loadFaces();
    } catch (err) {
      showToast(err.message, 'error');
    } finally {
      setFaceSubmitting(false);
    }
  };

  const openAddVehicle = () => {
    setEditingVehicle(null);
    setVehiclePlate('');
    setVehicleKind('car');
    setVehicleColor('black');
    setVehicleNotes('');
    setVehicleEnabled('active');
    setVehicleModalOpen(true);
  };

  const openEditVehicle = (vehicle) => {
    setEditingVehicle(vehicle);
    setVehiclePlate(vehicle.plate_number || '');
    setVehicleKind(vehicle.vehicle_type || 'car');
    setVehicleColor(vehicle.vehicle_color || 'black');
    setVehicleNotes(vehicle.notes || '');
    setVehicleEnabled(vehicle.status || 'active');
    setVehicleModalOpen(true);
  };

  const submitVehicle = async (event) => {
    event.preventDefault();
    if (!vehiclePlate.trim()) {
      showToast('Nhập biển số xe.', 'warning');
      return;
    }
    setVehicleSubmitting(true);
    try {
      const payload = {
        plate_number: vehiclePlate.trim(),
        vehicle_type: vehicleKind,
        vehicle_color: vehicleColor,
        notes: vehicleNotes.trim(),
        status: vehicleEnabled,
      };
      if (editingVehicle) {
        await updateVehicle(editingVehicle.id, payload);
        showToast('Đã cập nhật phương tiện.', 'success');
      } else {
        await createVehicle(payload);
        showToast('Đã thêm phương tiện vào Watchlist.', 'success');
      }
      setVehicleModalOpen(false);
      loadVehicles();
    } catch (err) {
      showToast(err.message, 'error');
    } finally {
      setVehicleSubmitting(false);
    }
  };

  const toggleFace = async (target) => {
    try {
      const response = await toggleTargetSelection(target.id, !target.selected);
      setFaces((items) => items.map((item) => item.id === target.id ? { ...item, selected: response.selected } : item));
      showToast('Đã cập nhật trạng thái theo dõi.', 'success');
    } catch (err) {
      showToast(err.message, 'error');
    }
  };

  const openFaceDetail = async (target) => {
    setDetailLoading(true);
    setDetail({ type: 'face', data: target, history: [] });
    try {
      const response = await fetchTargetDetail(target.id);
      setDetail({ type: 'face', data: response?.target || target, history: response?.detections || response?.history || [] });
    } catch (err) {
      showToast(`Không tải được chi tiết: ${err.message}`, 'error');
    } finally {
      setDetailLoading(false);
    }
  };

  const openVehicleDetail = async (vehicle) => {
    setDetailLoading(true);
    setDetail({ type: 'vehicle', data: vehicle, history: [] });
    try {
      const response = await fetchVehicleDetections(vehicle.id);
      setDetail({ type: 'vehicle', data: vehicle, history: response?.detections || [] });
    } catch (err) {
      showToast(`Không tải được lịch sử phát hiện: ${err.message}`, 'error');
    } finally {
      setDetailLoading(false);
    }
  };

  const confirmDelete = async () => {
    if (!deleteInfo) return;
    setDeleting(true);
    try {
      if (deleteInfo.type === 'face') await deleteTarget(deleteInfo.id);
      else await deleteVehicle(deleteInfo.id);
      showToast('Đã xóa khỏi Watchlist.', 'success');
      setDeleteInfo(null);
      if (deleteInfo.type === 'face') loadFaces();
      else loadVehicles();
    } catch (err) {
      showToast(err.message, 'error');
    } finally {
      setDeleting(false);
    }
  };

  const facePages = Math.max(1, Math.ceil(faceTotal / facePageSize));
  const vehiclePages = Math.max(1, Math.ceil(vehicleTotal / vehiclePageSize));

  return (
    <div className="monitor-page" id="watchlistPage">
      <header className="monitor-page-header">
        <div><h1>Watchlist</h1><p>Quản lý đối tượng khuôn mặt và phương tiện cần theo dõi.</p></div>
        <button
          type="button"
          className="monitor-button primary"
          onClick={activeTab === 'face' ? () => setFaceModalOpen(true) : openAddVehicle}
        >
          <FiPlus size={14} /> {activeTab === 'face' ? 'Add target' : 'Add vehicle'}
        </button>
      </header>

      <div className="watchlist-tabbar">
        <button type="button" className={`watchlist-tab ${activeTab === 'face' ? 'active' : ''}`} onClick={() => changeTab('face')}>
          <FiUsers size={15} /> Face
        </button>
        <button type="button" className={`watchlist-tab ${activeTab === 'vehicle' ? 'active' : ''}`} onClick={() => changeTab('vehicle')}>
          <FiTruck size={15} /> Vehicle
        </button>
      </div>

      <div className="monitor-card compact-filter-card">
        <div className="monitor-filter-row">
          <label className="monitor-search">
            <FiSearch size={15} />
            <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder={activeTab === 'face' ? 'Tìm tên / ID khuôn mặt…' : 'Tìm biển số…'} />
          </label>
          {activeTab === 'vehicle' ? (
            <>
              <select className="monitor-select" value={vehicleType} onChange={(e) => { setVehicleType(e.target.value); setVehiclePage(1); }}>
                <option value="all">Tất cả loại xe</option>
                <option value="car">Car</option>
                <option value="motorbike">Motorbike</option>
                <option value="truck">Truck</option>
                <option value="bus">Bus</option>
                <option value="other">Other</option>
              </select>
              <select className="monitor-select" value={vehicleStatus} onChange={(e) => { setVehicleStatus(e.target.value); setVehiclePage(1); }}>
                <option value="all">Tất cả trạng thái</option>
                <option value="active">Active</option>
                <option value="disabled">Disabled</option>
              </select>
            </>
          ) : null}
        </div>
      </div>

      {loading ? (
        <div className="monitor-card"><LoadingSpinner text="Đang tải Watchlist…" /></div>
      ) : error ? (
        <ErrorState message={error} onRetry={() => activeTab === 'face' ? loadFaces() : loadVehicles()} />
      ) : activeTab === 'face' ? (
        faces.length === 0 ? (
          <div className="monitor-card"><EmptyState icon={FiUsers} title="Chưa có khuôn mặt" message="Chưa có đối tượng phù hợp với bộ lọc hiện tại." /></div>
        ) : (
          <div className="monitor-card monitor-table-card">
            <div className="monitor-table-wrap">
              <table className="monitor-table watchlist-table">
                <thead><tr><th>Image</th><th>Target</th><th>Status</th><th>Detections / history</th><th>Actions</th></tr></thead>
                <tbody>
                  {faces.map((target) => (
                    <tr key={target.id}>
                      <td><AuthenticatedImage src={getTargetImageUrl(target.id)} alt={target.name || ''} className="watchlist-face-thumb" /></td>
                      <td><strong>{target.name || EMPTY}</strong><span className="subtle-row-text">{target.id}</span></td>
                      <td><span className={`monitor-badge ${target.selected ? 'online' : 'neutral'}`}>{target.selected ? 'active' : 'disabled'}</span></td>
                      <td>{target.detection_count ?? target.match_count ?? EMPTY}<span className="subtle-row-text">{formatTime(target.last_seen)}</span></td>
                      <td><div className="monitor-row-actions">
                        <button type="button" className="icon-action" title="Chi tiết" onClick={() => openFaceDetail(target)}><FiEye /></button>
                        <button type="button" className="icon-action" title="Bật/tắt theo dõi" onClick={() => toggleFace(target)}><FiCheck /></button>
                        <button type="button" className="icon-action danger" title="Xóa" onClick={() => setDeleteInfo({ type: 'face', id: target.id, name: target.name })}><FiTrash2 /></button>
                      </div></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="monitor-pagination"><span>{faceTotal} targets</span><div><button className="icon-action" disabled={facePage <= 1} onClick={() => setFacePage((p) => p - 1)}><FiChevronLeft /></button><span>{facePage} / {facePages}</span><button className="icon-action" disabled={facePage >= facePages} onClick={() => setFacePage((p) => p + 1)}><FiChevronRight /></button></div></div>
          </div>
        )
      ) : vehicles.length === 0 ? (
        <div className="monitor-card"><EmptyState icon={FiTruck} title="Chưa có phương tiện" message="Chưa có phương tiện phù hợp với bộ lọc hiện tại." /></div>
      ) : (
        <div className="monitor-card monitor-table-card">
          <div className="monitor-table-wrap">
            <table className="monitor-table watchlist-table" id="vehicleWatchlistTable">
              <thead><tr><th>Plate number</th><th>Vehicle type</th><th>Vehicle color</th><th>Status</th><th>Detections / history</th><th>Actions</th></tr></thead>
              <tbody>
                {vehicles.map((vehicle) => (
                  <tr key={vehicle.id}>
                    <td><strong className="plate-value">{vehicle.plate_number || EMPTY}</strong></td>
                    <td>{vehicle.vehicle_type || EMPTY}</td>
                    <td>{vehicle.vehicle_color || EMPTY}</td>
                    <td><span className={`monitor-badge ${vehicle.status === 'active' ? 'online' : 'neutral'}`}>{vehicle.status || EMPTY}</span></td>
                    <td>{vehicle.detection_count ?? EMPTY}<span className="subtle-row-text">{formatTime(vehicle.last_seen)}</span></td>
                    <td><div className="monitor-row-actions">
                      <button type="button" className="icon-action" title="Chi tiết" onClick={() => openVehicleDetail(vehicle)}><FiEye /></button>
                      <button type="button" className="icon-action" title="Sửa" onClick={() => openEditVehicle(vehicle)}><FiEdit2 /></button>
                      <button type="button" className="icon-action danger" title="Xóa" onClick={() => setDeleteInfo({ type: 'vehicle', id: vehicle.id, name: vehicle.plate_number })}><FiTrash2 /></button>
                    </div></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="monitor-pagination"><span>{vehicleTotal} vehicles</span><div><button className="icon-action" disabled={vehiclePage <= 1} onClick={() => setVehiclePage((p) => p - 1)}><FiChevronLeft /></button><span>{vehiclePage} / {vehiclePages}</span><button className="icon-action" disabled={vehiclePage >= vehiclePages} onClick={() => setVehiclePage((p) => p + 1)}><FiChevronRight /></button></div></div>
        </div>
      )}

      {faceModalOpen ? (
        <div className="monitor-modal-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) setFaceModalOpen(false); }}>
          <div className="monitor-modal" role="dialog" aria-modal="true">
            <div className="monitor-modal-header"><div><h2>Add Face Target</h2><span>Dùng dữ liệu thật từ ảnh tải lên</span></div><button type="button" className="icon-action" onClick={() => setFaceModalOpen(false)}><FiX /></button></div>
            <form onSubmit={submitFace} className="watchlist-form">
              <label>Tên đối tượng<input className="monitor-input" value={faceName} onChange={(e) => setFaceName(e.target.value)} required /></label>
              <label>Màu trang phục<input className="monitor-input" value={faceColor} onChange={(e) => setFaceColor(e.target.value)} placeholder="Tùy chọn" /></label>
              <label>Threshold<input className="monitor-input" type="number" min="0.2" max="0.9" step="0.05" value={faceThreshold} onChange={(e) => setFaceThreshold(e.target.value)} /></label>
              <label className="watchlist-file"><FiUpload /> Ảnh khuôn mặt<input type="file" accept="image/jpeg,image/png,image/webp" onChange={(e) => setFaceFile(e.target.files?.[0] || null)} required /></label>
              <div className="source-panel-actions"><button type="button" className="monitor-button secondary" onClick={() => setFaceModalOpen(false)}>Hủy</button><button type="submit" className="monitor-button primary" disabled={faceSubmitting}>{faceSubmitting ? 'Đang lưu…' : 'Lưu'}</button></div>
            </form>
          </div>
        </div>
      ) : null}

      {vehicleModalOpen ? (
        <div className="monitor-modal-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) setVehicleModalOpen(false); }}>
          <div className="monitor-modal" role="dialog" aria-modal="true">
            <div className="monitor-modal-header"><div><h2>{editingVehicle ? 'Edit Vehicle' : 'Add Vehicle'}</h2><span>Không sử dụng owner/display-name field</span></div><button type="button" className="icon-action" onClick={() => setVehicleModalOpen(false)}><FiX /></button></div>
            <form onSubmit={submitVehicle} className="watchlist-form">
              <label>Plate number<input className="monitor-input" value={vehiclePlate} onChange={(e) => setVehiclePlate(e.target.value)} required /></label>
              <div className="watchlist-form-grid"><label>Vehicle type<select className="monitor-select" value={vehicleKind} onChange={(e) => setVehicleKind(e.target.value)}><option value="car">Car</option><option value="motorbike">Motorbike</option><option value="truck">Truck</option><option value="bus">Bus</option><option value="other">Other</option></select></label><label>Vehicle color<select className="monitor-select" value={vehicleColor} onChange={(e) => setVehicleColor(e.target.value)}><option value="black">Black</option><option value="white">White</option><option value="silver">Silver</option><option value="gray">Gray</option><option value="red">Red</option><option value="blue">Blue</option><option value="other">Other</option></select></label></div>
              <label>Status<select className="monitor-select" value={vehicleEnabled} onChange={(e) => setVehicleEnabled(e.target.value)}><option value="active">Active</option><option value="disabled">Disabled</option></select></label>
              <label>Notes<textarea className="monitor-textarea" value={vehicleNotes} onChange={(e) => setVehicleNotes(e.target.value)} /></label>
              <div className="source-panel-actions"><button type="button" className="monitor-button secondary" onClick={() => setVehicleModalOpen(false)}>Hủy</button><button type="submit" className="monitor-button primary" disabled={vehicleSubmitting}>{vehicleSubmitting ? 'Đang lưu…' : 'Lưu'}</button></div>
            </form>
          </div>
        </div>
      ) : null}

      {detail ? (
        <div className="monitor-modal-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) setDetail(null); }}>
          <div className="monitor-modal" role="dialog" aria-modal="true">
            <div className="monitor-modal-header"><div><h2>{detail.type === 'face' ? 'Face Detail' : 'Vehicle Detail'}</h2><span>Thông tin và lịch sử backend cung cấp</span></div><button type="button" className="icon-action" onClick={() => setDetail(null)}><FiX /></button></div>
            {detailLoading ? <LoadingSpinner text="Đang tải chi tiết…" /> : (
              <div className="watchlist-detail-body">
                <div className="detail-list">
                  {detail.type === 'face' ? <><DetailRow label="Target" value={detail.data.name} /><DetailRow label="Target ID" value={detail.data.id} /><DetailRow label="Status" value={detail.data.selected ? 'active' : 'disabled'} /><DetailRow label="Detection count" value={detail.data.detection_count || detail.data.match_count} /><DetailRow label="Last seen" value={formatTime(detail.data.last_seen)} /></> : <><DetailRow label="Plate number" value={detail.data.plate_number} /><DetailRow label="Vehicle type" value={detail.data.vehicle_type} /><DetailRow label="Vehicle color" value={detail.data.vehicle_color} /><DetailRow label="Status" value={detail.data.status} /><DetailRow label="Detection count" value={detail.data.detection_count} /><DetailRow label="Last seen" value={formatTime(detail.data.last_seen)} /></>}
                </div>
                <div className="watchlist-history"><h3><FiCamera size={14} /> Detection history</h3>{detail.history?.length ? detail.history.slice(0, 20).map((item, index) => <div className="history-row" key={item.id || item.event_id || index}><span>{formatTime(item.timestamp || item.created_at)}</span><strong>{item.camera_name || item.camera_id || item.event_id || EMPTY}</strong></div>) : <p>Backend chưa trả về lịch sử phát hiện cho bản ghi này.</p>}</div>
              </div>
            )}
          </div>
        </div>
      ) : null}

      <DeleteConfirmModal
        isOpen={Boolean(deleteInfo)}
        title="Xác nhận xóa Watchlist"
        message={`Bạn có chắc chắn muốn xóa "${deleteInfo?.name || ''}"?`}
        onConfirm={confirmDelete}
        onClose={() => setDeleteInfo(null)}
        isDeleting={deleting}
      />
    </div>
  );
}
