import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
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

export default function App() {
  return (
    <BrowserRouter>
      <ToastProvider>
        <AppProvider>
          <NotificationToastWatcher />
          <div className="app-layout">
            <Sidebar />
            <main className="main-content">
              <AuthenticationNotice />
              <AppRoutes />
            </main>
            <ToastContainer />
          </div>
        </AppProvider>
      </ToastProvider>
    </BrowserRouter>
  );
}

function AppRoutes() {
  const { connectionRevision } = useApp();
  return (
              <Routes key={connectionRevision}>
                <Route path="/" element={<DashboardPage />} />
                <Route path="/dashboard" element={<DashboardPage />} />
                <Route path="/cameras" element={<CameraManagementPage />} />
                <Route path="/cameras/:id" element={<CameraViewPage />} />
                <Route path="/watchlist" element={<WatchlistPage />} />
                <Route path="/events" element={<EventCenterPage />} />
                <Route path="/alerts" element={<AlertCenterPage />} />
                <Route path="/settings" element={<SettingsPage />} />
                <Route path="/agent" element={<AgentPage />} />
                {/* Fallback to dashboard */}
                <Route path="*" element={<Navigate to="/" replace />} />
              </Routes>
  );
}
