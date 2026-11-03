#!/usr/bin/env python3
"""Write CPU and memory use per container, and for the whole runner, for a run's phases."""

from __future__ import annotations

import argparse
import json
import math
import sys
import urllib.parse
import urllib.request
from pathlib import Path

from summarize_service_latency import phase_windows, timestamp

SERVICE_LABEL = "container_label_com_docker_compose_service"
# The root cgroup, reported beside the Compose services under a name none of them use.
RUNNER = "runner"
RUNNER_SELECTOR = '{id="/"}'
CPU_COUNTER = "container_cpu_usage_seconds_total"
MEMORY_METRICS = {
    "memory_working_set_mb": "container_memory_working_set_bytes",
    "memory_usage_mb": "container_memory_usage_bytes",
}
# Reaches the scrape before the first phase starts, so its first interval has a CPU value.
LEAD_SECONDS = 60


def raw_series(url: str, metric: str, end: float, seconds: int) -> list[tuple[str, list]]:
    """Return each series' scraped points, without the averaging of a range query."""
    series = []
    for selector in (f'{{{SERVICE_LABEL}!=""}}', RUNNER_SELECTOR):
        parameters = urllib.parse.urlencode({"query": f"{metric}{selector}[{seconds}s]", "time": end})
        with urllib.request.urlopen(f"{url}/api/v1/query?{parameters}", timeout=30) as response:
            results = json.loads(response.read())["data"]["result"]
        series += [(item["metric"].get(SERVICE_LABEL, RUNNER), item["values"]) for item in results]
    return series


def collect_samples(url: str, start: float, end: float) -> list[dict]:
    seconds = math.ceil(end - start) + LEAD_SECONDS
    rows: dict[tuple[float, str], dict] = {}

    def row(at: float, service: str) -> dict:
        return rows.setdefault((at, service), {"at": at, "service": service})

    # Scrapes are about 15 seconds apart, but not exactly, so use their real spacing.
    for service, points in raw_series(url, CPU_COUNTER, end, seconds):
        for (before_at, before), (at, value) in zip(points, points[1:]):
            if float(value) >= float(before):
                row(at, service).update(
                    cpu_percent=round((float(value) - float(before)) / (at - before_at) * 100, 2),
                    interval_seconds=round(at - before_at, 3),
                )
    for name, metric in MEMORY_METRICS.items():
        for service, points in raw_series(url, metric, end, seconds):
            for at, value in points:
                row(at, service)[name] = round(float(value) / 1_000_000, 2)
    return [rows[key] for key in sorted(rows) if start <= key[0] <= end]


def summarize_phase(samples: list[dict], start: float, end: float) -> dict:
    # A sample's CPU covers the time since the previous scrape, so place it by that
    # interval's middle. Otherwise idle time just before the load would count as load.
    in_phase = [
        sample for sample in samples if start <= sample["at"] - sample.get("interval_seconds", 0) / 2 <= end
    ]
    services = {}
    for service in sorted({sample["service"] for sample in samples}):
        rows = [sample for sample in in_phase if sample["service"] == service]
        summary = {}
        for name in ("cpu_percent", *MEMORY_METRICS):
            values = [row[name] for row in rows if name in row]
            summary[name] = {
                "mean": round(sum(values) / len(values), 2) if values else None,
                "peak": max(values, default=None),
            }
        # Scrape spacing varies, so weight CPU by the time each sample covers.
        intervals = [(row["cpu_percent"], row["interval_seconds"]) for row in rows if "cpu_percent" in row]
        if intervals:
            summary["cpu_percent"]["mean"] = round(
                sum(cpu * seconds for cpu, seconds in intervals) / sum(seconds for _, seconds in intervals), 2
            )
        services[service] = summary
    return services


def summarize(url: str, results_dir: Path) -> dict:
    windows = phase_windows(results_dir)
    start = windows["load"]["start"]
    end = windows.get("catch_up", windows["load"])["end"]
    samples = collect_samples(url, start, end)
    if not any(sample["service"] != RUNNER for sample in samples):
        raise ValueError(
            "Prometheus has no per-container data. cAdvisor does not provide it on Docker Desktop."
        )

    phases = {}
    for name, window in windows.items():
        phases[name] = {
            **window,
            "start": timestamp(window["start"]),
            "end": timestamp(window["end"]),
            "services": summarize_phase(samples, window["start"], window["end"]),
        }
    return {
        "status": "ok",
        "phases": phases,
        "samples": [
            {"time": timestamp(sample["at"]), **{key: value for key, value in sample.items() if key != "at"}}
            for sample in samples
        ],
    }


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
        print(f"::warning::Resource usage was not recorded: {summary['error']}", file=sys.stderr)
    (args.results_dir / "resource-usage.json").write_text(json.dumps(summary, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
