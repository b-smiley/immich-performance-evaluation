#!/usr/bin/env python3
"""Write mean API, PostgreSQL, and Redis latency for a run's load and catch-up phases."""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# Commands the exporter itself runs on every scrape, which are not Immich's work.
REDIS_EXPORTER_COMMANDS = (
    r"info|latency\\|.*|client\\|list|config\\|.*|slowlog\\|.*|commandlog\\|.*|command\\|.*"
)
REDIS_FILTER = f'{{job="redis",cmd!~"{REDIS_EXPORTER_COMMANDS}"}}'
POSTGRES_FILTER = '{job="postgres"}'
PROMETHEUS_SERVICES = {
    "postgres": (
        f"pg_stat_statements_seconds_total{POSTGRES_FILTER}",
        f"pg_stat_statements_calls_total{POSTGRES_FILTER}",
    ),
    "redis": (
        f"redis_commands_duration_seconds_total{REDIS_FILTER}",
        f"redis_commands_total{REDIS_FILTER}",
    ),
}


def timestamp(seconds: float) -> str:
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat()


def parse_time(value: str) -> float:
    # k6 writes nanoseconds, which datetime cannot parse.
    trimmed = value.replace("Z", "+00:00")
    if "." in trimmed:
        whole, rest = trimmed.split(".", 1)
        fraction = rest.split("+")[0][:6]
        trimmed = f"{whole}.{fraction}+{rest.split('+')[1]}"
    return datetime.fromisoformat(trimmed).timestamp()


def query(url: str, expression: str, at: float) -> dict[tuple, float]:
    parameters = urllib.parse.urlencode({"query": expression, "time": at})
    with urllib.request.urlopen(f"{url}/api/v1/query?{parameters}", timeout=30) as response:
        results = json.loads(response.read())["data"]["result"]
    return {tuple(sorted(item["metric"].items())): float(item["value"][1]) for item in results}


def counter_change(url: str, expression: str, start: float, end: float) -> float:
    before = query(url, expression, start)
    # A series absent at the start first appeared during the phase, so counts from 0.
    return sum(
        max(0.0, value - before.get(series, 0.0))
        for series, value in query(url, expression, end).items()
    )


def service_latency(url: str, time_metric: str, count_metric: str, start: float, end: float) -> dict:
    total_seconds = counter_change(url, time_metric, start, end)
    operations = counter_change(url, count_metric, start, end)
    return {
        "mean_ms": round(total_seconds / operations * 1000, 3) if operations else None,
        "operations": int(operations),
        "total_seconds": round(total_seconds, 3),
    }


def load_window(k6_results: Path) -> tuple[float, float]:
    first = last = None
    with open(k6_results, encoding="utf-8") as lines:
        for line in lines:
            point = json.loads(line)
            if point.get("type") == "Point":
                first = first or point["data"]["time"]
                last = point["data"]["time"]
    if first is None:
        raise ValueError("k6.json has no data points")
    return parse_time(first), parse_time(last)


def phase_windows(results_dir: Path) -> dict[str, dict]:
    load_start, load_end = load_window(results_dir / "k6.json")
    windows = {"load": {"start": load_start, "end": load_end}}

    queue_summary = results_dir / "queue-summary.json"
    if queue_summary.exists():
        queues = json.loads(queue_summary.read_text())
        windows["catch_up"] = {
            "start": parse_time(queues["load_end"]) if queues["load_end"] else load_end,
            # A run that timed out has no drain time, so use when tracking stopped.
            "end": parse_time(queues["drained_at"]) if queues["drained_at"] else queue_summary.stat().st_mtime,
            "queue_status": queues["status"],
        }
    return windows


def summarize(url: str, results_dir: Path) -> dict:
    metrics = json.loads((results_dir / "k6-summary.json").read_text())["metrics"]
    windows = phase_windows(results_dir)
    load = windows["load"]

    # Immich v3.3.5 exposes no request timing, so the API figure comes from k6.
    waiting = metrics["http_req_waiting"]["values"]
    operations = metrics["http_reqs"]["values"]["count"]
    api = {
        "source": "k6 http_req_waiting, measured from the client",
        "mean_ms": round(waiting["avg"], 3),
        "operations": operations,
        "total_seconds": round(waiting["avg"] * operations / 1000, 3),
        "percentiles_ms": {key: round(value, 3) for key, value in waiting.items() if key.startswith("p(")},
    }
    phases = {
        "load": {
            "start": timestamp(load["start"]),
            "end": timestamp(load["end"]),
            "services": {
                "api": api,
                **{
                    name: service_latency(url, *series, load["start"], load["end"])
                    for name, series in PROMETHEUS_SERVICES.items()
                },
            },
        }
    }

    if "catch_up" in windows:
        catch_up = windows["catch_up"]
        phases["catch_up"] = {
            "start": timestamp(catch_up["start"]),
            "end": timestamp(catch_up["end"]),
            "queue_status": catch_up["queue_status"],
            "services": {
                name: service_latency(url, *series, catch_up["start"], catch_up["end"])
                for name, series in PROMETHEUS_SERVICES.items()
            },
        }
    return {"status": "ok", "phases": phases}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prometheus-url", required=True)
    parser.add_argument("--results-dir", type=Path, required=True)
    args = parser.parse_args()

    # A missing measurement must not change the load test's result.
    try:
        summary = summarize(args.prometheus_url.rstrip("/"), args.results_dir)
    except (OSError, ValueError, KeyError, TypeError) as error:
        summary = {"status": "error", "error": f"{type(error).__name__}: {error}"}
        print(f"::warning::Service latency was not measured: {summary['error']}")
    (args.results_dir / "service-latency.json").write_text(json.dumps(summary, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
