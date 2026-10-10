import React from 'react';
import { NavLink } from 'react-router-dom';
import {
  FiGrid,
  FiCamera,
  FiUsers,
  FiActivity,
  FiBell,
  FiCpu,
  FiSettings,
} from 'react-icons/fi';
import { useApp } from '../context/AppContext';

const NAV_ITEMS = [
  { to: '/', end: true, label: 'Dashboard', icon: FiGrid, id: 'navItemDashboard' },
  { to: '/cameras', label: 'Quản lý Camera', icon: FiCamera, id: 'navItemCameras' },
  { to: '/watchlist', label: 'Watchlist', icon: FiUsers, id: 'navItemWatchlist' },
  { to: '/events', label: 'Event Center', icon: FiActivity, id: 'navItemEvents' },
  { to: '/alerts', label: 'Alert Center', icon: FiBell, id: 'navItemAlerts' },
  { to: '/agent', label: 'AI Assistant', icon: FiCpu, id: 'navItemAgent' },
  { to: '/settings', label: 'Cài đặt', icon: FiSettings, id: 'navItemSettings' },
];

const ACCENTS = [
  ['blue', '#4f6df5'],
  ['green', '#41bf7a'],
  ['purple', '#8b5cf6'],
  ['amber', '#f59e0b'],
  ['rose', '#ef476f'],
];

export function Sidebar() {
  const { accentColor, setAccentColor } = useApp();

  return (
    <aside className="app-sidebar classic-sidebar" id="appSidebar">
      <div className="sidebar-header classic-sidebar-header">
        <div className="brand-badge">D</div>
        <div className="brand-info">
          <span className="brand-title">DATT AI</span>
          <span className="brand-subtitle">VISION MONITOR</span>
        </div>
      </div>

      <nav className="sidebar-nav classic-sidebar-nav" aria-label="Điều hướng chính">
        {NAV_ITEMS.map(({ to, end, label, icon: Icon, id }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}
            id={id}
          >
            <Icon size={16} aria-hidden="true" />
            <span>{label}</span>
          </NavLink>
        ))}
      </nav>

      <div className="classic-accent-footer">
        <span>Theme Accent</span>
        <div className="classic-accent-options" aria-label="Màu giao diện">
          {ACCENTS.map(([name, color]) => (
            <button
              key={name}
              type="button"
              className={`classic-accent-dot ${accentColor === name ? 'active' : ''}`}
              style={{ backgroundColor: color }}
              onClick={() => setAccentColor(name)}
              aria-label={`Chọn màu ${name}`}
              title={`Theme accent: ${name}`}
            />
          ))}
        </div>
      </div>
    </aside>
  );
}
