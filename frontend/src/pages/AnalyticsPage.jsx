import React, { useState, useEffect, useCallback } from 'react';
import { Header } from '../components/Header';
import { fetchCameras } from '../api/cameras';
import {
  fetchHistoricalAnalytics,
  fetchTomorrowForecast,
  generateDailyForecast,
  fetchForecastAlerts,
  fetchCameraAnalyticsConfig,
  saveCameraAnalyticsConfig,
  getExportCsvUrl,
} from '../api/analytics';
import { useToast } from '../context/ToastContext';
import { LoadingSpinner, EmptyState, ErrorState } from '../components/StatusStates';
import {
  BarChart3,
  TrendingUp,
  Clock,
  Calendar,
  AlertTriangle,
  Users,
  Car,
  Download,
  RefreshCw,
  Sliders,
  CheckCircle2,
  Info,
  ShieldAlert,
  ArrowUpRight,
  ArrowDownRight,
  Minus,
  Sparkles,
  X,
  Layers,
} from 'lucide-react';

export function AnalyticsPage() {
  const { showToast } = useToast();
  const [activeTab, setActiveTab] = useState('historical'); // 'historical' | 'forecast' | 'alerts'

  // Common camera list
  const [cameras, setCameras] = useState([]);
  const [selectedCamera, setSelectedCamera] = useState('all');

  // Tab 1: Historical Analytics State
  const [historicalData, setHistoricalData] = useState(null);
  const [loadingHistorical, setLoadingHistorical] = useState(true);
  const [historicalError, setHistoricalError] = useState(null);
  const [objectType, setObjectType] = useState('all'); // 'all' | 'person' | 'vehicle'
  const [timeRange, setTimeRange] = useState('7_days');
  const [directionFilter, setDirectionFilter] = useState('all');
  const [compareWith, setCompareWith] = useState('previous_period');

  // Tab 2: Tomorrow Forecast State
  const [forecastCamera, setForecastCamera] = useState('');
  const [forecastData, setForecastData] = useState(null);
  const [loadingForecast, setLoadingForecast] = useState(false);
  const [forecastError, setForecastError] = useState(null);
  const [generatingForecast, setGeneratingForecast] = useState(false);

  // Tab 3: Predictive Alerts State
  const [alerts, setAlerts] = useState([]);
  const [loadingAlerts, setLoadingAlerts] = useState(false);
  const [alertsError, setAlertsError] = useState(null);

  // Threshold Configuration Modal State
  const [showConfigModal, setShowConfigModal] = useState(false);
  const [configCamera, setConfigCamera] = useState('');
  const [configLoading, setConfigLoading] = useState(false);
  const [configForm, setConfigForm] = useState({
    enabled: true,
    capacity: 200,
    peak_traffic_threshold: 80,
    high_traffic_threshold: 300,
    in_direction: 'normal',
  });

  // Load cameras on mount
  useEffect(() => {
    let mounted = true;
    fetchCameras()
      .then((res) => {
        if (!mounted) return;
        const list = res?.cameras || [];
        setCameras(list);
        if (list.length > 0) {
          const firstId = String(list[0].id);
          setForecastCamera(firstId);
          setConfigCamera(firstId);
        }
      })
      .catch((err) => {
        console.error('Failed to load cameras:', err);
      });
    return () => {
      mounted = false;
    };
  }, []);

  // -------------------------------------------------------------
  // TAB 1: Load Historical Analytics
  // -------------------------------------------------------------
  const loadHistorical = useCallback(
    async (signal) => {
      setLoadingHistorical(true);
      setHistoricalError(null);
      try {
        const resp = await fetchHistoricalAnalytics(
          {
            camera_id: selectedCamera,
            object_type: objectType,
            direction: directionFilter,
            time_range: timeRange,
            compare_with: compareWith,
          },
          signal
        );
        if (resp?.status === 'success') {
          setHistoricalData(resp);
        } else {
          setHistoricalError(resp?.message || 'Không thể tải dữ liệu phân tích lịch sử.');
        }
      } catch (err) {
        if (err.name !== 'AbortError') {
          setHistoricalError(err.message || 'Lỗi kết nối khi tải phân tích lịch sử.');
        }
      } finally {
        setLoadingHistorical(false);
      }
    },
    [selectedCamera, objectType, directionFilter, timeRange, compareWith]
  );

  useEffect(() => {
    const controller = new AbortController();
    if (activeTab === 'historical') {
      loadHistorical(controller.signal);
    }
    return () => controller.abort();
  }, [activeTab, loadHistorical]);

  // -------------------------------------------------------------
  // TAB 2: Load Tomorrow Forecast
  // -------------------------------------------------------------
  const loadForecast = useCallback(
    async (signal) => {
      if (!forecastCamera) return;
      setLoadingForecast(true);
      setForecastError(null);
      try {
        const resp = await fetchTomorrowForecast({ camera_id: forecastCamera }, signal);
        if (resp) {
          setForecastData(resp);
        } else {
          setForecastError('Không nhận được kết quả dự báo.');
        }
      } catch (err) {
        if (err.name !== 'AbortError') {
          setForecastError(err.message || 'Lỗi khi tải dự báo ngày mai.');
        }
      } finally {
        setLoadingForecast(false);
      }
    },
    [forecastCamera]
  );

  useEffect(() => {
    const controller = new AbortController();
    if (activeTab === 'forecast' && forecastCamera) {
      loadForecast(controller.signal);
    }
    return () => controller.abort();
  }, [activeTab, forecastCamera, loadForecast]);

  const handleGenerateDaily = async () => {
    setGeneratingForecast(true);
    try {
      const res = await generateDailyForecast();
      showToast(
        `Đã tạo dự báo và đánh giá cảnh báo cho ${res?.cameras_processed || 0} camera!`,
        'success'
      );
      loadForecast();
      if (activeTab === 'alerts') {
        loadAlerts();
      }
    } catch (err) {
      showToast(`Lỗi tạo dự báo: ${err.message}`, 'error');
    } finally {
      setGeneratingForecast(false);
    }
  };

  // -------------------------------------------------------------
  // TAB 3: Load Predictive Alerts
  // -------------------------------------------------------------
  const loadAlerts = useCallback(async (signal) => {
    setLoadingAlerts(true);
    setAlertsError(null);
    try {
      const resp = await fetchForecastAlerts({}, signal);
      if (resp?.status === 'success') {
        setAlerts(resp.alerts || []);
      } else {
        setAlertsError(resp?.message || 'Không thể tải danh sách cảnh báo dự báo.');
      }
    } catch (err) {
      if (err.name !== 'AbortError') {
        setAlertsError(err.message || 'Lỗi khi tải cảnh báo.');
      }
    } finally {
      setLoadingAlerts(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    if (activeTab === 'alerts') {
      loadAlerts(controller.signal);
    }
    return () => controller.abort();
  }, [activeTab, loadAlerts]);

  // Load config for modal
  const openConfigModal = async (camId) => {
    const targetId = camId || forecastCamera || (cameras[0]?.id && String(cameras[0].id));
    if (!targetId) return;
    setConfigCamera(targetId);
    setShowConfigModal(true);
    setConfigLoading(true);
    try {
      const res = await fetchCameraAnalyticsConfig(targetId);
      if (res) {
        setConfigForm({
          enabled: res.enabled !== false,
          capacity: res.capacity || 200,
          peak_traffic_threshold: 80,
          high_traffic_threshold: 300,
          in_direction: res.in_direction || 'normal',
        });
      }
    } catch (err) {
      console.warn('Config fetch optional:', err);
    } finally {
      setConfigLoading(false);
    }
  };

  const handleSaveConfig = async (e) => {
    e.preventDefault();
    try {
      await saveCameraAnalyticsConfig({
        camera_id: configCamera,
        enabled: configForm.enabled,
        capacity: Number(configForm.capacity) || null,
        in_direction: configForm.in_direction,
      });
      showToast('Đã lưu cấu hình phân tích và ngưỡng cảnh báo!', 'success');
      setShowConfigModal(false);
      if (activeTab === 'forecast') loadForecast();
    } catch (err) {
      showToast(`Lỗi khi lưu cấu hình: ${err.message}`, 'error');
    }
  };

  return (
    <div className="page-container" id="analyticsPage">
      <Header
        title="Phân tích & Dự báo Lưu lượng"
        subtitle="Operational Intelligence — Thống kê lịch sử thực tế, dự báo ngày mai & cảnh báo đón đầu"
      />

      {/* Tabs bar */}
      <div className="analytics-tabs-header">
        <button
          type="button"
          className={`analytics-tab-btn ${activeTab === 'historical' ? 'active' : ''}`}
          onClick={() => setActiveTab('historical')}
          id="tabHistorical"
        >
          <BarChart3 size={18} />
          <span>Lịch sử Lưu lượng</span>
        </button>
        <button
          type="button"
          className={`analytics-tab-btn ${activeTab === 'forecast' ? 'active' : ''}`}
          onClick={() => setActiveTab('forecast')}
          id="tabForecast"
        >
          <Sparkles size={18} />
          <span>Dự báo Ngày mai</span>
        </button>
        <button
          type="button"
          className={`analytics-tab-btn ${activeTab === 'alerts' ? 'active' : ''}`}
          onClick={() => setActiveTab('alerts')}
          id="tabAlerts"
        >
          <ShieldAlert size={18} />
          <span>Cảnh báo Vận hành</span>
        </button>
      </div>

      {/* ========================================================= */}
      {/* TAB 1: HISTORICAL ANALYTICS */}
      {/* ========================================================= */}
      {activeTab === 'historical' && (
        <div className="analytics-section">
          {/* Controls Bar */}
          <div className="analytics-filter-card">
            <div className="filter-group">
              <label>Camera:</label>
              <select
                value={selectedCamera}
                onChange={(e) => setSelectedCamera(e.target.value)}
                className="analytics-select"
                id="filterCamera"
              >
                <option value="all">Tất cả camera ({cameras.length})</option>
                {cameras.map((c) => (
                  <option key={String(c.id)} value={String(c.id)}>
                    {c.name || c.id}
                  </option>
                ))}
              </select>
            </div>

            <div className="filter-group">
              <label>Đối tượng:</label>
              <select
                value={objectType}
                onChange={(e) => setObjectType(e.target.value)}
                className="analytics-select"
                id="filterObjectType"
              >
                <option value="all">Tất cả (Người & Xe)</option>
                <option value="person">Người / Khách đi bộ</option>
                <option value="vehicle">Phương tiện giao thông</option>
              </select>
            </div>

            <div className="filter-group">
              <label>Thời gian:</label>
              <select
                value={timeRange}
                onChange={(e) => setTimeRange(e.target.value)}
                className="analytics-select"
                id="filterTimeRange"
              >
                <option value="today">Hôm nay (từ 00:00 ICT)</option>
                <option value="yesterday">Hôm qua</option>
                <option value="7_days">7 ngày qua</option>
                <option value="this_week">Tuần này</option>
                <option value="last_week">Tuần trước</option>
                <option value="30_days">30 ngày qua</option>
              </select>
            </div>

            <div className="filter-group">
              <label>Hướng:</label>
              <select
                value={directionFilter}
                onChange={(e) => setDirectionFilter(e.target.value)}
                className="analytics-select"
                id="filterDirection"
              >
                <option value="all">Hai chiều (IN + OUT)</option>
                <option value="in">Chỉ chiều Vào (IN)</option>
                <option value="out">Chỉ chiều Ra (OUT)</option>
              </select>
            </div>

            <div className="filter-group">
              <label>Đối chứng:</label>
              <select
                value={compareWith}
                onChange={(e) => setCompareWith(e.target.value)}
                className="analytics-select"
                id="filterComparison"
              >
                <option value="previous_period">Kỳ trước</option>
                <option value="yesterday">Hôm qua</option>
                <option value="last_week">Tuần trước</option>
              </select>
            </div>

            <div className="filter-actions">
              <a
                href={getExportCsvUrl({ camera_id: selectedCamera, time_range: timeRange })}
                className="btn-export-csv"
                target="_blank"
                rel="noreferrer"
                id="btnExportCsv"
                title="Xuất bảng dữ liệu CSV"
              >
                <Download size={15} />
                <span>Xuất CSV</span>
              </a>
              <button
                type="button"
                className="btn-refresh-analytics"
                onClick={() => loadHistorical()}
                title="Làm mới"
              >
                <RefreshCw size={15} className={loadingHistorical ? 'spin' : ''} />
              </button>
            </div>
          </div>

          {loadingHistorical && <LoadingSpinner message="Đang phân tích dữ liệu lịch sử lưu lượng..." />}

          {historicalError && (
            <ErrorState title="Lỗi tải dữ liệu phân tích" message={historicalError} onRetry={loadHistorical} />
          )}

          {!loadingHistorical && !historicalError && historicalData && (
            <>
              {/* Metric Summary Cards */}
              <div className="analytics-kpi-grid">
                <div className="kpi-card">
                  <div className="kpi-header">
                    <span className="kpi-title">Tổng Lượt Di Chuyển</span>
                    <Layers size={18} className="kpi-icon text-blue" />
                  </div>
                  <div className="kpi-value">
                    {historicalData.metrics?.total_passages?.toLocaleString('vi-VN') || 0}
                  </div>
                  <div className="kpi-subtext">
                    <span className="badge-in">Vào: {historicalData.metrics?.person_in + historicalData.metrics?.vehicle_in || 0}</span>
                    <span className="badge-out">Ra: {historicalData.metrics?.person_out + historicalData.metrics?.vehicle_out || 0}</span>
                    <span className="badge-net">Chênh lệch: {historicalData.metrics?.net_flow || 0}</span>
                  </div>
                </div>

                <div className="kpi-card">
                  <div className="kpi-header">
                    <span className="kpi-title">Trung Bình Mỗi Giờ</span>
                    <Clock size={18} className="kpi-icon text-indigo" />
                  </div>
                  <div className="kpi-value">
                    {historicalData.metrics?.average_per_hour || 0}{' '}
                    <span className="kpi-unit">lượt/h</span>
                  </div>
                  <div className="kpi-subtext text-muted">
                    Tính trên {historicalData.duration_hours || 0} giờ quan sát thực tế
                  </div>
                </div>

                <div className="kpi-card">
                  <div className="kpi-header">
                    <span className="kpi-title">Giờ Cao Điểm Lịch Sử</span>
                    <TrendingUp size={18} className="kpi-icon text-rose" />
                  </div>
                  <div className="kpi-value text-rose">
                    {historicalData.metrics?.peak_hour_slot || 'Chưa rõ'}
                  </div>
                  <div className="kpi-subtext">
                    Đạt đỉnh: <strong>{historicalData.metrics?.peak_hour_passages || 0}</strong> lượt
                  </div>
                </div>

                <div className="kpi-card">
                  <div className="kpi-header">
                    <span className="kpi-title">So Với Kỳ Trước</span>
                    {historicalData.comparison?.difference > 0 ? (
                      <ArrowUpRight size={18} className="kpi-icon text-green" />
                    ) : historicalData.comparison?.difference < 0 ? (
                      <ArrowDownRight size={18} className="kpi-icon text-red" />
                    ) : (
                      <Minus size={18} className="kpi-icon text-gray" />
                    )}
                  </div>
                  <div className="kpi-value">
                    {historicalData.comparison?.percent_change !== null &&
                    historicalData.comparison?.percent_change !== undefined ? (
                      <span
                        className={
                          historicalData.comparison.percent_change >= 0 ? 'text-green' : 'text-red'
                        }
                      >
                        {historicalData.comparison.percent_change > 0 ? '+' : ''}
                        {historicalData.comparison.percent_change}%
                      </span>
                    ) : (
                      <span className="text-muted">Mới</span>
                    )}
                  </div>
                  <div className="kpi-subtext text-muted">
                    {historicalData.comparison?.trend_description || 'Không có mốc so sánh'}
                  </div>
                </div>

                <div className="kpi-card">
                  <div className="kpi-header">
                    <span className="kpi-title">Chất Lượng Dữ Liệu</span>
                    <CheckCircle2 size={18} className="kpi-icon text-emerald" />
                  </div>
                  <div className="kpi-value">
                    <span className={`quality-badge quality-${historicalData.metrics?.data_quality_status?.toLowerCase()}`}>
                      {historicalData.metrics?.data_quality_status || 'GOOD'}
                    </span>
                  </div>
                  <div className="kpi-subtext text-muted">
                    Độ bao phủ camera: {Math.round((historicalData.metrics?.coverage_ratio || 0) * 100)}%
                  </div>
                </div>
              </div>

              {/* Hourly Traffic Chart (24 Hours) */}
              <div className="analytics-card">
                <div className="card-header-clean">
                  <h3 className="card-title">Phân Bổ Lưu Lượng Theo 24 Khung Giờ (Giờ ICT)</h3>
                  <span className="card-tag">Đo lường từ CrossingEvent</span>
                </div>
                <div className="hourly-bar-chart">
                  {historicalData.hourly_distribution?.map((item) => {
                    const maxVal = Math.max(
                      ...historicalData.hourly_distribution.map((x) => x.total),
                      1
                    );
                    const heightPct = Math.round((item.total / maxVal) * 100);
                    const inPct = item.total > 0 ? (item.in / item.total) * 100 : 0;
                    const outPct = item.total > 0 ? (item.out / item.total) * 100 : 0;

                    return (
                      <div key={item.hour} className="hour-bar-col" title={`${item.hour_slot}: ${item.total} lượt (Vào: ${item.in}, Ra: ${item.out})`}>
                        <div className="bar-track">
                          <div
                            className="bar-fill"
                            style={{ height: `${Math.max(4, heightPct)}%` }}
                          >
                            <div className="bar-sub-in" style={{ height: `${inPct}%` }} />
                            <div className="bar-sub-out" style={{ height: `${outPct}%` }} />
                          </div>
                        </div>
                        <span className="hour-label">{item.hour}h</span>
                        {item.total > 0 && <span className="bar-num">{item.total}</span>}
                      </div>
                    );
                  })}
                </div>
                <div className="chart-legend">
                  <div className="legend-item">
                    <span className="legend-color bg-in" />
                    <span>Chiều Vào (IN)</span>
                  </div>
                  <div className="legend-item">
                    <span className="legend-color bg-out" />
                    <span>Chiều Ra (OUT)</span>
                  </div>
                </div>
              </div>

              {/* Grid 2 Columns: Weekday vs Weekend & Camera Rankings */}
              <div className="analytics-two-col">
                {/* Weekday vs Weekend Comparison */}
                <div className="analytics-card">
                  <div className="card-header-clean">
                    <h3 className="card-title">So Sánh Ngày Thường & Cuối Tuần</h3>
                    <Calendar size={16} className="text-muted" />
                  </div>
                  <div className="weekday-summary-alert">
                    <Info size={18} className="text-blue" />
                    <span>{historicalData.weekday_vs_weekend?.summary}</span>
                  </div>
                  <div className="weekday-bars">
                    {historicalData.weekday_comparison?.map((w) => (
                      <div key={w.weekday_index} className="weekday-row">
                        <span className="weekday-name">{w.weekday_name}</span>
                        <div className="weekday-progress-track">
                          <div
                            className={`weekday-progress-fill ${w.weekday_index >= 5 ? 'is-weekend' : ''}`}
                            style={{
                              width: `${Math.min(
                                100,
                                Math.round(
                                  (w.average_per_day /
                                    Math.max(
                                      ...historicalData.weekday_comparison.map(
                                        (x) => x.average_per_day
                                      ),
                                      1
                                    )) *
                                    100
                                )
                              )}%`,
                            }}
                          />
                        </div>
                        <span className="weekday-count">
                          <strong>{w.average_per_day}</strong> lượt/ngày
                        </span>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Camera Rankings */}
                <div className="analytics-card">
                  <div className="card-header-clean">
                    <h3 className="card-title">Xếp Hạng Lưu Lượng Camera</h3>
                    <BarChart3 size={16} className="text-muted" />
                  </div>
                  {historicalData.camera_rankings && historicalData.camera_rankings.length > 0 ? (
                    <div className="camera-ranking-list">
                      {historicalData.camera_rankings.map((cam, idx) => (
                        <div key={cam.camera_id} className="ranking-item">
                          <span className={`ranking-badge rank-${idx + 1}`}>{idx + 1}</span>
                          <div className="ranking-info">
                            <span className="ranking-name">{cam.camera_name}</span>
                            <span className="ranking-sub">ID: {cam.camera_id}</span>
                          </div>
                          <div className="ranking-stats">
                            <span className="ranking-total">{cam.total} lượt</span>
                            <span className="ranking-split text-muted">
                              (Vào: {cam.in} | Ra: {cam.out})
                            </span>
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <EmptyState message="Chưa có dữ liệu camera để xếp hạng." />
                  )}
                </div>
              </div>

              {/* Vehicle Type Breakdown if applicable */}
              {objectType !== 'person' && historicalData.vehicle_type_breakdown && (
                <div className="analytics-card">
                  <div className="card-header-clean">
                    <h3 className="card-title">Phân Loại Phương Tiện Giao Thông</h3>
                    <Car size={16} className="text-muted" />
                  </div>
                  <div className="vehicle-breakdown-grid">
                    {Object.entries(historicalData.vehicle_type_breakdown).map(([vClass, counts]) => (
                      <div key={vClass} className="vehicle-type-item">
                        <span className="vehicle-name">{vClass.toUpperCase()}</span>
                        <div className="vehicle-count-val">{counts.total}</div>
                        <div className="vehicle-split">
                          <span>Vào: {counts.in}</span>
                          <span>Ra: {counts.out}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      )}

      {/* ========================================================= */}
      {/* TAB 2: TOMORROW FORECAST */}
      {/* ========================================================= */}
      {activeTab === 'forecast' && (
        <div className="analytics-section">
          {/* Forecast Filter & Action Bar */}
          <div className="analytics-filter-card">
            <div className="filter-group">
              <label>Chọn Camera Dự Báo:</label>
              <select
                value={forecastCamera}
                onChange={(e) => setForecastCamera(e.target.value)}
                className="analytics-select"
                id="selectForecastCamera"
              >
                {cameras.map((c) => (
                  <option key={String(c.id)} value={String(c.id)}>
                    {c.name || c.id}
                  </option>
                ))}
              </select>
            </div>

            <div className="filter-actions">
              <button
                type="button"
                className="btn-configure-threshold"
                onClick={() => openConfigModal(forecastCamera)}
                id="btnOpenThresholdModal"
              >
                <Sliders size={15} />
                <span>Cấu hình ngưỡng</span>
              </button>
              <button
                type="button"
                className="btn-generate-forecast"
                onClick={handleGenerateDaily}
                disabled={generatingForecast}
                id="btnGenerateDailyForecast"
              >
                <RefreshCw size={15} className={generatingForecast ? 'spin' : ''} />
                <span>{generatingForecast ? 'Đang tính toán...' : 'Tạo dự báo ngày mai'}</span>
              </button>
            </div>
          </div>

          {loadingForecast && <LoadingSpinner message="Đang mô hình hóa dữ liệu và tính toán dự báo ngày mai..." />}

          {forecastError && (
            <ErrorState title="Lỗi tạo dự báo" message={forecastError} onRetry={loadForecast} />
          )}

          {!loadingForecast && !forecastError && forecastData && (
            <>
              {/* Quality Status Banner */}
              {forecastData.data_quality_status === 'INSUFFICIENT_DATA' ? (
                <div className="quality-banner banner-insufficient">
                  <AlertTriangle size={24} className="text-amber" />
                  <div>
                    <h4>Chưa đủ dữ liệu lịch sử</h4>
                    <p>{forecastData.message || 'Chưa đủ dữ liệu lịch sử đáng tin cậy để dự báo lưu lượng ngày mai.'}</p>
                    <span className="banner-note">
                      Hệ thống yêu cầu ít nhất 3 ngày cùng thứ trong lịch sử để kích hoạt mô hình dự báo.
                    </span>
                  </div>
                </div>
              ) : (
                <div className="quality-banner banner-ready">
                  <Sparkles size={24} className="text-blue" />
                  <div>
                    <h4>
                      Dự Báo Lưu Lượng Ngày Mai — {forecastData.weekday_name} ({forecastData.target_date})
                    </h4>
                    <p>
                      Mô hình: <code>{forecastData.model_version}</code> (Trọng số cùng thứ lịch sử). Trạng thái:{' '}
                      <span className="badge-ready">{forecastData.data_quality_status}</span>
                    </p>
                    <span className="banner-note">
                      Dựa trên {forecastData.historical_days_used} ngày {forecastData.weekday_name} gần nhất trong lịch sử.
                    </span>
                  </div>
                </div>
              )}

              {/* Forecast Highlights */}
              {forecastData.data_quality_status !== 'INSUFFICIENT_DATA' && (
                <>
                  <div className="analytics-kpi-grid">
                    <div className="kpi-card highlight-card">
                      <div className="kpi-header">
                        <span className="kpi-title">Dự Báo Tổng Lưu Lượng</span>
                        <Sparkles size={18} className="kpi-icon text-blue" />
                      </div>
                      <div className="kpi-value text-blue">
                        {forecastData.total_forecast?.expected || 0}{' '}
                        <span className="kpi-unit">lượt</span>
                      </div>
                      <div className="kpi-subtext">
                        Khoảng tin cậy 80%:{' '}
                        <strong>
                          {forecastData.total_forecast?.lower_bound_80} -{' '}
                          {forecastData.total_forecast?.upper_bound_80}
                        </strong>{' '}
                        lượt
                      </div>
                    </div>

                    <div className="kpi-card">
                      <div className="kpi-header">
                        <span className="kpi-title">Khung Giờ Cao Điểm Dự Kiến</span>
                        <TrendingUp size={18} className="kpi-icon text-rose" />
                      </div>
                      <div className="kpi-value text-rose">
                        {forecastData.peak_hours && forecastData.peak_hours.length > 0
                          ? forecastData.peak_hours[0].hour_slot
                          : 'Bình thường'}
                      </div>
                      <div className="kpi-subtext">
                        {forecastData.peak_hours && forecastData.peak_hours.length > 0
                          ? `Dự kiến: ${forecastData.peak_hours[0].expected_passages} lượt (${forecastData.peak_hours[0].range_80})`
                          : 'Không có khung đột biến'}
                      </div>
                    </div>

                    <div className="kpi-card">
                      <div className="kpi-header">
                        <span className="kpi-title">Số Ngày Lịch Sử Đối Chứng</span>
                        <Calendar size={18} className="kpi-icon text-indigo" />
                      </div>
                      <div className="kpi-value">{forecastData.historical_days_used || 0}</div>
                      <div className="kpi-subtext text-muted">
                        Áp dụng hàm suy giảm trọng số theo tuần gần nhất
                      </div>
                    </div>

                    <div className="kpi-card">
                      <div className="kpi-header">
                        <span className="kpi-title">Độ Chính Xác Backtest (WAPE)</span>
                        <CheckCircle2 size={18} className="kpi-icon text-emerald" />
                      </div>
                      <div className="kpi-value">
                        {forecastData.backtest_metrics?.wape_percent !== undefined
                          ? `${forecastData.backtest_metrics.wape_percent}%`
                          : 'Đang đo lường'}
                      </div>
                      <div className="kpi-subtext text-muted">
                        Độ phủ khoảng tin cậy:{' '}
                        {forecastData.backtest_metrics?.interval_coverage_80_percent || 0}%
                      </div>
                    </div>
                  </div>

                  {/* Hourly Forecast Progression */}
                  <div className="analytics-card">
                    <div className="card-header-clean">
                      <h3 className="card-title">Biểu Đồ Dự Báo Theo Khung Giờ Ngày Mai</h3>
                      <span className="card-tag">Dự báo thống kê (80% Confidence Interval)</span>
                    </div>

                    <div className="forecast-timeline-table-wrapper">
                      <table className="forecast-table">
                        <thead>
                          <tr>
                            <th>Khung giờ</th>
                            <th>Dự kiến (Lượt)</th>
                            <th>Khoảng tin cậy 80%</th>
                            <th>Chiều Vào (IN)</th>
                            <th>Chiều Ra (OUT)</th>
                            <th>Độ lệch chuẩn</th>
                          </tr>
                        </thead>
                        <tbody>
                          {forecastData.hourly_forecasts?.map((h) => {
                            const isPeak =
                              forecastData.peak_hours?.some((p) => p.hour === h.hour) || false;
                            return (
                              <tr key={h.hour} className={isPeak ? 'row-peak' : ''}>
                                <td>
                                  <strong>{h.hour_slot}</strong>
                                  {isPeak && <span className="peak-pill">Cao điểm</span>}
                                </td>
                                <td>
                                  <span className="expected-num">{h.expected_passages}</span>
                                </td>
                                <td>
                                  <span className="interval-range">
                                    [{h.prediction_interval_80.lower} - {h.prediction_interval_80.upper}]
                                  </span>
                                </td>
                                <td>{h.person_in + h.vehicle_in}</td>
                                <td>{h.person_out + h.vehicle_out}</td>
                                <td className="text-muted">±{h.std_deviation}</td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  </div>
                </>
              )}
            </>
          )}
        </div>
      )}

      {/* ========================================================= */}
      {/* TAB 3: PREDICTIVE ALERTS */}
      {/* ========================================================= */}
      {activeTab === 'alerts' && (
        <div className="analytics-section">
          <div className="alerts-action-bar">
            <div>
              <h3 className="section-title">Cảnh Báo Dự Báo & Khuyến Nghị Vận Hành</h3>
              <p className="section-subtitle">
                Cảnh báo trước 24 giờ cho ban quản trị để chủ động điều phối nhân sự trước các khung giờ cao điểm
              </p>
            </div>
            <button
              type="button"
              className="btn-refresh-analytics"
              onClick={() => loadAlerts()}
              title="Làm mới cảnh báo"
            >
              <RefreshCw size={15} className={loadingAlerts ? 'spin' : ''} />
              <span>Cập nhật</span>
            </button>
          </div>

          {loadingAlerts && <LoadingSpinner message="Đang tải danh sách cảnh báo dự báo..." />}

          {alertsError && (
            <ErrorState title="Lỗi tải cảnh báo" message={alertsError} onRetry={loadAlerts} />
          )}

          {!loadingAlerts && !alertsError && (
            <>
              {alerts.length === 0 ? (
                <EmptyState message="Hiện không có cảnh báo dự báo nào cho ngày mai. Lưu lượng dự kiến đều trong tầm kiểm soát." />
              ) : (
                <div className="predictive-alerts-grid">
                  {alerts.map((al) => (
                    <div key={al.id} className={`alert-card alert-sev-${al.severity?.toLowerCase()}`}>
                      <div className="alert-card-header">
                        <span className={`alert-type-pill pill-${al.alert_type?.toLowerCase()}`}>
                          {al.alert_type}
                        </span>
                        <span className={`alert-sev-badge sev-${al.severity?.toLowerCase()}`}>
                          {al.severity}
                        </span>
                      </div>

                      <div className="alert-meta">
                        <div className="meta-row">
                          <span className="meta-label">Camera:</span>
                          <span className="meta-val">{al.camera_name || al.camera_id}</span>
                        </div>
                        <div className="meta-row">
                          <span className="meta-label">Ngày dự báo:</span>
                          <span className="meta-val">{al.target_date}</span>
                        </div>
                        {al.peak_window && (
                          <div className="meta-row">
                            <span className="meta-label">Khung giờ cao điểm:</span>
                            <span className="meta-val text-rose">{al.peak_window}</span>
                          </div>
                        )}
                        {al.threshold_value && (
                          <div className="meta-row">
                            <span className="meta-label">Ngưỡng cảnh báo:</span>
                            <span className="meta-val">{al.threshold_value} lượt/h</span>
                          </div>
                        )}
                      </div>

                      {al.recommendation && (
                        <div className="alert-recommendation-box">
                          <div className="rec-header">
                            <Sparkles size={16} className="text-amber" />
                            <span>Đề xuất vận hành:</span>
                          </div>
                          <p className="rec-content">{al.recommendation}</p>
                        </div>
                      )}

                      <div className="alert-footer">
                        <span className="delivery-status">
                          Trạng thái gửi mail: <strong>{al.delivery_status}</strong>
                        </span>
                        <span className="alert-time text-muted">
                          {al.created_at ? new Date(al.created_at).toLocaleString('vi-VN') : ''}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      )}

      {/* ========================================================= */}
      {/* THRESHOLD CONFIGURATION MODAL */}
      {/* ========================================================= */}
      {showConfigModal && (
        <div className="modal-backdrop" onClick={() => setShowConfigModal(false)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <div className="modal-title-group">
                <Sliders size={20} className="text-blue" />
                <h3>Cấu Hình Ngưỡng Cảnh Báo & Phân Tích</h3>
              </div>
              <button
                type="button"
                className="modal-close-btn"
                onClick={() => setShowConfigModal(false)}
              >
                <X size={18} />
              </button>
            </div>

            {configLoading ? (
              <LoadingSpinner message="Đang tải cấu hình..." />
            ) : (
              <form onSubmit={handleSaveConfig} className="config-form">
                <div className="form-group">
                  <label>Camera cấu hình:</label>
                  <select
                    value={configCamera}
                    onChange={(e) => openConfigModal(e.target.value)}
                    className="modal-select"
                  >
                    {cameras.map((c) => (
                      <option key={String(c.id)} value={String(c.id)}>
                        {c.name || c.id}
                      </option>
                    ))}
                  </select>
                </div>

                <div className="form-group">
                  <label>Kích hoạt phân tích lưu lượng:</label>
                  <div className="checkbox-row">
                    <input
                      type="checkbox"
                      id="enableAnalyticsCheck"
                      checked={configForm.enabled}
                      onChange={(e) => setConfigForm({ ...configForm, enabled: e.target.checked })}
                    />
                    <label htmlFor="enableAnalyticsCheck">Cho phép đếm lượt qua vạch và dự báo</label>
                  </div>
                </div>

                <div className="form-group">
                  <label>Ngưỡng lưu lượng Giờ Cao Điểm (lượt/giờ):</label>
                  <input
                    type="number"
                    value={configForm.peak_traffic_threshold}
                    onChange={(e) =>
                      setConfigForm({ ...configForm, peak_traffic_threshold: Number(e.target.value) })
                    }
                    className="modal-input"
                    min="10"
                    max="5000"
                  />
                  <small className="help-text">
                    Kích hoạt cảnh báo EXPECTED_PEAK_TRAFFIC nếu lưu lượng giờ cao điểm vượt mức này
                  </small>
                </div>

                <div className="form-group">
                  <label>Sức chứa thiết kế (Capacity - chỗ đỗ / người):</label>
                  <input
                    type="number"
                    value={configForm.capacity}
                    onChange={(e) =>
                      setConfigForm({ ...configForm, capacity: Number(e.target.value) })
                    }
                    className="modal-input"
                    min="1"
                    max="10000"
                  />
                  <small className="help-text">
                    Chỉ kích hoạt cảnh báo Quá tải (EXPECTED_CAPACITY_RISK) khi sức chứa được cấu hình cụ thể
                  </small>
                </div>

                <div className="form-group">
                  <label>Hướng vào (IN Direction):</label>
                  <select
                    value={configForm.in_direction}
                    onChange={(e) => setConfigForm({ ...configForm, in_direction: e.target.value })}
                    className="modal-select"
                  >
                    <option value="normal">Mặc định (Từ trái qua phải / Trên xuống dưới)</option>
                    <option value="reverse">Đảo ngược (Ngược lại)</option>
                  </select>
                </div>

                <div className="modal-actions">
                  <button
                    type="button"
                    className="btn-cancel"
                    onClick={() => setShowConfigModal(false)}
                  >
                    Hủy
                  </button>
                  <button type="submit" className="btn-save" id="btnSaveAnalyticsConfig">
                    Lưu cấu hình
                  </button>
                </div>
              </form>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
