"""Public repositories for the persisted entities."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from dataclasses import dataclass, asdict
import math
from typing import Any, Sequence

from .base import Repository
from ..models import (
    Camera, VideoSource, Zone, Target, TargetEmbedding,
    DetectionEvent, VehicleEvent, PlateEvent, FaceEvent,
    VehiclePassage, BusinessEvent,
)


@dataclass
class VectorSearchResult:
    target_embedding_id: UUID
    target_id: UUID
    distance: float
    similarity: float
    model_name: str
    model_version: str | None

    def __getitem__(self, item: str) -> Any:
        return getattr(self, item)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CameraRepository(Repository[Camera]):
    model = Camera


class VideoSourceRepository(Repository[VideoSource]):
    model = VideoSource

    def get_by_storage_path(self, storage_path: str) -> VideoSource | None:
        statement = select(self.model).where(self.model.storage_path == storage_path)
        return self.session.scalars(statement).first()

    def query_sources(
        self,
        *,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[VideoSource]:
        statement = select(self.model)
        if status is not None:
            statement = statement.where(self.model.status == status)
        return self._page(statement.order_by(self.model.created_at.desc(), self.model.id), limit, offset)


class ZoneRepository(Repository[Zone]):
    model = Zone


class TargetRepository(Repository[Target]):
    model = Target

    def create(self, **values) -> Target:
        explicit_id = values.pop("id", None)
        self._validate_fields(values)
        if explicit_id is not None:
            item = self.model(id=explicit_id, **values)
        else:
            item = self.model(**values)
        self.session.add(item)
        self.session.flush()
        return item



class DetectionEventRepository(Repository[DetectionEvent]):
    model = DetectionEvent

    def query(self, *, camera_id: UUID | None = None, event_type: str | None = None,
              track_id: int | None = None, video_source_id: UUID | None = None,
              since: datetime | None = None, until: datetime | None = None,
              limit: int = 100, offset: int = 0):
        """Newest first; UTC time interval is [since, until)."""
        statement = select(self.model)
        for name, value in (
            ("camera_id", camera_id),
            ("event_type", event_type),
            ("track_id", track_id),
            ("video_source_id", video_source_id),
        ):
            if value is not None:
                statement = statement.where(getattr(self.model, name) == value)
        if since is not None:
            statement = statement.where(self.model.timestamp >= since)
        if until is not None:
            statement = statement.where(self.model.timestamp < until)
        return self._page(statement.order_by(self.model.timestamp.desc(), self.model.id), limit, offset)


class VehicleEventRepository(Repository[VehicleEvent]):
    model = VehicleEvent

    def create(self, **values) -> VehicleEvent:
        explicit_id = values.pop("id", None)
        explicit_created = values.pop("created_at", None)
        self._validate_fields(values)
        if explicit_id is not None:
            item = self.model(id=explicit_id, **values)
        else:
            item = self.model(**values)
        if explicit_created is not None:
            item.created_at = explicit_created
        self.session.add(item)
        self.session.flush()
        return item

    def query_events(
        self,
        *,
        track_id: int | None = None,
        vehicle_class: str | None = None,
        vehicle_color: str | None = None,
        zone_id: str | None = None,
        video_source_id: UUID | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[VehicleEvent]:
        statement = select(self.model)
        if track_id is not None:
            statement = statement.where(self.model.track_id == track_id)
        if vehicle_class is not None:
            statement = statement.where(self.model.vehicle_class == vehicle_class)
        if vehicle_color is not None:
            statement = statement.where(self.model.vehicle_color == vehicle_color)
        if zone_id is not None:
            statement = statement.where(self.model.zone_id == zone_id)
        if video_source_id is not None:
            statement = statement.where(self.model.video_source_id == video_source_id)
        if since is not None:
            statement = statement.where(self.model.first_seen >= since)
        if until is not None:
            statement = statement.where(self.model.first_seen < until)
        return self._page(statement.order_by(self.model.first_seen.desc(), self.model.id), limit, offset)


class PlateEventRepository(Repository[PlateEvent]):
    model = PlateEvent

    def create(self, **values) -> PlateEvent:
        explicit_id = values.pop("id", None)
        explicit_created = values.pop("created_at", None)
        self._validate_fields(values)
        if explicit_id is not None:
            item = self.model(id=explicit_id, **values)
        else:
            item = self.model(**values)
        if explicit_created is not None:
            item.created_at = explicit_created
        self.session.add(item)
        self.session.flush()
        return item

    def get_by_vehicle_event(self, vehicle_event_id: UUID) -> list[PlateEvent]:
        statement = select(self.model).where(self.model.vehicle_event_id == vehicle_event_id)
        return list(self.session.scalars(statement))

    def query_events(
        self,
        *,
        vehicle_event_id: UUID | None = None,
        plate_text: str | None = None,
        status: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[PlateEvent]:
        statement = select(self.model)
        if vehicle_event_id is not None:
            statement = statement.where(self.model.vehicle_event_id == vehicle_event_id)
        if plate_text is not None:
            statement = statement.where(self.model.plate_text.ilike(f"%{plate_text}%"))
        if status is not None:
            statement = statement.where(self.model.status == status)
        if since is not None:
            statement = statement.where(self.model.created_at >= since)
        if until is not None:
            statement = statement.where(self.model.created_at < until)
        return self._page(statement.order_by(self.model.created_at.desc(), self.model.id), limit, offset)


class FaceEventRepository(Repository[FaceEvent]):
    model = FaceEvent

    def create(self, **values) -> FaceEvent:
        explicit_id = values.pop("id", None)
        explicit_created = values.pop("created_at", None)
        self._validate_fields(values)
        if explicit_id is not None:
            item = self.model(id=explicit_id, **values)
        else:
            item = self.model(**values)
        if explicit_created is not None:
            item.created_at = explicit_created
        self.session.add(item)
        self.session.flush()
        return item

    def query_events(
        self,
        *,
        target_id: UUID | None = None,
        track_id: int | None = None,
        video_source_id: UUID | None = None,
        decision: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[FaceEvent]:
        statement = select(self.model)
        if target_id is not None:
            statement = statement.where(self.model.target_id == target_id)
        if track_id is not None:
            statement = statement.where(self.model.track_id == track_id)
        if video_source_id is not None:
            statement = statement.where(self.model.video_source_id == video_source_id)
        if decision is not None:
            statement = statement.where(self.model.decision == decision)
        if since is not None:
            statement = statement.where(self.model.created_at >= since)
        if until is not None:
            statement = statement.where(self.model.created_at < until)
        return self._page(statement.order_by(self.model.created_at.desc(), self.model.id), limit, offset)


class VehiclePassageRepository(Repository[VehiclePassage]):
    model = VehiclePassage

    def create(self, **values) -> VehiclePassage:
        explicit_id = values.pop("id", None)
        self._validate_fields(values)
        if explicit_id is not None:
            item = self.model(id=explicit_id, **values)
        else:
            item = self.model(**values)
        self.session.add(item)
        self.session.flush()
        return item

    def get_by_session_key(self, session_key: str) -> VehiclePassage | None:
        statement = select(self.model).where(self.model.session_key == session_key)
        return self.session.scalars(statement).first()

    def upsert_passage(self, session_key: str, **values) -> tuple[VehiclePassage, bool]:
        """Insert or update a passage by session_key.

        Returns (passage, created): created is True if inserted, False if updated.
        """
        existing = self.get_by_session_key(session_key)
        if existing is not None:
            # Update fields
            for key, val in values.items():
                if key in {"id", "created_at", "session_key"}:
                    continue
                if hasattr(existing, key) and val is not None:
                    setattr(existing, key, val)
            self.session.flush()
            return existing, False
        else:
            values["session_key"] = session_key
            item = self.create(**values)
            return item, True

    def query_passages(
        self,
        *,
        plate_text: str | None = None,
        camera_id: str | None = None,
        video_source_id: UUID | None = None,
        zone_id: str | None = None,
        vehicle_type: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[VehiclePassage]:
        statement = select(self.model)
        if plate_text is not None:
            statement = statement.where(self.model.plate_text == plate_text)
        if camera_id is not None:
            statement = statement.where(self.model.camera_id == camera_id)
        if video_source_id is not None:
            statement = statement.where(self.model.video_source_id == video_source_id)
        if zone_id is not None:
            statement = statement.where(self.model.zone_id == zone_id)
        if vehicle_type is not None:
            statement = statement.where(self.model.vehicle_type == vehicle_type)
        if since is not None:
            statement = statement.where(self.model.first_seen_at >= since)
        if until is not None:
            statement = statement.where(self.model.first_seen_at < until)
        return self._page(statement.order_by(self.model.first_seen_at.desc(), self.model.id), limit, offset)

    def count_vehicle_types(
        self,
        *,
        camera_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> dict[str, int]:
        statement = select(self.model.vehicle_type, func.count(self.model.id))
        if camera_id is not None:
            statement = statement.where(self.model.camera_id == camera_id)
        if since is not None:
            statement = statement.where(self.model.first_seen_at >= since)
        if until is not None:
            statement = statement.where(self.model.first_seen_at < until)
        statement = statement.group_by(self.model.vehicle_type)
        rows = self.session.execute(statement).all()
        return {r[0]: int(r[1]) for r in rows}


class BusinessEventRepository(Repository[BusinessEvent]):
    model = BusinessEvent

    def create(self, **values) -> BusinessEvent:
        if "metadata" in values and "event_metadata" not in values:
            values["event_metadata"] = values.pop("metadata")
        explicit_id = values.pop("id", None)
        self._validate_fields(values)
        if explicit_id is not None:
            item = self.model(id=explicit_id, **values)
        else:
            item = self.model(**values)
        self.session.add(item)
        self.session.flush()
        return item

    def get_by_idempotency_key(self, idempotency_key: str) -> BusinessEvent | None:
        statement = select(self.model).where(self.model.idempotency_key == idempotency_key)
        return self.session.scalars(statement).first()

    def insert_idempotent(self, **values) -> tuple[BusinessEvent, bool]:
        """Insert business event idempotently.

        Returns (event, created): created is True if inserted, False if already existed.
        """
        idempotency_key = values.get("idempotency_key")
        if idempotency_key:
            existing = self.get_by_idempotency_key(idempotency_key)
            if existing is not None:
                return existing, False
        event = self.create(**values)
        return event, True

    def query_events(
        self,
        *,
        camera_id: str | None = None,
        video_source_id: UUID | None = None,
        event_type: str | None = None,
        passage_id: UUID | None = None,
        plate_text: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[BusinessEvent]:
        statement = select(self.model)
        if camera_id is not None:
            statement = statement.where(self.model.camera_id == camera_id)
        if video_source_id is not None:
            statement = statement.where(self.model.video_source_id == video_source_id)
        if event_type is not None:
            statement = statement.where(self.model.event_type == event_type)
        if passage_id is not None:
            statement = statement.where(self.model.passage_id == passage_id)
        if plate_text is not None:
            statement = statement.where(self.model.plate_text == plate_text)
        if since is not None:
            statement = statement.where(self.model.event_time >= since)
        if until is not None:
            statement = statement.where(self.model.event_time < until)
        return self._page(statement.order_by(self.model.event_time.desc(), self.model.id), limit, offset)



class TargetEmbeddingRepository(Repository[TargetEmbedding]):
    model = TargetEmbedding

    def _validate_embedding(self, embedding: Any) -> list[float]:
        if hasattr(embedding, "tolist"):
            embedding = embedding.tolist()
        if not isinstance(embedding, (list, tuple)):
            raise ValueError(f"embedding must be a sequence of floats, got {type(embedding)}")
        if len(embedding) != 512:
            raise ValueError(f"embedding dimension must be exactly 512, got {len(embedding)}")
        for i, val in enumerate(embedding):
            if val is None or not isinstance(val, (int, float)) or math.isnan(val) or math.isinf(val):
                raise ValueError(f"embedding contains invalid value at index {i}: {val}")
        return [float(x) for x in embedding]

    def create(self, **values) -> TargetEmbedding:
        if "embedding" in values:
            values["embedding"] = self._validate_embedding(values["embedding"])
        return super().create(**values)

    def update(self, item_id: UUID, **values) -> TargetEmbedding | None:
        if "embedding" in values:
            values["embedding"] = self._validate_embedding(values["embedding"])
        return super().update(item_id, **values)

    def search_similar(
        self,
        embedding: Sequence[float],
        limit: int = 5,
        max_distance: float | None = None,
    ) -> list[VectorSearchResult]:
        """Perform exact cosine nearest-neighbor vector search."""
        if not (1 <= limit <= 1000):
            raise ValueError("limit must be between 1 and 1000")
        clean_emb = self._validate_embedding(embedding)

        distance_col = self.model.embedding.cosine_distance(clean_emb).label("distance")
        from sqlalchemy import select
        statement = (
            select(
                self.model.id,
                self.model.target_id,
                self.model.model_name,
                self.model.model_version,
                distance_col,
            )
            .order_by(distance_col.asc(), self.model.id.asc())
        )
        if max_distance is not None:
            statement = statement.where(distance_col <= max_distance)

        statement = statement.limit(limit)
        rows = self.session.execute(statement).all()
        results: list[VectorSearchResult] = []
        for r in rows:
            dist = float(r.distance)
            sim = float(1.0 - dist)
            results.append(
                VectorSearchResult(
                    target_embedding_id=r.id,
                    target_id=r.target_id,
                    distance=dist,
                    similarity=sim,
                    model_name=r.model_name,
                    model_version=r.model_version,
                )
            )
        return results


__all__ = [
    "VectorSearchResult",
    "CameraRepository",
    "VideoSourceRepository",
    "ZoneRepository",
    "TargetRepository",
    "DetectionEventRepository",
    "VehicleEventRepository",
    "PlateEventRepository",
    "FaceEventRepository",
    "VehiclePassageRepository",
    "BusinessEventRepository",
    "TargetEmbeddingRepository",
]

