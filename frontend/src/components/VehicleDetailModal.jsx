import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { fetchVehicleDetections } from '../api/watchlists';
import {
  X,
  Car,
  Clock,
  User,
  Tag,
  Palette,
  FileText,
  Activity,
  Calendar,
  ExternalLink,
  Edit,
  Trash2,
  Camera,
} from 'lucide-react';

export function VehicleDetailModal({
  vehicle,
  isOpen,
  onClose,
  onEdit,
  onDeleteRequest,
}) {
  const [detections, setDetections] = useState([]);
  const [loadingDetections, setLoadingDetections] = useState(false);
  const [detectionTotal, setDetectionTotal] = useState(0);

  useEffect(() => {
    if (!isOpen || !vehicle) {
      setDetections([]);
      return;
    }

    const abortCtrl = new AbortController();
    setLoadingDetections(true);

    (async () => {
      try {
        const resp = await fetchVehicleDetections(vehicle.id, abortCtrl.signal);
        if (resp && resp.status === 'ok') {
          setDetections(resp.detections || []);
          setDetectionTotal(resp.total_detections || resp.detections?.length || 0);
        }
      } catch (err) {
        // Fallback: no detections history
      } finally {
        setLoadingDetections(false);
      }
    })();

    return () => abortCtrl.abort();
  }, [isOpen, vehicle]);

  useEffect(() => {
    if (!isOpen) return;
    const handleKeyDown = (e) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen || !vehicle) return null;

  return (
    <div className="modal-overlay" onClick={onClose} role="dialog" aria-modal="true" id="vehicleDetailModalOverlay">
      <div
        className="modal-card detail-modal-card"
        onClick={(e) => e.stopPropagation()}
        id="vehicleDetailModal"
      >
        {/* Modal Header */}
        <div className="modal-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <Car size={20} style={{ color: 'var(--accent)' }} />
            <h3 className="modal-title" style={{ fontSize: '1.1rem' }}>
              Chi tiết Phương tiện Watchlist
            </h3>
          </div>
          <button
            type="button"
            className="btn btn-secondary btn-icon btn-sm"
            onClick={onClose}
            aria-label="Đóng cửa sổ"
            style={{ width: '32px', height: '32px', minWidth: '32px', minHeight: '32px' }}
          >
            <X size={16} />
          </button>
        </div>

        {/* Modal Body */}
        <div className="detail-modal-body">
          {/* Top Plate Banner */}
          <div className="detail-avatar-section">
            <div
              style={{
                fontFamily: 'var(--font-mono)',
                fontWeight: 800,
                fontSize: '1.5rem',
                color: 'var(--accent)',
                background: 'var(--accent-surface)',
                padding: '12px 20px',
                borderRadius: 'var(--radius-md)',
                border: '2px solid var(--accent)',
                letterSpacing: '1px',
                display: 'inline-flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              {vehicle.plate_number}
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
                <h4 style={{ fontSize: '1.15rem', fontWeight: 700, margin: 0, color: 'var(--text-primary)' }}>
                  {vehicle.display_name || vehicle.name || 'Không có tên gợi nhớ'}
                </h4>
                <span
                  className="tag-badge"
                  style={{
                    background: vehicle.status === 'active' ? 'rgba(16, 185, 129, 0.15)' : 'var(--bg-hover)',
                    color: vehicle.status === 'active' ? '#10b981' : 'var(--text-muted)',
                    fontWeight: 600,
                  }}
                >
                  {vehicle.status === 'active' ? 'HOẠT ĐỘNG' : 'TẮT THEO DÕI'}
                </span>
              </div>
              <p
                style={{
                  margin: '6px 0 0',
                  fontSize: '0.8rem',
                  fontFamily: 'var(--font-mono)',
                  color: 'var(--text-muted)',
                  wordBreak: 'break-all',
                }}
              >
                ID: {vehicle.id}
              </p>
            </div>
          </div>

          {/* Details Grid */}
          <div className="detail-grid">
            {/* Vehicle Type */}
            <div className="detail-item">
              <div className="detail-item-label" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                <Car size={13} />
                <span>Loại phương tiện</span>
              </div>
              <div className="detail-item-value">{vehicle.vehicle_type || 'Ô tô (car)'}</div>
            </div>

            {/* Vehicle Color */}
            <div className="detail-item">
              <div className="detail-item-label" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                <Palette size={13} />
                <span>Màu sơn xe</span>
              </div>
              <div className="detail-item-value">{vehicle.vehicle_color || 'Chưa ghi nhận'}</div>
            </div>

            {/* Owner Info */}
            <div className="detail-item">
              <div className="detail-item-label" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                <User size={13} />
                <span>Chủ sở hữu</span>
              </div>
              <div className="detail-item-value">{vehicle.owner_info || 'Chưa cập nhật'}</div>
            </div>

            {/* Detection count */}
            <div className="detail-item">
              <div className="detail-item-label" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                <Activity size={13} />
                <span>Số lần nhận diện</span>
              </div>
              <div className="detail-item-value" style={{ fontWeight: 600, color: 'var(--accent)' }}>
                {vehicle.detection_count ?? detectionTotal ?? 0} lần
              </div>
            </div>

            {/* Registration Time */}
            <div className="detail-item">
              <div className="detail-item-label" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                <Calendar size={13} />
                <span>Thời gian tạo</span>
              </div>
              <div className="detail-item-value">{vehicle.created_at || 'Chưa rõ'}</div>
            </div>

            {/* Last Seen */}
            <div className="detail-item">
              <div className="detail-item-label" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                <Clock size={13} />
                <span>Lần cuối xuất hiện</span>
              </div>
              <div className="detail-item-value">{vehicle.last_seen || 'Chưa từng phát hiện'}</div>
            </div>
          </div>

          {/* Notes */}
          {vehicle.notes && (
            <div className="detail-item">
              <div className="detail-item-label" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                <FileText size={13} />
                <span>Ghi chú</span>
              </div>
              <div className="detail-item-value" style={{ whiteSpace: 'pre-wrap' }}>
                {vehicle.notes}
              </div>
            </div>
          )}

          {/* Recent Detections Section */}
          <div style={{ marginTop: '4px' }}>
            <h5 style={{ fontSize: '0.9rem', fontWeight: 600, marginBottom: '8px', color: 'var(--text-secondary)' }}>
              Lịch sử phát hiện gần đây ({detections.length})
            </h5>
            {loadingDetections ? (
              <div style={{ padding: '16px', textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.85rem' }}>
                Đang tải dữ liệu phát hiện...
              </div>
            ) : detections.length === 0 ? (
              <div
                style={{
                  padding: '16px',
                  textAlign: 'center',
                  background: 'var(--bg-hover)',
                  borderRadius: 'var(--radius-sm)',
                  color: 'var(--text-muted)',
                  fontSize: '0.85rem',
                }}
              >
                Chưa có bản ghi phát hiện nào trong hệ thống
              </div>
            ) : (
              <div style={{ maxHeight: '160px', overflowY: 'auto', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-sm)' }}>
                <table className="data-table" style={{ fontSize: '0.8rem', margin: 0 }}>
                  <thead>
                    <tr>
                      <th style={{ padding: '6px 10px' }}>Thời gian</th>
                      <th style={{ padding: '6px 10px' }}>Biển số OCR</th>
                      <th style={{ padding: '6px 10px' }}>Độ tin cậy</th>
                      <th style={{ padding: '6px 10px' }}>Camera</th>
                    </tr>
                  </thead>
                  <tbody>
                    {detections.slice(0, 10).map((d) => (
                      <tr key={d.id}>
                        <td style={{ padding: '6px 10px' }}>{d.created_at}</td>
                        <td style={{ padding: '6px 10px', fontFamily: 'var(--font-mono)', fontWeight: 600 }}>{d.plate_text}</td>
                        <td style={{ padding: '6px 10px' }}>{d.confidence ? `${(d.confidence * 100).toFixed(1)}%` : '—'}</td>
                        <td style={{ padding: '6px 10px' }}>{d.camera_id ? String(d.camera_id).slice(0, 8) : 'Mặc định'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Link to Event Center */}
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              padding: '12px 16px',
              borderRadius: 'var(--radius-sm)',
              border: '1px solid var(--border-card)',
              background: 'var(--accent-surface)',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <Tag size={16} style={{ color: 'var(--accent)' }} />
              <span style={{ fontSize: '0.86rem', color: 'var(--text-primary)', fontWeight: 500 }}>
                Tra cứu sự kiện theo biển số {vehicle.plate_number}
              </span>
            </div>
            <Link
              to={`/events?search=${encodeURIComponent(vehicle.plate_number)}`}
              className="btn btn-secondary btn-sm"
              style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', textDecoration: 'none' }}
              onClick={onClose}
              id="linkViewVehicleEvents"
            >
              <span>Xem lịch sử sự kiện</span>
              <ExternalLink size={14} />
            </Link>
          </div>
        </div>

        {/* Modal Footer */}
        <div className="modal-footer" style={{ justifyContent: 'space-between' }}>
          <div style={{ display: 'flex', gap: '8px' }}>
            {onEdit && (
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={() => {
                  onClose();
                  onEdit(vehicle);
                }}
                style={{ display: 'inline-flex', alignItems: 'center', gap: '6px' }}
                id="btnEditVehicleFromDetailModal"
              >
                <Edit size={14} />
                <span>Sửa thông tin</span>
              </button>
            )}
            {onDeleteRequest && (
              <button
                type="button"
                className="btn btn-danger btn-sm"
                onClick={() => {
                  onClose();
                  onDeleteRequest(vehicle.id, vehicle.plate_number);
                }}
                style={{ display: 'inline-flex', alignItems: 'center', gap: '6px' }}
                id="btnDeleteVehicleFromDetailModal"
              >
                <Trash2 size={14} />
                <span>Xóa phương tiện</span>
              </button>
            )}
          </div>

          <button
            type="button"
            className="btn btn-secondary"
            onClick={onClose}
            id="btnCloseVehicleDetailModal"
          >
            Đóng
          </button>
        </div>
      </div>
    </div>
  );
}
