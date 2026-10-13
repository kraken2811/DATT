"""Repositories for Analytics, Crossing Events, and Forecasting."""

from datetime import datetime, timezone
from typing import Any, Sequence
from uuid import UUID, uuid4

from sqlalchemy import func, select, or_
from sqlalchemy.orm import Session

from .base import Repository
from ..models import (
    CrossingEvent,
    AnalyticsAggregate,
    CameraAnalyticsConfig,
    TrafficForecast,
    ForecastAlertRule,
    ForecastAlert,
)


class CrossingEventRepository(Repository[CrossingEvent]):
    model = CrossingEvent

    def create(self, **values) -> CrossingEvent:
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

    def get_by_idempotency_key(self, idempotency_key: str) -> CrossingEvent | None:
        statement = select(self.model).where(self.model.idempotency_key == idempotency_key)
        return self.session.scalars(statement).first()

    def insert_idempotent(self, **values) -> tuple[CrossingEvent, bool]:
        """Insert crossing event idempotently using idempotency_key.

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
        zone_id: str | None = None,
        object_type: str | None = None,
        direction: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[CrossingEvent]:
        statement = select(self.model)
        if camera_id is not None:
            statement = statement.where(self.model.camera_id == camera_id)
        if zone_id is not None:
            statement = statement.where(self.model.zone_id == zone_id)
        if object_type is not None:
            statement = statement.where(self.model.object_type == object_type)
        if direction is not None:
            statement = statement.where(self.model.direction == direction)
        if since is not None:
            statement = statement.where(self.model.event_time >= since)
        if until is not None:
            statement = statement.where(self.model.event_time <= until)

        return self._page(
            statement.order_by(self.model.event_time.desc(), self.model.id), limit, offset
        )


class AnalyticsAggregateRepository(Repository[AnalyticsAggregate]):
    model = AnalyticsAggregate

    def get_by_bucket(
        self,
        camera_id: str,
        bucket_start: datetime,
        zone_id: str | None = None,
    ) -> AnalyticsAggregate | None:
        statement = select(self.model).where(
            self.model.camera_id == camera_id,
            self.model.bucket_start == bucket_start,
        )
        if zone_id is not None:
            statement = statement.where(self.model.zone_id == zone_id)
        else:
            statement = statement.where(self.model.zone_id.is_(None))
        return self.session.scalars(statement).first()

    def upsert_aggregate(
        self,
        camera_id: str,
        bucket_start: datetime,
        bucket_end: datetime,
        zone_id: str | None = None,
        **metrics: Any,
    ) -> tuple[AnalyticsAggregate, bool]:
        """Upsert a 15-minute or custom time bucket aggregate."""
        existing = self.get_by_bucket(camera_id, bucket_start, zone_id=zone_id)
        if existing is not None:
            existing.bucket_end = bucket_end
            for k, v in metrics.items():
                if hasattr(existing, k) and v is not None:
                    setattr(existing, k, v)
            existing.updated_at = datetime.now(timezone.utc)
            self.session.flush()
            return existing, False
        else:
            item = self.model(
                id=uuid4(),
                camera_id=camera_id,
                zone_id=zone_id,
                bucket_start=bucket_start,
                bucket_end=bucket_end,
                **metrics,
            )
            self.session.add(item)
            self.session.flush()
            return item, True

    def query_aggregates(
        self,
        *,
        camera_id: str | None = None,
        zone_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> list[AnalyticsAggregate]:
        statement = select(self.model)
        if camera_id is not None:
            statement = statement.where(self.model.camera_id == camera_id)
        if zone_id is not None:
            statement = statement.where(self.model.zone_id == zone_id)
        if since is not None:
            statement = statement.where(self.model.bucket_start >= since)
        if until is not None:
            statement = statement.where(self.model.bucket_end <= until)

        return list(
            self.session.scalars(statement.order_by(self.model.bucket_start.asc())).all()
        )


class CameraAnalyticsConfigRepository(Repository[CameraAnalyticsConfig]):
    model = CameraAnalyticsConfig

    def get_by_camera_id(self, camera_id: str) -> CameraAnalyticsConfig | None:
        statement = select(self.model).where(self.model.camera_id == camera_id)
        return self.session.scalars(statement).first()

    def upsert_config(self, camera_id: str, **values: Any) -> CameraAnalyticsConfig:
        existing = self.get_by_camera_id(camera_id)
        if existing is not None:
            for k, v in values.items():
                if hasattr(existing, k) and v is not None:
                    setattr(existing, k, v)
            existing.updated_at = datetime.now(timezone.utc)
            self.session.flush()
            return existing
        else:
            item = self.model(id=uuid4(), camera_id=camera_id, **values)
            self.session.add(item)
            self.session.flush()
            return item


class TrafficForecastRepository(Repository[TrafficForecast]):
    model = TrafficForecast

    def get_forecast(
        self,
        camera_id: str,
        target_date: str,
        zone_id: str | None = None,
    ) -> TrafficForecast | None:
        statement = select(self.model).where(
            self.model.camera_id == camera_id,
            self.model.target_date == target_date,
        )
        if zone_id is not None:
            statement = statement.where(self.model.zone_id == zone_id)
        return self.session.scalars(statement).first()

    def save_forecast(
        self,
        camera_id: str,
        target_date: str,
        target_weekday: int,
        zone_id: str | None = None,
        **values: Any,
    ) -> TrafficForecast:
        existing = self.get_forecast(camera_id, target_date, zone_id=zone_id)
        if existing is not None:
            for k, v in values.items():
                if hasattr(existing, k):
                    setattr(existing, k, v)
            existing.generated_at = datetime.now(timezone.utc)
            self.session.flush()
            return existing
        else:
            item = self.model(
                id=uuid4(),
                camera_id=camera_id,
                zone_id=zone_id,
                target_date=target_date,
                target_weekday=target_weekday,
                **values,
            )
            self.session.add(item)
            self.session.flush()
            return item

    def get_latest_forecast(
        self,
        camera_id: str | None = None,
        target_date: str | None = None,
    ) -> TrafficForecast | None:
        statement = select(self.model)
        if camera_id is not None:
            statement = statement.where(self.model.camera_id == camera_id)
        if target_date is not None:
            statement = statement.where(self.model.target_date == target_date)
        statement = statement.order_by(self.model.generated_at.desc())
        return self.session.scalars(statement).first()


class ForecastAlertRuleRepository(Repository[ForecastAlertRule]):
    model = ForecastAlertRule

    def get_rules(
        self,
        camera_id: str | None = None,
        enabled_only: bool = True,
    ) -> list[ForecastAlertRule]:
        statement = select(self.model)
        if enabled_only:
            statement = statement.where(self.model.enabled.is_(True))
        if camera_id is not None:
            statement = statement.where(
                or_(self.model.camera_id == camera_id, self.model.camera_id.is_(None))
            )
        return list(self.session.scalars(statement).all())


class ForecastAlertRepository(Repository[ForecastAlert]):
    model = ForecastAlert

    def query_alerts(
        self,
        *,
        camera_id: str | None = None,
        target_date: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ForecastAlert]:
        statement = select(self.model)
        if camera_id is not None:
            statement = statement.where(self.model.camera_id == camera_id)
        if target_date is not None:
            statement = statement.where(self.model.target_date == target_date)
        if status is not None and status != "all":
            statement = statement.where(self.model.delivery_status == status)

        return self._page(
            statement.order_by(self.model.created_at.desc(), self.model.id), limit, offset
        )
