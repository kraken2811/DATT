"""Immutable Data Transfer Objects (DTOs) for vehicle passages and business events.

Realtime thread creates and enqueues these small immutable objects.
No DB sessions, ORM models, or raw frame arrays are transferred in DTOs.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4


@dataclass(frozen=True)
class VehiclePassageDTO:
    """Immutable snapshot of a vehicle passage for database persistence."""
    id: UUID
    session_key: str
    camera_id: str
    track_id: int
    first_seen_at: datetime
    last_seen_at: datetime
    video_source_id: UUID | None = None
    vehicle_type: str = "vehicle"
    vehicle_color: str | None = None
    vehicle_type_confidence: float | None = None
    vehicle_color_confidence: float | None = None
    zone_id: str | None = None
    plate_text: str | None = None
    plate_status: str | None = None
    plate_confidence: float | None = None
    direction: str | None = None
    duration_ms: float = 0.0
    best_vehicle_image_path: str | None = None
    best_plate_image_path: str | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    finalized_at: datetime | None = None
    is_final: bool = False


@dataclass(frozen=True)
class BusinessEventDTO:
    """Immutable snapshot of a business event for database persistence."""
    id: UUID
    passage_id: UUID | None
    camera_id: str
    event_type: str
    event_time: datetime
    idempotency_key: str
    video_source_id: UUID | None = None
    zone_id: str | None = None
    track_id: int | None = None
    vehicle_type: str | None = None
    plate_text: str | None = None
    direction: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass(frozen=True)
class FaceEventDTO:
    """Immutable snapshot of a face recognition event for database persistence."""
    id: UUID
    track_id: int
    camera_id: str
    target_id: UUID | None = None
    target_name: str | None = None
    similarity: float | None = None
    decision: str = "FACE_MATCH"
    video_source_id: UUID | None = None
    frame_id: int | None = None
    face_crop_path: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)

