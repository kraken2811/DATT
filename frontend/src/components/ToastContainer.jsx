import React from 'react';
import {
  FiX,
  FiCheckCircle,
  FiAlertTriangle,
  FiAlertCircle,
  FiInfo,
} from 'react-icons/fi';
import { useToast } from '../context/ToastContext';

export function ToastContainer() {
  const { toasts, removeToast } = useToast();
  if (!toasts?.length) return null;

  return (
    <div className="toast-container monitoring-toast-container" id="toastContainer" aria-live="polite">
      {toasts.map((toast) => {
        let Icon = FiInfo;
        if (toast.type === 'success') Icon = FiCheckCircle;
        else if (toast.type === 'error') Icon = FiAlertCircle;
        else if (toast.type === 'warning') Icon = FiAlertTriangle;

        return (
          <div key={toast.id} className={`toast-item ${toast.type}`} role="status">
            <Icon size={17} aria-hidden="true" />
            <div className="toast-message">{toast.message}</div>
            <button
              type="button"
              className="toast-close-btn"
              onClick={() => removeToast(toast.id)}
              aria-label="Đóng thông báo"
            >
              <FiX size={15} aria-hidden="true" />
            </button>
          </div>
        );
      })}
    </div>
  );
}
