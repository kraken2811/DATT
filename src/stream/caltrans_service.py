"""Caltrans CCTV Camera Catalog Service for DATT.

Fetches, filters, normalizes, and caches CCTV cameras from Caltrans ArcGIS FeatureServer:
https://caltrans-gis.dot.ca.gov/arcgis/rest/services/CHhighway/CCTV/FeatureServer/0/query

Required fields:
- locationName
- streamingVideoURL
- currentImageURL
- currentImageUpdateFrequency

Rules:
- Filter cameras where streamingVideoURL IS NOT NULL and non-empty.
- Normalize to internal structure:
  {
      "id": "caltrans_...",
      "name": "Hwy 5 at Pocket",
      "provider": "Caltrans",
      "source_type": "direct_hls",
      "stream_url": "...playlist.m3u8",
      "snapshot_url": "...jpg",
      "update_frequency": 30
  }
- Never expose ArcGIS-specific envelope / raw schema to frontend.
- Cache catalog for approximately 10 minutes (600s).
- Fallback gracefully to cache or seed catalog on network partition / API error.
"""

from dataclasses import asdict, dataclass
import hashlib
import json
import logging
import re
import threading
import time
from typing import Any
import urllib.parse
import urllib.request

logger = logging.getLogger("datt.caltrans")

CALTRANS_QUERY_URL = (
    "https://caltrans-gis.dot.ca.gov/arcgis/rest/services/CHhighway/CCTV/FeatureServer/0/query"
)

CACHE_TTL_SECONDS = 600.0  # 10 minutes cache

# High quality fallback seed catalog for offline operation, unit tests, or network failures
SEED_CALTRANS_CAMERAS = [
    {
        "id": "caltrans_hwy5_pocket",
        "name": "Hwy 5 at Pocket",
        "provider": "Caltrans",
        "source_type": "direct_hls",
        "stream_url": "https://cctv.dot.ca.gov/data/d3/hls/hwy5_pocket.stream/playlist.m3u8",
        "snapshot_url": "https://cctv.dot.ca.gov/data/d3/cctv/image/hwy5_pocket.jpg",
        "update_frequency": 30,
        "district": "District 3",
        "county": "Sacramento",
    },
    {
        "id": "caltrans_i80_donner_summit",
        "name": "I-80 at Donner Summit",
        "provider": "Caltrans",
        "source_type": "direct_hls",
        "stream_url": "https://cctv.dot.ca.gov/data/d3/hls/i80_donner_summit.stream/playlist.m3u8",
        "snapshot_url": "https://cctv.dot.ca.gov/data/d3/cctv/image/i80_donner_summit.jpg",
        "update_frequency": 30,
        "district": "District 3",
        "county": "Nevada",
    },
    {
        "id": "caltrans_us101_van_ness",
        "name": "US-101 at Van Ness Ave",
        "provider": "Caltrans",
        "source_type": "direct_hls",
        "stream_url": "https://cctv.dot.ca.gov/data/d4/hls/us101_van_ness.stream/playlist.m3u8",
        "snapshot_url": "https://cctv.dot.ca.gov/data/d4/cctv/image/us101_van_ness.jpg",
        "update_frequency": 30,
        "district": "District 4",
        "county": "San Francisco",
    },
    {
        "id": "caltrans_i80_bay_bridge",
        "name": "I-80 at Bay Bridge Toll Plaza",
        "provider": "Caltrans",
        "source_type": "direct_hls",
        "stream_url": "https://cctv.dot.ca.gov/data/d4/hls/i80_bay_bridge.stream/playlist.m3u8",
        "snapshot_url": "https://cctv.dot.ca.gov/data/d4/cctv/image/i80_bay_bridge.jpg",
        "update_frequency": 30,
        "district": "District 4",
        "county": "Alameda",
    },
    {
        "id": "caltrans_i5_hollywood_way",
        "name": "I-5 at Hollywood Way",
        "provider": "Caltrans",
        "source_type": "direct_hls",
        "stream_url": "https://cctv.dot.ca.gov/data/d7/hls/i5_hollywood_way.stream/playlist.m3u8",
        "snapshot_url": "https://cctv.dot.ca.gov/data/d7/cctv/image/i5_hollywood_way.jpg",
        "update_frequency": 30,
        "district": "District 7",
        "county": "Los Angeles",
    },
    {
        "id": "caltrans_sr99_fruitridge",
        "name": "SR-99 at Fruitridge Rd",
        "provider": "Caltrans",
        "source_type": "direct_hls",
        "stream_url": "https://cctv.dot.ca.gov/data/d3/hls/sr99_fruitridge.stream/playlist.m3u8",
        "snapshot_url": "https://cctv.dot.ca.gov/data/d3/cctv/image/sr99_fruitridge.jpg",
        "update_frequency": 30,
        "district": "District 3",
        "county": "Sacramento",
    },
    {
        "id": "caltrans_i10_santa_monica",
        "name": "I-10 at Santa Monica Blvd",
        "provider": "Caltrans",
        "source_type": "direct_hls",
        "stream_url": "https://cctv.dot.ca.gov/data/d7/hls/i10_santa_monica.stream/playlist.m3u8",
        "snapshot_url": "https://cctv.dot.ca.gov/data/d7/cctv/image/i10_santa_monica.jpg",
        "update_frequency": 30,
        "district": "District 7",
        "county": "Los Angeles",
    },
    {
        "id": "caltrans_i15_cajon_pass",
        "name": "I-15 at Cajon Pass",
        "provider": "Caltrans",
        "source_type": "direct_hls",
        "stream_url": "https://cctv.dot.ca.gov/data/d8/hls/i15_cajon_pass.stream/playlist.m3u8",
        "snapshot_url": "https://cctv.dot.ca.gov/data/d8/cctv/image/i15_cajon_pass.jpg",
        "update_frequency": 30,
        "district": "District 8",
        "county": "San Bernardino",
    },
]


@dataclass
class NormalizedCamera:
    """Normalized internal representation of a public CCTV camera."""

    id: str
    name: str
    provider: str
    source_type: str
    stream_url: str
    snapshot_url: str
    update_frequency: int = 30
    district: str = ""
    county: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def make_camera_id(name: str, url: str) -> str:
    """Generate a clean, deterministic, URL-friendly camera identifier."""
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", name.lower()).strip("_")
    if not slug:
        slug = "cam"
    hash_suffix = hashlib.md5(url.encode("utf-8")).hexdigest()[:6]
    return f"caltrans_{slug}_{hash_suffix}"


def parse_arcgis_response(raw_json: dict[str, Any]) -> list[NormalizedCamera]:
    """Parse ArcGIS FeatureServer query response and filter valid HLS streaming cameras."""
    features = raw_json.get("features", [])
    if not isinstance(features, list):
        return []

    cameras: list[NormalizedCamera] = []
    seen_urls: set[str] = set()

    for item in features:
        if not isinstance(item, dict):
            continue
        attrs = item.get("attributes", {})
        if not isinstance(attrs, dict):
            continue

        video_url = attrs.get("streamingVideoURL")
        if not video_url or not isinstance(video_url, str):
            continue
        video_url = video_url.strip()
        if not video_url or video_url.lower() == "null":
            continue

        if video_url in seen_urls:
            continue
        seen_urls.add(video_url)

        location_name = attrs.get("locationName") or "Caltrans CCTV Camera"
        location_name = str(location_name).strip()

        snapshot_url = attrs.get("currentImageURL") or ""
        snapshot_url = str(snapshot_url).strip()

        freq = attrs.get("currentImageUpdateFrequency") or 30
        try:
            freq_val = int(freq)
        except (ValueError, TypeError):
            freq_val = 30

        district = str(attrs.get("district") or attrs.get("District") or "").strip()
        county = str(attrs.get("county") or attrs.get("County") or "").strip()

        cam_id = make_camera_id(location_name, video_url)

        cameras.append(
            NormalizedCamera(
                id=cam_id,
                name=location_name,
                provider="Caltrans",
                source_type="direct_hls",
                stream_url=video_url,
                snapshot_url=snapshot_url,
                update_frequency=freq_val,
                district=district,
                county=county,
            )
        )

    return cameras


class CaltransCameraService:
    """Thread-safe catalog provider with 10-minute caching and resilient fallback."""

    def __init__(
        self,
        endpoint_url: str = CALTRANS_QUERY_URL,
        cache_ttl: float = CACHE_TTL_SECONDS,
        timeout: float = 6.0,
    ) -> None:
        self.endpoint_url = endpoint_url
        self.cache_ttl = cache_ttl
        self.timeout = timeout

        self._lock = threading.Lock()
        self._cached_cameras: list[NormalizedCamera] = []
        self._cache_timestamp: float = 0.0
        self._last_error: str = ""

    @property
    def is_cache_valid(self) -> bool:
        with self._lock:
            if not self._cached_cameras:
                return False
            return (time.time() - self._cache_timestamp) < self.cache_ttl

    def get_cameras(self, force_refresh: bool = False, query: str = "") -> list[dict[str, Any]]:
        """Retrieve Caltrans cameras, utilizing 10-minute cache with fallback."""
        with self._lock:
            cache_alive = (
                not force_refresh
                and self._cached_cameras
                and (time.time() - self._cache_timestamp) < self.cache_ttl
            )
            if cache_alive:
                cameras = self._cached_cameras
            else:
                cameras = None

        if cameras is None:
            cameras = self._fetch_and_cache(force_refresh=force_refresh)

        # Apply optional text search filter
        result = [c.to_dict() for c in cameras]
        if query and query.strip():
            q = query.strip().lower()
            result = [
                c
                for c in result
                if q in c["name"].lower()
                or q in c.get("district", "").lower()
                or q in c.get("county", "").lower()
            ]

        return result

    def _fetch_and_cache(self, force_refresh: bool = False) -> list[NormalizedCamera]:
        """Fetch latest camera records from ArcGIS endpoint or fallback."""
        params = {
            "where": "streamingVideoURL IS NOT NULL",
            "outFields": "locationName,streamingVideoURL,currentImageURL,currentImageUpdateFrequency,district,county",
            "f": "json",
            "returnGeometry": "false",
            "resultRecordCount": "200",
        }
        full_url = f"{self.endpoint_url}?{urllib.parse.urlencode(params)}"

        fetched: list[NormalizedCamera] = []
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
                    fetched = parse_arcgis_response(raw_data)
                    logger.info("CaltransService: Successfully fetched %d cameras from API", len(fetched))
        except Exception as exc:
            self._last_error = str(exc)
            logger.warning("CaltransService: ArcGIS request failed (%s). Using cache or seed fallback.", exc)

        with self._lock:
            if fetched:
                self._cached_cameras = fetched
                self._cache_timestamp = time.time()
                self._last_error = ""
                return self._cached_cameras

            # If fetch failed but we have previous cache, keep using it
            if self._cached_cameras:
                logger.info("CaltransService: Returning %d cached cameras after fetch failure", len(self._cached_cameras))
                return self._cached_cameras

            # Fallback to curated seed catalog
            logger.info("CaltransService: Serving fallback seed catalog (%d cameras)", len(SEED_CALTRANS_CAMERAS))
            seed_objects = [
                NormalizedCamera(
                    id=c["id"],
                    name=c["name"],
                    provider=c["provider"],
                    source_type=c["source_type"],
                    stream_url=c["stream_url"],
                    snapshot_url=c["snapshot_url"],
                    update_frequency=c.get("update_frequency", 30),
                    district=c.get("district", ""),
                    county=c.get("county", ""),
                )
                for c in SEED_CALTRANS_CAMERAS
            ]
            self._cached_cameras = seed_objects
            self._cache_timestamp = time.time()
            return self._cached_cameras

    def get_camera_by_id(self, camera_id: str) -> dict[str, Any] | None:
        """Find a single camera by normalized ID."""
        for cam in self.get_cameras():
            if cam["id"] == camera_id:
                return cam
        return None


# Global singleton instance
caltrans_service = CaltransCameraService()
