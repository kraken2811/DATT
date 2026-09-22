"""Streamlit Realtime Monitoring Dashboard for DATT.

Phase 4 Version 3: Camera Management & Event Logging.
Provides a modern camera management & observability dashboard:
- Camera Control: Multi-camera selector and dynamic switching
- Video Monitor: Smooth 25-30 FPS native MJPEG video stream
- Realtime Telemetry: Live metrics refreshed at 5-10 Hz
- Event Viewer: Realtime occupancy change event log with snapshot thumbnails

Usage:
    streamlit run src/ui/dashboard.py
"""

import json
import time
from typing import Any
import urllib.error
import urllib.parse
import urllib.request

import streamlit as st

# Configure page layout
st.set_page_config(
    page_title="DATT — AI People Counter & Camera Monitor",
    page_icon="🎥",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom Styling for modern dark observability aesthetic
st.markdown(
    """
    <style>
        .block-container { padding-top: 1.2rem; padding-bottom: 2rem; max-width: 98%; }
        .main-header {
            font-size: 1.8rem;
            font-weight: 700;
            color: #00E5FF;
            margin-bottom: 0.2rem;
            display: flex;
            align-items: center;
            gap: 12px;
        }
        .status-badge {
            padding: 4px 12px;
            border-radius: 6px;
            font-weight: 700;
            font-size: 0.85rem;
            display: inline-block;
        }
        .status-running { background-color: #059669; color: #FFFFFF; }
        .status-stopped { background-color: #4B5563; color: #FFFFFF; }
        .status-error { background-color: #DC2626; color: #FFFFFF; }
        .status-switching { background-color: #D97706; color: #FFFFFF; }
        .status-disconnected { background-color: #D97706; color: #FFFFFF; }
        .video-container {
            border-radius: 10px;
            overflow: hidden;
            background-color: #000000;
            border: 1px solid #1E293B;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.4);
        }
        .video-container img {
            width: 100%;
            height: auto;
            display: block;
        }
        [data-testid="stMetricValue"] {
            font-size: 1.5rem !important;
            color: #00E5FF !important;
            font-weight: 700 !important;
        }
        [data-testid="stMetricLabel"] {
            color: #94A3B8 !important;
            font-size: 0.85rem !important;
            font-weight: 600 !important;
        }
        .event-card {
            background-color: #1E293B;
            border: 1px solid #334155;
            border-radius: 8px;
            padding: 10px 14px;
            margin-bottom: 8px;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }
        .event-time { font-size: 0.8rem; color: #94A3B8; }
        .event-cam { font-weight: 600; color: #38BDF8; }
        .event-change { font-weight: 700; color: #34D399; font-size: 1rem; }
    </style>
    """,
    unsafe_allow_html=True,
)


def fetch_json(url: str, timeout: float = 1.2) -> dict[str, Any] | None:
    """Fetch JSON from given endpoint with timeout."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "DATT-Dashboard"})
        with urllib.request.urlopen(req, timeout=timeout) as response:
            if response.status == 200:
                return json.loads(response.read().decode("utf-8"))
    except Exception:
        pass
    return None


def trigger_camera_switch(server_url: str, camera_id: str) -> tuple[bool, str]:
    """Send camera switch request to the streaming server."""
    endpoint = f"{server_url.rstrip('/')}/switch_camera?id={urllib.parse.quote(camera_id)}"
    try:
        req = urllib.request.Request(endpoint, headers={"User-Agent": "DATT-Dashboard"})
        with urllib.request.urlopen(req, timeout=5.0) as response:
            data = json.loads(response.read().decode("utf-8"))
            if data.get("status") == "ok":
                return True, data.get("message", "Switched successfully")
            return False, data.get("message", "Switch failed")
    except Exception as exc:
        return False, str(exc)


def main() -> None:
    # Sidebar: Connection & Camera Management
    with st.sidebar:
        st.subheader("🎥 Camera Management")
        server_url = st.text_input(
            "AI Server URL",
            value="http://localhost:8000",
            help="Base URL of the AI streaming server ('python app.py --ui').",
        )

        # Fetch available cameras from API
        cameras_data = fetch_json(f"{server_url.rstrip('/')}/cameras") or {}
        camera_list = cameras_data.get("cameras", [])
        active_cam_id = cameras_data.get("active_camera_id", "camera_01")

        if camera_list:
            cam_options = {c["id"]: f"{c['name']} ({c['type']})" for c in camera_list}
            selected_cam_id = st.selectbox(
                "Select Camera Stream",
                options=list(cam_options.keys()),
                format_func=lambda x: cam_options[x],
                index=list(cam_options.keys()).index(active_cam_id)
                if active_cam_id in cam_options
                else 0,
            )

            if st.button("🔄 Switch Camera", use_container_width=True):
                with st.spinner(f"Switching to {selected_cam_id}..."):
                    success, msg = trigger_camera_switch(server_url, selected_cam_id)
                    if success:
                        st.success(f"Active Camera: {selected_cam_id}")
                        time.sleep(1.0)
                        st.rerun()
                    else:
                        st.error(f"Switch error: {msg}")
        else:
            st.caption("Waiting for camera configuration from server...")

        st.divider()
        refresh_interval_ms = st.slider(
            "Telemetry Refresh Rate (Hz)",
            min_value=2,
            max_value=12,
            value=6,
            help="Frequency of telemetry metrics refresh (default: 6 Hz).",
        )
        st.markdown(
            "**DATT - AI People Counter (Phase 4.3)**  \n"
            "*Level 2 Realtime Monitoring & Camera Control*"
        )

    # 1. Header & Operational Status
    header_col1, header_col2 = st.columns([3, 1])
    with header_col1:
        st.markdown(
            '<div class="main-header">👥 DATT AI Vision Monitor & Camera Manager</div>',
            unsafe_allow_html=True,
        )

    status_placeholder = header_col2.empty()
    error_placeholder = st.empty()

    # 2. Main Two-Column Layout (Video + Telemetry)
    col_video, col_metrics = st.columns([13, 7], gap="medium")

    with col_video:
        st.markdown("##### 📹 Live Camera Stream (25-30 FPS MJPEG)")
        video_feed_url = f"{server_url.rstrip('/')}/video_feed"
        # Render native MJPEG stream via HTML <img>. Never calls st.image in a loop!
        st.markdown(
            f"""
            <div class="video-container">
                <img src="{video_feed_url}" alt="Realtime AI Video Feed">
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.caption("Zero-queue native MJPEG stream with dynamic camera switching.")

    with col_metrics:
        st.markdown("##### 📊 Realtime AI Telemetry")
        telemetry_placeholder = st.empty()

    # 3. Recent Events Section
    st.divider()
    st.markdown("##### 📋 Recent Occupancy Events & Snapshots")
    events_placeholder = st.empty()

    # 4. Independent Telemetry Refresh Loop (5-10 Hz)
    sleep_sec = 1.0 / refresh_interval_ms

    while True:
        telem = fetch_json(f"{server_url.rstrip('/')}/telemetry")
        if telem is None:
            telem = {
                "status": "DISCONNECTED",
                "error_message": "Connecting to AI pipeline server...",
                "people_count": 0,
                "detection_count": 0,
                "track_count": 0,
                "stream_fps": 0.0,
                "processing_fps": 0.0,
                "yolo_latency_ms": 0.0,
                "pipeline_latency_ms": 0.0,
                "device": "N/A",
                "gpu_name": "N/A",
                "vram_mb": 0.0,
                "model_name": "YOLO11s",
                "input_size": "640x640",
                "camera_id": "N/A",
                "camera_name": "Connecting...",
                "last_event": "None",
                "event_count_today": 0,
            }

        status = telem.get("status", "DISCONNECTED")
        error_msg = telem.get("error_message", "")

        # Update Header Status Badge
        badge_class = f"status-{status.lower()}"
        status_placeholder.markdown(
            f'<div style="text-align: right; margin-top: 10px;">'
            f'<span class="status-badge {badge_class}">STATUS: {status}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

        # Update Error Banner
        if status == "ERROR" and error_msg:
            error_placeholder.error(f"⚠️ Camera Status: ERROR — Reason: {error_msg}")
        elif status == "DISCONNECTED":
            error_placeholder.warning(
                f"📡 Connecting to AI pipeline at {server_url}... Ensure 'python app.py --ui' is active."
            )
        else:
            error_placeholder.empty()

        # Render Telemetry Metrics
        with telemetry_placeholder.container():
            # Active Camera Name
            cam_display = telem.get("camera_name") or telem.get("camera_id") or "Camera"
            st.markdown(f"**Active Camera:** `{cam_display}`")

            # People in View (Primary Metric)
            st.metric("PEOPLE IN VIEW", telem.get("people_count", 0))

            # Counts
            m1, m2 = st.columns(2)
            m1.metric("Detections", telem.get("detection_count", 0))
            m2.metric("Active Tracks", telem.get("track_count", 0))

            # FPS
            f1, f2 = st.columns(2)
            f1.metric("Processing FPS", f"{telem.get('processing_fps', 0.0):.1f}")
            f2.metric("Stream FPS", f"{telem.get('stream_fps', 0.0):.1f}")

            # Latency
            l1, l2 = st.columns(2)
            l1.metric("YOLO Latency", f"{telem.get('yolo_latency_ms', 0.0):.1f} ms")
            l2.metric("Pipeline Latency", f"{telem.get('pipeline_latency_ms', 0.0):.1f} ms")

            # Hardware & Events info
            st.divider()
            st.caption(
                f"**Hardware:** {telem.get('device', 'N/A')} ({telem.get('gpu_name', 'N/A')}) | "
                f"**VRAM:** {telem.get('vram_mb', 0.0):.1f} MB  \n"
                f"**Model:** {telem.get('model_name', 'YOLO11s')} ({telem.get('input_size', '640x640')})  \n"
                f"**Last Event:** `{telem.get('last_event', 'None')}` | "
                f"**Events Today:** `{telem.get('event_count_today', 0)}`"
            )

        # Render Recent Events in Bottom Section
        events_resp = fetch_json(f"{server_url.rstrip('/')}/events?limit=6") or {}
        recent_events = events_resp.get("events", [])
        with events_placeholder.container():
            if recent_events:
                ev_cols = st.columns(min(len(recent_events), 4))
                for idx, ev in enumerate(recent_events[:4]):
                    col = ev_cols[idx]
                    with col:
                        st.markdown(
                            f"""
                            <div style="background:#1E293B; border-radius:8px; padding:10px; border:1px solid #334155;">
                                <div style="font-size:0.8rem; color:#94A3B8;">🕒 {ev['timestamp']}</div>
                                <div style="font-weight:600; color:#38BDF8;">📹 {ev['camera_id']}</div>
                                <div style="font-size:1.1rem; font-weight:700; color:#34D399; margin:4px 0;">
                                    Count: {ev['old_value']} ➔ {ev['new_value']}
                                </div>
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )
                        snap_path = ev.get("snapshot_path", "")
                        if snap_path:
                            snap_url = f"{server_url.rstrip('/')}/event_snapshot?path={urllib.parse.quote(snap_path)}"
                            st.image(snap_url, caption=f"Snapshot @ {ev['timestamp']}", use_container_width=True)
            else:
                st.info("No occupancy change events logged yet today.")

        time.sleep(sleep_sec)


if __name__ == "__main__":
    main()
