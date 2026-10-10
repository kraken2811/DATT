"""Cold + five-warm sequential latency benchmark for DATT operational APIs.

Run against an already-started local/Colab Web API. No credentials are printed.
Example:
    python -m scripts.benchmark_api_latency --base-url http://127.0.0.1:8501
Use DATT_BENCH_TOKEN for Bearer auth when operational auth is enabled.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import time
import uuid

import requests

ENDPOINTS = (
    ('CAMERAS', '/api/cameras'),
    ('TARGETS', '/api/targets?page=1&page_size=25'),
    ('VEHICLE_WATCHLIST', '/api/watchlist/vehicles?page=1&page_size=25'),
    ('EVENT_CENTER_25', '/api/event_center/events?page=1&page_size=25'),
    ('EVENT_CENTER_5', '/api/event_center/events?page=1&page_size=5'),
    ('EVENT_CENTER_5_NO_TOTAL', '/api/event_center/events?page=1&page_size=5&include_total=false'),
    ('ALERT_CENTER', '/api/alerts?page=1&page_size=25'),
    ('VIDEO_SOURCES', '/video_sources'),
)
TIMING_HEADERS = {
    'db_connect_ms': 'X-DATT-DB-Connect-Ms',
    'db_query_ms': 'X-DATT-DB-Query-Ms',
    'serialization_ms': 'X-DATT-Serialization-Ms',
    'request_total_ms': 'X-DATT-Request-Total-Ms',
}


def percentile(values, percentile_value):
    ordered = sorted(values)
    if not ordered:
        return None
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile_value
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    fraction = position - low
    return ordered[low] * (1 - fraction) + ordered[high] * fraction


def request_once(session, url, headers, timeout):
    started = time.perf_counter()
    response = session.get(url, headers=headers, timeout=timeout)
    client_ms = (time.perf_counter() - started) * 1000.0
    response.raise_for_status()
    result = {'client_total_ms': client_ms, 'status': response.status_code}
    for name, header in TIMING_HEADERS.items():
        try:
            result[name] = float(response.headers.get(header, 'nan'))
        except ValueError:
            result[name] = float('nan')
    return result


def summarize(rows):
    summary = {}
    for field in ('client_total_ms', *TIMING_HEADERS.keys()):
        values = [r[field] for r in rows if r.get(field) == r.get(field)]
        if values:
            summary[field] = {
                'p50': round(percentile(values, 0.50), 2),
                'p95': round(percentile(values, 0.95), 2),
                'mean': round(statistics.fmean(values), 2),
            }
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', default='http://127.0.0.1:8501')
    parser.add_argument('--timeout', type=float, default=30.0)
    parser.add_argument('--label', default='current')
    args = parser.parse_args()

    headers = {'Accept': 'application/json', 'X-Session-Id': 'bench-' + uuid.uuid4().hex}
    token = os.getenv('DATT_BENCH_TOKEN', '').strip()
    if token:
        headers['Authorization'] = 'Bearer ' + token

    base = args.base_url.rstrip('/')
    report = {'label': args.label, 'base_url': base, 'endpoints': {}}
    with requests.Session() as session:
        for name, path in ENDPOINTS:
            cold = request_once(session, base + path, headers, args.timeout)
            warm = [request_once(session, base + path, headers, args.timeout) for _ in range(5)]
            report['endpoints'][name] = {
                'path': path,
                'cold': {k: round(v, 2) if isinstance(v, float) and v == v else v for k, v in cold.items()},
                'warm': summarize(warm),
            }
            warm_p50 = report['endpoints'][name]['warm'].get('client_total_ms', {}).get('p50')
            warm_p95 = report['endpoints'][name]['warm'].get('client_total_ms', {}).get('p95')
            print(f'{name}: cold={cold["client_total_ms"]:.2f}ms warm_p50={warm_p50}ms warm_p95={warm_p95}ms')

    exact = report['endpoints']['EVENT_CENTER_5']['warm'].get('client_total_ms', {}).get('p50')
    light = report['endpoints']['EVENT_CENTER_5_NO_TOTAL']['warm'].get('client_total_ms', {}).get('p50')
    if exact is not None and light is not None:
        report['event_center_count_cost_estimate_p50_ms'] = round(max(0.0, exact - light), 2)
        print('EVENT_COUNT_COST_ESTIMATE_P50_MS=' + str(report['event_center_count_cost_estimate_p50_ms']))

    print('\n[DATT_API_LATENCY_JSON]')
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
