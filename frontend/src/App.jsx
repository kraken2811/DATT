import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { Menu } from 'lucide-react';
import { ToastProvider } from './context/ToastContext';
import { AppProvider, useApp } from './context/AppContext';
import { AuthenticationNotice } from './components/AuthenticationNotice';
import { Sidebar } from './components/Sidebar';
import { ToastContainer } from './components/ToastContainer';
import { NotificationToastWatcher } from './components/NotificationToastWatcher';

// Pages
import { DashboardPage } from './pages/DashboardPage';
import { CameraManagementPage } from './pages/CameraManagementPage';
import { CameraViewPage } from './pages/CameraViewPage';
import { WatchlistPage } from './pages/WatchlistPage';
import { EventCenterPage } from './pages/EventCenterPage';
import { AlertCenterPage } from './pages/AlertCenterPage';
import { SettingsPage } from './pages/SettingsPage';
import { AgentPage } from './pages/AgentPage';
import { AnalyticsPage } from './pages/AnalyticsPage';

export default function App() {
  return (
    <BrowserRouter>
      <ToastProvider>
        <AppProvider>
          <NotificationToastWatcher />
          <AppShell />
        </AppProvider>
      </ToastProvider>
    </BrowserRouter>
  );
}

function AppShell() {
  const { sidebarOpen, closeSidebar, toggleSidebar } = useApp();

  return (
    <div className="app-layout">
      {/* Mobile Top Navigation Header (< 1024px) */}
      <header className="mobile-top-bar" id="mobileTopBar">
        <button
          type="button"
          className="btn-hamburger"
          id="btnToggleMobileSidebar"
          onClick={toggleSidebar}
          aria-label="Mở menu điều hướng"
          title="Menu"
        >
          <Menu size={22} />
        </button>
        <div className="mobile-brand">
          <div className="brand-badge small">D</div>
          <span className="brand-title">DATT AI Vision</span>
        </div>
      </header>

      {/* Mobile Backdrop Overlay */}
      {sidebarOpen && (
        <div
          className="sidebar-backdrop active"
          id="sidebarBackdrop"
          onClick={closeSidebar}
          aria-hidden="true"
        />
      )}

      <Sidebar isOpen={sidebarOpen} onClose={closeSidebar} />
      <main className="main-content" id="mainContent">
        <AuthenticationNotice />
        <AppRoutes />
      </main>
      <ToastContainer />
    </div>
  );
}

function AppRoutes() {
  const { connectionRevision } = useApp();
  return (
              <Routes key={connectionRevision}>
                <Route path="/" element={<DashboardPage />} />
                <Route path="/dashboard" element={<DashboardPage />} />
                <Route path="/monitor" element={<CameraViewPage />} />
                <Route path="/cameras" element={<CameraManagementPage />} />
                <Route path="/cameras/:id" element={<CameraViewPage />} />
                <Route path="/watchlist" element={<WatchlistPage />} />
                <Route path="/events" element={<EventCenterPage />} />
                <Route path="/alerts" element={<AlertCenterPage />} />
                <Route path="/analytics" element={<AnalyticsPage />} />
                <Route path="/settings" element={<SettingsPage />} />
                <Route path="/agent" element={<AgentPage />} />
                {/* Fallback to dashboard */}
                <Route path="*" element={<Navigate to="/" replace />} />
              </Routes>
  );
}
