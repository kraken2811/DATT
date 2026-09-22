"""Streamlit Realtime Monitoring Dashboard for DATT.

Phase 4: Level 2 Realtime Monitoring UI.
Provides a modern observability dashboard:
- Left: Smooth 25-30 FPS MJPEG Video Stream (rendered natively via HTML <img> tag)
- Right: Realtime Telemetry Cards (refreshed at 5-10 Hz without re-rendering video)

Usage:
    streamlit run src/ui/dashboard.py
"""

import json
import time
from typing import Any
import urllib.error
import urllib.request

import streamlit as st

# Configure page layout
st.set_page_config(
    page_title="DATT — AI People Counter",
    page_icon="👥",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Custom Styling for modern dark observability aesthetic
st.markdown(
    """
    <style>
        .block-container { padding-top: 1.5rem; padding-bottom: 2rem; max-width: 98%; }
        .main-header {
            font-size: 1.8rem;
            font-weight: 700;
            color: #00E5FF;
            margin-bottom: 0.5rem;
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
            font-size: 1.6rem !important;
            color: #00E5FF !important;
            font-weight: 700 !important;
        }
        [data-testid="stMetricLabel"] {
            color: #94A3B8 !important;
            font-size: 0.85rem !important;
            font-weight: 600 !important;
        }
    </style>
    """,
    unsafe_allow_html=True,
)


def fetch_telemetry(server_url: str) -> dict[str, Any]:
    """Fetch current telemetry JSON from the AI pipeline stream server."""
    endpoint = f"{server_url.rstrip('/')}/telemetry"
    try:
        req = urllib.request.Request(endpoint, headers={"User-Agent": "DATT-Dashboard"})
        with urllib.request.urlopen(req, timeout=1.0) as response:
            if response.status == 200:
                data = json.loads(response.read().decode("utf-8"))
                return data
    except Exception:
        pass

    # Fallback status if server is unreachable
    return {
        "status": "DISCONNECTED",
        "error_message": "Cannot connect to AI pipeline stream server",
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
    }


def main() -> None:
    # Sidebar: connection settings and controls
    with st.sidebar:
        st.subheader("⚙️ Connection Settings")
        server_url = st.text_input(
            "AI Stream Server URL",
            value="http://localhost:8000",
            help="URL of the MJPEG stream server started by 'python app.py --ui'.",
        )
        refresh_interval_ms = st.slider(
            "Telemetry Refresh Rate (Hz)",
            min_value=2,
            max_value=15,
            value=8,
            help="Frequency of telemetry metrics refresh (default: 8 Hz).",
        )
        st.divider()
        st.markdown(
            "**DATT - AI People Counter**  \n"
            "Phase 4: Level 2 Realtime Monitoring UI  \n"
            "*Video stream runs independently at 25-30 FPS via native MJPEG.*"
        )

    # 1. Header & System Status
    header_col1, header_col2 = st.columns([3, 1])
    with header_col1:
        st.markdown(
            '<div class="main-header">👥 DATT AI People Counter — Realtime Monitor</div>',
            unsafe_allow_html=True,
        )

    status_placeholder = header_col2.empty()
    error_placeholder = st.empty()

    # 2. Main Two-Column Layout
    col_video, col_metrics = st.columns([13, 7], gap="medium")

    with col_video:
        st.markdown("##### 📹 AI Video Monitor (25-30 FPS MJPEG)")
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
        st.caption("Native browser MJPEG feed — zero queue buffer, latest frame only.")

    with col_metrics:
        st.markdown("##### 📊 Realtime AI Telemetry")
        telemetry_placeholder = st.empty()

    # 3. Telemetry Refresh Loop (5-10 Hz)
    sleep_sec = 1.0 / refresh_interval_ms

    while True:
        data = fetch_telemetry(server_url)
        status = data.get("status", "DISCONNECTED")
        error_msg = data.get("error_message", "")

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
            error_placeholder.error(f"⚠️ Pipeline Error: {error_msg}")
        elif status == "DISCONNECTED":
            error_placeholder.warning(
                f"📡 Connecting to AI pipeline at {server_url}... Ensure 'python app.py --ui' is running."
            )
        else:
            error_placeholder.empty()

        # Render Telemetry Metrics in Right Column
        with telemetry_placeholder.container():
            # 1. People in View (Primary Metric)
            st.metric("PEOPLE IN VIEW", data.get("people_count", 0))

            # 2. Counts
            m1, m2 = st.columns(2)
            m1.metric("Detections", data.get("detection_count", 0))
            m2.metric("Active Tracks", data.get("track_count", 0))

            # 3. FPS
            f1, f2 = st.columns(2)
            f1.metric("Processing FPS", f"{data.get('processing_fps', 0.0):.1f}")
            f2.metric("Stream FPS", f"{data.get('stream_fps', 0.0):.1f}")

            # 4. Latency
            l1, l2 = st.columns(2)
            l1.metric("YOLO Latency", f"{data.get('yolo_latency_ms', 0.0):.1f} ms")
            l2.metric("Pipeline Latency", f"{data.get('pipeline_latency_ms', 0.0):.1f} ms")

            # 5. Hardware Info
            st.divider()
            st.markdown("###### 🖥️ Hardware & Model")
            h1, h2 = st.columns(2)
            h1.caption(f"**Device:** {data.get('device', 'N/A')}")
            h2.caption(f"**GPU:** {data.get('gpu_name', 'N/A')}")

            v1, v2 = st.columns(2)
            v1.caption(f"**VRAM:** {data.get('vram_mb', 0.0):.1f} MB")
            v2.caption(f"**Model / Size:** {data.get('model_name', 'YOLO11s')} ({data.get('input_size', '640x640')})")

        time.sleep(sleep_sec)


if __name__ == "__main__":
    main()
