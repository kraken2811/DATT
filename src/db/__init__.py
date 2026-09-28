"""Independent persistence layer; importing this package performs no I/O."""

from .database import Database

__all__ = ["Database"]
