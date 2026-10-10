"""Credential-free request/database latency instrumentation.

Metrics are kept in a ContextVar so SQLAlchemy work in the current request can
contribute timing without logging SQL text, credentials, or DATABASE_URL.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from time import perf_counter
from typing import Iterator


@dataclass
class LatencyTrace:
    started_at: float = field(default_factory=perf_counter)
    metrics: dict[str, float] = field(default_factory=dict)

    def add(self, name: str, milliseconds: float) -> None:
        self.metrics[name] = self.metrics.get(name, 0.0) + max(0.0, float(milliseconds))


_current_trace: ContextVar[LatencyTrace | None] = ContextVar("datt_latency_trace", default=None)


def begin_trace() -> tuple[LatencyTrace, Token]:
    trace = LatencyTrace()
    return trace, _current_trace.set(trace)


def end_trace(token: Token) -> None:
    _current_trace.reset(token)


def current_trace() -> LatencyTrace | None:
    return _current_trace.get()


def add_metric(name: str, milliseconds: float) -> None:
    trace = current_trace()
    if trace is not None:
        trace.add(name, milliseconds)


@contextmanager
def measure(name: str) -> Iterator[None]:
    started = perf_counter()
    try:
        yield
    finally:
        add_metric(name, (perf_counter() - started) * 1000.0)


def snapshot(trace: LatencyTrace) -> dict[str, float]:
    values = dict(trace.metrics)
    values["request_total_ms"] = (perf_counter() - trace.started_at) * 1000.0
    for required in ("db_connect_ms", "db_query_ms", "serialization_ms"):
        values.setdefault(required, 0.0)
    return values
