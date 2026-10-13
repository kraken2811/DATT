"""Benchmark DATT API and database latency end-to-end.

Measures:
- db_connect_ms: Time spent establishing physical PostgreSQL/DB connections
- db_query_ms: Time spent executing queries over the wire
- serialization_ms: Time spent serializing responses to JSON
- request_total_ms: Total end-to-end request latency

Per endpoint:
- 1 cold request
- 5 warm sequential requests
Reports P50 and P95.
"""
import os
import sys
import time
import json
import numpy as np
from pathlib import Path
from contextvars import ContextVar

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from starlette.testclient import TestClient

import threading

# Thread-safe metrics tracking per request
_lock = threading.Lock()
_current_metrics = None

def _start_req_metrics():
    global _current_metrics
    with _lock:
        _current_metrics = {
            "connect_ms": 0.0,
            "query_ms": 0.0,
            "query_count": 0,
            "serialization_ms": 0.0,
        }

def _stop_req_metrics():
    global _current_metrics
    with _lock:
        res = dict(_current_metrics) if _current_metrics else {
            "connect_ms": 0.0, "query_ms": 0.0, "query_count": 0, "serialization_ms": 0.0
        }
        _current_metrics = None
        return res

# Instrument DB connect
try:
    import psycopg
    _orig_psycopg_connect = psycopg.connect
    def _timed_psycopg_connect(*args, **kwargs):
        t0 = time.perf_counter()
        con = _orig_psycopg_connect(*args, **kwargs)
        duration = (time.perf_counter() - t0) * 1000.0
        with _lock:
            if _current_metrics is not None:
                _current_metrics["connect_ms"] += duration
        return con
    psycopg.connect = _timed_psycopg_connect
except ImportError:
    pass

# Instrument SQLite connect if used
try:
    import sqlite3
    _orig_sqlite_connect = sqlite3.connect
    def _timed_sqlite_connect(*args, **kwargs):
        t0 = time.perf_counter()
        con = _orig_sqlite_connect(*args, **kwargs)
        duration = (time.perf_counter() - t0) * 1000.0
        with _lock:
            if _current_metrics is not None:
                _current_metrics["connect_ms"] += duration
        return con
    sqlite3.connect = _timed_sqlite_connect
except ImportError:
    pass

# Instrument SQLAlchemy engine queries
from sqlalchemy import event
from sqlalchemy.engine import Engine

@event.listens_for(Engine, "before_cursor_execute")
def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    context._datt_query_start = time.perf_counter()

@event.listens_for(Engine, "after_cursor_execute")
def after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    start = getattr(context, "_datt_query_start", None)
    if start is not None:
        duration = (time.perf_counter() - start) * 1000.0
        with _lock:
            if _current_metrics is not None:
                _current_metrics["query_ms"] += duration
                _current_metrics["query_count"] += 1

# Instrument serialization
from starlette.responses import JSONResponse
_orig_json_render = JSONResponse.render
def _timed_json_render(self, content):
    t0 = time.perf_counter()
    res = _orig_json_render(self, content)
    duration = (time.perf_counter() - t0) * 1000.0
    with _lock:
        if _current_metrics is not None:
            _current_metrics["serialization_ms"] += duration
    return res
JSONResponse.render = _timed_json_render

from src.ui.web_server import app

ENDPOINTS = [
    "/api/cameras",
    "/api/targets?page=1&page_size=25",
    "/api/watchlist/vehicles?page=1&page_size=25",
    "/api/event_center/events?page=1&page_size=25",
    "/api/event_center/events?page=1&page_size=5",
    "/api/event_center/events?page=1&page_size=5&include_total=false",
    "/api/alerts?page=1&page_size=25",
    "/video_sources",
]

def run_single_request(client: TestClient, path: str):
    _start_req_metrics()
    t0 = time.perf_counter()
    resp = client.get(path)
    total_ms = (time.perf_counter() - t0) * 1000.0
    m = _stop_req_metrics()

    return {
        "status_code": resp.status_code,
        "request_total_ms": total_ms,
        "db_connect_ms": m["connect_ms"],
        "db_query_ms": m["query_ms"],
        "query_count": m["query_count"],
        "serialization_ms": m["serialization_ms"],
    }

def run_benchmark():
    print("=" * 80)
    print("DATT LATENCY BENCHMARK")
    print("=" * 80)
    client = TestClient(app)

    all_results = {}

    for path in ENDPOINTS:
        print(f"\nEndpoint: GET {path}")
        # Cold run
        cold = run_single_request(client, path)
        print(f"  [COLD] total: {cold['request_total_ms']:7.2f}ms | connect: {cold['db_connect_ms']:7.2f}ms | query: {cold['db_query_ms']:7.2f}ms ({cold['query_count']} queries) | ser: {cold['serialization_ms']:5.2f}ms | status: {cold['status_code']}")

        # 5 Warm sequential runs
        warm_runs = []
        for i in range(5):
            warm = run_single_request(client, path)
            warm_runs.append(warm)
            print(f"  [WARM #{i+1}] total: {warm['request_total_ms']:7.2f}ms | connect: {warm['db_connect_ms']:7.2f}ms | query: {warm['db_query_ms']:7.2f}ms ({warm['query_count']} queries) | ser: {warm['serialization_ms']:5.2f}ms | status: {warm['status_code']}")

        warm_totals = [r["request_total_ms"] for r in warm_runs]
        warm_connects = [r["db_connect_ms"] for r in warm_runs]
        warm_queries = [r["db_query_ms"] for r in warm_runs]
        warm_ser = [r["serialization_ms"] for r in warm_runs]

        p50 = float(np.percentile(warm_totals, 50))
        p95 = float(np.percentile(warm_totals, 95))

        print(f"  --> SUMMARY: Cold={cold['request_total_ms']:.2f}ms | Warm P50={p50:.2f}ms | Warm P95={p95:.2f}ms")

        all_results[path] = {
            "cold": cold,
            "warm_runs": warm_runs,
            "warm_p50": p50,
            "warm_p95": p95,
            "warm_query_p50": float(np.percentile(warm_queries, 50)),
            "warm_connect_p50": float(np.percentile(warm_connects, 50)),
        }

    return all_results

if __name__ == "__main__":
    results = run_benchmark()
    out_file = Path("benchmark_baseline.json") if len(sys.argv) == 1 else Path(sys.argv[1])
    out_file.write_text(json.dumps(results, indent=2))
    print(f"\nSaved results to {out_file}")
