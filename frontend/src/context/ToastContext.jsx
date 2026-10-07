import React, { createContext, useContext, useState, useCallback, useRef } from 'react';

const ToastContext = createContext(null);

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);
  const timerMapRef = useRef(new Map());

  const removeToast = useCallback((id) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
    if (timerMapRef.current.has(id)) {
      clearTimeout(timerMapRef.current.get(id));
      timerMapRef.current.delete(id);
    }
  }, []);

  const showToast = useCallback((message, type = 'info', duration = 5000) => {
    const id = Date.now().toString() + Math.random().toString(36).substring(2, 6);
    const newToast = { id, message, type, timestamp: Date.now() };

    setToasts((prev) => {
      // Maintain max 3 toasts. New notification pushes older ones
      const next = [...prev, newToast];
      if (next.length > 3) {
        const removed = next.shift();
        if (removed && timerMapRef.current.has(removed.id)) {
          clearTimeout(timerMapRef.current.get(removed.id));
          timerMapRef.current.delete(removed.id);
        }
      }
      return next;
    });

    if (duration > 0) {
      const timer = setTimeout(() => {
        removeToast(id);
      }, duration);
      timerMapRef.current.set(id, timer);
    }

    return id;
  }, [removeToast]);

  React.useEffect(() => {
    window.showToast = showToast;
    return () => {
      delete window.showToast;
    };
  }, [showToast]);

  return (
    <ToastContext.Provider value={{ toasts, showToast, removeToast }}>
      {children}
    </ToastContext.Provider>
  );
}

export function useToast() {
  const context = useContext(ToastContext);
  if (!context) {
    throw new Error('useToast must be used within a ToastProvider');
  }
  return context;
}
