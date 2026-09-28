"""CRUD repositories use the caller's transaction; never commit internally."""

from typing import Generic, TypeVar
from uuid import UUID

from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from ..models import Base

Model = TypeVar("Model", bound=Base)


class Repository(Generic[Model]):
    model: type[Model]

    def __init__(self, session: Session):
        self.session = session

    def _validate_fields(self, values):
        allowed = {prop.key for prop in inspect(self.model).column_attrs}
        invalid = set(values) - (allowed - {"id", "created_at", "updated_at"})
        if invalid:
            raise ValueError(f"Unknown or immutable fields: {sorted(invalid)}")

    def create(self, **values) -> Model:
        self._validate_fields(values)
        item = self.model(**values)
        self.session.add(item)
        self.session.flush()
        return item

    def get(self, item_id: UUID) -> Model | None:
        return self.session.get(self.model, item_id)

    def list(self, *, limit: int = 100, offset: int = 0, **filters) -> list[Model]:
        self._validate_filters(filters)
        statement = select(self.model).filter_by(**filters).order_by(self.model.id)
        return self._page(statement, limit, offset)

    def _validate_filters(self, filters):
        allowed = {prop.key for prop in inspect(self.model).column_attrs}
        if set(filters) - allowed:
            raise ValueError("Unknown filter fields")

    def _page(self, statement, limit, offset):
        if not 1 <= limit <= 1000 or offset < 0:
            raise ValueError("limit must be 1..1000 and offset must be nonnegative")
        return list(self.session.scalars(statement.limit(limit).offset(offset)))

    def update(self, item_id: UUID, **values) -> Model | None:
        self._validate_fields(values)
        item = self.get(item_id)
        if item is not None:
            for key, value in values.items():
                setattr(item, key, value)
            self.session.flush()
        return item

    def delete(self, item_id: UUID) -> bool:
        item = self.get(item_id)
        if item is None:
            return False
        self.session.delete(item)
        self.session.flush()
        return True
