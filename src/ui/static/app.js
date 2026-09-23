/**
 * DATT AI Vision Monitor & Camera Manager - Frontend Client
 * Phase 4.4: Stable Browser-Based Monitoring Interface
 *
 * Rules:
 * - Pure Vanilla JavaScript (no frameworks)
 * - Restful polling: Telemetry (1000 ms), Events (10000 ms)
 * - In-place DOM updates only (no full dashboard recreation)
 * - Video stream auto-reconnect on disconnect (3-second retry)
 * - Lazy loaded event snapshot thumbnails
 */

(function () {
    "use strict";

    // Configuration & State
    const CONFIG = {
        telemetryIntervalMs: 1000,
        eventsIntervalMs: 10000,
        videoReconnectDelayMs: 3000,
        defaultBackendUrl: "http://localhost:8000"
    };

    const state = {
        backendUrl: CONFIG.defaultBackendUrl,
        activeCameraId: "",
        isSwitchingCamera: false,
        telemetryTimer: null,
        eventsTimer: null,
        videoReconnectTimer: null,
        lastEventsJson: "",
        consecutiveErrors: 0
    };

    // DOM Elements Cache
    const DOM = {
        backendUrlInput: document.getElementById("backendUrlInput"),
        cameraSelect: document.getElementById("cameraSelect"),
        switchCameraBtn: document.getElementById("switchCameraBtn"),
        cameraSwitchFeedback: document.getElementById("cameraSwitchFeedback"),
        sidebarConnStatus: document.getElementById("sidebarConnStatus"),
        pingLatency: document.getElementById("pingLatency"),
        statusBadge: document.getElementById("statusBadge"),
        alertBanner: document.getElementById("alertBanner"),

        // Video Elements
        videoFeed: document.getElementById("videoFeed"),
        videoErrorOverlay: document.getElementById("videoErrorOverlay"),
        streamCamName: document.getElementById("streamCamName"),
        streamResolution: document.getElementById("streamResolution"),

        // Telemetry Elements
        telemActiveCam: document.getElementById("telemActiveCam"),
        metricPeopleCount: document.getElementById("metricPeopleCount"),
        metricDetections: document.getElementById("metricDetections"),
        metricTracks: document.getElementById("metricTracks"),
        metricProcessingFps: document.getElementById("metricProcessingFps"),
        metricStreamFps: document.getElementById("metricStreamFps"),
        metricYoloLatency: document.getElementById("metricYoloLatency"),
        metricPipelineLatency: document.getElementById("metricPipelineLatency"),

        // Info Elements
        infoDevice: document.getElementById("infoDevice"),
        infoGpu: document.getElementById("infoGpu"),
        infoVram: document.getElementById("infoVram"),
        infoModel: document.getElementById("infoModel"),
        infoEventsToday: document.getElementById("infoEventsToday"),
        infoFilteredEvents: document.getElementById("infoFilteredEvents"),
        infoLastSavedCount: document.getElementById("infoLastSavedCount"),
        infoLastEvent: document.getElementById("infoLastEvent"),

        // Events Elements
        eventsContainer: document.getElementById("eventsContainer")
    };

    /**
     * Resolve API endpoint URL.
     * Uses relative path to hit FastAPI proxy, or appends backend query if configured.
     */
    function apiUrl(path) {
        return path;
    }

    /**
     * Update connection badges and status headers.
     */
    function updateStatus(status, errorMessage) {
        const cleanStatus = (status || "DISCONNECTED").toUpperCase();

        // Header status badge
        DOM.statusBadge.textContent = `STATUS: ${cleanStatus}`;
        DOM.statusBadge.className = `status-badge status-${cleanStatus.toLowerCase()}`;

        // Sidebar status badge
        DOM.sidebarConnStatus.textContent = cleanStatus;
        DOM.sidebarConnStatus.className = `badge badge-${cleanStatus.toLowerCase()}`;

        // Alert Banner
        if (cleanStatus === "ERROR") {
            DOM.alertBanner.style.display = "block";
            DOM.alertBanner.className = "alert-banner alert-error";
            DOM.alertBanner.innerHTML = `⚠️ <strong>Camera Status: ERROR</strong> — ${errorMessage || "Stream ended or camera disconnected unexpectedly."}`;
        } else if (cleanStatus === "WARNING") {
            DOM.alertBanner.style.display = "block";
            DOM.alertBanner.className = "alert-banner alert-warning";
            DOM.alertBanner.innerHTML = `⚠️ <strong>Camera Warning:</strong> ${errorMessage || "Frame delay detected (>5s)..."}`;
        } else if (cleanStatus === "DISCONNECTED") {
            DOM.alertBanner.style.display = "block";
            DOM.alertBanner.className = "alert-banner alert-warning";
            DOM.alertBanner.innerHTML = `📡 <strong>Connecting to AI pipeline...</strong> Ensure <code>python src/main.py</code> is running.`;
        } else if (cleanStatus === "SWITCHING") {
            DOM.alertBanner.style.display = "block";
            DOM.alertBanner.className = "alert-banner alert-warning";
            DOM.alertBanner.innerHTML = `🔄 <strong>Switching camera stream...</strong> Please wait.`;
        } else {
            // RUNNING: clear any alert banner cleanly
            DOM.alertBanner.style.display = "none";
        }
    }

    /**
     * Poll Realtime AI Telemetry (every 1000 ms).
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

    /**
     * Apply telemetry metrics cleanly into existing DOM elements.
     */
    function applyTelemetry(data) {
        // Prioritize camera_status from backend, falling back to status
        const status = state.isSwitchingCamera ? "SWITCHING" : (data.camera_status || data.status || "DISCONNECTED");
        updateStatus(status, data.error_message);

        // Active Camera Name
        const camName = data.camera_name || data.camera_id || "Camera";
        DOM.telemActiveCam.textContent = camName;
        DOM.streamCamName.textContent = `Camera: ${camName}`;
        DOM.streamResolution.textContent = data.input_size || "640x640";

        // Hero Metric: People in View
        DOM.metricPeopleCount.textContent = data.people_count !== undefined ? data.people_count : 0;

        // Secondary Metrics
        DOM.metricDetections.textContent = data.detection_count || 0;
        DOM.metricTracks.textContent = data.track_count || 0;
        DOM.metricProcessingFps.textContent = Number(data.processing_fps || 0).toFixed(1);
        DOM.metricStreamFps.textContent = Number(data.stream_fps || 0).toFixed(1);
        DOM.metricYoloLatency.textContent = `${Number(data.yolo_latency_ms || 0).toFixed(1)} ms`;
        DOM.metricPipelineLatency.textContent = `${Number(data.pipeline_latency_ms || 0).toFixed(1)} ms`;

        // Hardware & Model
        DOM.infoDevice.textContent = data.device || "CPU";
        DOM.infoGpu.textContent = data.gpu_name || "N/A";
        DOM.infoVram.textContent = `${Number(data.vram_mb || 0).toFixed(1)} MB`;
        DOM.infoModel.textContent = `${data.model_name || "YOLO11s"} (${data.input_size || "640x640"})`;

        // Event Statistics
        DOM.infoEventsToday.textContent = data.event_count_today || 0;
        DOM.infoFilteredEvents.textContent = data.filtered_event_count || 0;
        DOM.infoLastSavedCount.textContent = data.last_saved_people_count || 0;
        DOM.infoLastEvent.textContent = data.last_event_time || data.last_event || "None";

        // Sync dropdown selection if active camera changed externally
        if (data.camera_id && data.camera_id !== state.activeCameraId && !state.isSwitchingCamera) {
            state.activeCameraId = data.camera_id;
            if (DOM.cameraSelect.value !== data.camera_id) {
                DOM.cameraSelect.value = data.camera_id;
            }
        }
    }

    function handleTelemetryError() {
        state.consecutiveErrors++;
        DOM.pingLatency.textContent = "-- ms";
        // Do not trigger error/disconnect on transient network or Colab latency (require 3 consecutive failures)
        if (state.consecutiveErrors >= 3) {
            updateStatus("DISCONNECTED", "AI Server connection lost");
        }
    }

    /**
     * Fetch Camera Configuration List.
     */
    async function fetchCameras() {
        try {
            const response = await fetch(apiUrl("/cameras"));
            if (response.ok) {
                const data = await response.json();
                const cameras = data.cameras || [];
                const activeId = data.active_camera_id || (cameras[0] ? cameras[0].id : "");

                state.activeCameraId = activeId;
                DOM.cameraSelect.innerHTML = "";

                if (cameras.length === 0) {
                    DOM.cameraSelect.innerHTML = '<option value="" disabled>No cameras configured</option>';
                    return;
                }

                cameras.forEach(cam => {
                    const opt = document.createElement("option");
                    opt.value = cam.id;
                    opt.textContent = `${cam.name} (${cam.type})`;
                    if (cam.id === activeId) {
                        opt.selected = true;
                    }
                    DOM.cameraSelect.appendChild(opt);
                });
            }
        } catch (err) {
            DOM.cameraSelect.innerHTML = '<option value="" disabled>Failed to load cameras</option>';
        }
    }

    /**
     * Switch Active Camera.
     */
    async function switchCamera() {
        const selectedId = DOM.cameraSelect.value;
        if (!selectedId || state.isSwitchingCamera) return;

        state.isSwitchingCamera = true;
        DOM.switchCameraBtn.disabled = true;
        DOM.switchCameraBtn.querySelector(".btn-text").textContent = "Switching...";
        DOM.cameraSwitchFeedback.className = "feedback-msg";
        DOM.cameraSwitchFeedback.textContent = `Switching to ${selectedId}...`;
        updateStatus("SWITCHING");

        try {
            const response = await fetch(apiUrl(`/switch_camera?id=${encodeURIComponent(selectedId)}`));
            const data = await response.json();

            if (response.ok && data.status === "ok") {
                state.activeCameraId = selectedId;
                DOM.cameraSwitchFeedback.className = "feedback-msg success";
                DOM.cameraSwitchFeedback.textContent = `Switched: ${data.camera_name || selectedId}`;
                triggerVideoRefresh();
            } else {
                DOM.cameraSwitchFeedback.className = "feedback-msg error";
                DOM.cameraSwitchFeedback.textContent = data.message || "Camera switch failed";
            }
        } catch (err) {
            DOM.cameraSwitchFeedback.className = "feedback-msg error";
            DOM.cameraSwitchFeedback.textContent = `Error: ${err.message}`;
        } finally {
            setTimeout(() => {
                state.isSwitchingCamera = false;
                DOM.switchCameraBtn.disabled = false;
                DOM.switchCameraBtn.querySelector(".btn-text").textContent = "Switch Camera";
            }, 1000);
        }
    }

    /**
     * Poll Recent Occupancy Events (every 10000 ms).
     */
    async function pollEvents() {
        try {
            const response = await fetch(apiUrl("/events?limit=5"));
            if (response.ok) {
                const data = await response.json();
                renderEvents(data.events || []);
            }
        } catch (err) {
            // Keep existing event list on fetch failure
        }
    }

    /**
     * Render latest 5 events with lazy loading thumbnails.
     * Only mutates DOM if event IDs or count change.
     */
    function renderEvents(events) {
        const signature = JSON.stringify(events.map(e => ({ id: e.id, ts: e.timestamp, n: e.new_count })));
        if (signature === state.lastEventsJson) {
            return; // No change, skip DOM rebuild
        }
        state.lastEventsJson = signature;

        if (!events || events.length === 0) {
            DOM.eventsContainer.innerHTML = '<div class="events-empty">No occupancy change events logged yet today.</div>';
            return;
        }

        DOM.eventsContainer.innerHTML = "";
        events.slice(0, 5).forEach(ev => {
            const card = document.createElement("div");
            card.className = "event-card";

            const header = document.createElement("div");
            header.className = "event-card-header";
            header.innerHTML = `
                <span class="event-time">🕒 ${escapeHtml(ev.timestamp || "")}</span>
                <span class="event-cam">📹 ${escapeHtml(ev.camera_id || "")}</span>
            `;

            const body = document.createElement("div");
            body.className = "event-card-body";

            const oldCount = ev.old_count !== undefined ? ev.old_count : (ev.old_value !== undefined ? ev.old_value : 0);
            const newCount = ev.new_count !== undefined ? ev.new_count : (ev.new_value !== undefined ? ev.new_value : 0);

            const transition = document.createElement("div");
            transition.className = "event-transition";
            transition.textContent = `Count: ${oldCount} ➔ ${newCount} people`;
            body.appendChild(transition);

            if (ev.snapshot_path || ev.id || ev.snapshot_id) {
                const thumbWrapper = document.createElement("div");
                thumbWrapper.className = "event-thumb-wrapper";

                const img = document.createElement("img");
                img.className = "event-thumb";
                // Attribute loading="lazy" assigned before src to guarantee lazy network fetch
                img.setAttribute("loading", "lazy");
                img.loading = "lazy";
                img.alt = `Snapshot @ ${ev.timestamp}`;

                // Use id query parameter for efficient lazy snapshot retrieval
                const snapId = ev.snapshot_id || ev.id;
                const snapParam = snapId
                    ? `id=${encodeURIComponent(snapId)}`
                    : `path=${encodeURIComponent(ev.snapshot_path)}`;
                img.src = `/event_snapshot?${snapParam}`;

                img.onerror = () => {
                    thumbWrapper.style.display = "none";
                };

                thumbWrapper.appendChild(img);
                body.appendChild(thumbWrapper);
            }

            card.appendChild(header);
            card.appendChild(body);
            DOM.eventsContainer.appendChild(card);
        });
    }

    /**
     * Native Video Stream Management & Auto-Reconnect
     */
    function setupVideoStream() {
        DOM.videoFeed.onerror = handleVideoError;
        DOM.videoFeed.onload = handleVideoSuccess;
    }

    function handleVideoError() {
        DOM.videoErrorOverlay.style.display = "flex";
        if (state.videoReconnectTimer) return;

        // Auto-reconnect after 3 seconds with timestamp bust
        state.videoReconnectTimer = setTimeout(() => {
            state.videoReconnectTimer = null;
            triggerVideoRefresh();
        }, CONFIG.videoReconnectDelayMs);
    }

    function handleVideoSuccess() {
        DOM.videoErrorOverlay.style.display = "none";
        if (state.videoReconnectTimer) {
            clearTimeout(state.videoReconnectTimer);
            state.videoReconnectTimer = null;
        }
    }

    function triggerVideoRefresh() {
        const timestamp = Date.now();
        DOM.videoFeed.src = `/video_feed?t=${timestamp}`;
    }

    function escapeHtml(str) {
        return String(str)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    /**
     * Initialize Application.
     */
    function init() {
        // Event Listeners
        DOM.switchCameraBtn.addEventListener("click", switchCamera);

        DOM.backendUrlInput.addEventListener("change", (e) => {
            const url = e.target.value.trim();
            if (url) {
                state.backendUrl = url;
            }
        });

        // Setup Native Video
        setupVideoStream();

        // Initial Data Fetch
        fetchCameras();
        pollTelemetry();
        pollEvents();

        // Start Periodic Polling Timers
        state.telemetryTimer = setInterval(pollTelemetry, CONFIG.telemetryIntervalMs);
        state.eventsTimer = setInterval(pollEvents, CONFIG.eventsIntervalMs);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
