/**
 * DATT AI Vision Monitor & Camera Manager - Frontend Client
 * Phase 4.6: Initial Camera Selection, Public CCTV, Direct HLS & Multi-Source Routing
 *
 * UI States:
 * - SELECT_CAMERA : Initial selection screen (Public CCTV, Direct HLS, YouTube Live, Local)
 * - CONNECTING    : Connecting overlay, verifying first frame
 * - MONITORING    : Active monitoring dashboard
 * - ERROR         : Connection timeout or failure screen with retry
 */

(function () {
    "use strict";

    // Application Configuration
    const CONFIG = {
        telemetryIntervalMs: 1000,
        eventsIntervalMs: 10000,
        videoReconnectDelayMs: 3000,
        connectionTimeoutMs: 16000,
        sourceStatusPollMs: 500,
        defaultBackendUrl: "http://localhost:8000"
    };

    // UI States
    const UI_STATE = {
        SELECT_CAMERA: "SELECT_CAMERA",
        CONNECTING: "CONNECTING",
        MONITORING: "MONITORING",
        ERROR: "ERROR"
    };

    // Client State
    const state = {
        uiState: UI_STATE.SELECT_CAMERA,
        backendUrl: CONFIG.defaultBackendUrl,
        activeCameraId: "",
        activeCameraName: "",
        activeProvider: "",
        activeSourceType: "",
        connectingSourceData: null,
        isSwitchingCamera: false,
        telemetryTimer: null,
        eventsTimer: null,
        videoReconnectTimer: null,
        connectionTimer: null,
        lastEventsJson: "",
        consecutiveErrors: 0,
        cctvCameras: [],
        cctvProvider: "seattle",
        previewingCamera: null,
        isPreviewLive: false
    };

    // DOM Elements Cache
    const DOM = {
        // Screens
        selectionScreen: document.getElementById("selectionScreen"),
        connectingScreen: document.getElementById("connectingScreen"),
        errorScreen: document.getElementById("errorScreen"),
        monitoringScreen: document.getElementById("monitoringScreen"),

        // Connecting & Error UI
        connectingTargetName: document.getElementById("connectingTargetName"),
        badgeStepReader: document.getElementById("badgeStepReader"),
        badgeStepFrame: document.getElementById("badgeStepFrame"),
        badgeStepAi: document.getElementById("badgeStepAi"),
        errorMessageText: document.getElementById("errorMessageText"),
        errorDebugBox: document.getElementById("errorDebugBox"),
        btnRetryConnection: document.getElementById("btnRetryConnection"),
        btnBackToSelection: document.getElementById("btnBackToSelection"),

        // Source Header on Dashboard
        dashHeaderCamName: document.getElementById("dashHeaderCamName"),
        dashHeaderProvider: document.getElementById("dashHeaderProvider"),
        dashHeaderStatus: document.getElementById("dashHeaderStatus"),
        btnSwitchCameraFromDash: document.getElementById("btnSwitchCameraFromDash"),

        // Public CCTV Catalog Elements
        cctvSearchInput: document.getElementById("cctvSearchInput"),
        cctvCountBadge: document.getElementById("cctvCountBadge"),
        refreshCatalogBtn: document.getElementById("refreshCatalogBtn"),
        cctvCardsGrid: document.getElementById("cctvCardsGrid"),

        // Direct HLS Tab Elements
        hlsCustomName: document.getElementById("hlsCustomName"),
        hlsCustomUrl: document.getElementById("hlsCustomUrl"),
        btnPreviewDirectHls: document.getElementById("btnPreviewDirectHls"),
        btnConnectDirectHls: document.getElementById("btnConnectDirectHls"),
        hlsCustomFeedback: document.getElementById("hlsCustomFeedback"),

        // YouTube Tab Elements
        ytPresetSelect: document.getElementById("ytPresetSelect"),
        ytCustomName: document.getElementById("ytCustomName"),
        ytCustomUrl: document.getElementById("ytCustomUrl"),
        btnPreviewYouTube: document.getElementById("btnPreviewYouTube"),
        btnConnectYouTube: document.getElementById("btnConnectYouTube"),
        ytFeedback: document.getElementById("ytFeedback"),

        // Local Video Tab Elements (Upload flow)
        localUploadDropzone: document.getElementById("localUploadDropzone"),
        localVideoFileInput: document.getElementById("localVideoFileInput"),
        btnBrowseVideo: document.getElementById("btnBrowseVideo"),
        localFileInfoCard: document.getElementById("localFileInfoCard"),
        localFileNameText: document.getElementById("localFileNameText"),
        localFileSizeText: document.getElementById("localFileSizeText"),
        localFileStatusBadge: document.getElementById("localFileStatusBadge"),
        uploadProgressBarContainer: document.getElementById("uploadProgressBarContainer"),
        uploadProgressBarFill: document.getElementById("uploadProgressBarFill"),
        uploadProgressText: document.getElementById("uploadProgressText"),
        btnUploadAndConnect: document.getElementById("btnUploadAndConnect"),
        localVideoLoop: document.getElementById("localVideoLoop"),
        localFeedback: document.getElementById("localFeedback"),

        // Preview Modal Elements
        previewModal: document.getElementById("previewModal"),
        closePreviewBtn: document.getElementById("closePreviewBtn"),
        previewModalTitle: document.getElementById("previewModalTitle"),
        previewBadgeProvider: document.getElementById("previewBadgeProvider"),
        previewImage: document.getElementById("previewImage"),
        previewStream: document.getElementById("previewStream"),
        previewSpinner: document.getElementById("previewSpinner"),
        previewStreamUrl: document.getElementById("previewStreamUrl"),
        previewSourceType: document.getElementById("previewSourceType"),
        btnToggleLivePreview: document.getElementById("btnToggleLivePreview"),
        toggleLiveText: document.getElementById("toggleLiveText"),
        btnCancelPreview: document.getElementById("btnCancelPreview"),
        btnConfirmSelectCamera: document.getElementById("btnConfirmSelectCamera"),

        // Sidebar / Dashboard Elements
        backendUrlInput: document.getElementById("backendUrlInput"),
        cameraSelect: document.getElementById("cameraSelect"),
        switchCameraBtn: document.getElementById("switchCameraBtn"),
        cameraSwitchFeedback: document.getElementById("cameraSwitchFeedback"),
        sidebarConnStatus: document.getElementById("sidebarConnStatus"),
        pingLatency: document.getElementById("pingLatency"),
        statusBadge: document.getElementById("statusBadge"),
        alertBanner: document.getElementById("alertBanner"),

        // Video Feed Elements
        videoFeed: document.getElementById("videoFeed"),
        videoErrorOverlay: document.getElementById("videoErrorOverlay"),
        streamCamName: document.getElementById("streamCamName"),
        streamResolution: document.getElementById("streamResolution"),

        // Telemetry Elements
        telemActiveCam: document.getElementById("telemActiveCam"),
        metricPeopleCount: document.getElementById("metricPeopleCount"),
        metricCarCount: document.getElementById("metricCarCount"),
        metricDetections: document.getElementById("metricDetections"),
        metricTracks: document.getElementById("metricTracks"),
        metricProcessingFps: document.getElementById("metricProcessingFps"),
        metricStreamFps: document.getElementById("metricStreamFps"),
        metricYoloLatency: document.getElementById("metricYoloLatency"),
        metricPipelineLatency: document.getElementById("metricPipelineLatency"),

        // Hardware & Model Elements
        infoDevice: document.getElementById("infoDevice"),
        infoGpu: document.getElementById("infoGpu"),
        infoVram: document.getElementById("infoVram"),
        infoModel: document.getElementById("infoModel"),
        infoEventsToday: document.getElementById("infoEventsToday"),
        infoFilteredEvents: document.getElementById("infoFilteredEvents"),
        infoLastSavedCount: document.getElementById("infoLastSavedCount"),
        infoLastEvent: document.getElementById("infoLastEvent"),

        // Events Elements
        eventsContainer: document.getElementById("eventsContainer"),

        // Video Source Sidebar Elements
        sourceTypeSelect: document.getElementById("sourceTypeSelect"),
        sourceInput: document.getElementById("sourceInput"),
        sourceLoopCheckbox: document.getElementById("sourceLoopCheckbox"),
        applySourceBtn: document.getElementById("applySourceBtn"),
        sourceFeedback: document.getElementById("sourceFeedback"),

        // Target Registration Elements
        targetNameInput: document.getElementById("targetNameInput"),
        targetColorSelect: document.getElementById("targetColorSelect"),
        targetFaceInput: document.getElementById("targetFaceInput"),
        targetFaceFilename: document.getElementById("targetFaceFilename"),
        registerTargetBtn: document.getElementById("registerTargetBtn"),
        targetFeedback: document.getElementById("targetFeedback"),
        targetCount: document.getElementById("targetCount"),
        targetsList: document.getElementById("targetsList")
    };

    /**
     * Resolve API endpoint URL.
     */
    function apiUrl(path) {
        return path;
    }

    /**
     * UI State Machine Transition Controller.
     */
    function setUiState(newState, meta) {
        state.uiState = newState;
        meta = meta || {};

        // Hide all screens first
        DOM.selectionScreen.style.display = "none";
        DOM.connectingScreen.style.display = "none";
        DOM.errorScreen.style.display = "none";
        DOM.monitoringScreen.style.display = "none";

        if (newState === UI_STATE.SELECT_CAMERA) {
            DOM.selectionScreen.style.display = "flex";
            stopMonitoringTimers();
            stopConnectionPolling();
            window.dattLoadMetrics = window.dattLoadMetrics || { startTime: performance.now() };
            window.dattLoadMetrics.uiShellReady = performance.now();
            fetchPublicCctvCameras();
            // Note: Defer fetchConfigCameras() to when YouTube tab is selected to keep initial load lightweight
        } else if (newState === UI_STATE.CONNECTING) {
            DOM.connectingScreen.style.display = "flex";
            stopMonitoringTimers();
            const camName = meta.name || "Camera";
            DOM.connectingTargetName.textContent = `Đang kết nối luồng "${camName}" và đợi khung hình đầu tiên...`;
            resetConnectingSteps();
        } else if (newState === UI_STATE.ERROR) {
            DOM.errorScreen.style.display = "flex";
            stopMonitoringTimers();
            stopConnectionPolling();
            DOM.errorMessageText.textContent = meta.message || "Không thể kết nối camera. Vui lòng kiểm tra lại luồng phát.";
            if (meta.debug) {
                DOM.errorDebugBox.style.display = "block";
                DOM.errorDebugBox.textContent = `Chi tiết lỗi: ${meta.debug}`;
            } else {
                DOM.errorDebugBox.style.display = "none";
            }
        } else if (newState === UI_STATE.MONITORING) {
            DOM.monitoringScreen.style.display = "block";
            stopConnectionPolling();
            updateSourceHeader(meta.name, meta.provider, meta.source_type);
            triggerVideoRefresh();
            startMonitoringTimers();
        }
    }

    function resetConnectingSteps() {
        DOM.badgeStepReader.className = "status-pill active-step";
        DOM.badgeStepFrame.className = "status-pill";
        DOM.badgeStepAi.className = "status-pill";
    }

    function updateSourceHeader(name, provider, sourceType) {
        state.activeCameraName = name || state.activeCameraName || "Active Camera";
        state.activeProvider = provider || state.activeProvider || "Camera Source";
        state.activeSourceType = sourceType || state.activeSourceType || "HLS";

        DOM.dashHeaderCamName.textContent = state.activeCameraName;
        DOM.dashHeaderProvider.textContent = `${state.activeProvider} • ${state.activeSourceType}`;
        DOM.dashHeaderStatus.textContent = "● LIVE";
    }

    /**
     * Start/Stop Polling Timers.
     */
    function startMonitoringTimers() {
        stopMonitoringTimers();
        pollTelemetry();
        pollEvents();
        loadTargets();
        state.telemetryTimer = setInterval(pollTelemetry, CONFIG.telemetryIntervalMs);
        state.eventsTimer = setInterval(pollEvents, CONFIG.eventsIntervalMs);
    }

    function stopMonitoringTimers() {
        if (state.telemetryTimer) {
            clearInterval(state.telemetryTimer);
            state.telemetryTimer = null;
        }
        if (state.eventsTimer) {
            clearInterval(state.eventsTimer);
            state.eventsTimer = null;
        }
    }

    function stopConnectionPolling() {
        if (state.connectionTimer) {
            clearInterval(state.connectionTimer);
            state.connectionTimer = null;
        }
    }

    /**
     * Switch Tabs on Camera Selection Screen.
     */
    function initTabs() {
        const tabBtns = document.querySelectorAll(".source-tab-btn");
        tabBtns.forEach(btn => {
            btn.addEventListener("click", () => {
                const targetId = btn.getAttribute("data-tab");
                tabBtns.forEach(b => b.classList.remove("active"));
                btn.classList.add("active");

                document.querySelectorAll(".tab-pane").forEach(pane => {
                    pane.classList.remove("active");
                });
                const targetPane = document.getElementById(targetId);
                if (targetPane) {
                    targetPane.classList.add("active");
                }
                if (targetId === "tab-youtube") {
                    fetchConfigCameras();
                }
            });
        });
    }

    /**
     * Provider Selector (Seattle SDOT vs Caltrans).
     */
    function initProviderSelector() {
        const providerBtns = document.querySelectorAll(".provider-btn");
        providerBtns.forEach(btn => {
            btn.addEventListener("click", () => {
                const provider = btn.getAttribute("data-provider");
                providerBtns.forEach(b => b.classList.remove("active"));
                btn.classList.add("active");
                state.cctvProvider = provider;
                if (DOM.cctvSearchInput) {
                    DOM.cctvSearchInput.value = "";
                }
                fetchPublicCctvCameras(false);
            });
        });
    }

    const PLACEHOLDER_THUMBNAIL = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='320' height='180' viewBox='0 0 320 180'%3E%3Crect width='100%25' height='100%25' fill='%23131722'/%3E%3Ctext x='50%25' y='50%25' dominant-baseline='middle' text-anchor='middle' fill='%2364748b' font-family='sans-serif' font-size='12'%3E%F0%9F%93%B7 CCTV Camera%3C/text%3E%3C/svg%3E";

    let cctvThumbObserver = null;
    function setupThumbnailObserver() {
        if (cctvThumbObserver) {
            cctvThumbObserver.disconnect();
        }
        if (!('IntersectionObserver' in window)) {
            document.querySelectorAll(".cctv-thumb-img[data-src]").forEach(img => {
                const src = img.getAttribute("data-src");
                if (src) {
                    img.src = src;
                    img.removeAttribute("data-src");
                }
            });
            return;
        }

        cctvThumbObserver = new IntersectionObserver((entries, observer) => {
            entries.forEach(entry => {
                if (entry.isIntersecting) {
                    const img = entry.target;
                    const src = img.getAttribute("data-src");
                    if (src) {
                        img.src = src;
                        img.removeAttribute("data-src");
                    }
                    observer.unobserve(img);
                }
            });
        }, { rootMargin: "150px 0px" });

        document.querySelectorAll(".cctv-thumb-img[data-src]").forEach(img => {
            cctvThumbObserver.observe(img);
        });
    }

    /**
     * Fetch & Render Public CCTV Cameras (Seattle SDOT or Caltrans).
     */
    async function fetchPublicCctvCameras(forceRefresh) {
        try {
            DOM.cctvCountBadge.textContent = "Đang tải danh mục...";
            const provider = state.cctvProvider || "seattle";
            const refreshParam = forceRefresh ? "&refresh=true" : "";
            const url = apiUrl(`/api/public_cameras?provider=${encodeURIComponent(provider)}${refreshParam}`);
            const fetchStart = performance.now();
            const resp = await fetch(url);
            if (resp.ok) {
                const data = await resp.json();
                state.cctvCameras = data.cameras || [];
                const providerLabel = provider === "seattle" ? "Seattle SDOT" : "Caltrans";
                DOM.cctvCountBadge.textContent = `Hiển thị ${state.cctvCameras.length} camera (${providerLabel})`;

                if (window.dattLoadMetrics) {
                    window.dattLoadMetrics.catalogFetchedTime = performance.now();
                    const fetchElapsed = (window.dattLoadMetrics.catalogFetchedTime - fetchStart).toFixed(1);
                    console.log(`[DATT Perf] CCTV metadata (${provider}) fetched in ${fetchElapsed} ms`);
                }

                renderCctvCards(state.cctvCameras);
            } else {
                DOM.cctvCountBadge.textContent = "Lỗi tải camera";
                DOM.cctvCardsGrid.innerHTML = `
                    <div class="cards-loading-state">
                        <p style="color:#ef4444;">⚠️ Không thể tải danh mục camera CCTV. Vui lòng bấm làm mới.</p>
                    </div>`;
            }
        } catch (err) {
            DOM.cctvCountBadge.textContent = "Lỗi kết nối";
            DOM.cctvCardsGrid.innerHTML = `
                <div class="cards-loading-state">
                    <p style="color:#ef4444;">⚠️ Lỗi kết nối mạng: ${err.message}</p>
                </div>`;
        }
    }

    /**
     * Render CCTV Cards in Responsive Grid with Lazy-Loaded Thumbnails.
     */
    function renderCctvCards(cameras) {
        if (!cameras || cameras.length === 0) {
            DOM.cctvCardsGrid.innerHTML = `
                <div class="cards-loading-state">
                    <p>Không tìm thấy camera nào phù hợp với từ khóa.</p>
                </div>`;
            return;
        }

        const providerDefault = state.cctvProvider === "seattle" ? "Seattle SDOT" : "Caltrans";

        DOM.cctvCardsGrid.innerHTML = cameras.map(cam => {
            const safeName = escapeHtml(cam.name);
            const safeId = escapeHtml(cam.id);
            const safeStream = escapeHtml(cam.stream_url);
            const safeSnapshot = escapeHtml(cam.snapshot_url || "");
            const provider = escapeHtml(cam.provider || providerDefault);
            const sourceType = escapeHtml(cam.source_type || "direct_hls");
            const resBadge = cam.resolution ? `<span class="cctv-tag font-mono">${escapeHtml(cam.resolution)}</span>` : "";

            // Use lightweight server-cached thumbnail endpoint with HLS 1-frame fallback
            const thumbUrl = `/api/camera_thumbnail?camera_id=${encodeURIComponent(cam.id)}&provider=${encodeURIComponent(provider)}&snapshot_url=${encodeURIComponent(cam.snapshot_url || '')}&stream_url=${encodeURIComponent(cam.stream_url || '')}`;

            return `
                <div class="cctv-card" id="card_${safeId}">
                    <div class="cctv-thumb-box">
                        <img src="${PLACEHOLDER_THUMBNAIL}"
                             data-src="${thumbUrl}"
                             alt="${safeName}"
                             class="cctv-thumb-img"
                             loading="lazy"
                             onerror="this.onerror=null;this.src='${PLACEHOLDER_THUMBNAIL}';">
                        <div class="cctv-status-badge">
                            <span class="pulse-dot"></span> LIVE
                        </div>
                    </div>
                    <div class="cctv-card-body">
                        <h4 class="cctv-card-title">${safeName}</h4>
                        <div class="cctv-meta-row">
                            <span>Provider: <strong>${provider}</strong></span>
                            ${resBadge}
                            <span class="cctv-tag">${sourceType}</span>
                        </div>
                        <div class="cctv-card-actions">
                            <button type="button" class="btn-preview-card"
                                    onclick="window.dattPreviewCamera('${safeId}', '${safeName}', '${safeStream}', '${safeSnapshot}', '${provider}', '${sourceType}')">
                                👁️ Xem thử
                            </button>
                            <button type="button" class="btn-select-card"
                                    onclick="window.dattSelectCamera('${safeName}', '${safeStream}', '${sourceType}', '${provider}')">
                                ▶️ Chọn
                            </button>
                        </div>
                    </div>
                </div>
            `;
        }).join("");

        // Setup lazy loading for visible thumbnails
        setupThumbnailObserver();

        if (window.dattLoadMetrics) {
            window.dattLoadMetrics.cardsRenderedTime = performance.now();
            const totalElapsed = (window.dattLoadMetrics.cardsRenderedTime - window.dattLoadMetrics.startTime).toFixed(1);
            console.log(`[DATT Perf] Initial CCTV cards rendered in ${totalElapsed} ms`);
        }
    }

    /**
     * Real-time Local Search Filter for CCTV Cards.
     */
    function initSearch() {
        DOM.cctvSearchInput.addEventListener("input", (e) => {
            const query = e.target.value.trim().toLowerCase();
            if (!query) {
                DOM.cctvCountBadge.textContent = `Hiển thị ${state.cctvCameras.length} camera`;
                renderCctvCards(state.cctvCameras);
                return;
            }

            const filtered = state.cctvCameras.filter(c => {
                const name = (c.name || "").toLowerCase();
                const streamName = (c.stream_name || "").toLowerCase();
                const district = (c.district || "").toLowerCase();
                const county = (c.county || "").toLowerCase();
                const city = (c.city || "").toLowerCase();
                return (
                    name.includes(query) ||
                    streamName.includes(query) ||
                    district.includes(query) ||
                    county.includes(query) ||
                    city.includes(query)
                );
            });

            DOM.cctvCountBadge.textContent = `Tìm thấy ${filtered.length} / ${state.cctvCameras.length} camera`;
            renderCctvCards(filtered);
        });

        DOM.refreshCatalogBtn.addEventListener("click", () => {
            fetchPublicCctvCameras(true);
        });
    }

    /**
     * Preview Modal Controller (Snapshot first, optional live stream).
     */
    window.dattPreviewCamera = function (id, name, streamUrl, snapshotUrl, provider, sourceType) {
        state.previewingCamera = { id, name, streamUrl, snapshotUrl, provider, sourceType };
        state.isPreviewLive = false;

        DOM.previewModalTitle.textContent = `Xem trước: ${name}`;
        DOM.previewBadgeProvider.textContent = provider || "Caltrans";
        DOM.previewStreamUrl.textContent = streamUrl || "--";
        DOM.previewSourceType.textContent = sourceType || "Direct HLS";

        // Snapshot first
        DOM.previewStream.style.display = "none";
        DOM.previewStream.src = "";
        DOM.previewImage.style.display = "block";
        DOM.previewSpinner.style.display = "none";
        DOM.toggleLiveText.textContent = "Phát trực tiếp";

        const proxySnapshot = snapshotUrl ? `/api/camera_snapshot?url=${encodeURIComponent(snapshotUrl)}` : "";
        DOM.previewImage.src = proxySnapshot || "/static/favicon.ico";

        DOM.previewModal.style.display = "flex";
    };

    async function closePreview() {
        DOM.previewModal.style.display = "none";
        DOM.previewStream.src = "";
        DOM.previewStream.style.display = "none";
        state.isPreviewLive = false;
        state.previewingCamera = null;

        // Clean up preview resources on backend
        try {
            await fetch(apiUrl("/api/stop_preview"), { method: "POST" });
        } catch (e) {
            // suppress
        }
    }

    async function toggleLivePreview() {
        if (!state.previewingCamera || !state.previewingCamera.streamUrl) return;

        if (!state.isPreviewLive) {
            // Switch to Live Preview
            state.isPreviewLive = true;
            DOM.previewImage.style.display = "none";
            DOM.previewStream.style.display = "block";
            DOM.previewSpinner.style.display = "flex";
            DOM.previewLoadingText.textContent = "Đang kết nối luồng xem trước...";
            DOM.toggleLiveText.textContent = "Xem ảnh chụp (Snapshot)";

            DOM.previewStream.onload = () => {
                DOM.previewSpinner.style.display = "none";
            };

            const streamUrl = state.previewingCamera.streamUrl;
            const provider = state.previewingCamera.provider || "";
            DOM.previewStream.src = `/api/preview_feed?url=${encodeURIComponent(streamUrl)}&provider=${encodeURIComponent(provider)}&t=${Date.now()}`;
        } else {
            // Switch back to Snapshot
            state.isPreviewLive = false;
            DOM.previewStream.style.display = "none";
            DOM.previewStream.src = "";
            DOM.previewImage.style.display = "block";
            DOM.previewSpinner.style.display = "none";
            DOM.toggleLiveText.textContent = "Phát trực tiếp";

            try {
                await fetch(apiUrl("/api/stop_preview"), { method: "POST" });
            } catch (e) {}
        }
    }

    /**
     * Primary Camera Selection & Connection Verification Sequence.
     * Criteria: frames_received > 0, frame_age_seconds < 5.0, stream_alive is true.
     */
    window.dattSelectCamera = async function (name, streamUrl, sourceType, provider) {
        await closePreview();

        const sourceData = {
            name: name,
            source: streamUrl,
            stream_url: streamUrl,
            source_type: sourceType || "direct_hls",
            provider: provider || "Caltrans"
        };
        state.connectingSourceData = sourceData;

        // Transition to CONNECTING state
        setUiState(UI_STATE.CONNECTING, { name: name });

        try {
            // 1. Tell backend to stop old source & start new source
            const resp = await fetch(apiUrl("/api/select_source"), {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    source_type: sourceData.source_type,
                    source: sourceData.source,
                    url: sourceData.source,
                    name: sourceData.name,
                    provider: sourceData.provider
                })
            });

            if (!resp.ok) {
                const errData = await resp.json().catch(() => ({}));
                setUiState(UI_STATE.ERROR, {
                    message: "Không thể gửi yêu cầu kết nối camera tới máy chủ.",
                    debug: errData.message || resp.statusText
                });
                return;
            }

            DOM.badgeStepReader.className = "status-pill active-step";

            // 2. Poll /api/source_status until verified or timeout
            pollConnectionVerification(sourceData);

        } catch (err) {
            setUiState(UI_STATE.ERROR, {
                message: "Lỗi mạng khi kết nối camera.",
                debug: err.message
            });
        }
    };

    function pollConnectionVerification(sourceData) {
        stopConnectionPolling();
        const startConnectTime = Date.now();

        state.connectionTimer = setInterval(async () => {
            const elapsed = Date.now() - startConnectTime;

            // Timeout check
            if (elapsed > CONFIG.connectionTimeoutMs) {
                stopConnectionPolling();
                setUiState(UI_STATE.ERROR, {
                    message: `Không nhận được khung hình từ camera "${sourceData.name}" sau 15 giây.`,
                    debug: "Connection verification timed out (first frame not arrived)"
                });
                return;
            }

            try {
                const resp = await fetch(apiUrl("/api/source_status"));
                if (resp.ok) {
                    const data = await resp.json();

                    // Step badge updates
                    if (data.status === "RUNNING" || data.status === "SWITCHING") {
                        DOM.badgeStepReader.className = "status-pill active-step";
                    }
                    if (data.frames_received > 0) {
                        DOM.badgeStepFrame.className = "status-pill active-step";
                    }

                    // Successful Connection Criteria:
                    // 1. frames_received > 0
                    // 2. frame_age_seconds is recent (< 5.0s)
                    // 3. stream_alive is true
                    // 4. status is RUNNING
                    const framesOk = (data.frames_received > 0);
                    const ageOk = (data.frame_age_seconds <= 5.0);
                    const aliveOk = (data.stream_alive === true);
                    const statusOk = (data.status === "RUNNING");

                    if (framesOk && ageOk && aliveOk && statusOk) {
                        DOM.badgeStepAi.className = "status-pill active-step";
                        stopConnectionPolling();

                        // Short delay to let AI pipeline finish first inference frame cleanly
                        setTimeout(() => {
                            setUiState(UI_STATE.MONITORING, {
                                name: sourceData.name,
                                provider: sourceData.provider,
                                source_type: sourceData.source_type
                            });
                        }, 400);
                        return;
                    }

                    if (data.status === "VIDEO_FINISHED") {
                        stopConnectionPolling();
                        setUiState(UI_STATE.MONITORING, {
                            name: sourceData.name,
                            provider: sourceData.provider,
                            source_type: sourceData.source_type
                        });
                        return;
                    }

                    if (data.status === "ERROR") {
                        stopConnectionPolling();
                        const reason = data.error_reason || "Mất kết nối luồng";
                        const isAuth = reason.includes("AUTH/ANTI_BOT") || reason.toLowerCase().includes("not a bot");
                        setUiState(UI_STATE.ERROR, {
                            message: isAuth
                                ? `YouTube yêu cầu xác minh bot ("Sign in to confirm you're not a bot"). Đã dừng kết nối và không retry.`
                                : `Camera báo lỗi: ${reason}`,
                            debug: reason
                        });
                        return;
                    }
                }
            } catch (err) {
                // Ignore transient network blips during polling
            }
        }, CONFIG.sourceStatusPollMs);
    }

    /**
     * Stop Camera & Return to Selection.
     */
    async function stopActiveCameraAndReturn() {
        try {
            await fetch(apiUrl("/api/stop_camera"), { method: "POST" });
        } catch (e) {}

        state.activeCameraId = "";
        state.activeCameraName = "";
        state.connectingSourceData = null;
        setUiState(UI_STATE.SELECT_CAMERA);
    }

    /**
     * Manual Direct HLS Tab Setup.
     */
    function initDirectHlsTab() {
        DOM.btnPreviewDirectHls.addEventListener("click", () => {
            const url = DOM.hlsCustomUrl.value.trim();
            const name = DOM.hlsCustomName.value.trim() || "Custom HLS Camera";
            if (!url) {
                DOM.hlsCustomFeedback.className = "feedback-msg error";
                DOM.hlsCustomFeedback.textContent = "Vui lòng nhập URL stream HLS (.m3u8).";
                return;
            }
            DOM.hlsCustomFeedback.textContent = "";
            window.dattPreviewCamera("custom_hls", name, url, "", "Direct HLS", "direct_hls");
        });

        DOM.btnConnectDirectHls.addEventListener("click", () => {
            const url = DOM.hlsCustomUrl.value.trim();
            const name = DOM.hlsCustomName.value.trim() || "Custom HLS Camera";
            if (!url) {
                DOM.hlsCustomFeedback.className = "feedback-msg error";
                DOM.hlsCustomFeedback.textContent = "Vui lòng nhập URL stream HLS (.m3u8).";
                return;
            }
            DOM.hlsCustomFeedback.textContent = "";
            window.dattSelectCamera(name, url, "direct_hls", "Direct HLS");
        });
    }

    /**
     * YouTube Live Tab Setup.
     */
    async function fetchConfigCameras() {
        try {
            const resp = await fetch(apiUrl("/cameras"));
            if (resp.ok) {
                const data = await resp.json();
                const cameras = data.cameras || [];

                DOM.ytPresetSelect.innerHTML = '<option value="">-- Chọn camera định cấu hình sẵn --</option>';
                cameras.forEach(c => {
                    const opt = document.createElement("option");
                    opt.value = c.id;
                    opt.textContent = `${c.name} (${c.type})`;
                    opt.dataset.url = c.url;
                    opt.dataset.name = c.name;
                    opt.dataset.type = c.type;
                    DOM.ytPresetSelect.appendChild(opt);
                });

                // Also populate sidebar select
                DOM.cameraSelect.innerHTML = "";
                cameras.forEach(c => {
                    const opt = document.createElement("option");
                    opt.value = c.id;
                    opt.textContent = `${c.name} (${c.type})`;
                    DOM.cameraSelect.appendChild(opt);
                });
            }
        } catch (e) {}
    }

    function initYouTubeTab() {
        DOM.ytPresetSelect.addEventListener("change", (e) => {
            const selectedOpt = e.target.selectedOptions[0];
            if (selectedOpt && selectedOpt.dataset.url) {
                DOM.ytCustomName.value = selectedOpt.dataset.name || "";
                DOM.ytCustomUrl.value = selectedOpt.dataset.url || "";
            }
        });

        DOM.btnPreviewYouTube.addEventListener("click", () => {
            const url = DOM.ytCustomUrl.value.trim();
            const name = DOM.ytCustomName.value.trim() || "YouTube Stream";
            if (!url) {
                DOM.ytFeedback.className = "feedback-msg error";
                DOM.ytFeedback.textContent = "Vui lòng chọn hoặc nhập liên kết YouTube.";
                return;
            }
            DOM.ytFeedback.textContent = "";
            window.dattPreviewCamera("custom_yt", name, url, "", "YouTube", "youtube");
        });

        DOM.btnConnectYouTube.addEventListener("click", () => {
            const url = DOM.ytCustomUrl.value.trim();
            const name = DOM.ytCustomName.value.trim() || "YouTube Stream";
            if (!url) {
                DOM.ytFeedback.className = "feedback-msg error";
                DOM.ytFeedback.textContent = "Vui lòng chọn hoặc nhập liên kết YouTube.";
                return;
            }
            DOM.ytFeedback.textContent = "";
            window.dattSelectCamera(name, url, "youtube", "YouTube Live");
        });
    }

    /**
     * Local Video Tab Setup (Real Browser File Upload Flow).
     */
    function initLocalVideoTab() {
        let selectedFile = null;

        function formatBytes(bytes) {
            if (bytes === 0) return "0 Bytes";
            const k = 1024;
            const sizes = ["Bytes", "KB", "MB", "GB"];
            const i = Math.floor(Math.log(bytes) / Math.log(k));
            return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + " " + sizes[i];
        }

        function handleFileSelection(file) {
            if (!file) return;
            const allowed = [".mp4", ".mov", ".mkv", ".avi"];
            const ext = "." + file.name.split(".").pop().toLowerCase();
            if (!allowed.includes(ext)) {
                if (DOM.localFeedback) {
                    DOM.localFeedback.className = "feedback-msg error";
                    DOM.localFeedback.textContent = `Định dạng tệp "${ext}" không được hỗ trợ. Vui lòng chọn MP4, MOV, MKV hoặc AVI.`;
                }
                return;
            }

            selectedFile = file;
            if (DOM.localFileNameText) DOM.localFileNameText.textContent = file.name;
            if (DOM.localFileSizeText) DOM.localFileSizeText.textContent = formatBytes(file.size);
            if (DOM.localFileStatusBadge) {
                DOM.localFileStatusBadge.textContent = "Sẵn sàng upload";
                DOM.localFileStatusBadge.className = "file-status-badge";
            }
            if (DOM.localFileInfoCard) DOM.localFileInfoCard.style.display = "block";
            if (DOM.uploadProgressBarContainer) DOM.uploadProgressBarContainer.style.display = "none";
            if (DOM.uploadProgressBarFill) DOM.uploadProgressBarFill.style.width = "0%";
            if (DOM.uploadProgressText) DOM.uploadProgressText.textContent = "0%";
            if (DOM.btnUploadAndConnect) DOM.btnUploadAndConnect.disabled = false;
            if (DOM.localFeedback) DOM.localFeedback.textContent = "";
        }

        if (DOM.btnBrowseVideo) {
            DOM.btnBrowseVideo.addEventListener("click", () => {
                if (DOM.localVideoFileInput) DOM.localVideoFileInput.click();
            });
        }

        if (DOM.localVideoFileInput) {
            DOM.localVideoFileInput.addEventListener("change", (e) => {
                const file = e.target.files[0];
                handleFileSelection(file);
            });
        }

        if (DOM.localUploadDropzone) {
            DOM.localUploadDropzone.addEventListener("dragover", (e) => {
                e.preventDefault();
                DOM.localUploadDropzone.classList.add("dragover");
            });

            DOM.localUploadDropzone.addEventListener("dragleave", (e) => {
                e.preventDefault();
                DOM.localUploadDropzone.classList.remove("dragover");
            });

            DOM.localUploadDropzone.addEventListener("drop", (e) => {
                e.preventDefault();
                DOM.localUploadDropzone.classList.remove("dragover");
                if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
                    handleFileSelection(e.dataTransfer.files[0]);
                }
            });
        }

        if (DOM.btnUploadAndConnect) {
            DOM.btnUploadAndConnect.addEventListener("click", () => {
                if (!selectedFile) {
                    if (DOM.localFeedback) {
                        DOM.localFeedback.className = "feedback-msg error";
                        DOM.localFeedback.textContent = "Vui lòng chọn tệp video trước khi upload.";
                    }
                    return;
                }

                DOM.btnUploadAndConnect.disabled = true;
                if (DOM.uploadProgressBarContainer) DOM.uploadProgressBarContainer.style.display = "flex";
                if (DOM.uploadProgressBarFill) DOM.uploadProgressBarFill.style.width = "0%";
                if (DOM.uploadProgressText) DOM.uploadProgressText.textContent = "0%";
                if (DOM.localFileStatusBadge) {
                    DOM.localFileStatusBadge.textContent = "Đang tải lên...";
                    DOM.localFileStatusBadge.className = "file-status-badge uploading";
                }
                if (DOM.localFeedback) DOM.localFeedback.textContent = "";

                const formData = new FormData();
                formData.append("file", selectedFile);

                const xhr = new XMLHttpRequest();
                xhr.open("POST", apiUrl("/api/upload_video"), true);

                xhr.upload.onprogress = (event) => {
                    if (event.lengthComputable) {
                        const percent = Math.round((event.loaded / event.total) * 100);
                        if (DOM.uploadProgressBarFill) DOM.uploadProgressBarFill.style.width = `${percent}%`;
                        if (DOM.uploadProgressText) DOM.uploadProgressText.textContent = `${percent}%`;
                    }
                };

                xhr.onload = () => {
                    if (xhr.status === 200) {
                        try {
                            const res = JSON.parse(xhr.responseText);
                            if (res.status === "ok") {
                                if (DOM.localFileStatusBadge) {
                                    DOM.localFileStatusBadge.textContent = "Upload thành công ✓";
                                    DOM.localFileStatusBadge.className = "file-status-badge success";
                                }
                                if (DOM.uploadProgressBarFill) DOM.uploadProgressBarFill.style.width = "100%";
                                if (DOM.uploadProgressText) DOM.uploadProgressText.textContent = "100%";

                                // Trigger camera selection with server path
                                const displayName = `Local: ${res.filename || selectedFile.name}`;
                                window.dattSelectCamera(displayName, res.server_path, "local", "Local Video");
                                return;
                            }
                        } catch (e) {}
                    }

                    // Error handling
                    DOM.btnUploadAndConnect.disabled = false;
                    if (DOM.localFileStatusBadge) {
                        DOM.localFileStatusBadge.textContent = "Upload thất bại ✗";
                        DOM.localFileStatusBadge.className = "file-status-badge error";
                    }
                    let errorMsg = "Tải tệp video thất bại.";
                    try {
                        const err = JSON.parse(xhr.responseText);
                        if (err.message) errorMsg = err.message;
                    } catch (e) {}
                    if (DOM.localFeedback) {
                        DOM.localFeedback.className = "feedback-msg error";
                        DOM.localFeedback.textContent = errorMsg;
                    }
                };

                xhr.onerror = () => {
                    DOM.btnUploadAndConnect.disabled = false;
                    if (DOM.localFileStatusBadge) {
                        DOM.localFileStatusBadge.textContent = "Lỗi kết nối ✗";
                        DOM.localFileStatusBadge.className = "file-status-badge error";
                    }
                    if (DOM.localFeedback) {
                        DOM.localFeedback.className = "feedback-msg error";
                        DOM.localFeedback.textContent = "Lỗi mạng khi tải lên tệp video.";
                    }
                };

                xhr.send(formData);
            });
        }
    }

    /**
     * Preview Modal Actions Setup.
     */
    function initPreviewModal() {
        DOM.closePreviewBtn.addEventListener("click", closePreview);
        DOM.btnCancelPreview.addEventListener("click", closePreview);
        DOM.btnToggleLivePreview.addEventListener("click", toggleLivePreview);

        DOM.btnConfirmSelectCamera.addEventListener("click", () => {
            if (state.previewingCamera) {
                const cam = state.previewingCamera;
                window.dattSelectCamera(cam.name, cam.streamUrl, cam.sourceType, cam.provider);
            }
        });

        // Close on escape key
        document.addEventListener("keydown", (e) => {
            if (e.key === "Escape" && DOM.previewModal.style.display !== "none") {
                closePreview();
            }
        });
    }

    /**
     * Error & Retrying Actions Setup.
     */
    function initErrorActions() {
        DOM.btnRetryConnection.addEventListener("click", () => {
            if (state.connectingSourceData) {
                const d = state.connectingSourceData;
                window.dattSelectCamera(d.name, d.source, d.source_type, d.provider);
            } else {
                setUiState(UI_STATE.SELECT_CAMERA);
            }
        });

        DOM.btnBackToSelection.addEventListener("click", () => {
            setUiState(UI_STATE.SELECT_CAMERA);
        });

        // Switch camera button from monitoring dashboard
        DOM.btnSwitchCameraFromDash.addEventListener("click", stopActiveCameraAndReturn);
    }

    /**
     * Video Stream MJPEG Reconnect Logic.
     */
    function triggerVideoRefresh() {
        if (!DOM.videoFeed) return;
        DOM.videoErrorOverlay.style.display = "none";
        DOM.videoFeed.src = `/video_feed?t=${Date.now()}`;
    }

    function setupVideoStream() {
        if (!DOM.videoFeed) return;

        DOM.videoFeed.onerror = function () {
            DOM.videoErrorOverlay.style.display = "flex";
            if (!state.videoReconnectTimer) {
                state.videoReconnectTimer = setTimeout(() => {
                    state.videoReconnectTimer = null;
                    if (state.uiState === UI_STATE.MONITORING) {
                        triggerVideoRefresh();
                    }
                }, CONFIG.videoReconnectDelayMs);
            }
        };

        DOM.videoFeed.onload = function () {
            DOM.videoErrorOverlay.style.display = "none";
            if (state.videoReconnectTimer) {
                clearTimeout(state.videoReconnectTimer);
                state.videoReconnectTimer = null;
            }
        };
    }

    /**
     * Poll Realtime AI Telemetry.
     */
    async function pollTelemetry() {
        const startTime = performance.now();
        try {
            const response = await fetch(apiUrl("/telemetry"), {
                headers: { "Accept": "application/json" }
            });
            const latencyMs = Math.round(performance.now() - startTime);
            DOM.pingLatency.textContent = `${latencyMs} ms`;

            if (response.ok) {
                const data = await response.json();
                state.consecutiveErrors = 0;
                applyTelemetry(data);
            } else {
                handleTelemetryError();
            }
        } catch (err) {
            handleTelemetryError();
        }
    }

    function applyTelemetry(data) {
        const status = state.isSwitchingCamera ? "SWITCHING" : (data.camera_status || data.status || "DISCONNECTED");
        updateStatus(status, data.error_message);

        const camName = data.camera_name || data.camera_id || state.activeCameraName || "Camera";
        DOM.telemActiveCam.textContent = camName;
        DOM.streamCamName.textContent = `Camera: ${camName}`;
        DOM.streamResolution.textContent = data.input_size || "640x640";

        DOM.metricPeopleCount.textContent = data.people_count !== undefined ? data.people_count : 0;
        if (DOM.metricCarCount) {
            DOM.metricCarCount.textContent = data.car_count !== undefined ? data.car_count : 0;
        }
        DOM.metricDetections.textContent = data.detection_count || 0;
        DOM.metricTracks.textContent = data.track_count || 0;
        DOM.metricProcessingFps.textContent = Number(data.processing_fps || 0).toFixed(1);
        DOM.metricStreamFps.textContent = Number(data.stream_fps || 0).toFixed(1);
        DOM.metricYoloLatency.textContent = `${Number(data.yolo_latency_ms || 0).toFixed(1)} ms`;
        DOM.metricPipelineLatency.textContent = `${Number(data.pipeline_latency_ms || 0).toFixed(1)} ms`;

        DOM.infoDevice.textContent = data.device || "CPU";
        DOM.infoGpu.textContent = data.gpu_name || "N/A";
        DOM.infoVram.textContent = `${Number(data.vram_mb || 0).toFixed(1)} MB`;
        DOM.infoModel.textContent = `${data.model_name || "YOLO11s"} (${data.input_size || "640x640"})`;

        DOM.infoEventsToday.textContent = data.event_count_today || 0;
        DOM.infoFilteredEvents.textContent = data.filtered_event_count || 0;
        DOM.infoLastSavedCount.textContent = data.last_saved_people_count || 0;
        DOM.infoLastEvent.textContent = data.last_event_time || data.last_event || "None";
    }

    function handleTelemetryError() {
        state.consecutiveErrors++;
        DOM.pingLatency.textContent = "-- ms";
        if (state.consecutiveErrors >= 3) {
            updateStatus("DISCONNECTED", "AI Server connection lost");
        }
    }

    function updateStatus(status, errorMessage) {
        const cleanStatus = (status || "DISCONNECTED").toUpperCase();

        DOM.statusBadge.textContent = `STATUS: ${cleanStatus}`;
        DOM.statusBadge.className = `status-badge status-${cleanStatus.toLowerCase()}`;
        DOM.sidebarConnStatus.textContent = cleanStatus;
        DOM.sidebarConnStatus.className = `badge badge-${cleanStatus.toLowerCase()}`;

        if (cleanStatus === "ERROR") {
            DOM.alertBanner.style.display = "block";
            DOM.alertBanner.className = "alert-banner alert-error";
            const isAuth = (errorMessage || "").includes("AUTH/ANTI_BOT") || (errorMessage || "").toLowerCase().includes("not a bot");
            if (isAuth) {
                DOM.alertBanner.innerHTML = `⛔ <strong>Lỗi AUTH/ANTI_BOT:</strong> YouTube yêu cầu xác minh bot ("Sign in to confirm you're not a bot"). Đã dừng kết nối.`;
            } else {
                DOM.alertBanner.innerHTML = `⚠️ <strong>Camera Status: ERROR</strong> — ${errorMessage || "Stream ended or camera disconnected unexpectedly."}`;
            }
        } else if (cleanStatus === "VIDEO_FINISHED") {
            DOM.alertBanner.style.display = "block";
            DOM.alertBanner.className = "alert-banner alert-info";
            DOM.alertBanner.innerHTML = `🏁 <strong>Video đã phát xong (VIDEO_FINISHED).</strong>`;
        } else if (cleanStatus === "WARNING") {
            DOM.alertBanner.style.display = "block";
            DOM.alertBanner.className = "alert-banner alert-warning";
            DOM.alertBanner.innerHTML = `⚠️ <strong>Camera Warning:</strong> ${errorMessage || "Frame delay detected (>5s)..."}`;
        } else if (cleanStatus === "DISCONNECTED") {
            DOM.alertBanner.style.display = "block";
            DOM.alertBanner.className = "alert-banner alert-warning";
            DOM.alertBanner.innerHTML = `📡 <strong>Connecting to AI pipeline...</strong> Ensure <code>python src/main.py</code> is running.`;
        } else {
            DOM.alertBanner.style.display = "none";
        }
    }

    /**
     * Poll Recent Occupancy Events.
     */
    async function pollEvents() {
        try {
            const response = await fetch(apiUrl("/events?limit=5"));
            if (response.ok) {
                const data = await response.json();
                renderEvents(data.events || []);
            }
        } catch (err) {}
    }

    function renderEvents(events) {
        const jsonStr = JSON.stringify(events);
        if (jsonStr === state.lastEventsJson) return;
        state.lastEventsJson = jsonStr;

        if (!events || events.length === 0) {
            DOM.eventsContainer.innerHTML = '<div class="events-empty">No occupancy change events logged yet today.</div>';
            return;
        }

        DOM.eventsContainer.innerHTML = events.slice(0, 5).map(ev => {
            const countDiff = ev.new_count - ev.old_count;
            const diffClass = countDiff > 0 ? "event-badge-increase" : "event-badge-decrease";
            const diffSign = countDiff > 0 ? `+${countDiff}` : `${countDiff}`;
            const timeStr = formatEventTime(ev.timestamp);
            const snapshotUrl = ev.snapshot_path
                ? apiUrl(`/event_snapshot?path=${encodeURIComponent(ev.snapshot_path)}`)
                : (ev.id ? apiUrl(`/event_snapshot?id=${encodeURIComponent(ev.id)}`) : "");

            return `
                <div class="event-card">
                    <div class="event-thumb-wrapper">
                        ${snapshotUrl
                            ? `<img class="event-thumb" src="${snapshotUrl}" alt="Event ${ev.id}" loading="lazy" onerror="this.parentElement.innerHTML='<div class=\\'event-thumb-placeholder\\'>📷 No Image</div>';">`
                            : `<div class="event-thumb-placeholder">📷 No Image</div>`}
                    </div>
                    <div class="event-details">
                        <div class="event-top-row">
                            <span class="event-badge ${diffClass}">${diffSign} People</span>
                            <span class="event-time">${timeStr}</span>
                        </div>
                        <div class="event-count-flow">
                            <span class="count-old">${ev.old_count}</span>
                            <span class="count-arrow">→</span>
                            <span class="count-new">${ev.new_count}</span>
                        </div>
                        <div class="event-meta">
                            <span>ID: #${ev.id}</span>
                            <span>Cam: ${escapeHtml(ev.camera_id || "cam")}</span>
                        </div>
                    </div>
                </div>
            `;
        }).join("");
    }

    function formatEventTime(timestamp) {
        if (!timestamp) return "Just now";
        try {
            const date = new Date(timestamp * 1000);
            return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
        } catch (e) {
            return "Just now";
        }
    }

    /**
     * Target Registration & Management.
     */
    async function loadTargets() {
        try {
            const resp = await fetch(apiUrl("/api/targets"));
            if (resp.ok) {
                const data = await resp.json();
                renderTargets(data.targets || []);
            }
        } catch (e) {}
    }

    function renderTargets(targets) {
        DOM.targetCount.textContent = targets.length;
        if (targets.length === 0) {
            DOM.targetsList.innerHTML = '<div class="target-item-empty">No active targets registered.</div>';
            return;
        }

        DOM.targetsList.innerHTML = targets.map(t => {
            const colorBadge = t.clothing_color ? `<span class="target-badge badge-color">${escapeHtml(t.clothing_color)}</span>` : "";
            const faceBadge = t.has_face_feature ? `<span class="target-badge badge-face">Face ID</span>` : "";
            return `
                <div class="target-item">
                    <div class="target-info">
                        <span class="target-name">${escapeHtml(t.name)}</span>
                        <div class="target-badges">${faceBadge}${colorBadge}</div>
                    </div>
                    <button type="button" class="target-del-btn" title="Remove Target" onclick="window.dattDeleteTarget('${escapeHtml(t.id)}')">✖</button>
                </div>
            `;
        }).join("");
    }

    window.dattDeleteTarget = async function(targetId) {
        try {
            const resp = await fetch(apiUrl(`/api/targets/${encodeURIComponent(targetId)}`), {
                method: "DELETE"
            });
            if (resp.ok) {
                await loadTargets();
            }
        } catch (err) {}
    };

    async function registerTarget() {
        const name = DOM.targetNameInput.value.trim();
        const color = DOM.targetColorSelect.value;
        const file = DOM.targetFaceInput.files[0];

        if (!name) {
            DOM.targetFeedback.className = "feedback-msg error";
            DOM.targetFeedback.textContent = "Target name is required.";
            return;
        }

        const formData = new FormData();
        formData.append("name", name);
        if (color) formData.append("color", color);
        if (file) formData.append("face_image", file);

        DOM.registerTargetBtn.disabled = true;
        DOM.targetFeedback.className = "feedback-msg";
        DOM.targetFeedback.textContent = "Registering...";

        try {
            const resp = await fetch(apiUrl("/api/register_target"), {
                method: "POST",
                body: formData
            });
            const data = await resp.json();
            if (resp.ok && data.status === "ok") {
                DOM.targetFeedback.className = "feedback-msg success";
                DOM.targetFeedback.textContent = `Registered: ${data.target.name}`;
                DOM.targetNameInput.value = "";
                DOM.targetFaceInput.value = "";
                DOM.targetFaceFilename.textContent = "Face Image (Optional)";
                await loadTargets();
            } else {
                DOM.targetFeedback.className = "feedback-msg error";
                DOM.targetFeedback.textContent = data.message || "Registration failed.";
            }
        } catch (err) {
            DOM.targetFeedback.className = "feedback-msg error";
            DOM.targetFeedback.textContent = `Error: ${err.message}`;
        } finally {
            DOM.registerTargetBtn.disabled = false;
        }
    }

    function escapeHtml(str) {
        if (!str) return "";
        return String(str)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    /**
     * Initial App Launch Sequence.
     * Check if camera is already running; if not, open on Camera Selection screen.
     */
    async function checkInitialAppState() {
        try {
            const resp = await fetch(apiUrl("/api/source_status"));
            if (resp.ok) {
                const data = await resp.json();
                if (data.is_ready && data.status === "RUNNING") {
                    setUiState(UI_STATE.MONITORING, {
                        name: (data.camera && data.camera.name) || "Live Camera",
                        provider: "System",
                        source_type: (data.camera && data.camera.type) || "Stream"
                    });
                    return;
                }
            }
        } catch (e) {}

        // Default: Open on Camera Selection
        setUiState(UI_STATE.SELECT_CAMERA);
    }

    /**
     * Application Initialization.
     */
    function init() {
        initTabs();
        initProviderSelector();
        initSearch();
        initDirectHlsTab();
        initYouTubeTab();
        initLocalVideoTab();
        initPreviewModal();
        initErrorActions();
        setupVideoStream();

        if (DOM.registerTargetBtn) {
            DOM.registerTargetBtn.addEventListener("click", registerTarget);
        }

        if (DOM.targetFaceInput) {
            DOM.targetFaceInput.addEventListener("change", (e) => {
                const file = e.target.files[0];
                DOM.targetFaceFilename.textContent = file ? file.name : "Face Image (Optional)";
            });
        }

        checkInitialAppState();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
