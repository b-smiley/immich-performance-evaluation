#!/usr/bin/env python3
"""Write a load test run's summaries for its load and catch-up phases.

- service-latency.json: mean API, PostgreSQL, and Redis latency, from k6 and the
  PostgreSQL and Redis exporters.
- resource-usage.json: CPU and memory per container, and for the whole runner, from
  cAdvisor.
- worker-usage.json: what the Immich background worker did. Per-process CPU and
  memory come from process-exporter, and ffmpeg CPU from the worker's finished
  children (monitoring/child-cpu-exporter). Jobs, active queues, and the time spent
  in each internal step come from Immich's own telemetry for the worker.

Each summary is written even when another fails, and a failed one records
status error instead of changing the load test's result.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Shared helpers: Prometheus queries, phase windows, and writing summaries
# ---------------------------------------------------------------------------

# Reaches the scrape before the first phase starts, so its first interval has a CPU value.
LEAD_SECONDS = 60
# The root cgroup, reported beside the Compose services under a name none of them use.
RUNNER = "runner"
SERVICE_LABEL = "container_label_com_docker_compose_service"
RUNNER_SELECTOR = '{id="/"}'


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


def raw_series(
    url: str,
    metric: str,
    end: float,
    seconds: int,
    selectors: tuple[str, ...] = (f'{{{SERVICE_LABEL}!=""}}', RUNNER_SELECTOR),
    label: str = SERVICE_LABEL,
) -> list[tuple[str, list]]:
    """Return each series' scraped points, without the averaging of a range query.

    Each series is named by its `label`, or `runner` when it has none.
    """
    series = []
    for selector in selectors:
        parameters = urllib.parse.urlencode({"query": f"{metric}{selector}[{seconds}s]", "time": end})
        with urllib.request.urlopen(f"{url}/api/v1/query?{parameters}", timeout=30) as response:
            results = json.loads(response.read())["data"]["result"]
        series += [(item["metric"].get(label, RUNNER), item["values"]) for item in results]
    return series


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


def summarize_phase(
    samples: list[dict], start: float, end: float, memory_names: tuple[str, ...]
) -> dict:
    """Return CPU and memory mean and peak per service or process group for a phase."""
    # A sample's CPU covers the time since the previous scrape, so place it by that
    # interval's middle. Otherwise idle time just before the load would count as load.
    in_phase = [
        sample for sample in samples if start <= sample["at"] - sample.get("interval_seconds", 0) / 2 <= end
    ]
    services = {}
    for service in sorted({sample["service"] for sample in samples}):
        rows = [sample for sample in in_phase if sample["service"] == service]
        summary = {}
        for name in ("cpu_percent", *memory_names):
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


def sample_rows(samples: list[dict]) -> list[dict]:
    return [
        {"time": timestamp(sample["at"]), **{key: value for key, value in sample.items() if key != "at"}}
        for sample in samples
    ]


def write_summary(
    results_dir: Path, name: str, failure: str, build: Callable[[], dict], warning_stream=sys.stderr
) -> dict:
    """Write one summary file, recording a failure instead of raising it.

    A missing measurement must not change the load test's result.
    """
    try:
        summary = build()
    except (OSError, ValueError, KeyError, TypeError) as error:
        summary = {"status": "error", "error": f"{type(error).__name__}: {error}"}
        print(f"::warning::{failure}: {summary['error']}", file=warning_stream)
    (results_dir / name).write_text(json.dumps(summary, indent=2) + "\n")
    return summary


# ---------------------------------------------------------------------------
# service-latency.json
# ---------------------------------------------------------------------------

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


def service_latency(url: str, time_metric: str, count_metric: str, start: float, end: float) -> dict:
    total_seconds = counter_change(url, time_metric, start, end)
    operations = counter_change(url, count_metric, start, end)
    return {
        "mean_ms": round(total_seconds / operations * 1000, 3) if operations else None,
        "operations": int(operations),
        "total_seconds": round(total_seconds, 3),
    }


def summarize_latency(url: str, results_dir: Path) -> dict:
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


# ---------------------------------------------------------------------------
# resource-usage.json
# ---------------------------------------------------------------------------

CPU_COUNTER = "container_cpu_usage_seconds_total"
MEMORY_METRICS = {
    "memory_working_set_mb": "container_memory_working_set_bytes",
    "memory_usage_mb": "container_memory_usage_bytes",
}


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


def summarize_resources(url: str, results_dir: Path) -> dict:
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
            "services": summarize_phase(samples, window["start"], window["end"], tuple(MEMORY_METRICS)),
        }
    return {"status": "ok", "phases": phases, "samples": sample_rows(samples)}


# ---------------------------------------------------------------------------
# worker-usage.json
# ---------------------------------------------------------------------------

PROCESS_LABEL = "groupname"
PROCESS_CPU = "namedprocess_namegroup_cpu_seconds_total"
PROCESS_MEMORY = "namedprocess_namegroup_memory_bytes"
PROCESS_MEMORY_NAME = "memory_resident_mb"
# Groups from monitoring/process-exporter/config.yml. The Node processes always run,
# so a missing one means the grouping failed; exiftool may never start.
REQUIRED_GROUPS = ("immich-api", "immich-worker")
OPTIONAL_GROUPS = ("exiftool",)

# ffmpeg CPU is all finished children of the worker less those that are not ffmpeg.
CHILD_CPU = 'job="child-cpu"'
FINISHED_CHILDREN = f"immich_worker_finished_children_cpu_seconds_total{{{CHILD_CPU}}}"
FINISHED_TRACKED = f"immich_worker_finished_tracked_children_cpu_seconds_total{{{CHILD_CPU}}}"
RESOURCE_FILE = "resource-usage.json"
CONTAINER = "immich-server"

# Prometheus moves the names Immich puts inside metric names into these labels; see
# metric_relabel_configs in monitoring/prometheus/prometheus.yml.
WORKER = 'job="immich-worker"'
JOB_COUNTERS = f"immich_jobs_total{{{WORKER}}}"
QUEUE_GAUGES = f'{{{WORKER},state="active"}}'
QUEUE_METRIC = "immich_queue_jobs"
STEP_SUMS = f"immich_repository_duration_ms_sum{{{WORKER}}}"
STEP_COUNTS = f"immich_repository_duration_ms_count{{{WORKER}}}"
STEP_BUCKETS = f"immich_repository_duration_ms_bucket{{{WORKER}}}"
STEP_PERCENTILES = (50, 95, 99)
TOP_STEPS = 10
# These repositories dispatch jobs and events and are timed around the steps they
# run, so ranking them would only repeat the time of the steps inside them.
WRAPPER_REPOSITORIES = ("event", "job")
# Timed once per job of any kind, including those Immich keeps no counter for.
JOB_RUN_STEP = ("job", "run")
# Media steps Immich times inside other media steps (Immich v3.4.2
# media.repository.ts), so their time is already in their parents'. Only
# transform does real work; the others build sharp pipelines.
NESTED_STEPS = {
    "media.transform": ("media.decode_image", "media.generate_thumbnail", "media.generate_thumbhash"),
    "media.get_image_decoding_pipeline": ("media.decode_image",),
    "media.encoded": ("media.get_image_decoding_pipeline",),
    "media.get_pipeline_colorspace": ("media.get_image_decoding_pipeline", "media.tag"),
    "media.raw": ("media.transform", "media.tag"),
    "media.edit": ("media.transform",),
    "media.tag": ("media.generate_thumbnail",),
}
# Top-level steps of each chain stage; every other top-level step counts as other.
# Video thumbnails come from ffmpeg (transcode) and video metadata from ffprobe (probe).
CHAIN_STAGES = {
    "metadata": ("metadata.read_tags", "media.probe", "media.probe_packets"),
    "thumbnail": (
        "media.decode_image", "media.generate_thumbnail", "media.generate_thumbhash", "media.transcode",
    ),
}
# Disabled by default, so its jobs are skipped and it has no timed steps of its own.
STORAGE_TEMPLATE_JOB = "storage_template_migration_single"


def collect_process_samples(url: str, start: float, end: float) -> list[dict]:
    """Return CPU and resident memory per process group, in summarize_phase's format."""
    seconds = math.ceil(end - start) + LEAD_SECONDS
    rows: dict[tuple[float, str], dict] = {}

    def row(at: float, group: str) -> dict:
        return rows.setdefault((at, group), {"at": at, "service": group})

    # Each group has a user and a system CPU series from the same scrape, so add them.
    for group, points in raw_series(url, PROCESS_CPU, end, seconds, ("",), PROCESS_LABEL):
        for (before_at, before), (at, value) in zip(points, points[1:]):
            if float(value) >= float(before):
                sample = row(at, group)
                sample["cpu_percent"] = round(
                    sample.get("cpu_percent", 0.0) + (float(value) - float(before)) / (at - before_at) * 100, 2
                )
                sample["interval_seconds"] = round(at - before_at, 3)
    for group, points in raw_series(url, PROCESS_MEMORY, end, seconds, ('{memtype="resident"}',), PROCESS_LABEL):
        for at, value in points:
            row(at, group)[PROCESS_MEMORY_NAME] = round(float(value) / 1_000_000, 2)
    return [rows[key] for key in sorted(rows) if start <= key[0] <= end]


def summarize_processes(samples: list[dict], start: float, end: float) -> dict:
    processes = summarize_phase(samples, start, end, (PROCESS_MEMORY_NAME,))
    # A process that never started used nothing, which is different from not knowing.
    for group in OPTIONAL_GROUPS:
        if group not in processes:
            processes[group] = {
                "cpu_percent": {"mean": 0.0, "peak": 0.0},
                PROCESS_MEMORY_NAME: {"mean": 0.0, "peak": 0.0},
            }
    return processes


def summarize_ffmpeg(url: str, start: float, end: float) -> dict:
    """Return the CPU of ffmpeg and ffprobe processes that finished during the phase."""
    cpu_seconds = counter_change(url, FINISHED_CHILDREN, start, end) - counter_change(
        url, FINISHED_TRACKED, start, end
    )
    # A child collected between two exporter readings can make a phase edge read just below 0.
    cpu_seconds = max(0.0, cpu_seconds)
    duration = end - start
    return {
        "cpu_seconds": round(cpu_seconds, 2),
        "cpu_percent": {"mean": round(cpu_seconds / duration * 100, 2) if duration > 0 else None},
    }


def container_cpu(usage: dict) -> tuple[dict | None, str | None]:
    """Return immich-server CPU per phase from the resource summary, or why it is missing."""
    if usage.get("status") != "ok":
        return None, f"{RESOURCE_FILE} status is {usage.get('status')!r}: {usage.get('error')}"
    return {
        name: phase["services"].get(CONTAINER, {}).get("cpu_percent", {}).get("mean")
        for name, phase in usage["phases"].items()
    }, None


def summarize_unattributed(container_mean: float | None, reason: str | None, parts: list) -> dict:
    """Return container CPU not covered by the process groups and ffmpeg."""
    if reason:
        return {"cpu_percent": {"mean": None}, "reason": reason}
    if container_mean is None or any(part is None for part in parts):
        return {"cpu_percent": {"mean": None}, "reason": "a CPU figure for this phase is missing"}
    return {"cpu_percent": {"mean": round(container_mean - sum(parts), 2)}}


def counter_changes(
    url: str, expression: str, labels: tuple[str, ...], start: float, end: float
) -> dict[tuple[str, ...], float]:
    """Return each counter's increase over the phase, keyed by the given labels' values."""
    before = query(url, expression, start)
    changes: dict[tuple[str, ...], float] = {}
    for series, value in query(url, expression, end).items():
        found = dict(series)
        key = tuple(found.get(label, "") for label in labels)
        # A counter absent at the start first appeared during the phase, so counts from 0.
        changes[key] = changes.get(key, 0.0) + max(0.0, value - before.get(series, 0.0))
    return changes


def summarize_jobs(url: str, start: float, end: float, job_runs: tuple[float, float] | None) -> dict:
    by_job: dict[str, dict[str, int]] = {}
    for (job, outcome), change in counter_changes(url, JOB_COUNTERS, ("immich_job", "outcome"), start, end).items():
        if change:
            by_job.setdefault(job, {})[outcome] = int(round(change))
    total = {
        outcome: sum(counts.get(outcome, 0) for counts in by_job.values())
        for outcome in ("success", "failed", "skipped")
    }
    duration = end - start
    run_ms, runs = job_runs or (0.0, 0.0)
    return {
        "by_job": dict(sorted(by_job.items())),
        "total_success": total["success"],
        "total_failed": total["failed"],
        "total_skipped": total["skipped"],
        "success_per_s": round(total["success"] / duration, 3) if duration > 0 else None,
        "runs": int(round(runs)),
        "runs_per_s": round(runs / duration, 3) if duration > 0 else None,
        "mean_run_ms": round(run_ms / runs, 3) if runs else None,
    }


def summarize_queues(url: str, start: float, end: float) -> dict:
    seconds = math.ceil(end - start) + LEAD_SECONDS
    queues = {}
    for queue, points in raw_series(url, QUEUE_METRIC, end, seconds, (QUEUE_GAUGES,), "queue"):
        values = [float(value) for at, value in points if start <= at <= end]
        if values:
            queues[queue] = {"mean": round(sum(values) / len(values), 2), "peak": max(values)}
    return dict(sorted(queues.items()))


def step_times(url: str, start: float, end: float) -> dict[tuple[str, str], tuple[float, float]]:
    """Return (total ms, calls) for each of the worker's internal steps. Immich reports ms."""
    labels = ("repository", "method")
    sums = counter_changes(url, STEP_SUMS, labels, start, end)
    counts = counter_changes(url, STEP_COUNTS, labels, start, end)
    return {step: (total_ms, counts.get(step, 0.0)) for step, total_ms in sums.items()}


def rank_steps(times: dict[tuple[str, str], tuple[float, float]]) -> list[dict]:
    """Return the steps with the most total time, leaving out the wrappers."""
    steps = []
    for (repository, method), (total_ms, calls) in times.items():
        if repository not in WRAPPER_REPOSITORIES and total_ms and calls:
            steps.append({
                "step": f"{repository}.{method}",
                "total_seconds": round(total_ms / 1000, 3),
                "calls": int(round(calls)),
                "mean_ms": round(total_ms / calls, 3),
            })
    steps.sort(key=lambda item: item["total_seconds"], reverse=True)
    return steps[:TOP_STEPS]


def step_buckets(url: str, start: float, end: float) -> dict[tuple[str, str], dict[float, float]]:
    """Return each step's cumulative bucket counts for the phase, keyed by upper bound in ms."""
    buckets: dict[tuple[str, str], dict[float, float]] = {}
    for (repository, method, bound), count in counter_changes(
        url, STEP_BUCKETS, ("repository", "method", "le"), start, end
    ).items():
        buckets.setdefault((repository, method), {})[float(bound)] = count
    return buckets


def bucket_percentiles(buckets: dict[float, float]) -> dict[str, float | None]:
    """Estimate percentiles from cumulative bucket counts the way histogram_quantile does.

    Interpolates linearly inside the bucket, so an estimate can be off by up to that
    bucket's width. A percentile that falls in the +Inf bucket is None.
    """
    bounds = sorted(buckets)
    total = buckets[bounds[-1]] if bounds else 0.0
    estimates: dict[str, float | None] = {}
    for percent in STEP_PERCENTILES:
        rank = percent / 100 * total
        estimate = None
        lower, below = 0.0, 0.0
        for bound in bounds:
            count = buckets[bound]
            if total and count >= rank:
                if not math.isinf(bound):
                    estimate = bound if count == below else lower + (bound - lower) * (rank - below) / (count - below)
                break
            lower, below = bound, count
        estimates[f"p{percent}_ms"] = round(estimate, 3) if estimate is not None else None
    return estimates


def all_steps(
    times: dict[tuple[str, str], tuple[float, float]], buckets: dict[tuple[str, str], dict[float, float]]
) -> list[dict]:
    """Return every step except the wrappers, with percentiles, marking nested ones."""
    steps = []
    for (repository, method), (total_ms, calls) in times.items():
        if repository in WRAPPER_REPOSITORIES or not (total_ms and calls):
            continue
        name = f"{repository}.{method}"
        step = {
            "step": name,
            "total_seconds": round(total_ms / 1000, 3),
            "calls": int(round(calls)),
            "mean_ms": round(total_ms / calls, 3),
            **bucket_percentiles(buckets.get((repository, method), {})),
        }
        if name in NESTED_STEPS:
            step["nested_in"] = list(NESTED_STEPS[name])
        steps.append(step)
    steps.sort(key=lambda item: item["total_seconds"], reverse=True)
    return steps


def summarize_chain(steps: list[dict], jobs: dict, processes: dict, ffmpeg: dict) -> dict:
    """Return each chain stage's share of the summed top-level step time."""
    top_level = [step for step in steps if "nested_in" not in step]
    total = sum(step["total_seconds"] for step in top_level)
    seconds = {
        stage: sum(step["total_seconds"] for step in top_level if step["step"] in names)
        for stage, names in CHAIN_STAGES.items()
    }
    seconds["other"] = total - sum(seconds.values())
    return {
        "stages": {
            stage: {"seconds": round(value, 3), "share_pct": round(100 * value / total, 1) if total else None}
            for stage, value in seconds.items()
        },
        "storage_template_jobs": jobs["by_job"].get(STORAGE_TEMPLATE_JOB, {}),
        "exiftool_cpu_percent_mean": processes.get("exiftool", {}).get("cpu_percent", {}).get("mean"),
        "ffmpeg_cpu_seconds": ffmpeg["cpu_seconds"],
    }


def summarize_worker(url: str, results_dir: Path, resource_usage: dict) -> dict:
    windows = phase_windows(results_dir)
    start = windows["load"]["start"]
    end = windows.get("catch_up", windows["load"])["end"]
    samples = collect_process_samples(url, start, end)
    if not samples:
        raise ValueError("Prometheus has no process-exporter data.")
    warnings = [
        f"No process matched the {group} group, so its usage is unknown."
        for group in REQUIRED_GROUPS
        if not any(sample["service"] == group for sample in samples)
    ]
    if not query(url, f'up{{{WORKER}}} == 1', end):
        warnings.append("The worker's telemetry was not scraped, so jobs, queues, and steps are empty.")
    child_cpu_up = bool(query(url, f"immich_worker_up{{{CHILD_CPU}}} == 1", end))
    if not child_cpu_up:
        warnings.append("The worker's finished-child CPU was not measured, so ffmpeg CPU is empty.")
    containers, container_reason = container_cpu(resource_usage)

    phases = {}
    bucket_bounds: set[float] = set()
    for name, window in windows.items():
        phase_start, phase_end = window["start"], window["end"]
        times = step_times(url, phase_start, phase_end)
        buckets = step_buckets(url, phase_start, phase_end)
        for counts in buckets.values():
            bucket_bounds.update(bound for bound in counts if not math.isinf(bound))
        steps = all_steps(times, buckets)
        jobs = summarize_jobs(url, phase_start, phase_end, times.get(JOB_RUN_STEP))
        processes = summarize_processes(samples, phase_start, phase_end)
        ffmpeg = (
            summarize_ffmpeg(url, phase_start, phase_end)
            if child_cpu_up
            else {"cpu_seconds": None, "cpu_percent": {"mean": None}}
        )
        parts = [
            processes.get(group, {}).get("cpu_percent", {}).get("mean")
            for group in (*REQUIRED_GROUPS, *OPTIONAL_GROUPS)
        ] + [ffmpeg["cpu_percent"]["mean"]]
        phases[name] = {
            **window,
            "start": timestamp(phase_start),
            "end": timestamp(phase_end),
            "processes": processes,
            "ffmpeg": ffmpeg,
            "unattributed": summarize_unattributed(
                (containers or {}).get(name), container_reason, parts
            ),
            "jobs": jobs,
            "queues_active": summarize_queues(url, phase_start, phase_end),
            "steps": rank_steps(times),
            "steps_all": steps,
            "chain": summarize_chain(steps, jobs, processes, ffmpeg),
        }
    summary = {
        "status": "ok",
        "step_notes": {
            "timing": "Step times are wall-clock, measured while jobs run concurrently, so they are not CPU time.",
            "percentiles": "Estimated from Immich's histogram buckets by linear interpolation; empty when above "
            "the top bucket.",
            "bucket_bounds_ms": sorted(bucket_bounds),
            "nested": "Steps with nested_in are timed inside those steps; never add them to their parents.",
            "chain": "Shares of summed top-level step time. exiftool and ffmpeg CPU are listed beside the shares, "
            "not added, because the steps already include waiting on them.",
        },
        "phases": phases,
    }
    if warnings:
        summary["warnings"] = warnings
        for warning in warnings:
            print(f"::warning::{warning}", file=sys.stderr)
    summary["samples"] = sample_rows(samples)
    return summary


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--prometheus-url", required=True)
    parser.add_argument("--results-dir", type=Path, required=True)
    args = parser.parse_args()
    url = args.prometheus_url.rstrip("/")
    results_dir = args.results_dir

    write_summary(
        results_dir, "service-latency.json", "Service latency was not measured",
        lambda: summarize_latency(url, results_dir), warning_stream=sys.stdout,
    )
    resource_usage = write_summary(
        results_dir, RESOURCE_FILE, "Resource usage was not recorded",
        lambda: summarize_resources(url, results_dir),
    )
    write_summary(
        results_dir, "worker-usage.json", "Worker usage was not recorded",
        lambda: summarize_worker(url, results_dir, resource_usage),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
