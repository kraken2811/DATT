import React, { useEffect } from 'react';
import { AlertTriangle, X } from 'lucide-react';

export function DeleteConfirmModal({
  isOpen,
  title = 'Xác nhận xóa',
  message = 'Bạn có chắc chắn muốn xóa bản ghi này? Thao tác này không thể hoàn tác.',
  onConfirm,
  onClose,
  isDeleting = false,
}) {
  useEffect(() => {
    if (!isOpen) return;
    const handleKeyDown = (e) => {
      if (e.key === 'Escape' && !isDeleting) {
        onClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose, isDeleting]);

  if (!isOpen) return null;

  return (
    <div className="modal-overlay" onClick={isDeleting ? undefined : onClose} role="dialog" aria-modal="true">
      <div
        className="modal-card"
        style={{ maxWidth: '440px', width: '90%' }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <div
              style={{
                width: '36px',
                height: '36px',
                borderRadius: '50%',
                background: 'rgba(239, 68, 68, 0.15)',
                color: 'var(--status-danger)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                flexShrink: 0,
              }}
            >
              <AlertTriangle size={20} />
            </div>
            <h3 className="modal-title" style={{ fontSize: '1.05rem', margin: 0 }}>
              {title}
            </h3>
          </div>
          <button
            type="button"
            className="btn btn-secondary btn-icon btn-sm"
            onClick={onClose}
            disabled={isDeleting}
            aria-label="Đóng hộp thoại"
            style={{ width: '32px', height: '32px', minWidth: '32px', minHeight: '32px' }}
          >
            <X size={16} />
          </button>
        </div>

        <div className="modal-body" style={{ padding: '16px 20px' }}>
          <p style={{ margin: 0, fontSize: '0.9rem', color: 'var(--text-secondary)', lineHeight: 1.5 }}>
            {message}
          </p>
        </div>

        <div className="modal-footer" style={{ padding: '12px 20px' }}>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={onClose}
            disabled={isDeleting}
          >
            Hủy
          </button>
          <button
            type="button"
            className="btn btn-danger"
            onClick={onConfirm}
            disabled={isDeleting}
            id="btnConfirmDeleteAction"
          >
            {isDeleting ? 'Đang xóa...' : 'Xác nhận xóa'}
          </button>
        </div>
      </div>
    </div>
  );
}
