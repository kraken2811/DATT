import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Header } from '../components/Header';
import { fetchEvents, fetchEventDetail, getEventEvidenceUrl } from '../api/events';
import { LoadingSpinner, EmptyState, ErrorState } from '../components/StatusStates';
import {
  Search,
  Filter,
  Eye,
  Calendar,
  ChevronLeft,
  ChevronRight,
  X,
  ShieldAlert,
  Download,
} from 'lucide-react';

export function EventCenterPage() {
  const [events, setEvents] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Filters
  const [searchTerm, setSearchTerm] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [eventType, setEventType] = useState('all');
  const [matchFilter, setMatchFilter] = useState('all');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');

  // Event Detail Modal
  const [selectedEventId, setSelectedEventId] = useState(null);
  const [eventDetail, setEventDetail] = useState(null);
  const [loadingDetail, setLoadingDetail] = useState(false);

  // Debounce search input (350ms)
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearch(searchTerm);
      setPage(1); // Reset to page 1 on new search
    }, 350);
    return () => clearTimeout(timer);
  }, [searchTerm]);

  const loadEvents = useCallback(async (signal) => {
    setLoading(true);
    setError(null);
    try {
      const resp = await fetchEvents(
        {
          page,
          page_size: pageSize,
          search: debouncedSearch,
          event_type: eventType,
          watchlist_match: matchFilter,
          from: dateFrom ? new Date(dateFrom).toISOString() : '',
          to: dateTo ? new Date(dateTo).toISOString() : '',
        },
        signal
      );

      if (resp && resp.status === 'ok') {
        setEvents(resp.events || []);
        setTotal(resp.total || 0);
      } else {
        throw new Error(resp?.detail || 'Không thể tải danh sách sự kiện');
      }
    } catch (err) {
      if (err.name !== 'AbortError') {
        setError(err.message || 'Lỗi kết nối máy chủ');
      }
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, debouncedSearch, eventType, matchFilter, dateFrom, dateTo]);

  useEffect(() => {
    const abortCtrl = new AbortController();
    loadEvents(abortCtrl.signal);
    return () => abortCtrl.abort();
  }, [loadEvents]);

  // Load event detail
  const handleOpenDetail = async (eventId) => {
    setSelectedEventId(eventId);
    setEventDetail(null);
    setLoadingDetail(true);
    try {
      const resp = await fetchEventDetail(eventId);
      if (resp && resp.status === 'ok') {
        setEventDetail(resp.event);
      }
    } catch (err) {
      console.error('Failed to load event detail:', err);
    } finally {
      setLoadingDetail(false);
    }
  };

  const totalPages = Math.ceil(total / pageSize) || 1;

  return (
    <>
      <Header title="Trung tâm Sự kiện (Event Center)" />

      <div className="page-container" id="eventCenterPage">
        {/* Filter and Search Bar */}
        <div className="card" style={{ marginBottom: '20px' }}>
          <div className="filter-bar" style={{ margin: 0 }}>
            {/* Search Input */}
            <div className="search-input-wrapper">
              <Search size={16} className="search-input-icon" />
              <input
                type="text"
                className="input-field with-icon"
                placeholder="Tìm kiếm sự kiện (biển số, camera, loại đối tượng...)"
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                id="eventSearchInput"
              />
            </div>

            {/* Event Type Filter */}
            <select
              className="select-field"
              value={eventType}
              onChange={(e) => {
                setEventType(e.target.value);
                setPage(1);
              }}
              id="eventTypeSelect"
            >
              <option value="all">Tất cả loại sự kiện</option>
              <option value="face">Khuôn mặt (Face)</option>
              <option value="plate">Biển số xe (Plate)</option>
              <option value="vehicle">Phương tiện (Vehicle)</option>
              <option value="passage">Lượt qua (Passage)</option>
              <option value="business">Sự kiện nghiệp vụ (Business)</option>
            </select>

            {/* Watchlist Match Filter */}
            <select
              className="select-field"
              value={matchFilter}
              onChange={(e) => {
                setMatchFilter(e.target.value);
                setPage(1);
              }}
              id="eventMatchSelect"
            >
              <option value="all">Tất cả đối tượng</option>
              <option value="true">Chỉ đối tượng Watchlist</option>
              <option value="false">Không trong Watchlist</option>
            </select>

            {/* Page Size */}
            <select
              className="select-field"
              value={pageSize}
              onChange={(e) => {
                setPageSize(Number(e.target.value));
                setPage(1);
              }}
            >
              <option value={10}>10 dòng / trang</option>
              <option value={25}>25 dòng / trang</option>
              <option value={50}>50 dòng / trang</option>
              <option value={100}>100 dòng / trang</option>
            </select>
          </div>
        </div>

        {/* Content Area */}
        {loading ? (
          <div className="card">
            <LoadingSpinner text="Đang tải danh sách sự kiện từ cơ sở dữ liệu..." />
          </div>
        ) : error ? (
          <ErrorState message={error} onRetry={() => loadEvents()} />
        ) : events.length === 0 ? (
          <div className="card">
            <EmptyState
              icon={ShieldAlert}
              title="Không tìm thấy sự kiện nào"
              message="Thử thay đổi từ khóa tìm kiếm hoặc làm mới bộ lọc."
            />
          </div>
        ) : (
          <div className="table-container">
            <table className="data-table" id="eventCenterTable">
              <thead>
                <tr>
                  <th>Thời gian</th>
                  <th>Hình ảnh</th>
                  <th>Loại sự kiện</th>
                  <th>Camera</th>
                  <th>Chi tiết nhận diện</th>
                  <th>Watchlist</th>
                  <th>Thông báo</th>
                  <th style={{ textAlign: 'center' }}>Thao tác</th>
                </tr>
              </thead>
              <tbody>
                {events.map((evt) => {
                  const hasEvidence = !!evt.evidence?.url;
                  const isMatch = evt.watchlist_match;

                  return (
                    <tr key={evt.event_id}>
                      <td style={{ whiteSpace: 'nowrap', fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                        {evt.timestamp ? new Date(evt.timestamp).toLocaleString() : 'N/A'}
                      </td>
                      <td>
                        {hasEvidence ? (
                          <img
                            src={evt.evidence.url}
                            alt="Snapshot"
                            style={{
                              width: '42px',
                              height: '42px',
                              objectFit: 'cover',
                              borderRadius: 'var(--radius-sm)',
                              border: '1px solid var(--border-subtle)',
                              cursor: 'pointer',
                            }}
                            onClick={() => handleOpenDetail(evt.event_id)}
                            onError={(e) => {
                              e.currentTarget.style.display = 'none';
                            }}
                          />
                        ) : (
                          <div
                            style={{
                              width: '42px',
                              height: '42px',
                              background: 'var(--bg-hover)',
                              borderRadius: 'var(--radius-sm)',
                              display: 'flex',
                              alignItems: 'center',
                              justifyContent: 'center',
                              fontSize: '0.65rem',
                              color: 'var(--text-muted)',
                            }}
                          >
                            N/A
                          </div>
                        )}
                      </td>
                      <td>
                        <span
                          className="tag-badge"
                          style={{
                            background:
                              evt.event_type === 'face'
                                ? 'rgba(59, 130, 246, 0.15)'
                                : evt.event_type === 'plate'
                                ? 'rgba(16, 185, 129, 0.15)'
                                : 'var(--bg-hover)',
                            color:
                              evt.event_type === 'face'
                                ? '#3b82f6'
                                : evt.event_type === 'plate'
                                ? '#10b981'
                                : 'var(--text-muted)',
                          }}
                        >
                          {evt.semantic_type || evt.event_type}
                        </span>
                      </td>
                      <td style={{ fontSize: '0.8rem' }}>{evt.camera_id || 'N/A'}</td>
                      <td>
                        {evt.plate ? (
                          <div style={{ fontWeight: 600 }}>Biển số: {evt.plate}</div>
                        ) : evt.target_id ? (
                          <div>Target: {evt.target_id.slice(0, 8)}...</div>
                        ) : (
                          <div style={{ color: 'var(--text-secondary)' }}>{evt.object_type || 'Đối tượng'}</div>
                        )}
                        {typeof evt.confidence === 'number' && (
                          <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                            Độ tin cậy: {(evt.confidence * 100).toFixed(0)}%
                          </div>
                        )}
                      </td>
                      <td>
                        {isMatch ? (
                          <span className="tag-badge" style={{ background: 'rgba(239, 68, 68, 0.15)', color: '#ef4444' }}>
                            TRÙNG KHỚP
                          </span>
                        ) : (
                          <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Không</span>
                        )}
                      </td>
                      <td>
                        <span
                          className="tag-badge"
                          style={{
                            background:
                              evt.notification_status === 'sent'
                                ? 'rgba(16, 185, 129, 0.15)'
                                : evt.notification_status === 'failed'
                                ? 'rgba(239, 68, 68, 0.15)'
                                : 'var(--bg-hover)',
                            color:
                              evt.notification_status === 'sent'
                                ? '#10b981'
                                : evt.notification_status === 'failed'
                                ? '#ef4444'
                                : 'var(--text-muted)',
                          }}
                        >
                          {evt.notification_status || 'none'}
                        </span>
                      </td>
                      <td style={{ textAlign: 'center' }}>
                        <button
                          type="button"
                          className="btn btn-secondary btn-icon btn-sm"
                          onClick={() => handleOpenDetail(evt.event_id)}
                          title="Xem chi tiết sự kiện"
                          aria-label="Xem chi tiết sự kiện"
                        >
                          <Eye size={14} />
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>

            {/* Server-Side Pagination Bar */}
            <div className="pagination-container">
              <div>
                Hiển thị {events.length > 0 ? (page - 1) * pageSize + 1 : 0} -{' '}
                {Math.min(page * pageSize, total)} trong tổng số <strong>{total}</strong> sự kiện
              </div>
              <div className="pagination-controls">
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  disabled={page <= 1}
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  id="btnPrevPage"
                >
                  <ChevronLeft size={14} />
                  <span>Trước</span>
                </button>
                <div style={{ display: 'flex', alignItems: 'center', padding: '0 8px', fontSize: '0.85rem' }}>
                  Trang {page} / {totalPages}
                </div>
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  disabled={page >= totalPages}
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  id="btnNextPage"
                >
                  <span>Sau</span>
                  <ChevronRight size={14} />
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Event Detail Modal */}
        {selectedEventId && (
          <div className="modal-overlay" onClick={() => setSelectedEventId(null)}>
            <div className="modal-card" onClick={(e) => e.stopPropagation()} style={{ maxWidth: '640px' }}>
              <div className="modal-header">
                <h3 className="modal-title">Chi tiết Sự kiện: {selectedEventId}</h3>
                <button
                  type="button"
                  className="btn btn-secondary btn-icon btn-sm"
                  onClick={() => setSelectedEventId(null)}
                >
                  <X size={16} />
                </button>
              </div>

              <div className="modal-body">
                {loadingDetail ? (
                  <LoadingSpinner text="Đang tải chi tiết bằng chứng..." />
                ) : eventDetail ? (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                    {eventDetail.evidence?.url && (
                      <div style={{ textAlign: 'center', background: '#000', borderRadius: 'var(--radius-md)', padding: '12px' }}>
                        <img
                          src={eventDetail.evidence.url}
                          alt="Bằng chứng nhận diện"
                          style={{ maxHeight: '280px', maxWidth: '100%', objectFit: 'contain', borderRadius: 'var(--radius-sm)' }}
                        />
                      </div>
                    )}

                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px', fontSize: '0.85rem' }}>
                      <div>
                        <span style={{ color: 'var(--text-muted)' }}>Thời gian:</span>
                        <div style={{ fontWeight: 600 }}>{new Date(eventDetail.timestamp).toLocaleString()}</div>
                      </div>
                      <div>
                        <span style={{ color: 'var(--text-muted)' }}>Loại sự kiện:</span>
                        <div style={{ fontWeight: 600 }}>{eventDetail.semantic_type || eventDetail.event_type}</div>
                      </div>
                      <div>
                        <span style={{ color: 'var(--text-muted)' }}>Mã Camera:</span>
                        <div style={{ fontWeight: 600 }}>{eventDetail.camera_id || 'N/A'}</div>
                      </div>
                      <div>
                        <span style={{ color: 'var(--text-muted)' }}>Khớp Watchlist:</span>
                        <div style={{ fontWeight: 600, color: eventDetail.watchlist_match ? '#ef4444' : '#10b981' }}>
                          {eventDetail.watchlist_match ? 'CÓ (TRÙNG KHỚP)' : 'KHÔNG'}
                        </div>
                      </div>
                      {eventDetail.plate && (
                        <div>
                          <span style={{ color: 'var(--text-muted)' }}>Biển số xe:</span>
                          <div style={{ fontWeight: 600, fontSize: '1rem', color: 'var(--accent)' }}>
                            {eventDetail.plate}
                          </div>
                        </div>
                      )}
                      {typeof eventDetail.confidence === 'number' && (
                        <div>
                          <span style={{ color: 'var(--text-muted)' }}>Độ tương đồng / tin cậy:</span>
                          <div style={{ fontWeight: 600 }}>{(eventDetail.confidence * 100).toFixed(1)}%</div>
                        </div>
                      )}
                    </div>
                  </div>
                ) : (
                  <div>Không thể tải chi tiết sự kiện này.</div>
                )}
              </div>

              <div className="modal-footer">
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => setSelectedEventId(null)}
                >
                  Đóng
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </>
  );
}
