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

const NAV_ITEMS = [
  { to: '/', end: true, label: 'Dashboard', icon: FiGrid, id: 'navItemDashboard' },
  { to: '/cameras', label: 'Camera', icon: FiCamera, id: 'navItemCameras' },
  { to: '/watchlist', label: 'Watchlist', icon: FiUsers, id: 'navItemWatchlist' },
  { to: '/events', label: 'Event Center', icon: FiActivity, id: 'navItemEvents' },
  { to: '/alerts', label: 'Alert Center', icon: FiBell, id: 'navItemAlerts' },
  { to: '/agent', label: 'AI Assistant', icon: FiCpu, id: 'navItemAgent' },
];

export function Sidebar() {
  return (
    <aside className="app-sidebar monitoring-sidebar" id="appSidebar">
      <div className="sidebar-header">
        <div className="brand-badge">D</div>
        <div className="brand-info">
          <span className="brand-title">DATT AI</span>
          <span className="brand-subtitle">Vision Monitor</span>
        </div>
      </div>

      <nav className="sidebar-nav" aria-label="Điều hướng chính">
        {NAV_ITEMS.map(({ to, end, label, icon: Icon, id }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}
            id={id}
          >
            <Icon size={17} aria-hidden="true" />
            <span>{label}</span>
          </NavLink>
        ))}
      </nav>

      <div className="sidebar-footer monitoring-sidebar-footer">
        <NavLink
          to="/settings"
          className={({ isActive }) => `sidebar-settings-button ${isActive ? 'active' : ''}`}
          id="navItemSettings"
          aria-label="Cài đặt"
          title="Cài đặt"
        >
          <FiSettings size={18} aria-hidden="true" />
        </NavLink>
      </div>
    </aside>
  );
}
