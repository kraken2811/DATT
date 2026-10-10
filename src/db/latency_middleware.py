"""ASGI middleware exposing credential-free latency metrics in response headers."""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware

from src.db.latency import begin_trace, end_trace, snapshot


class DatabaseLatencyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        trace, token = begin_trace()
        try:
            response = await call_next(request)
            values = snapshot(trace)
            response.headers["Server-Timing"] = ", ".join((
                f"db_connect;dur={values['db_connect_ms']:.2f}",
                f"db_query;dur={values['db_query_ms']:.2f}",
                f"serialization;dur={values['serialization_ms']:.2f}",
                f"total;dur={values['request_total_ms']:.2f}",
            ))
            response.headers["X-DATT-DB-Connect-Ms"] = f"{values['db_connect_ms']:.2f}"
            response.headers["X-DATT-DB-Query-Ms"] = f"{values['db_query_ms']:.2f}"
            response.headers["X-DATT-Serialization-Ms"] = f"{values['serialization_ms']:.2f}"
            response.headers["X-DATT-Request-Total-Ms"] = f"{values['request_total_ms']:.2f}"
            return response
        finally:
            end_trace(token)
