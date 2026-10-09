import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { AuthenticatedImage } from './AuthenticatedImage';
import { getTargetImageUrl, fetchTargetDetail } from '../api/watchlists';
import {
  X,
  User,
  Shield,
  Eye,
  EyeOff,
  Clock,
  Fingerprint,
  Tag,
  Sliders,
  FileText,
  ExternalLink,
  Trash2,
} from 'lucide-react';

export function FaceDetailModal({
  target,
  isOpen,
  onClose,
  onToggleActive,
  onDeleteRequest,
}) {
  const [detailData, setDetailData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [toggling, setToggling] = useState(false);

  useEffect(() => {
    if (!isOpen || !target) {
      setDetailData(null);
      return;
    }

    setDetailData(target);
    const abortCtrl = new AbortController();
    setLoading(true);

    (async () => {
      try {
        const resp = await fetchTargetDetail(target.id, abortCtrl.signal);
        if (resp && resp.status === 'ok' && resp.target) {
          setDetailData((prev) => ({
            ...prev,
            ...resp.target,
          }));
        }
      } catch (err) {
        // Fallback to target passed as prop
      } finally {
        setLoading(false);
      }
    })();

    return () => abortCtrl.abort();
  }, [isOpen, target]);

  useEffect(() => {
    if (!isOpen) return;
    const handleKeyDown = (e) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen || !target) return null;

  const current = detailData || target;
  const isSelected = Boolean(current.selected);
  const hasEmbedding = Boolean(current.has_embedding);
  const formattedDate = current.created_at
    ? new Date(current.created_at).toLocaleString('vi-VN', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
      })
    : 'Không xác định';

  const handleToggle = async () => {
    if (toggling) return;
    setToggling(true);
    try {
      if (onToggleActive) {
        await onToggleActive(current.id, isSelected);
        setDetailData((prev) => (prev ? { ...prev, selected: !isSelected } : null));
      }
    } finally {
      setToggling(false);
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose} role="dialog" aria-modal="true" id="faceDetailModalOverlay">
      <div
        className="modal-card detail-modal-card"
        onClick={(e) => e.stopPropagation()}
        id="faceDetailModal"
      >
        {/* Modal Header */}
        <div className="modal-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <User size={20} style={{ color: 'var(--accent)' }} />
            <h3 className="modal-title" style={{ fontSize: '1.1rem' }}>
              Chi tiết Đối tượng Khuôn mặt
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
          {/* Top Avatar Banner */}
          <div className="detail-avatar-section">
            <AuthenticatedImage
              src={getTargetImageUrl(current.id)}
              alt={current.name}
              className="detail-avatar-img"
            />
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
                <h4 style={{ fontSize: '1.2rem', fontWeight: 700, margin: 0, color: 'var(--text-primary)' }}>
                  {current.name}
                </h4>
                <span
                  className="tag-badge"
                  style={{
                    background: current.active !== false ? 'rgba(16, 185, 129, 0.15)' : 'var(--bg-hover)',
                    color: current.active !== false ? '#10b981' : 'var(--text-muted)',
                    fontWeight: 600,
                  }}
                >
                  {current.active !== false ? 'ĐANG KÍCH HOẠT' : 'ĐÃ VÔ HIỆU'}
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
                UUID: {current.id}
              </p>
            </div>
          </div>

          {/* Video Recognition Live Toggle Control */}
          <div className="detail-toggle-banner">
            <div>
              <div style={{ fontSize: '0.88rem', fontWeight: 600, color: 'var(--text-primary)' }}>
                Kích hoạt nhận diện trong luồng video
              </div>
              <div style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', marginTop: '2px' }}>
                {isSelected
                  ? 'Đang tìm kiếm và so khớp khuôn mặt này trên tất cả camera'
                  : 'Đã tạm dừng nhận diện khuôn mặt này trong luồng video'}
              </div>
            </div>
            <button
              type="button"
              className={`btn btn-sm ${isSelected ? 'btn-primary' : 'btn-secondary'}`}
              onClick={handleToggle}
              disabled={toggling}
              id="btnToggleFaceActiveInModal"
              style={{ minWidth: '135px', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px' }}
            >
              {isSelected ? <Eye size={16} /> : <EyeOff size={16} />}
              <span>{toggling ? 'Đang lưu...' : (isSelected ? 'Đang kích hoạt' : 'Kích hoạt ngay')}</span>
            </button>
          </div>

          {/* Details Grid */}
          <div className="detail-grid">
            {/* Registered Timestamp */}
            <div className="detail-item">
              <div className="detail-item-label" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                <Clock size={13} />
                <span>Thời gian đăng ký</span>
              </div>
              <div className="detail-item-value">{formattedDate}</div>
            </div>

            {/* Threshold */}
            <div className="detail-item">
              <div className="detail-item-label" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                <Sliders size={13} />
                <span>Ngưỡng nhận diện (Threshold)</span>
              </div>
              <div className="detail-item-value">
                {current.face_threshold != null ? String(current.face_threshold) : '0.45'}
              </div>
            </div>

            {/* Clothing color */}
            <div className="detail-item">
              <div className="detail-item-label" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                <Tag size={13} />
                <span>Màu trang phục nhận diện</span>
              </div>
              <div className="detail-item-value">
                {current.clothing_color ? (
                  <span className="tag-badge" style={{ background: 'var(--bg-hover)', color: 'var(--text-primary)' }}>
                    {current.clothing_color}
                  </span>
                ) : (
                  'Không thiết lập'
                )}
              </div>
            </div>

            {/* Biometric Embedding Registration Status */}
            <div className="detail-item">
              <div className="detail-item-label" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                <Fingerprint size={13} />
                <span>Véc-tơ đặc trưng khuôn mặt</span>
              </div>
              <div className="detail-item-value" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                <span
                  style={{
                    display: 'inline-block',
                    width: '8px',
                    height: '8px',
                    borderRadius: '50%',
                    background: hasEmbedding ? '#10b981' : '#f59e0b',
                  }}
                />
                <span style={{ fontWeight: 500, fontSize: '0.85rem' }}>
                  {hasEmbedding ? 'Đã trích xuất (512-dim embedding)' : 'Chưa có véc-tơ đặc trưng'}
                </span>
              </div>
            </div>
          </div>

          {/* Description or Notes */}
          {(current.notes || current.metadata?.description) && (
            <div className="detail-item" style={{ gridColumn: '1 / -1' }}>
              <div className="detail-item-label" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                <FileText size={13} />
                <span>Ghi chú bổ sung</span>
              </div>
              <div className="detail-item-value" style={{ whiteSpace: 'pre-wrap' }}>
                {current.notes || current.metadata?.description}
              </div>
            </div>
          )}

          {/* Event History Action Link */}
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
              <Shield size={16} style={{ color: 'var(--accent)' }} />
              <span style={{ fontSize: '0.86rem', color: 'var(--text-primary)', fontWeight: 500 }}>
                Tra cứu lịch sử xuất hiện của đối tượng
              </span>
            </div>
            <Link
              to={`/events?search=${encodeURIComponent(current.name)}`}
              className="btn btn-secondary btn-sm"
              style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', textDecoration: 'none' }}
              onClick={onClose}
              id="linkViewFaceEvents"
            >
              <span>Xem lịch sử sự kiện</span>
              <ExternalLink size={14} />
            </Link>
          </div>
        </div>

        {/* Modal Footer */}
        <div className="modal-footer" style={{ justifyContent: 'space-between' }}>
          {onDeleteRequest ? (
            <button
              type="button"
              className="btn btn-danger btn-sm"
              onClick={() => {
                onClose();
                onDeleteRequest(current.id, current.name);
              }}
              style={{ display: 'inline-flex', alignItems: 'center', gap: '6px' }}
              id="btnDeleteFaceFromDetailModal"
            >
              <Trash2 size={14} />
              <span>Xóa đối tượng</span>
            </button>
          ) : <div />}

          <button
            type="button"
            className="btn btn-secondary"
            onClick={onClose}
            id="btnCloseFaceDetailModal"
          >
            Đóng
          </button>
        </div>
      </div>
    </div>
  );
}
