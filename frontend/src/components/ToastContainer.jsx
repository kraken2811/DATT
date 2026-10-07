import React from 'react';
import { useToast } from '../context/ToastContext';
import { X, CheckCircle, AlertTriangle, AlertCircle, Info } from 'lucide-react';

export function ToastContainer() {
  const { toasts, removeToast } = useToast();

  if (!toasts || toasts.length === 0) return null;

  return (
    <div className="toast-container" id="toastContainer">
      {toasts.map((toast) => {
        let Icon = Info;
        if (toast.type === 'success') Icon = CheckCircle;
        else if (toast.type === 'error') Icon = AlertCircle;
        else if (toast.type === 'warning') Icon = AlertTriangle;

        return (
          <div key={toast.id} className={`toast-item ${toast.type}`}>
            <Icon size={18} />
            <div className="toast-message">{toast.message}</div>
            <button
              type="button"
              className="toast-close-btn"
              onClick={() => removeToast(toast.id)}
              aria-label="Close notification"
            >
              <X size={16} />
            </button>
          </div>
        );
      })}
    </div>
  );
}
