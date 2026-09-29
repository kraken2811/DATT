"""Public repositories for the persisted entities."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from dataclasses import dataclass, asdict
import math
from typing import Any, Sequence

from .base import Repository
from ..models import (
    Camera, Zone, Target, TargetEmbedding,
    DetectionEvent, VehicleEvent, PlateEvent, FaceEvent,
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


class ZoneRepository(Repository[Zone]):
    model = Zone


class TargetRepository(Repository[Target]):
    model = Target


class DetectionEventRepository(Repository[DetectionEvent]):
    model = DetectionEvent

    def query(self, *, camera_id: UUID | None = None, event_type: str | None = None,
              track_id: int | None = None, since: datetime | None = None,
              until: datetime | None = None, limit: int = 100, offset: int = 0):
        """Newest first; UTC time interval is [since, until)."""
        statement = select(self.model)
        for name, value in (("camera_id", camera_id), ("event_type", event_type), ("track_id", track_id)):
            if value is not None:
                statement = statement.where(getattr(self.model, name) == value)
        if since is not None:
            statement = statement.where(self.model.timestamp >= since)
        if until is not None:
            statement = statement.where(self.model.timestamp < until)
        return self._page(statement.order_by(self.model.timestamp.desc(), self.model.id), limit, offset)


class VehicleEventRepository(Repository[VehicleEvent]):
    model = VehicleEvent


class PlateEventRepository(Repository[PlateEvent]):
    model = PlateEvent


class FaceEventRepository(Repository[FaceEvent]):
    model = FaceEvent


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
