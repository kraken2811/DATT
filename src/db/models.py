"""Portable PostgreSQL/SQLite event schema."""

from datetime import datetime, timezone
from uuid import UUID, uuid4
from typing import Any

from sqlalchemy import UniqueConstraint, CheckConstraint, Boolean, DateTime, Float, ForeignKey, Index, Integer, JSON, MetaData, String, Text, Uuid
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
    registry_key: Mapped[str | None] = mapped_column(String(255), unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    thumbnail_path: Mapped[str | None] = mapped_column(Text)
    last_active: Mapped[datetime | None] = mapped_column(UTCDateTime())
    active_token: Mapped[str | None] = mapped_column(String(64))
    active_until: Mapped[datetime | None] = mapped_column(UTCDateTime())
    video_source_id: Mapped[UUID | None] = mapped_column(ForeignKey("video_sources.id", ondelete="RESTRICT"))
    name: Mapped[str] = mapped_column(String(255))
    source_type: Mapped[str] = mapped_column(String(50))
    source: Mapped[str] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, onupdate=utc_now)


class VideoSource(Identity, Base):
    __tablename__ = "video_sources"
    original_filename: Mapped[str] = mapped_column(String(255))
    storage_path: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(50), default="ready", index=True)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    fps: Mapped[float | None] = mapped_column(Float, nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    video_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSON_DATA, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, index=True)
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
    camera_id: Mapped[UUID | None] = mapped_column(ForeignKey("cameras.id", ondelete="RESTRICT"), nullable=True, index=True)
    video_source_id: Mapped[UUID | None] = mapped_column(ForeignKey("video_sources.id", ondelete="SET NULL"), nullable=True, index=True)
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
    detection_event_id: Mapped[UUID | None] = mapped_column(ForeignKey("detection_events.id", ondelete="CASCADE"), nullable=True, index=True)
    video_source_id: Mapped[UUID | None] = mapped_column(ForeignKey("video_sources.id", ondelete="SET NULL"), nullable=True, index=True)
    vehicle_class: Mapped[str] = mapped_column(String(100))
    track_id: Mapped[int] = mapped_column(Integer, index=True)
    zone_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    vehicle_color: Mapped[str | None] = mapped_column(String(50), nullable=True)
    vehicle_image_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    first_seen: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    last_seen: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class PlateEvent(Identity, Base):
    __tablename__ = "plate_events"
    vehicle_event_id: Mapped[UUID] = mapped_column(ForeignKey("vehicle_events.id", ondelete="CASCADE"), index=True)
    plate_text: Mapped[str] = mapped_column(String(100), index=True)
    normalized_plate: Mapped[str | None] = mapped_column(String(100), index=True)
    confidence: Mapped[float | None] = mapped_column(Float)
    plate_bbox: Mapped[list[float] | None] = mapped_column(JSON_DATA)
    plate_crop_path: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(50), default="pending")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class FaceEvent(Identity, Base):
    __tablename__ = "face_events"
    camera_id: Mapped[str | None] = mapped_column(String(255), index=True)
    detection_event_id: Mapped[UUID | None] = mapped_column(ForeignKey("detection_events.id", ondelete="CASCADE"), nullable=True, index=True)
    video_source_id: Mapped[UUID | None] = mapped_column(ForeignKey("video_sources.id", ondelete="SET NULL"), nullable=True, index=True)
    target_id: Mapped[UUID | None] = mapped_column(ForeignKey("targets.id", ondelete="SET NULL"), index=True)
    track_id: Mapped[int | None] = mapped_column(Integer, index=True)
    frame_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
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
    video_source_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("video_sources.id", ondelete="SET NULL"), nullable=True, index=True
    )
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
    video_source_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("video_sources.id", ondelete="SET NULL"), nullable=True, index=True
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



class Notification(Identity, Base):
    """Durable email outbox and delivery history; no provider credentials."""
    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint("event_id", "channel", "recipient", name="uq_notifications_event_channel_recipient"),
        CheckConstraint("status IN ('pending','sent','failed','suppressed')", name="notification_status"),
        UniqueConstraint("plate_event_id", "channel", "recipient", name="uq_notifications_plate_channel_recipient"),
        CheckConstraint("(event_id IS NOT NULL AND plate_event_id IS NULL) OR (event_id IS NULL AND plate_event_id IS NOT NULL)", name="notification_event_kind"),
        Index("ix_notifications_vehicle_cooldown", "vehicle_watchlist_id", "camera_id", "created_at"),
        Index("ix_notifications_due", "status", "next_attempt_at"),
        Index("ix_notifications_cooldown", "target_id", "camera_id", "created_at"),
    )
    event_id: Mapped[UUID | None] = mapped_column(ForeignKey("face_events.id", ondelete="CASCADE"))
    plate_event_id: Mapped[UUID | None] = mapped_column(ForeignKey("plate_events.id", ondelete="CASCADE"))
    vehicle_watchlist_id: Mapped[UUID | None] = mapped_column(ForeignKey("vehicle_watchlists.id", ondelete="SET NULL"))
    target_id: Mapped[UUID | None] = mapped_column(ForeignKey("targets.id", ondelete="SET NULL"))
    camera_id: Mapped[str] = mapped_column(String(255))
    channel: Mapped[str] = mapped_column(String(30), default="email")
    recipient: Mapped[str] = mapped_column(String(320))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(String(100))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON_DATA)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    next_attempt_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class VehicleWatchlist(Identity, Base):
    __tablename__ = "vehicle_watchlists"
    __table_args__ = (CheckConstraint("status IN ('active','disabled')", name="vehicle_watchlist_status"),)
    plate_number: Mapped[str] = mapped_column(String(100), unique=True)
    vehicle_type: Mapped[str] = mapped_column(String(100), default="car")
    vehicle_color: Mapped[str | None] = mapped_column(String(20), nullable=True)
    display_name: Mapped[str] = mapped_column(String(255), default="")
    owner_info: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="active")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, onupdate=utc_now)


class VehicleWatchlistResult(Identity, Base):
    """Snapshot of watchlist lookup at PlateEvent persistence time."""
    __tablename__ = "vehicle_watchlist_results"
    plate_event_id: Mapped[UUID] = mapped_column(ForeignKey("plate_events.id", ondelete="CASCADE"), unique=True)
    watchlist_id: Mapped[UUID | None] = mapped_column(ForeignKey("vehicle_watchlists.id", ondelete="SET NULL"), index=True)
    normalized_plate: Mapped[str] = mapped_column(String(100), index=True)
    decision: Mapped[str] = mapped_column(String(20))
    display_name: Mapped[str | None] = mapped_column(String(255))
    camera_id: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    __table_args__ = (CheckConstraint("decision IN ('MATCH','NO_MATCH')", name="vehicle_watchlist_decision"),)


class KnowledgeDocument(Identity, Base):
    """Catalog of ingested reference and troubleshooting documents for RAG."""
    __tablename__ = "knowledge_documents"
    title: Mapped[str] = mapped_column(String(255))
    source: Mapped[str] = mapped_column(String(1024), index=True)
    document_type: Mapped[str] = mapped_column(String(50), default="markdown", index=True)
    content_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    doc_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSON_DATA, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, onupdate=utc_now)


class KnowledgeChunk(Identity, Base):
    """Segmented passages and their 384D vector embeddings for semantic search."""
    __tablename__ = "knowledge_chunks"
    document_id: Mapped[UUID] = mapped_column(ForeignKey("knowledge_documents.id", ondelete="CASCADE"), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[Any] = mapped_column(Vector(384), nullable=True)
    chunk_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSON_DATA, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, onupdate=utc_now)

    __table_args__ = (
        Index("ix_knowledge_chunks_doc_idx", "document_id", "chunk_index"),
    )


class AgentConversation(Identity, Base):
    """Registry of persistent user conversations for DATT AI Agent."""
    __tablename__ = "agent_conversations"

    thread_id: Mapped[str] = mapped_column(String(128), index=True)
    user_id: Mapped[str] = mapped_column(String(255), index=True)
    title: Mapped[str] = mapped_column(String(255), default="Cuộc trò chuyện mới")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, onupdate=utc_now)
    last_message_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)

    __table_args__ = (
        UniqueConstraint("thread_id", name="uq_agent_conversations_thread_id"),
        Index("ix_agent_conversations_user_updated", "user_id", "updated_at"),
        Index("ix_agent_conversations_user_last_msg", "user_id", "last_message_at"),
    )


class CrossingEvent(Identity, Base):
    """Directional passage crossing event for people and vehicles."""
    __tablename__ = "crossing_events"

    camera_id: Mapped[str] = mapped_column(String(255), index=True)
    zone_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    object_type: Mapped[str] = mapped_column(String(50), index=True)  # "person" or "vehicle"
    object_class: Mapped[str] = mapped_column(String(50), default="person")
    direction: Mapped[str] = mapped_column(String(20), index=True)  # "in" or "out"
    track_id: Mapped[int] = mapped_column(Integer, index=True)
    tracking_session_id: Mapped[str] = mapped_column(String(255), index=True)
    event_time: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, index=True)
    source_type: Mapped[str] = mapped_column(String(50), default="live")
    video_source_id: Mapped[UUID | None] = mapped_column(ForeignKey("video_sources.id", ondelete="SET NULL"), nullable=True, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    event_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSON_DATA, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)

    __table_args__ = (
        Index("ix_crossing_events_cam_time", "camera_id", "event_time"),
        Index("ix_crossing_events_type_time", "object_type", "event_time"),
        Index("ix_crossing_events_zone_time", "zone_id", "event_time"),
    )


class AnalyticsAggregate(Identity, Base):
    """Pre-computed time-bucket aggregate metrics (15-minute default)."""
    __tablename__ = "analytics_aggregates"

    camera_id: Mapped[str] = mapped_column(String(255), index=True)
    zone_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    bucket_start: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    bucket_end: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    timezone: Mapped[str] = mapped_column(String(50), default="Asia/Ho_Chi_Minh")
    bucket_duration_minutes: Mapped[int] = mapped_column(Integer, default=15)
    person_in_count: Mapped[int] = mapped_column(Integer, default=0)
    person_out_count: Mapped[int] = mapped_column(Integer, default=0)
    vehicle_in_count: Mapped[int] = mapped_column(Integer, default=0)
    vehicle_out_count: Mapped[int] = mapped_column(Integer, default=0)
    vehicle_type_breakdown: Mapped[dict[str, Any]] = mapped_column(JSON_DATA, default=dict)
    average_visible_person_count: Mapped[float] = mapped_column(Float, default=0.0)
    maximum_visible_person_count: Mapped[int] = mapped_column(Integer, default=0)
    average_visible_vehicle_count: Mapped[float] = mapped_column(Float, default=0.0)
    maximum_visible_vehicle_count: Mapped[int] = mapped_column(Integer, default=0)
    observed_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    expected_seconds: Mapped[float] = mapped_column(Float, default=900.0)
    coverage_ratio: Mapped[float] = mapped_column(Float, default=0.0)
    data_quality_status: Mapped[str] = mapped_column(String(50), default="EXCELLENT")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, onupdate=utc_now)

    __table_args__ = (
        UniqueConstraint("camera_id", "zone_id", "bucket_start", name="uq_analytics_aggregates_cam_zone_bucket"),
        Index("ix_analytics_aggregates_cam_start", "camera_id", "bucket_start"),
    )


class CameraAnalyticsConfig(Identity, Base):
    """Configuration for camera line crossing, ROI, and analytics thresholds."""
    __tablename__ = "camera_analytics_configs"

    camera_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    counting_line: Mapped[dict[str, Any] | None] = mapped_column(JSON_DATA, nullable=True)
    in_direction: Mapped[str] = mapped_column(String(50), default="normal")
    roi_polygon: Mapped[list[list[float]] | None] = mapped_column(JSON_DATA, nullable=True)
    supported_classes: Mapped[list[str]] = mapped_column(JSON_DATA, default=lambda: ["person", "car", "motorcycle", "bus", "truck"])
    min_crossing_distance: Mapped[float] = mapped_column(Float, default=0.015)
    hysteresis_frames: Mapped[int] = mapped_column(Integer, default=2)
    capacity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, onupdate=utc_now)


class TrafficForecast(Identity, Base):
    """Computed traffic forecast for tomorrow with prediction intervals and backtest metrics."""
    __tablename__ = "traffic_forecasts"

    camera_id: Mapped[str] = mapped_column(String(255), index=True)
    zone_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    target_date: Mapped[str] = mapped_column(String(20), index=True)  # YYYY-MM-DD
    target_weekday: Mapped[int] = mapped_column(Integer)  # 0..6
    generated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    model_version: Mapped[str] = mapped_column(String(50), default="weighted_same_weekday_v1")
    data_quality_status: Mapped[str] = mapped_column(String(50), default="READY")
    hourly_forecasts: Mapped[list[dict[str, Any]]] = mapped_column(JSON_DATA, default=list)
    peak_hours: Mapped[list[dict[str, Any]]] = mapped_column(JSON_DATA, default=list)
    total_forecast_traffic: Mapped[dict[str, Any]] = mapped_column(JSON_DATA, default=dict)
    historical_days_used: Mapped[int] = mapped_column(Integer, default=0)
    backtest_metrics: Mapped[dict[str, Any]] = mapped_column(JSON_DATA, default=dict)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)

    __table_args__ = (
        UniqueConstraint("camera_id", "zone_id", "target_date", name="uq_traffic_forecasts_cam_zone_date"),
        Index("ix_traffic_forecasts_cam_date", "camera_id", "target_date"),
    )


class ForecastAlertRule(Identity, Base):
    """Rule definition for automated predictive alerts."""
    __tablename__ = "forecast_alert_rules"

    camera_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    zone_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    alert_type: Mapped[str] = mapped_column(String(50), default="EXPECTED_HIGH_TRAFFIC")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    high_traffic_threshold: Mapped[int] = mapped_column(Integer, default=200)
    peak_traffic_threshold: Mapped[int] = mapped_column(Integer, default=500)
    capacity_threshold_ratio: Mapped[float] = mapped_column(Float, default=0.85)
    min_coverage_ratio: Mapped[float] = mapped_column(Float, default=0.70)
    recipient_emails: Mapped[list[str]] = mapped_column(JSON_DATA, default=list)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, onupdate=utc_now)


class ForecastAlert(Identity, Base):
    """Generated forecast alert record."""
    __tablename__ = "forecast_alerts"

    forecast_id: Mapped[UUID | None] = mapped_column(ForeignKey("traffic_forecasts.id", ondelete="CASCADE"), nullable=True, index=True)
    camera_id: Mapped[str] = mapped_column(String(255), index=True)
    zone_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    alert_type: Mapped[str] = mapped_column(String(50), index=True)
    severity: Mapped[str] = mapped_column(String(20), default="HIGH")
    target_date: Mapped[str] = mapped_column(String(20), index=True)
    peak_window: Mapped[str | None] = mapped_column(String(100), nullable=True)
    expected_traffic: Mapped[dict[str, Any]] = mapped_column(JSON_DATA, default=dict)
    threshold_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    recommendation: Mapped[str | None] = mapped_column(Text, nullable=True)
    delivery_status: Mapped[str] = mapped_column(String(20), default="pending")
    recipient: Mapped[str | None] = mapped_column(String(320), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)

    __table_args__ = (
        Index("ix_forecast_alerts_cam_date", "camera_id", "target_date"),
        Index("ix_forecast_alerts_status", "delivery_status"),
    )
