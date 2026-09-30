"""Portable PostgreSQL/SQLite event schema."""

from datetime import datetime, timezone
from uuid import UUID, uuid4
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, JSON, MetaData, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator
from pgvector.sqlalchemy import Vector


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """Reject ambiguous naive input and restore timezone on SQLite reads."""
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        return value.astimezone(timezone.utc)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention={
        "ix": "ix_%(table_name)s_%(column_0_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
    })


JSON_DATA = JSON().with_variant(JSONB(), "postgresql")


class Identity:
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)


class Camera(Identity, Base):
    __tablename__ = "cameras"
    name: Mapped[str] = mapped_column(String(255))
    source_type: Mapped[str] = mapped_column(String(50))
    source: Mapped[str] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, onupdate=utc_now)


class Zone(Identity, Base):
    __tablename__ = "zones"
    camera_id: Mapped[UUID] = mapped_column(ForeignKey("cameras.id", ondelete="RESTRICT"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    polygon: Mapped[list[list[float]]] = mapped_column(JSON_DATA)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, onupdate=utc_now)


class Target(Identity, Base):
    __tablename__ = "targets"
    name: Mapped[str] = mapped_column(String(255))
    target_type: Mapped[str] = mapped_column(String(50))
    embedding: Mapped[list[float] | None] = mapped_column(JSON_DATA)
    reference_metadata: Mapped[dict[str, Any]] = mapped_column(JSON_DATA, default=dict)
    image_path: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class TargetEmbedding(Identity, Base):
    __tablename__ = "target_embeddings"
    target_id: Mapped[UUID] = mapped_column(ForeignKey("targets.id", ondelete="CASCADE"), index=True)
    embedding: Mapped[Any] = mapped_column(Vector(512), nullable=False)
    model_name: Mapped[str] = mapped_column(String(255))
    model_version: Mapped[str | None] = mapped_column(String(255))
    source_image_path: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class DetectionEvent(Identity, Base):
    __tablename__ = "detection_events"
    camera_id: Mapped[UUID] = mapped_column(ForeignKey("cameras.id", ondelete="RESTRICT"), index=True)
    event_type: Mapped[str] = mapped_column(String(50), index=True)
    frame_id: Mapped[int] = mapped_column(Integer)
    timestamp: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, index=True)
    track_id: Mapped[int | None] = mapped_column(Integer, index=True)
    class_name: Mapped[str | None] = mapped_column(String(100))
    confidence: Mapped[float | None] = mapped_column(Float)
    bbox: Mapped[list[float] | None] = mapped_column(JSON_DATA)
    snapshot_path: Mapped[str | None] = mapped_column(Text)
    event_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSON_DATA, default=dict)


class VehicleEvent(Identity, Base):
    __tablename__ = "vehicle_events"
    detection_event_id: Mapped[UUID] = mapped_column(ForeignKey("detection_events.id", ondelete="CASCADE"), index=True)
    vehicle_class: Mapped[str] = mapped_column(String(100))
    track_id: Mapped[int] = mapped_column(Integer, index=True)
    zone_id: Mapped[str | None] = mapped_column(String(100))
    first_seen: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    last_seen: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class PlateEvent(Identity, Base):
    __tablename__ = "plate_events"
    vehicle_event_id: Mapped[UUID] = mapped_column(ForeignKey("vehicle_events.id", ondelete="CASCADE"), index=True)
    plate_text: Mapped[str] = mapped_column(String(100), index=True)
    confidence: Mapped[float | None] = mapped_column(Float)
    plate_bbox: Mapped[list[float] | None] = mapped_column(JSON_DATA)
    plate_crop_path: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(50), default="pending")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class FaceEvent(Identity, Base):
    __tablename__ = "face_events"
    detection_event_id: Mapped[UUID] = mapped_column(ForeignKey("detection_events.id", ondelete="CASCADE"), index=True)
    target_id: Mapped[UUID | None] = mapped_column(ForeignKey("targets.id", ondelete="SET NULL"), index=True)
    track_id: Mapped[int | None] = mapped_column(Integer, index=True)
    similarity: Mapped[float | None] = mapped_column(Float)
    decision: Mapped[str] = mapped_column(String(50))
    face_crop_path: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class VehiclePassage(Identity, Base):
    """One continuous vehicle appearance in one camera.

    vehicle_color is nullable and currently unavailable in the detector runtime;
    not fabricated.
    """
    __tablename__ = "vehicle_passages"

    camera_id: Mapped[str] = mapped_column(String(255), index=True)
    zone_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)

    track_id: Mapped[int] = mapped_column(Integer, index=True)
    session_key: Mapped[str] = mapped_column(String(255), unique=True, index=True)

    vehicle_type: Mapped[str] = mapped_column(String(100), default="vehicle")
    vehicle_color: Mapped[str | None] = mapped_column(String(50), nullable=True)
    vehicle_type_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    vehicle_color_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    plate_text: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    plate_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    plate_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    direction: Mapped[str | None] = mapped_column(String(50), nullable=True)

    first_seen_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, index=True)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    duration_ms: Mapped[float] = mapped_column(Float, default=0.0)

    best_vehicle_image_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    best_plate_image_path: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, onupdate=utc_now)
    finalized_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)

    __table_args__ = (
        Index("ix_vehicle_passages_cam_first_seen", "camera_id", "first_seen_at"),
        Index("ix_vehicle_passages_zone_first_seen", "zone_id", "first_seen_at"),
        Index("ix_vehicle_passages_type_first_seen", "vehicle_type", "first_seen_at"),
    )


class BusinessEvent(Identity, Base):
    """Meaningful business domain event linked to a vehicle passage or system domain."""
    __tablename__ = "business_events"

    passage_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("vehicle_passages.id", ondelete="CASCADE"), nullable=True, index=True
    )
    camera_id: Mapped[str] = mapped_column(String(255), index=True)
    zone_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    track_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    event_type: Mapped[str] = mapped_column(String(50), index=True)
    event_time: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, index=True)

    vehicle_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    plate_text: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    direction: Mapped[str | None] = mapped_column(String(50), nullable=True)

    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    event_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSON_DATA, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)

    __table_args__ = (
        Index("ix_business_events_cam_time", "camera_id", "event_time"),
    )

