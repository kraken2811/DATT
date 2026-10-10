import React, { useCallback, useEffect, useState } from 'react';
import {
  FiActivity,
  FiChevronLeft,
  FiChevronRight,
  FiEye,
  FiSearch,
  FiX,
} from 'react-icons/fi';
import { fetchEventDetail, fetchEvents, getEventEvidenceUrl } from '../api/events';
import { AuthenticatedImage } from '../components/AuthenticatedImage';
import { EmptyState, ErrorState, LoadingSpinner } from '../components/StatusStates';
import { useToast } from '../context/ToastContext';

const EMPTY = '—';

function formatTime(value) {
  if (!value) return EMPTY;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function eventType(event) {
  return event.event_type || event.type || event.semantic_type || EMPTY;
}

function eventStatus(event) {
  return event.status || event.notification_status || (event.watchlist_match ? 'watchlist match' : 'recorded');
}

function DetailRow({ label, value }) {
  if (value === undefined || value === null || value === '') return null;
  return <div className="detail-row"><span>{label}</span><strong>{String(value)}</strong></div>;
}

export function EventCenterPage() {
  const { showToast } = useToast();
  const [events, setEvents] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [search, setSearch] = useState('');
  const [query, setQuery] = useState('');
  const [eventTypeFilter, setEventTypeFilter] = useState('all');
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
      const response = await fetchEvents({
        page,
        page_size: pageSize,
        search: query,
        event_type: eventTypeFilter,
      }, signal);
      if (response?.status !== 'ok') throw new Error(response?.detail || 'Không tải được Event Center');
      setEvents(response.events || []);
      setTotal(response.total || 0);
    } catch (err) {
      if (err.name !== 'AbortError') setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, query, eventTypeFilter]);

  useEffect(() => {
    const controller = new AbortController();
    load(controller.signal);
    return () => controller.abort();
  }, [load]);

  const openDetail = async (id) => {
    setDetailLoading(true);
    setDetail({ event_id: id });
    try {
      const response = await fetchEventDetail(id);
      if (response?.status === 'ok') setDetail(response.event);
      else throw new Error(response?.detail || 'Không tải được chi tiết sự kiện');
    } catch (err) {
      showToast(err.message, 'error');
      setDetail(null);
    } finally {
      setDetailLoading(false);
    }
  };

  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  return (
    <div className="monitor-page" id="eventCenterPage">
      <header className="monitor-page-header">
        <div><h1>Event Center</h1><p>Tra cứu sự kiện từ backend DATT.</p></div>
      </header>

      <div className="monitor-card compact-filter-card">
        <div className="monitor-filter-row">
          <label className="monitor-search">
            <FiSearch size={15} />
            <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Tìm biển số, camera, đối tượng…" />
          </label>
          <select className="monitor-select" value={eventTypeFilter} onChange={(e) => { setEventTypeFilter(e.target.value); setPage(1); }}>
            <option value="all">Tất cả loại sự kiện</option>
            <option value="face">Face</option>
            <option value="plate">Plate</option>
            <option value="vehicle">Vehicle</option>
            <option value="passage">Passage</option>
            <option value="business">Business</option>
          </select>
          <select className="monitor-select" value={pageSize} onChange={(e) => { setPageSize(Number(e.target.value)); setPage(1); }}>
            <option value={10}>10 / trang</option>
            <option value={25}>25 / trang</option>
            <option value={50}>50 / trang</option>
          </select>
        </div>
      </div>

      {loading ? (
        <div className="monitor-card"><LoadingSpinner text="Đang tải sự kiện…" /></div>
      ) : error ? (
        <ErrorState message={error} onRetry={() => load()} />
      ) : events.length === 0 ? (
        <div className="monitor-card"><EmptyState icon={FiActivity} title="Không có sự kiện" message="Không có bản ghi phù hợp với bộ lọc hiện tại." /></div>
      ) : (
        <div className="monitor-card monitor-table-card">
          <div className="monitor-table-wrap">
            <table className="monitor-table event-main-table">
              <thead>
                <tr>
                  <th>Thời gian</th>
                  <th>Hình ảnh</th>
                  <th>Loại sự kiện</th>
                  <th>Camera</th>
                  <th>Trạng thái</th>
                  <th aria-label="Thao tác" />
                </tr>
              </thead>
              <tbody>
                {events.map((event) => (
                  <tr key={event.event_id}>
                    <td>{formatTime(event.timestamp || event.created_at)}</td>
                    <td>
                      <AuthenticatedImage
                        src={event.evidence?.url || getEventEvidenceUrl(event.event_id)}
                        alt=""
                        className="event-thumb"
                        fallback={<div className="event-thumb-fallback"><FiActivity size={16} /></div>}
                      />
                    </td>
                    <td><span className="monitor-badge neutral">{eventType(event)}</span></td>
                    <td>{event.camera_name || event.camera_id || EMPTY}</td>
                    <td><span className={`monitor-badge ${event.watchlist_match ? 'warning' : 'neutral'}`}>{eventStatus(event)}</span></td>
                    <td className="cell-action">
                      <button type="button" className="icon-action" onClick={() => openDetail(event.event_id)} title="Xem chi tiết">
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
          <div className="monitor-modal event-detail-modal" role="dialog" aria-modal="true">
            <div className="monitor-modal-header">
              <div><h2>Event Detail</h2><span>{detail.event_id}</span></div>
              <button type="button" className="icon-action" onClick={() => setDetail(null)}><FiX /></button>
            </div>
            {detailLoading ? <LoadingSpinner text="Đang tải chi tiết…" /> : (
              <div className="event-detail-grid">
                <div className="event-evidence-panel">
                  <AuthenticatedImage
                    src={detail.evidence?.url || getEventEvidenceUrl(detail.event_id)}
                    alt="Evidence"
                    className="event-evidence-image"
                    fallback={<div className="event-evidence-fallback"><FiActivity size={26} /><span>Evidence unavailable</span></div>}
                  />
                </div>
                <div className="detail-list">
                  <DetailRow label="Loại sự kiện" value={eventType(detail)} />
                  <DetailRow label="Camera" value={detail.camera_name || detail.camera_id} />
                  <DetailRow label="Thời gian" value={formatTime(detail.timestamp || detail.created_at)} />
                  <DetailRow label="Biển số" value={detail.plate || detail.plate_number || detail.plate_text} />
                  <DetailRow label="Loại xe" value={detail.vehicle_type} />
                  <DetailRow label="Màu xe" value={detail.vehicle_color} />
                  <DetailRow label="Watchlist match" value={detail.watchlist_match} />
                  <DetailRow label="Target" value={detail.target_name || detail.target_id} />
                  <DetailRow label="Confidence" value={detail.confidence} />
                  <DetailRow label="Notification" value={detail.notification_status} />
                  {detail.metadata ? <DetailRow label="Metadata" value={JSON.stringify(detail.metadata)} /> : null}
                </div>
              </div>
            )}
          </div>
        </div>
      ) : null}
    </div>
  );
}
