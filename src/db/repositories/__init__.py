"""Public repositories for the persisted entities."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select

from .base import Repository
from ..models import Camera, Zone, Target, DetectionEvent, VehicleEvent, PlateEvent, FaceEvent


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
