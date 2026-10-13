import React from 'react';
import { NavLink } from 'react-router-dom';
import { LayoutDashboard, Camera, ShieldAlert, Users, Bell, Settings, Bot, BarChart3, X } from 'lucide-react';
import { useApp } from '../context/AppContext';

export function Sidebar({ isOpen, onClose }) {
  const { accentColor, setAccentColor } = useApp();

  const handleNavClick = () => {
    if (typeof window !== 'undefined' && window.innerWidth < 1024 && onClose) {
      onClose();
    }
  };

  const themes = [
    { id: 'blue', color: '#3b82f6', label: 'Blue' },
    { id: 'emerald', color: '#10b981', label: 'Emerald' },
    { id: 'violet', color: '#8b5cf6', label: 'Violet' },
    { id: 'amber', color: '#f59e0b', label: 'Amber' },
    { id: 'rose', color: '#f43f5e', label: 'Rose' },
  ];

  return (
    <aside className={`app-sidebar ${isOpen ? 'mobile-open' : ''}`} id="appSidebar">
      <div className="sidebar-header">
        <div className="brand-badge">D</div>
        <div className="brand-info">
          <span className="brand-title">DATT AI</span>
          <span className="brand-subtitle">Vision Monitor</span>
        </div>
        {onClose && (
          <button
            type="button"
            className="sidebar-close-btn"
            id="btnCloseMobileSidebar"
            onClick={onClose}
            aria-label="Đóng menu điều hướng"
            title="Đóng menu"
          >
            <X size={18} />
          </button>
        )}
      </div>

      <nav className="sidebar-nav">
        <NavLink
          to="/"
          end
          className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}
          id="navItemDashboard"
          onClick={handleNavClick}
        >
          <LayoutDashboard size={18} />
          <span>Dashboard</span>
        </NavLink>

        <NavLink
          to="/cameras"
          className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}
          id="navItemCameras"
          onClick={handleNavClick}
        >
          <Camera size={18} />
          <span>Quản lý Camera</span>
        </NavLink>

        <NavLink
          to="/watchlist"
          className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}
          id="navItemWatchlist"
          onClick={handleNavClick}
        >
          <Users size={18} />
          <span>Watchlist</span>
        </NavLink>

        <NavLink
          to="/events"
          className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}
          id="navItemEvents"
          onClick={handleNavClick}
        >
          <ShieldAlert size={18} />
          <span>Event Center</span>
        </NavLink>

        <NavLink
          to="/alerts"
          className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}
          id="navItemAlerts"
          onClick={handleNavClick}
        >
          <Bell size={18} />
          <span>Alert Center</span>
        </NavLink>

        <NavLink
          to="/analytics"
          className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}
          id="navItemAnalytics"
          onClick={handleNavClick}
        >
          <BarChart3 size={18} />
          <span>Phân tích & Dự báo</span>
        </NavLink>

        <NavLink
          to="/agent"
          className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}
          id="navItemAgent"
          onClick={handleNavClick}
        >
          <Bot size={18} />
          <span>AI Assistant</span>
        </NavLink>

        <NavLink
          to="/settings"
          className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}
          id="navItemSettings"
          onClick={handleNavClick}
        >
          <Settings size={18} />
          <span>Cài đặt</span>
        </NavLink>
      </nav>

      <div className="sidebar-footer">
        <div className="theme-selector">
          <span>Theme Accent</span>
          <div className="theme-dots">
            {themes.map((t) => (
              <button
                key={t.id}
                type="button"
                className={`theme-dot ${accentColor === t.id ? 'active' : ''}`}
                style={{ backgroundColor: t.color, color: t.color }}
                onClick={() => setAccentColor(t.id)}
                title={t.label}
                aria-label={`Select ${t.label} accent theme`}
              />
            ))}
          </div>
        </div>
      </div>
    </aside>
  );
}
