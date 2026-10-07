import React, { createContext, useContext, useState, useEffect, useRef, useCallback } from 'react';
import { fetchTelemetry } from '../api/telemetry';
import { switchCamera as apiSwitchCamera, stopCamera as apiStopCamera, fetchCameras } from '../api/cameras';
import { useToast } from './ToastContext';

const AppContext = createContext(null);

export function AppProvider({ children }) {
  const { showToast } = useToast();

  // Theme Mode persistence ('light' | 'dark', default 'light')
  const [themeMode, setThemeMode] = useState(() => {
    try {
      const saved = localStorage.getItem('datt_theme');
      return saved === 'dark' ? 'dark' : 'light';
    } catch {
      return 'light';
    }
  });

  useEffect(() => {
    try {
      localStorage.setItem('datt_theme', themeMode);
      document.documentElement.dataset.theme = themeMode;
    } catch {}
  }, [themeMode]);

  // Theme accent persistence
  const [accentColor, setAccentColor] = useState(() => {
    try {
      return localStorage.getItem('datt_accent_color') || 'blue';
    } catch {
      return 'blue';
    }
  });

  useEffect(() => {
    try {
      localStorage.setItem('datt_accent_color', accentColor);
      document.documentElement.dataset.accent = accentColor;
    } catch {}
  }, [accentColor]);

  // Real Backend Telemetry state (No mocks)
  const [telemetry, setTelemetry] = useState({
    status: 'CONNECTING',
    camera_status: 'CONNECTING',
    stream_alive: false,
    people_count: 0,
    car_count: 0,
    stream_fps: 0,
    processing_fps: 0,
    yolo_latency_ms: 0,
    pipeline_latency_ms: 0,
    camera_name: 'Connecting...',
    error_message: null,
  });

  const [activeCamera, setActiveCamera] = useState({
    id: 'default',
    name: 'Initializing Camera...',
    source_url: '',
    source_type: 'rtsp',
  });

  // Track stream generation token to prevent race conditions
  const streamTokenRef = useRef(0);
  const activeSwitchAbortRef = useRef(null);

  // Switch camera with race condition prevention
  const switchActiveCamera = useCallback(async (sourcePayload) => {
    const token = ++streamTokenRef.current;

    // 1. Abort previous in-flight switch request
    if (activeSwitchAbortRef.current) {
      activeSwitchAbortRef.current.abort();
      activeSwitchAbortRef.current = null;
    }
    const abortController = new AbortController();
    activeSwitchAbortRef.current = abortController;

    // 2. Clear stale telemetry / set connecting state for new camera
    const displayName = sourcePayload.name || sourcePayload.camera_name || 'Loading Camera...';
    setActiveCamera((prev) => ({
      ...prev,
      name: displayName,
      id: sourcePayload.id || sourcePayload.camera_id || prev.id,
      source_url: sourcePayload.source_url || sourcePayload.url || prev.source_url,
      source_type: sourcePayload.source_type || sourcePayload.type || prev.source_type,
    }));

    setTelemetry((prev) => ({
      ...prev,
      camera_name: displayName,
      camera_status: 'CONNECTING',
      stream_alive: false,
      stream_fps: 0,
    }));

    try {
      const resp = await apiSwitchCamera(
        {
          source: sourcePayload.source_url || sourcePayload.url || sourcePayload.source,
          source_type: sourcePayload.source_type || sourcePayload.type,
          name: displayName,
          loop: sourcePayload.loop ?? true,
        },
        abortController.signal
      );

      // Invalidate if a newer camera switch started
      if (token !== streamTokenRef.current) {
        return;
      }

      showToast(`Switched to camera: ${displayName}`, 'success');
    } catch (err) {
      if (err.name === 'AbortError' || token !== streamTokenRef.current) {
        return;
      }
      showToast(`Camera switch failed: ${err.message}`, 'error');
      setTelemetry((prev) => ({
        ...prev,
        camera_status: 'ERROR',
        error_message: err.message,
      }));
    } finally {
      if (activeSwitchAbortRef.current === abortController) {
        activeSwitchAbortRef.current = null;
      }
    }
  }, [showToast]);

  // Stop camera stream
  const stopActiveCamera = useCallback(async () => {
    ++streamTokenRef.current;
    if (activeSwitchAbortRef.current) {
      activeSwitchAbortRef.current.abort();
      activeSwitchAbortRef.current = null;
    }
    try {
      await apiStopCamera();
      showToast('Camera stream stopped', 'info');
      setTelemetry((prev) => ({
        ...prev,
        camera_status: 'STOPPED',
        stream_alive: false,
        stream_fps: 0,
      }));
    } catch (err) {
      showToast(`Stop camera error: ${err.message}`, 'error');
    }
  }, [showToast]);

  // Telemetry Poller (1-second frequency with StrictMode protection and cleanup)
  useEffect(() => {
    let isMounted = true;
    let abortController = null;

    const poll = async () => {
      if (!isMounted) return;
      abortController = new AbortController();
      try {
        const data = await fetchTelemetry(abortController.signal);
        if (isMounted && data) {
          setTelemetry((prev) => ({
            ...prev,
            ...data,
          }));
          if (data.camera_name && data.camera_name !== 'Disconnected') {
            setActiveCamera((prev) => ({
              ...prev,
              name: data.camera_name,
            }));
          }
        }
      } catch (err) {
        if (err.name !== 'AbortError' && isMounted) {
          // Keep previous data but indicate disconnected
          setTelemetry((prev) => ({
            ...prev,
            status: 'DISCONNECTED',
            camera_status: 'DISCONNECTED',
            stream_alive: false,
          }));
        }
      }
    };

    poll();
    const interval = setInterval(poll, 1000);

    return () => {
      isMounted = false;
      clearInterval(interval);
      if (abortController) {
        abortController.abort();
      }
    };
  }, []);

  return (
    <AppContext.Provider
      value={{
        theme: themeMode,
        themeMode,
        setTheme: setThemeMode,
        setThemeMode,
        accentColor,
        setAccentColor,
        telemetry,
        activeCamera,
        switchActiveCamera,
        stopActiveCamera,
        streamToken: streamTokenRef.current,
      }}
    >
      {children}
    </AppContext.Provider>
  );
}

export function useApp() {
  const context = useContext(AppContext);
  if (!context) {
    throw new Error('useApp must be used within an AppProvider');
  }
  return context;
}
