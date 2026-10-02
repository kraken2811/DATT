/* Alert Center: database delivery history, refreshed by polling (not push). */
(function () {
    "use strict";
    const labels = {PENDING: "Đang chờ gửi", SENT: "Đã gửi", FAILED: "Gửi thất bại", SUPPRESSED: "Không gửi (đã chặn)"};
    let active = false, page = 1, total = 0, timer = null, request = null;
    let detailRequest = null, selected = null, apiUrl = path => path, generation = 0;
    const el = id => document.getElementById(id);
    const text = (id, value) => { el(id).textContent = value ?? "—"; };
    const date = value => value ? new Date(value).toLocaleString("vi-VN") : "—";

    function stop() {
        generation++;
        clearTimeout(timer);
        if (request) request.abort();
        if (detailRequest) detailRequest.abort();
        request = detailRequest = null;
    }

    async function detail(id) {
        selected = id;
        if (detailRequest) detailRequest.abort();
        const controller = detailRequest = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 15000);
        el("alertDetail").hidden = false;
        text("alertDetailStatus", "Đang tải chi tiết…");
        el("alertDetailFields").hidden = true;
        try {
            const response = await fetch(apiUrl(`/api/alerts/${encodeURIComponent(id)}`), {signal: controller.signal, cache: "no-store"});
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const {alert} = await response.json();
            if (!active || detailRequest !== controller) return;
            text("alertDetailStatus", labels[alert.status] || alert.status);
            text("alertDetailRecipient", alert.recipient_email || "Chưa cấu hình");
            text("alertDetailCamera", alert.camera_name || alert.camera_id || "Không xác định");
            text("alertDetailType", alert.event_type);
            text("alertDetailTarget", alert.plate_number || alert.target_name || alert.target_id);
            text("alertDetailCreated", date(alert.created_at));
            text("alertDetailSent", date(alert.sent_at));
            text("alertDetailError", alert.error_message);
            text("alertDetailRetries", alert.retry_count);
            text("alertDetailId", alert.id);
            const link = el("alertEventLink");
            link.href = `/events?id=${encodeURIComponent(alert.event_center_id)}`;
            text("alertEventLink", `Xem Event: ${alert.event_id}`);
            el("alertDetailFields").hidden = false;
        } catch (error) {
            if (active && detailRequest === controller) text("alertDetailStatus", "Không tải được chi tiết. Vui lòng thử lại.");
        } finally {
            clearTimeout(timeout);
            if (detailRequest === controller) detailRequest = null;
        }
    }

    async function load() {
        if (!active || request) return;
        clearTimeout(timer);
        if (document.hidden) { timer = setTimeout(load, 10000); return; }
        const epoch = generation;
        const controller = request = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 15000);
        text("alertsFeedback", "Đang tải lịch sử gửi email…");
        const params = new URLSearchParams({page: String(page), page_size: "25"});
        for (const [key, id] of [["status", "alertsStatus"], ["event_type", "alertsType"], ["camera_id", "alertsCamera"]]) {
            const value = el(id).value.trim();
            if (value) params.set(key, value);
        }
        try {
            const response = await fetch(apiUrl(`/api/alerts?${params}`), {signal: controller.signal, cache: "no-store"});
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const data = await response.json();
            if (!active || epoch !== generation) return;
            total = data.total;
            const body = el("alertsBody"); body.replaceChildren();
            for (const alert of data.alerts) {
                const row = document.createElement("tr");
                for (const value of [alert.event_type.replaceAll("_", " "), alert.camera_name || alert.camera_id || "Không xác định",
                    alert.recipient_email || "Chưa cấu hình", labels[alert.status] || alert.status,
                    date(alert.sent_at), date(alert.created_at)]) {
                    const cell = document.createElement("td"); cell.textContent = value; row.appendChild(cell);
                }
                const statusBadge = document.createElement("span");
                statusBadge.className = "badge-notification notif-" + (Object.hasOwn(labels, alert.status) ? alert.status.toLowerCase() : "suppressed");
                statusBadge.textContent = labels[alert.status] || alert.status;
                row.children[3].textContent = "";
                row.children[3].appendChild(statusBadge);
                const cell = document.createElement("td"), button = document.createElement("button");
                button.type = "button"; button.className = "secondary-btn btn-sm"; button.textContent = "Chi tiết";
                button.addEventListener("click", () => detail(alert.id)); cell.appendChild(button); row.appendChild(cell); body.appendChild(row);
            }
            text("alertsFeedback", data.alerts.length ? `Cập nhật lúc ${date(new Date().toISOString())}` : "Không có thông báo phù hợp.");
            text("alertsPage", `Trang ${page} / ${Math.max(1, Math.ceil(total / 25))} · ${total} thông báo`);
            el("alertsPrev").disabled = page <= 1;
            el("alertsNext").disabled = page * 25 >= total;
            if (selected) detail(selected);
        } catch (error) {
            if (active && epoch === generation) text("alertsFeedback", "Không tải được Alert Center. Dữ liệu cũ có thể chưa cập nhật; hãy thử Làm mới.");
        } finally {
            clearTimeout(timeout);
            if (request === controller) request = null;
            if (active && epoch === generation) timer = setTimeout(load, 10000);
        }
    }

    function reload(resetPage = false) {
        stop();
        if (resetPage) page = 1;
        load();
    }

    window.DattAlerts = {
        init(resolveUrl) {
            apiUrl = resolveUrl;
            el("alertsRefresh").addEventListener("click", () => reload());
            el("alertsFilters").addEventListener("submit", event => { event.preventDefault(); reload(true); });
            el("alertsPrev").addEventListener("click", () => { if (page > 1) { page--; reload(); } });
            el("alertsNext").addEventListener("click", () => { if (page * 25 < total) { page++; reload(); } });
            el("alertDetailClose").addEventListener("click", () => {
                selected = null;
                if (detailRequest) detailRequest.abort();
                detailRequest = null;
                el("alertDetail").hidden = true;
            });
            document.addEventListener("visibilitychange", () => { if (active && !document.hidden) reload(); });
        },
        setActive(value) {
            active = value; stop();
            if (active) load();
            else { selected = null; el("alertDetail").hidden = true; }
        }
    };
})();
