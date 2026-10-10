import React, { useEffect } from 'react';
import { FiAlertTriangle, FiX } from 'react-icons/fi';

export function DeleteConfirmModal({
  isOpen,
  title = 'Xác nhận xóa',
  message = 'Bạn có chắc chắn muốn xóa bản ghi này? Thao tác này không thể hoàn tác.',
  onConfirm,
  onClose,
  isDeleting = false,
}) {
  useEffect(() => {
    if (!isOpen) return undefined;
    const handleKeyDown = (event) => {
      if (event.key === 'Escape' && !isDeleting) onClose();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose, isDeleting]);

  if (!isOpen) return null;

  return (
    <div className="monitor-modal-backdrop" onMouseDown={(event) => {
      if (event.target === event.currentTarget && !isDeleting) onClose();
    }} role="presentation">
      <div className="monitor-modal delete-confirm-modal" role="dialog" aria-modal="true">
        <div className="monitor-modal-header">
          <div className="delete-confirm-title">
            <FiAlertTriangle size={18} aria-hidden="true" />
            <div><h2>{title}</h2><span>Thao tác này cần xác nhận</span></div>
          </div>
          <button type="button" className="icon-action" onClick={onClose} disabled={isDeleting} aria-label="Đóng">
            <FiX size={15} />
          </button>
        </div>
        <div className="delete-confirm-body">{message}</div>
        <div className="delete-confirm-actions">
          <button type="button" className="monitor-button secondary" onClick={onClose} disabled={isDeleting}>Hủy</button>
          <button type="button" className="monitor-button danger" onClick={onConfirm} disabled={isDeleting}>
            {isDeleting ? 'Đang xóa…' : 'Xóa'}
          </button>
        </div>
      </div>
    </div>
  );
}
