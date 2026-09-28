"""Seattle SDOT Traffic Camera Catalog Service for DATT.

Fetches, filters, normalizes, and caches CCTV cameras from Seattle SDOT ArcGIS FeatureServer:
https://services.arcgis.com/ZOyb2t4B0UYuYNYH/arcgis/rest/services/Traffic_Cameras_CDL/FeatureServer/0/query

Dynamically retrieves the live Wowza HLS template from:
https://web.seattle.gov/Travelers/api/Map/WowsaUrl

Rules:
- NEVER hard-code the streamlock hostname.
- Whitelist only verified initial integration cameras:
    2_Pike_NS, 2_Pike_EW, 2_Stewart_NS, 3_Columbia_EW, 3_Spring_EW,
    3_Stewart_NS, 3_Union_SWC, 3_University_NS, 4_S_Washington_NS, 8_Madison
- Filter cameras where STREAM_NAME is present and in whitelist.
- Construct direct HLS stream:
    stream_id = f"{STREAM_NAME}.stream"
    stream_url = template.replace("{stream}", stream_id)
- Normalize to standard schema:
    {
        "id": "seattle_<STREAM_NAME>",
        "name": LOCATION,
        "provider": "Seattle SDOT",
        "city": "Seattle",
        "state": "Washington",
        "stream_name": STREAM_NAME,
        "stream_url": constructed HLS URL,
        "snapshot_url": URL (prefer https://www.seattle.gov/...),
        "latitude": latitude,
        "longitude": longitude,
        "source_type": "direct_hls",
        "status": "ACTV"
    }
- Cache catalog for 10 minutes (600s), Wowza template for 5 minutes (300s).
- Thread-safe caching with resilient fallback.
- Snapshot failure must NOT make camera unavailable; HLS stream is authoritative.
"""

from dataclasses import asdict, dataclass
import json
import logging
import re
import threading
import time
from typing import Any
import urllib.parse
import urllib.request

logger = logging.getLogger("datt.seattle_sdot")

SEATTLE_ARCGIS_QUERY_URL = (
    "https://services.arcgis.com/ZOyb2t4B0UYuYNYH/arcgis/rest/services/Traffic_Cameras_CDL/FeatureServer/0/query"
)
SEATTLE_WOWZA_TEMPLATE_URL = "https://web.seattle.gov/Travelers/api/Map/WowsaUrl"

CATALOG_CACHE_TTL_SECONDS = 600.0   # 10 minutes
TEMPLATE_CACHE_TTL_SECONDS = 300.0  # 5 minutes

# Verified camera whitelist for initial integration phase
SEATTLE_WHITELIST_CAMERAS: set[str] = {
    "2_Pike_NS",
    "2_Pike_EW",
    "2_Stewart_NS",
    "3_Columbia_EW",
    "3_Spring_EW",
    "3_Stewart_NS",
    "3_Union_SWC",
    "3_University_NS",
    "4_S_Washington_NS",
    "8_Madison",
}

# Standard HTTP headers for accessing Seattle SDOT video feeds
SEATTLE_STREAM_HEADERS: dict[str, str] = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) DATT/4.5",
    "Referer": "https://web.seattle.gov/Travelers/",
}


@dataclass
class SeattleCamera:
    """Normalized internal representation of a Seattle SDOT CCTV camera."""

    id: str
    name: str
    provider: str
    city: str
    state: str
    stream_name: str
    stream_url: str
    snapshot_url: str
    latitude: float | None
    longitude: float | None
    source_type: str = "direct_hls"
    status: str = "ACTV"
    headers: dict[str, str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def upgrade_snapshot_url(url: str | None) -> str:
    """Upgrade HTTP Seattle.gov snapshot URLs to HTTPS."""
    if not url:
        return ""
    url_str = str(url).strip()
    if url_str.startswith("http://www.seattle.gov/"):
        return "https://www.seattle.gov/" + url_str[len("http://www.seattle.gov/"):]
    elif url_str.startswith("http://seattle.gov/"):
        return "https://seattle.gov/" + url_str[len("http://seattle.gov/"):]
    return url_str


def parse_seattle_arcgis_response(
    raw_json: dict[str, Any],
    hls_template: str,
    whitelist: set[str] | None = SEATTLE_WHITELIST_CAMERAS,
) -> list[SeattleCamera]:
    """Parse ArcGIS FeatureServer query response and construct direct HLS cameras.

    Filters:
    - STREAM_NAME must be non-empty and valid string.
    - If whitelist is provided, STREAM_NAME must match whitelist.
    - Ignores null, blank, or missing STREAM_NAME entries.
    """
    if not hls_template or "{stream}" not in hls_template:
        logger.warning("SeattleSDOT: Invalid HLS template supplied: %s", hls_template)
        return []

    features = raw_json.get("features", [])
    if not isinstance(features, list):
        return []

    cameras: list[SeattleCamera] = []
    seen_streams: set[str] = set()

    for item in features:
        if not isinstance(item, dict):
            continue
        attrs = item.get("attributes", {})
        if not isinstance(attrs, dict):
            continue

        raw_stream_name = attrs.get("STREAM_NAME")
        if not raw_stream_name or not isinstance(raw_stream_name, str):
            continue
        stream_name = raw_stream_name.strip()
        if not stream_name or stream_name.lower() in ("null", "none"):
            continue

        # Whitelist filtering
        if whitelist is not None and stream_name not in whitelist:
            continue

        if stream_name in seen_streams:
            continue
        seen_streams.add(stream_name)

        location_name = attrs.get("LOCATION") or attrs.get("NAME") or stream_name
        location_name = str(location_name).strip()

        raw_url = attrs.get("URL") or ""
        snapshot_url = upgrade_snapshot_url(str(raw_url).strip())

        # Construct stream URL from dynamic Wowza template
        stream_id = f"{stream_name}.stream"
        stream_url = hls_template.replace("{stream}", stream_id)

        geom = item.get("geometry", {})
        longitude = geom.get("x") if isinstance(geom, dict) else None
        latitude = geom.get("y") if isinstance(geom, dict) else None

        cam_id = f"seattle_{stream_name}"
        status = str(attrs.get("SERVSTAT") or "ACTV").strip()

        cameras.append(
            SeattleCamera(
                id=cam_id,
                name=location_name,
                provider="Seattle SDOT",
                city="Seattle",
                state="Washington",
                stream_name=stream_name,
                stream_url=stream_url,
                snapshot_url=snapshot_url,
                latitude=latitude,
                longitude=longitude,
                source_type="direct_hls",
                status=status,
                headers=dict(SEATTLE_STREAM_HEADERS),
            )
        )

    # Sort consistently by name
    cameras.sort(key=lambda c: c.name)
    return cameras


class SeattleSDOTService:
    """Thread-safe catalog service for Seattle SDOT cameras with dynamic Wowza template fetching."""

    def __init__(
        self,
        arcgis_url: str = SEATTLE_ARCGIS_QUERY_URL,
        template_url: str = SEATTLE_WOWZA_TEMPLATE_URL,
        catalog_ttl: float = CATALOG_CACHE_TTL_SECONDS,
        template_ttl: float = TEMPLATE_CACHE_TTL_SECONDS,
        timeout: float = 6.0,
    ) -> None:
        self.arcgis_url = arcgis_url
        self.template_url = template_url
        self.catalog_ttl = catalog_ttl
        self.template_ttl = template_ttl
        self.timeout = timeout

        self._lock = threading.RLock()
        self._cached_cameras: list[SeattleCamera] = []
        self._catalog_timestamp: float = 0.0
        self._cached_template: str | None = None
        self._template_timestamp: float = 0.0
        self._last_error: str = ""

    def get_wowza_template(self, force_refresh: bool = False) -> str:
        """Fetch current Wowza HLS template dynamically.

        Never hard-codes streamlock hostname.
        Caches for 5 minutes.
        If refresh fails and a previous cached template exists, continues using it.
        """
        with self._lock:
            cache_valid = (
                not force_refresh
                and self._cached_template is not None
                and (time.time() - self._template_timestamp) < self.template_ttl
            )
            if cache_valid and self._cached_template:
                return self._cached_template

        fetched_template: str | None = None
        try:
            req = urllib.request.Request(
                self.template_url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) DATT/4.5",
                    "Accept": "application/json, text/plain, */*",
                },
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                if resp.status == 200:
                    raw_text = resp.read().decode("utf-8", errors="replace").strip()
                    # Response is either a JSON string or plain text template URL
                    try:
                        parsed = json.loads(raw_text)
                        if isinstance(parsed, str):
                            raw_text = parsed
                    except Exception:
                        pass
                    raw_text = raw_text.strip().strip('"').strip("'")
                    if "{stream}" in raw_text:
                        fetched_template = raw_text
                        logger.info("SeattleSDOT: Successfully fetched Wowza template: %s", fetched_template)
                    else:
                        logger.warning("SeattleSDOT: Unexpected WowzaUrl format: %s", raw_text)
        except Exception as exc:
            self._last_error = f"Wowza template fetch failed: {exc}"
            logger.warning("SeattleSDOT: Failed to fetch Wowza template: %s", exc)

        with self._lock:
            if fetched_template:
                self._cached_template = fetched_template
                self._template_timestamp = time.time()
                return fetched_template

            # Fallback to previously cached template if available
            if self._cached_template:
                logger.info("SeattleSDOT: Reusing previous cached template after refresh error")
                return self._cached_template

        raise RuntimeError("Unable to retrieve Seattle Wowza HLS template and no cached template is available.")

    def get_cameras(
        self,
        force_refresh: bool = False,
        query: str = "",
        whitelist: set[str] | None = SEATTLE_WHITELIST_CAMERAS,
    ) -> list[dict[str, Any]]:
        """Retrieve normalized Seattle SDOT cameras, utilizing 10-minute cache with fallback."""
        with self._lock:
            cache_alive = (
                not force_refresh
                and self._cached_cameras
                and (time.time() - self._catalog_timestamp) < self.catalog_ttl
            )
            if cache_alive:
                cameras = self._cached_cameras
            else:
                cameras = None

        if cameras is None:
            cameras = self._fetch_and_cache(force_refresh=force_refresh, whitelist=whitelist)

        # Apply optional text query filter
        result = [c.to_dict() for c in cameras]
        if query and query.strip():
            q = query.strip().lower()
            result = [
                c
                for c in result
                if q in c["name"].lower()
                or q in c.get("stream_name", "").lower()
                or q in c.get("city", "").lower()
            ]

        return result

    def _fetch_and_cache(
        self,
        force_refresh: bool = False,
        whitelist: set[str] | None = SEATTLE_WHITELIST_CAMERAS,
    ) -> list[SeattleCamera]:
        """Fetch latest Wowza template and ArcGIS features, parse and cache."""
        template = ""
        try:
            template = self.get_wowza_template(force_refresh=force_refresh)
        except Exception as exc:
            logger.warning("SeattleSDOT: Could not get Wowza template: %s", exc)

        fetched: list[SeattleCamera] = []
        if template:
            params = {
                "where": "OWNERSHIP='SDOT' AND SERVSTAT='ACTV'",
                "outFields": "NAME,LOCATION,DISTRICT,URL,STREAM_NAME,SERVSTAT",
                "returnGeometry": "true",
                "outSR": "4326",
                "f": "json",
            }
            full_url = f"{self.arcgis_url}?{urllib.parse.urlencode(params)}"
            try:
                req = urllib.request.Request(
                    full_url,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) DATT/4.5",
                        "Accept": "application/json",
                    },
                )
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    if resp.status == 200:
                        raw_data = json.loads(resp.read().decode("utf-8", errors="replace"))
                        fetched = parse_seattle_arcgis_response(
                            raw_data,
                            hls_template=template,
                            whitelist=whitelist,
                        )
                        logger.info("SeattleSDOT: Successfully fetched %d cameras from API", len(fetched))
            except Exception as exc:
                self._last_error = str(exc)
                logger.warning("SeattleSDOT: ArcGIS request failed (%s). Checking cache fallback.", exc)

        with self._lock:
            if fetched:
                self._cached_cameras = fetched
                self._catalog_timestamp = time.time()
                self._last_error = ""
                return self._cached_cameras

            # If fetch failed but we have a previous cache, keep using it
            if self._cached_cameras:
                logger.info("SeattleSDOT: Returning %d cached cameras after fetch failure", len(self._cached_cameras))
                return self._cached_cameras

            # If completely offline / no cache exists
            logger.warning("SeattleSDOT: No cameras available from API or cache.")
            return []

    def get_camera_by_stream_name(self, stream_name: str) -> dict[str, Any] | None:
        """Find a single camera by STREAM_NAME."""
        for cam in self.get_cameras():
            if cam.get("stream_name") == stream_name or cam.get("id") == f"seattle_{stream_name}":
                return cam
        return None


# Global singleton instance
seattle_service = SeattleSDOTService()
