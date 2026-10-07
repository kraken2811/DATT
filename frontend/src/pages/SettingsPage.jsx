import React, { useState, useEffect } from 'react';
import { Header } from '../components/Header';
import { useApp } from '../context/AppContext';
import { useToast } from '../context/ToastContext';
import { apiRequest, getBackendBaseUrl } from '../api/client';
import { Settings, Server, Palette, Cpu, Check, RefreshCw, Sun, Moon } from 'lucide-react';

export function SettingsPage() {
  const { accentColor, setAccentColor, theme, setTheme } = useApp();
  const { showToast } = useToast();

  const [backendUrl, setBackendUrl] = useState(() => getBackendBaseUrl() || window.location.origin);
  const [deviceInfo, setDeviceInfo] = useState(null);
  const [loadingDevices, setLoadingDevices] = useState(false);

  const themes = [
    { id: 'blue', color: '#3b82f6', label: 'Electric Blue' },
    { id: 'emerald', color: '#10b981', label: 'Emerald Green' },
    { id: 'violet', color: '#8b5cf6', label: 'Neon Violet' },
    { id: 'amber', color: '#f59e0b', label: 'Amber Cyber' },
    { id: 'rose', color: '#f43f5e', label: 'Vibrant Rose' },
  ];

  const handleSaveBackendUrl = (e) => {
    e.preventDefault();
    try {
      localStorage.setItem('datt_backend_url', backendUrl.trim());
      showToast('Đã lưu cấu hình địa chỉ máy chủ backend!', 'success');
    } catch (err) {
      showToast('Không thể lưu cấu hình', 'error');
    }
  };

  const loadDevices = async () => {
    setLoadingDevices(true);
    try {
      const resp = await apiRequest('/api/runtime_devices?instrument=true');
      setDeviceInfo(resp);
    } catch (err) {
      console.error('Device audit error:', err);
    } finally {
      setLoadingDevices(false);
    }
  };

  useEffect(() => {
    loadDevices();
  }, []);

  return (
    <>
      <Header title="Cài đặt Hệ thống (Settings)" />

      <div className="page-container" id="settingsPage" style={{ maxWidth: '900px' }}>
        {/* Backend Configuration */}
        <div className="card" style={{ marginBottom: '24px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '16px' }}>
            <Server size={20} style={{ color: 'var(--accent)' }} />
            <h3 style={{ fontSize: '1.05rem', fontWeight: 600 }}>Cấu hình Kết nối Máy chủ AI Backend</h3>
          </div>

          <form onSubmit={handleSaveBackendUrl}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              <div>
                <label style={{ display: 'block', fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '6px' }}>
                  Địa chỉ AI Server URL (Mặc định sử dụng cổng UI 8501)
                </label>
                <input
                  type="text"
                  className="input-field"
                  placeholder="http://localhost:8501 hoặc https://..."
                  value={backendUrl}
                  onChange={(e) => setBackendUrl(e.target.value)}
                  id="inputBackendUrl"
                />
              </div>

              <div style={{ display: 'flex', gap: '10px' }}>
                <button type="submit" className="btn btn-primary btn-sm" id="btnSaveBackendUrl">
                  <Check size={14} />
                  <span>Lưu cấu hình</span>
                </button>
              </div>
            </div>
          </form>
        </div>

        {/* Appearance - Theme Mode Setting */}
        <div className="card" style={{ marginBottom: '24px' }} id="settingCardTheme">
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '16px' }}>
            <Sun size={20} style={{ color: 'var(--accent)' }} />
            <div>
              <h3 style={{ fontSize: '1.05rem', fontWeight: 600 }}>Giao diện (Appearance)</h3>
              <p style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>Chế độ hiển thị (Theme)</p>
            </div>
          </div>

          <div style={{ display: 'flex', gap: '16px', flexWrap: 'wrap' }}>
            <button
              type="button"
              className={`card theme-option-btn ${theme === 'light' ? 'active' : ''}`}
              style={{
                padding: '16px 28px',
                display: 'flex',
                alignItems: 'center',
                gap: '12px',
                cursor: 'pointer',
                border: theme === 'light' ? '2px solid var(--accent)' : '1px solid var(--border-card)',
                background: theme === 'light' ? 'var(--accent-surface)' : 'var(--bg-card)',
                color: theme === 'light' ? 'var(--accent)' : 'var(--text-primary)',
              }}
              onClick={() => {
                setTheme('light');
                showToast('Đã chuyển sang giao diện Sáng (Light Mode)', 'info');
              }}
              id="btnThemeLight"
            >
              <Sun size={18} />
              <span style={{ fontSize: '0.95rem', fontWeight: 600 }}>Light</span>
            </button>

            <button
              type="button"
              className={`card theme-option-btn ${theme === 'dark' ? 'active' : ''}`}
              style={{
                padding: '16px 28px',
                display: 'flex',
                alignItems: 'center',
                gap: '12px',
                cursor: 'pointer',
                border: theme === 'dark' ? '2px solid var(--accent)' : '1px solid var(--border-card)',
                background: theme === 'dark' ? 'var(--accent-surface)' : 'var(--bg-card)',
                color: theme === 'dark' ? 'var(--accent)' : 'var(--text-primary)',
              }}
              onClick={() => {
                setTheme('dark');
                showToast('Đã chuyển sang giao diện Tối (Dark Mode)', 'info');
              }}
              id="btnThemeDark"
            >
              <Moon size={18} />
              <span style={{ fontSize: '0.95rem', fontWeight: 600 }}>Dark</span>
            </button>
          </div>
        </div>

        {/* Theme Accent Customization */}
        <div className="card" style={{ marginBottom: '24px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '16px' }}>
            <Palette size={20} style={{ color: 'var(--accent)' }} />
            <h3 style={{ fontSize: '1.05rem', fontWeight: 600 }}>Tùy biến Giao diện (Theme Accent)</h3>
          </div>

          <div style={{ display: 'flex', gap: '16px', flexWrap: 'wrap' }}>
            {themes.map((t) => (
              <button
                key={t.id}
                type="button"
                className={`card ${accentColor === t.id ? 'active' : ''}`}
                style={{
                  padding: '16px 20px',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '12px',
                  cursor: 'pointer',
                  border: accentColor === t.id ? `2px solid ${t.color}` : '1px solid var(--border-card)',
                  background: accentColor === t.id ? 'var(--accent-surface)' : 'var(--bg-card)',
                }}
                onClick={() => {
                  setAccentColor(t.id);
                  showToast(`Đã chuyển theme: ${t.label}`, 'info');
                }}
                id={`btnTheme${t.id}`}
              >
                <div style={{ width: '20px', height: '20px', borderRadius: '50%', backgroundColor: t.color, boxShadow: `0 0 10px ${t.color}` }} />
                <span style={{ fontSize: '0.9rem', fontWeight: 500 }}>{t.label}</span>
              </button>
            ))}
          </div>
        </div>

        {/* Device & Hardware Info */}
        <div className="card">
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              <Cpu size={20} style={{ color: 'var(--accent)' }} />
              <h3 style={{ fontSize: '1.05rem', fontWeight: 600 }}>Thông tin Thiết bị & Phần cứng (Hardware Audit)</h3>
            </div>
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={loadDevices}
              disabled={loadingDevices}
            >
              <RefreshCw size={14} />
              <span>{loadingDevices ? 'Đang kiểm tra...' : 'Làm mới'}</span>
            </button>
          </div>

          {deviceInfo ? (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '14px', fontSize: '0.85rem' }}>
              <div>
                <span style={{ color: 'var(--text-muted)' }}>Thiết bị chính:</span>
                <div style={{ fontWeight: 600 }}>{deviceInfo.primary_device || 'CPU'}</div>
              </div>
              <div>
                <span style={{ color: 'var(--text-muted)' }}>GPU Name:</span>
                <div style={{ fontWeight: 600 }}>{deviceInfo.gpu_name || 'N/A'}</div>
              </div>
              <div>
                <span style={{ color: 'var(--text-muted)' }}>Bộ nhớ VRAM:</span>
                <div style={{ fontWeight: 600 }}>{deviceInfo.vram_allocated_mb ? `${deviceInfo.vram_allocated_mb} MB` : 'N/A'}</div>
              </div>
              <div>
                <span style={{ color: 'var(--text-muted)' }}>Môi trường:</span>
                <div style={{ fontWeight: 600 }}>{deviceInfo.is_colab ? 'Google Colab' : 'Local / Server'}</div>
              </div>
            </div>
          ) : (
            <div style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>
              Đang tải thông tin thiết bị phần cứng...
            </div>
          )}
        </div>
      </div>
    </>
  );
}
