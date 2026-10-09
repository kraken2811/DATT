import React, { createContext, useContext, useState, useEffect, useRef, useCallback } from 'react';
import { fetchTelemetry } from '../api/telemetry';
import { switchCamera as apiSwitchCamera, stopCamera as apiStopCamera } from '../api/cameras';
import { useToast } from './ToastContext';
import { CONNECTION_CHANGED, AUTH_REJECTED } from '../api/connection';

const AppContext = createContext(null);

export function AppProvider({ children }) {
  const { showToast } = useToast();
  const [connectionRevision, setConnectionRevision] = useState(0);
  const [authenticationStatus, setAuthenticationStatus] = useState(null);
  const [apiStatus, setApiStatus] = useState('connecting');

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
    people_count: null,
    car_count: null,
    stream_fps: null,
    processing_fps: null,
    yolo_latency_ms: null,
    pipeline_latency_ms: null,
    camera_name: 'Connecting...',
    error_message: null,
  });

  const [activeCamera, setActiveCamera] = useState({
    id: 'default',
    name: 'Initializing Camera...',
    source_url: '',
    source_type: 'rtsp',
  });

  useEffect(() => {
    const changed = () => {
      setAuthenticationStatus(null);
      setTelemetry(prev => ({ ...prev, people_count: null, car_count: null,
        stream_fps: null, processing_fps: null, pipeline_latency_ms: null,
        stream_alive: false, camera_status: 'CONNECTING', status: 'CONNECTING' }));
      setActiveCamera({ id: 'default', name: 'Initializing Camera...', source_url: '', source_type: 'rtsp' });
      setConnectionRevision(value => value + 1);
    };
    const rejected = event => setAuthenticationStatus(event.detail.status);
    const storageChanged = event => {
      if (!event.key || ['datt_backend_url', 'datt_auth_token', 'datt_auth_token_scope', 'datt_agent_session_id'].includes(event.key)) changed();
    };
    window.addEventListener(CONNECTION_CHANGED, changed);
    window.addEventListener(AUTH_REJECTED, rejected);
    window.addEventListener('storage', storageChanged);
    return () => {
      window.removeEventListener(CONNECTION_CHANGED, changed);
      window.removeEventListener(AUTH_REJECTED, rejected);
      window.removeEventListener('storage', storageChanged);
    };
  }, []);

  // Track stream generation token to prevent race conditions
  const streamTokenRef = useRef(0);
  const activeSwitchAbortRef = useRef(null);
  const activeSwitchKeyRef = useRef(null);
  const activeSwitchPromiseRef = useRef(null);

  // Switch camera with race condition prevention
  const switchActiveCamera = useCallback(async (sourcePayload) => {
    const cameraId = sourcePayload.id || sourcePayload.camera_id;
    const sourceType = sourcePayload.source_type || sourcePayload.type || '';
    const source = sourcePayload.source_url || sourcePayload.url || sourcePayload.source || '';
    const switchKey = cameraId ? `camera:${cameraId}` : `source:${sourceType}:${source}`;
    if (activeSwitchKeyRef.current === switchKey && activeSwitchPromiseRef.current) {
      return activeSwitchPromiseRef.current;
    }
    const token = ++streamTokenRef.current;

    // 1. Abort previous in-flight switch request
    if (activeSwitchAbortRef.current) {
      activeSwitchAbortRef.current.abort();
      activeSwitchAbortRef.current = null;
    }
    const abortController = new AbortController();
    activeSwitchAbortRef.current = abortController;

    // Keep the current camera visible until the backend accepts the switch.
    const displayName = sourcePayload.name || sourcePayload.camera_name || 'Loading Camera...';

    setTelemetry((prev) => ({
      ...prev,
      camera_name: displayName,
      camera_status: 'CONNECTING',
      stream_alive: false,
      stream_fps: 0,
    }));

    try {
      const request = apiSwitchCamera(sourcePayload, abortController.signal);
      activeSwitchKeyRef.current = switchKey;
      activeSwitchPromiseRef.current = request;
      const resp = await request;

      // Invalidate if a newer camera switch started
      if (token !== streamTokenRef.current) {
        return;
      }

      setActiveCamera((prev) => ({
        ...prev,
        name: resp.camera_name || displayName,
        id: resp.camera_id || cameraId || prev.id,
        source_url: source || prev.source_url,
        source_type: sourceType || prev.source_type,
      }));
      showToast(`Switched to camera: ${resp.camera_name || displayName}`, 'success');
      return resp;
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
      if (activeSwitchKeyRef.current === switchKey) {
        activeSwitchKeyRef.current = null;
        activeSwitchPromiseRef.current = null;
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

  // Sequential polling: pause after authentication denial until credentials change.
  useEffect(() => {
    let isMounted = true;
    let abortController = null;
    let timer = null;
    let authDenied = false;

    const poll = async () => {
      if (!isMounted) return;
      abortController = new AbortController();
      try {
        const data = await fetchTelemetry(abortController.signal);
        if (isMounted && data) {
          setApiStatus('connected');
          setTelemetry((prev) => ({
            ...prev,
            ...data,
          }));
          if (!data.is_fallback && data.camera_name && data.camera_name !== 'Disconnected') {
            setActiveCamera((prev) => ({
              ...prev,
              name: data.camera_name,
            }));
          }
        }
      } catch (err) {
        if (err.name !== 'AbortError' && isMounted) {
          authDenied = err.status === 401 || err.status === 403;
          if (authDenied) {
            setAuthenticationStatus(err.status);
            setApiStatus('auth_required');
          } else {
            setApiStatus('disconnected');
          }
          setTelemetry((prev) => ({
            ...prev,
            status: authDenied ? 'AUTH_REQUIRED' : 'DISCONNECTED',
            camera_status: authDenied ? 'AUTH_REQUIRED' : 'DISCONNECTED',
            stream_alive: false,
            people_count: null, car_count: null, stream_fps: null,
            processing_fps: null, pipeline_latency_ms: null,
            error_message: authDenied ? 'Cần xác thực trong Cài đặt.' : err.message,
          }));
        }
      } finally {
        if (isMounted && !authDenied) timer = setTimeout(poll, 1000);
      }
    };

    poll();

    return () => {
      isMounted = false;
      clearTimeout(timer);
      if (abortController) {
        abortController.abort();
      }
    };
  }, [connectionRevision]);

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
        connectionRevision,
        authenticationStatus,
        apiStatus,
        setApiStatus,
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
