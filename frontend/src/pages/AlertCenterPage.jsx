import React, { useCallback, useEffect, useState } from 'react';
import {
  FiBell,
  FiChevronLeft,
  FiChevronRight,
  FiEye,
  FiMail,
  FiSearch,
  FiX,
} from 'react-icons/fi';
import { fetchAlertDetail, fetchAlerts } from '../api/alerts';
import { EmptyState, ErrorState, LoadingSpinner } from '../components/StatusStates';
import { useToast } from '../context/ToastContext';

const EMPTY = '—';

function formatTime(value) {
  if (!value) return EMPTY;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function DetailRow({ label, value }) {
  if (value === undefined || value === null || value === '') return null;
  return <div className="detail-row"><span>{label}</span><strong>{String(value)}</strong></div>;
}

export function AlertCenterPage() {
  const { showToast } = useToast();
  const [alerts, setAlerts] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize] = useState(25);
  const [search, setSearch] = useState('');
  const [query, setQuery] = useState('');
  const [status, setStatus] = useState('all');
  const [eventType, setEventType] = useState('all');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [detail, setDetail] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);

  useEffect(() => {
    const timer = setTimeout(() => {
      setQuery(search.trim());
      setPage(1);
    }, 300);
    return () => clearTimeout(timer);
  }, [search]);

  const load = useCallback(async (signal) => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetchAlerts({
        page,
        page_size: pageSize,
        search: query,
        status,
        event_type: eventType,
      }, signal);
      if (response?.status !== 'ok') throw new Error(response?.detail || 'Không tải được Alert Center');
      setAlerts(response.alerts || []);
      setTotal(response.total || 0);
    } catch (err) {
      if (err.name !== 'AbortError') setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, query, status, eventType]);

  useEffect(() => {
    const controller = new AbortController();
    load(controller.signal);
    return () => controller.abort();
  }, [load]);

  const openDetail = async (id) => {
    setDetailLoading(true);
    setDetail({ id });
    try {
      const response = await fetchAlertDetail(id);
      if (response?.status === 'ok') setDetail(response.alert);
      else throw new Error(response?.detail || 'Không tải được chi tiết cảnh báo');
    } catch (err) {
      showToast(err.message, 'error');
      setDetail(null);
    } finally {
      setDetailLoading(false);
    }
  };

  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  return (
    <div className="monitor-page" id="alertCenterPage">
      <header className="monitor-page-header">
        <div><h1>Alert Center</h1><p>Trạng thái cảnh báo và notification do backend cung cấp.</p></div>
      </header>

      <div className="monitor-card compact-filter-card">
        <div className="monitor-filter-row">
          <label className="monitor-search">
            <FiSearch size={15} />
            <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Tìm cảnh báo, camera, biển số…" />
          </label>
          <select className="monitor-select" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}>
            <option value="all">Tất cả trạng thái</option>
            <option value="sent">Sent</option>
            <option value="pending">Pending</option>
            <option value="failed">Failed</option>
            <option value="suppressed">Suppressed</option>
          </select>
          <select className="monitor-select" value={eventType} onChange={(e) => { setEventType(e.target.value); setPage(1); }}>
            <option value="all">Tất cả loại</option>
            <option value="FACE_WATCHLIST_MATCH">Face watchlist</option>
            <option value="VEHICLE_WATCHLIST_MATCH">Vehicle watchlist</option>
          </select>
        </div>
      </div>

      {loading ? (
        <div className="monitor-card"><LoadingSpinner text="Đang tải cảnh báo…" /></div>
      ) : error ? (
        <ErrorState message={error} onRetry={() => load()} />
      ) : alerts.length === 0 ? (
        <div className="monitor-card"><EmptyState icon={FiBell} title="Không có cảnh báo" message="Không có bản ghi phù hợp với bộ lọc hiện tại." /></div>
      ) : (
        <div className="monitor-card monitor-table-card">
          <div className="monitor-table-wrap">
            <table className="monitor-table">
              <thead>
                <tr>
                  <th>Thời gian</th>
                  <th>Loại</th>
                  <th>Camera / Event</th>
                  <th>Notification</th>
                  <th>Retry / Send</th>
                  <th>Status</th>
                  <th aria-label="Thao tác" />
                </tr>
              </thead>
              <tbody>
                {alerts.map((alert) => (
                  <tr key={alert.id}>
                    <td>{formatTime(alert.created_at || alert.timestamp)}</td>
                    <td><span className="monitor-badge neutral">{alert.event_type || EMPTY}</span></td>
                    <td>
                      <strong>{alert.camera_name || alert.camera_id || EMPTY}</strong>
                      <span className="subtle-row-text">{alert.event_id || EMPTY}</span>
                    </td>
                    <td>
                      <span className="notification-cell"><FiMail size={14} />{alert.notification_status || alert.delivery_status || alert.status || EMPTY}</span>
                    </td>
                    <td>{alert.retry_count ?? alert.send_attempts ?? EMPTY}</td>
                    <td><span className={`monitor-badge ${String(alert.status || '').toLowerCase()}`}>{alert.status || EMPTY}</span></td>
                    <td className="cell-action">
                      <button type="button" className="icon-action" onClick={() => openDetail(alert.id)} title="Xem chi tiết">
                        <FiEye size={15} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="monitor-pagination">
            <span>{total} bản ghi</span>
            <div>
              <button type="button" className="icon-action" disabled={page <= 1} onClick={() => setPage((value) => value - 1)}><FiChevronLeft /></button>
              <span>{page} / {totalPages}</span>
              <button type="button" className="icon-action" disabled={page >= totalPages} onClick={() => setPage((value) => value + 1)}><FiChevronRight /></button>
            </div>
          </div>
        </div>
      )}

      {detail ? (
        <div className="monitor-modal-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) setDetail(null); }}>
          <div className="monitor-modal" role="dialog" aria-modal="true">
            <div className="monitor-modal-header">
              <div><h2>Alert Detail</h2><span>{detail.id}</span></div>
              <button type="button" className="icon-action" onClick={() => setDetail(null)}><FiX /></button>
            </div>
            {detailLoading ? <LoadingSpinner text="Đang tải chi tiết…" /> : (
              <div className="detail-list">
                <DetailRow label="Event relation" value={detail.event_id} />
                <DetailRow label="Event type" value={detail.event_type} />
                <DetailRow label="Camera" value={detail.camera_name || detail.camera_id} />
                <DetailRow label="Target" value={detail.target_name || detail.target_id || detail.plate_number} />
                <DetailRow label="Status" value={detail.status} />
                <DetailRow label="Notification status" value={detail.notification_status || detail.delivery_status} />
                <DetailRow label="Recipient" value={detail.recipient_email || detail.recipient_masked} />
                <DetailRow label="Retry count" value={detail.retry_count} />
                <DetailRow label="Last error" value={detail.last_error} />
                <DetailRow label="Created" value={formatTime(detail.created_at)} />
                <DetailRow label="Updated" value={formatTime(detail.updated_at)} />
              </div>
            )}
          </div>
        </div>
      ) : null}
    </div>
  );
}
