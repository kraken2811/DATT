import React, { useState, useEffect, useCallback } from 'react';
import { Header } from '../components/Header';
import { fetchAlerts, fetchAlertDetail } from '../api/alerts';
import { LoadingSpinner, EmptyState, ErrorState } from '../components/StatusStates';
import {
  Bell,
  Search,
  Eye,
  Mail,
  ChevronLeft,
  ChevronRight,
  X,
  CheckCircle,
  AlertTriangle,
  Clock,
  ExternalLink,
} from 'lucide-react';

export function AlertCenterPage() {
  const [alerts, setAlerts] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Filters
  const [searchTerm, setSearchTerm] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [typeFilter, setTypeFilter] = useState('all');

  // Detail Modal
  const [selectedAlertId, setSelectedAlertId] = useState(null);
  const [alertDetail, setAlertDetail] = useState(null);
  const [loadingDetail, setLoadingDetail] = useState(false);

  // Debounce search
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearch(searchTerm);
      setPage(1);
    }, 350);
    return () => clearTimeout(timer);
  }, [searchTerm]);

  const loadAlerts = useCallback(async (signal) => {
    setLoading(true);
    setError(null);
    try {
      const resp = await fetchAlerts(
        {
          page,
          page_size: pageSize,
          search: debouncedSearch,
          status: statusFilter,
          event_type: typeFilter,
        },
        signal
      );
      if (resp && resp.status === 'ok') {
        setAlerts(resp.alerts || []);
        setTotal(resp.total || 0);
      } else {
        throw new Error(resp?.detail || 'Không thể tải danh sách cảnh báo');
      }
    } catch (err) {
      if (err.name !== 'AbortError') {
        setError(err.message || 'Lỗi kết nối máy chủ');
      }
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, debouncedSearch, statusFilter, typeFilter]);

  useEffect(() => {
    const abortCtrl = new AbortController();
    loadAlerts(abortCtrl.signal);
    return () => abortCtrl.abort();
  }, [loadAlerts]);

  const handleOpenDetail = async (alertId) => {
    setSelectedAlertId(alertId);
    setAlertDetail(null);
    setLoadingDetail(true);
    try {
      const resp = await fetchAlertDetail(alertId);
      if (resp && resp.status === 'ok') {
        setAlertDetail(resp.alert);
      }
    } catch (err) {
      console.error('Failed to load alert detail:', err);
    } finally {
      setLoadingDetail(false);
    }
  };

  const totalPages = Math.ceil(total / pageSize) || 1;

  const getAlertCenterStatus = () => {
    if (error) {
      const errStr = String(error).toLowerCase();
      if (errStr.includes('401') || errStr.includes('xác thực') || errStr.includes('unauthorized')) {
        return { className: 'disconnected', label: 'CẦN XÁC THỰC' };
      }
      if (errStr.includes('403') || errStr.includes('forbidden') || errStr.includes('quyền')) {
        return { className: 'disconnected', label: 'CHƯA CÓ QUYỀN' };
      }
      if (errStr.includes('500') || errStr.includes('503') || errStr.includes('database')) {
        return { className: 'disconnected', label: 'LỖI MÁY CHỦ' };
      }
      if (errStr.includes('network') || errStr.includes('failed to fetch')) {
        return { className: 'disconnected', label: 'MẤT KẾT NỐI' };
      }
      return { className: 'disconnected', label: 'KHÔNG THỂ TRUY XUẤT' };
    }
    if (loading) {
      return { className: 'connecting', label: 'ĐANG TẢI...' };
    }
    return { className: 'live', label: 'ĐÃ KẾT NỐI' };
  };

  return (
    <>
      <Header
        title="Trung tâm Cảnh báo (Alert Center)"
        status={getAlertCenterStatus()}
      />

      <div className="page-container" id="alertCenterPage">
        {/* Filter Bar */}
        <div className="card" style={{ marginBottom: '20px' }}>
          <div className="filter-bar" style={{ margin: 0 }}>
            <div className="search-input-wrapper">
              <Search size={16} className="search-input-icon" />
              <input
                type="text"
                className="input-field with-icon"
                placeholder="Tìm kiếm cảnh báo (email, đối tượng, biển số, camera...)"
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                id="alertSearchInput"
              />
            </div>

            <select
              className="select-field"
              value={statusFilter}
              onChange={(e) => {
                setStatusFilter(e.target.value);
                setPage(1);
              }}
              id="alertStatusSelect"
            >
              <option value="all">Tất cả trạng thái</option>
              <option value="sent">Đã gửi (Sent)</option>
              <option value="pending">Đang chờ (Pending)</option>
              <option value="failed">Thất bại (Failed)</option>
              <option value="suppressed">Bị chặn / Trùng (Suppressed)</option>
            </select>

            <select
              className="select-field"
              value={typeFilter}
              onChange={(e) => {
                setTypeFilter(e.target.value);
                setPage(1);
              }}
              id="alertTypeSelect"
            >
              <option value="all">Tất cả loại cảnh báo</option>
              <option value="FACE_WATCHLIST_MATCH">Khuôn mặt Watchlist</option>
              <option value="VEHICLE_WATCHLIST_MATCH">Biển số Watchlist</option>
            </select>

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
            </select>
          </div>
        </div>

        {/* Alerts Table */}
        {loading ? (
          <div className="card">
            <LoadingSpinner text="Đang tải danh sách cảnh báo..." />
          </div>
        ) : error ? (
          <ErrorState message={error} onRetry={() => loadAlerts()} />
        ) : alerts.length === 0 ? (
          <div className="card">
            <EmptyState
              icon={Bell}
              title="Không có thông báo cảnh báo nào"
              message="Chưa có thông báo gửi email nào khớp với bộ lọc hiện tại."
            />
          </div>
        ) : (
          <div className="table-container">
            <table className="data-table" id="alertCenterTable">
              <thead>
                <tr>
                  <th>Thời gian tạo</th>
                  <th>Loại cảnh báo</th>
                  <th>Đối tượng</th>
                  <th>Camera</th>
                  <th>Kênh / Người nhận</th>
                  <th>Trạng thái</th>
                  <th style={{ textAlign: 'center' }}>Thao tác</th>
                </tr>
              </thead>
              <tbody>
                {alerts.map((item) => {
                  let statusBg = 'var(--bg-hover)';
                  let statusColor = 'var(--text-muted)';
                  if (item.status === 'SENT') {
                    statusBg = 'rgba(16, 185, 129, 0.15)';
                    statusColor = '#10b981';
                  } else if (item.status === 'FAILED') {
                    statusBg = 'rgba(239, 68, 68, 0.15)';
                    statusColor = '#ef4444';
                  } else if (item.status === 'PENDING') {
                    statusBg = 'rgba(245, 158, 11, 0.15)';
                    statusColor = '#f59e0b';
                  }

                  return (
                    <tr key={item.id}>
                      <td style={{ fontSize: '0.8rem', whiteSpace: 'nowrap', color: 'var(--text-secondary)' }}>
                        {item.created_at ? new Date(item.created_at).toLocaleString() : 'N/A'}
                      </td>
                      <td>
                        <span className="tag-badge" style={{ background: 'var(--accent-surface)', color: 'var(--accent)' }}>
                          {item.event_type}
                        </span>
                      </td>
                      <td>
                        <div style={{ fontWeight: 600 }}>{item.target_name || item.plate_number || 'Đối tượng theo dõi'}</div>
                        {item.plate_number && (
                          <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                            Biển số: {item.plate_number}
                          </span>
                        )}
                      </td>
                      <td style={{ fontSize: '0.8rem' }}>{item.camera_name || item.camera_id || 'N/A'}</td>
                      <td>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                          <Mail size={14} style={{ color: 'var(--text-muted)' }} />
                          <span style={{ fontSize: '0.85rem' }}>{item.recipient_email || 'Default Email'}</span>
                        </div>
                      </td>
                      <td>
                        <span className="tag-badge" style={{ background: statusBg, color: statusColor }}>
                          {item.status}
                        </span>
                      </td>
                      <td style={{ textAlign: 'center' }}>
                        <button
                          type="button"
                          className="btn btn-secondary btn-icon btn-sm"
                          onClick={() => handleOpenDetail(item.id)}
                          title="Xem chi tiết cảnh báo"
                          aria-label="Xem chi tiết cảnh báo"
                        >
                          <Eye size={14} />
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>

            {/* Pagination */}
            <div className="pagination-container">
              <div>
                Hiển thị {(page - 1) * pageSize + 1} -{' '}
                {Math.min(page * pageSize, total)} trong tổng số <strong>{total}</strong> thông báo
              </div>
              <div className="pagination-controls">
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  disabled={page <= 1}
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  id="btnPrevAlertPage"
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
                  id="btnNextAlertPage"
                >
                  <span>Sau</span>
                  <ChevronRight size={14} />
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Alert Detail Modal */}
        {selectedAlertId && (
          <div className="modal-overlay" onClick={() => setSelectedAlertId(null)}>
            <div className="modal-card" onClick={(e) => e.stopPropagation()}>
              <div className="modal-header">
                <h3 className="modal-title">Chi tiết Cảnh báo Outbox</h3>
                <button
                  type="button"
                  className="btn btn-secondary btn-icon btn-sm"
                  onClick={() => setSelectedAlertId(null)}
                >
                  <X size={16} />
                </button>
              </div>

              <div className="modal-body">
                {loadingDetail ? (
                  <LoadingSpinner text="Đang tải thông tin chi tiết..." />
                ) : alertDetail ? (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '14px', fontSize: '0.85rem' }}>
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                      <div>
                        <span style={{ color: 'var(--text-muted)' }}>Mã cảnh báo:</span>
                        <div style={{ fontWeight: 600 }}>{alertDetail.id}</div>
                      </div>
                      <div>
                        <span style={{ color: 'var(--text-muted)' }}>Trạng thái:</span>
                        <div style={{ fontWeight: 600 }}>{alertDetail.status}</div>
                      </div>
                      <div>
                        <span style={{ color: 'var(--text-muted)' }}>Loại sự kiện:</span>
                        <div style={{ fontWeight: 600 }}>{alertDetail.event_type}</div>
                      </div>
                      <div>
                        <span style={{ color: 'var(--text-muted)' }}>Đối tượng:</span>
                        <div style={{ fontWeight: 600 }}>{alertDetail.target_name || alertDetail.plate_number || 'N/A'}</div>
                      </div>
                      <div>
                        <span style={{ color: 'var(--text-muted)' }}>Camera:</span>
                        <div style={{ fontWeight: 600 }}>{alertDetail.camera_name || alertDetail.camera_id}</div>
                      </div>
                      <div>
                        <span style={{ color: 'var(--text-muted)' }}>Người nhận:</span>
                        <div style={{ fontWeight: 600 }}>{alertDetail.recipient_email}</div>
                      </div>
                      <div>
                        <span style={{ color: 'var(--text-muted)' }}>Tạo lúc:</span>
                        <div>{new Date(alertDetail.created_at).toLocaleString()}</div>
                      </div>
                      <div>
                        <span style={{ color: 'var(--text-muted)' }}>Gửi lúc:</span>
                        <div>{alertDetail.sent_at ? new Date(alertDetail.sent_at).toLocaleString() : 'Chưa gửi'}</div>
                      </div>
                    </div>

                    {alertDetail.error_message && (
                      <div style={{ padding: '12px', background: 'rgba(239, 68, 68, 0.1)', border: '1px solid rgba(239, 68, 68, 0.2)', borderRadius: 'var(--radius-sm)', color: '#ef4444' }}>
                        Lỗi chuyển phát: {alertDetail.error_message}
                      </div>
                    )}

                    {alertDetail.event_url && (
                      <div style={{ marginTop: '6px' }}>
                        <a href={alertDetail.event_url} className="btn btn-secondary btn-sm">
                          <span>Xem sự kiện gốc tại Event Center</span>
                          <ExternalLink size={12} />
                        </a>
                      </div>
                    )}
                  </div>
                ) : (
                  <div>Không thể tải chi tiết cảnh báo này.</div>
                )}
              </div>

              <div className="modal-footer">
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => setSelectedAlertId(null)}
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
