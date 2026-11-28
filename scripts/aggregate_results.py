#!/usr/bin/env python3
"""Aggregate downloaded load-test workflow artifacts into one CSV row per run."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import statistics
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

from watch_queues import backlog

# ---------------------------------------------------------------------------
# Artifacts and k6 upload metrics
# ---------------------------------------------------------------------------
ARTIFACT_NAME = re.compile(r"^immich-load_run=(\d+)_role=(client|server)_")
PERCENTILES = (50, 75, 90, 95, 99)
LATENCY_COLUMNS = [f"upload_p{p}_ms" for p in PERCENTILES]
SERVICES = ("immich-server", "database", "redis")
# Matches MB in generate_fixtures.py.
MB = 1_000_000

# ---------------------------------------------------------------------------
# Service metrics: per-phase summaries written by summarize_run.py (client)
# ---------------------------------------------------------------------------
LATENCY_FILE = "service-latency.json"
RESOURCE_FILE = "resource-usage.json"
WORKER_FILE = "worker-usage.json"
# Column -> (client file, key path under its "phases").
SERVICE_SOURCES = {
    "api_waiting_p95_ms": (LATENCY_FILE, ("load", "services", "api", "percentiles_ms", "p(95)")),
    "postgres_mean_ms": (LATENCY_FILE, ("load", "services", "postgres", "mean_ms")),
    "redis_mean_ms": (LATENCY_FILE, ("load", "services", "redis", "mean_ms")),
    "immich_cpu_mean_pct": (RESOURCE_FILE, ("load", "services", "immich-server", "cpu_percent", "mean")),
    "catch_up_immich_cpu_mean_pct": (
        RESOURCE_FILE, ("catch_up", "services", "immich-server", "cpu_percent", "mean")
    ),
    "database_cpu_mean_pct": (RESOURCE_FILE, ("load", "services", "database", "cpu_percent", "mean")),
    "catch_up_database_cpu_mean_pct": (
        RESOURCE_FILE, ("catch_up", "services", "database", "cpu_percent", "mean")
    ),
    "redis_cpu_mean_pct": (RESOURCE_FILE, ("load", "services", "redis", "cpu_percent", "mean")),
    "catch_up_redis_cpu_mean_pct": (RESOURCE_FILE, ("catch_up", "services", "redis", "cpu_percent", "mean")),
    "immich_mem_mean_mb": (RESOURCE_FILE, ("load", "services", "immich-server", "memory_working_set_mb", "mean")),
    "immich_mem_peak_mb": (RESOURCE_FILE, ("load", "services", "immich-server", "memory_working_set_mb", "peak")),
    "database_mem_peak_mb": (RESOURCE_FILE, ("load", "services", "database", "memory_working_set_mb", "peak")),
    "api_cpu_mean_pct": (WORKER_FILE, ("load", "processes", "immich-api", "cpu_percent", "mean")),
    "worker_cpu_mean_pct": (WORKER_FILE, ("load", "processes", "immich-worker", "cpu_percent", "mean")),
    "catch_up_worker_cpu_mean_pct": (
        WORKER_FILE, ("catch_up", "processes", "immich-worker", "cpu_percent", "mean")
    ),
    "ffmpeg_cpu_mean_pct": (WORKER_FILE, ("load", "ffmpeg", "cpu_percent", "mean")),
    "catch_up_ffmpeg_cpu_mean_pct": (WORKER_FILE, ("catch_up", "ffmpeg", "cpu_percent", "mean")),
    "unattributed_cpu_mean_pct": (WORKER_FILE, ("load", "unattributed", "cpu_percent", "mean")),
    "catch_up_unattributed_cpu_mean_pct": (
        WORKER_FILE, ("catch_up", "unattributed", "cpu_percent", "mean")
    ),
    "worker_jobs_per_s": (WORKER_FILE, ("load", "jobs", "success_per_s")),
    "catch_up_worker_jobs_per_s": (WORKER_FILE, ("catch_up", "jobs", "success_per_s")),
}
SERVICE_COLUMNS = list(SERVICE_SOURCES)

# ---------------------------------------------------------------------------
# Thumbnails: per-asset timeline (server) and queue polls (client)
# ---------------------------------------------------------------------------
TIMELINE_FILE = "asset-timeline.csv"
QUEUE_STATS_FILE = "queue-stats.jsonl"
THUMBNAIL_QUEUE = "thumbnailGeneration"
METADATA_QUEUE = "metadataExtraction"
# A shorter metadata-free span is too noisy to trust as the steady rate.
MIN_STEADY_SECONDS = 60
CURVE_STEP_SECONDS = 10
KINDS = {"IMAGE": "photo", "VIDEO": "video"}
# Stage -> (start, end) timeline columns.
STAGES = {
    "upload_to_metadata": ("uploaded_at", "metadata_at"),
    "metadata_to_preview": ("metadata_at", "preview_at"),
    "upload_to_preview": ("uploaded_at", "preview_at"),
}
STAGE_PERCENTILES = {"p50": 50, "p95": 95, "max": 100}
TIMELINE_COLUMNS = [
    "steady_previews_per_s", "steady_photo_previews_per_s", "steady_video_previews_per_s",
    "steady_span_s", "metadata_busy", "queue_steady_thumbnails_per_s", "steady_rate_diff_pct",
    "previews_remaining", "projected_catch_up_s",
    *(f"{kind}_viewable_pct" for kind in KINDS.values()),
    *(
        f"{kind}_{stage}_{stat}_s"
        for kind in KINDS.values() for stage in STAGES for stat in STAGE_PERCENTILES
    ),
]

# ---------------------------------------------------------------------------
# Help text: where every column comes from
# ---------------------------------------------------------------------------
EPILOG = """\
input layout (as written by gh run download):
  RUNS_DIR/<run_id>/immich-load_run=<run_id>_role=client_.../
  RUNS_DIR/<run_id>/immich-load_run=<run_id>_role=server_.../
  Artifact folders are found at any depth and paired by run id.

columns:
  run_id                     from the artifact folder name
  <factor>                   client (else server) run-params.json parameters.*
  upload_p50_ms..p99_ms      k6-summary.json metrics.http_req_duration.values
  error_rate                 k6-summary.json metrics.http_req_failed.values.rate
  uploads_per_s              k6-summary.json metrics.successful_uploads.values.rate
  mb_per_s                   successful_upload_bytes.values.rate / 1,000,000
  queue_status, catch_up_s   queue-summary.json status, catch_up_seconds
  peak_backlog_<queue>, _max queue-summary.json peak_backlog
  api_waiting_p95_ms         service-latency.json phases.load.services
  postgres_mean_ms             .api.percentiles_ms["p(95)"], .postgres.mean_ms,
  redis_mean_ms                .redis.mean_ms
  immich_cpu_mean_pct        resource-usage.json phases.load.services
  database_cpu_mean_pct        .<service>.cpu_percent.mean for immich-server,
  redis_cpu_mean_pct           database and redis
  catch_up_immich_cpu_mean_pct the same CPU means in phases.catch_up
  catch_up_database_cpu_mean_pct
  catch_up_redis_cpu_mean_pct
                             cpu_percent is not capped at 100 (240 = ~2.4 vCPUs)
  immich_mem_mean_mb         resource-usage.json phases.load.services
  immich_mem_peak_mb           ["immich-server"].memory_working_set_mb.mean, .peak
  database_mem_peak_mb         and .database.memory_working_set_mb.peak
  api_cpu_mean_pct           worker-usage.json phases.load.processes
  worker_cpu_mean_pct          .<group>.cpu_percent.mean for immich-api and
                               immich-worker
  ffmpeg_cpu_mean_pct        worker-usage.json phases.load.ffmpeg.cpu_percent.mean,
                               ffmpeg and ffprobe from the worker's finished
                               children; empty for runs before it was measured
  unattributed_cpu_mean_pct  worker-usage.json phases.load.unattributed
                               .cpu_percent.mean, immich-server CPU not covered
                               by the groups and ffmpeg
  catch_up_worker_cpu_mean_pct the same CPU means in phases.catch_up
  catch_up_ffmpeg_cpu_mean_pct
  catch_up_unattributed_cpu_mean_pct
  worker_jobs_per_s          worker-usage.json phases.load.jobs.success_per_s
  catch_up_worker_jobs_per_s   and phases.catch_up.jobs.success_per_s
  cpu_model                 server cpu-limits.json cpu.model
  server_cloud, server_region
                             server run-params.json host.cloud, host.region
  pinned_cores               services.*.pinned_cores, empty if services disagree
  expected_cores             cpu-limits.json expected_cores
  cpu_model_flag             1 if cpu_model differs from the most common model in
                             the folder, 0 if it matches, empty if unknown

thumbnail columns (server asset-timeline.csv, client queue-summary.json and
queue-stats.jsonl):
  The cut-off is queue-summary load_end + drain_timeout_seconds. A preview
  created after it counts as unfinished. Asset times come from the server
  database and poll times from the client; both runners use NTP.
  steady_previews_per_s      previews created / time over the steady span:
  steady_photo_previews_per_s  queue polls after load_end, up to the cut-off,
  steady_video_previews_per_s  where thumbnailGeneration had a backlog and
  steady_span_s                metadataExtraction had none; span length in s
  metadata_busy              1 if that span was under MIN_STEADY_SECONDS, so
                               the span with any thumbnail backlog was used
                               instead; the rate may then be too low
  queue_steady_thumbnails_per_s
                             cross-check: thumbnailGeneration backlog drop
                               over the same span / its length. Immich removes
                               finished jobs, so the completed count stays 0.
                               Only valid while nothing new is queued, so
                               expect a gap when metadata_busy is 1
  steady_rate_diff_pct       (queue rate - steady_previews_per_s) /
                               steady_previews_per_s x 100; how far the two
                               sources disagree
  previews_remaining         assets without a preview at the cut-off
  projected_catch_up_s       previews_remaining / steady_previews_per_s; a
                               projection, not a measurement
  <kind>_viewable_pct        % of photo (or video) assets with a preview by
                               the cut-off
  <kind>_<stage>_p50_s       nearest-rank percentiles per kind for stages
  <kind>_<stage>_p95_s         upload_to_metadata, metadata_to_preview and
  <kind>_<stage>_max_s         upload_to_preview; unfinished assets rank last,
                               so a value is empty unless at least that share
                               finished; report it as over
                               drain_timeout_seconds

--curves FILE:
  Also writes cumulative % of assets viewable every CURVE_STEP_SECONDS from
  the first upload to the cut-off, as run_id, kind, seconds, viewable_pct rows.

  A missing file or field gives an empty cell.

--group:
  One row per set of identical factors, with n_runs, run_ids, and the sample
  mean and standard deviation (<metric>_mean, <metric>_std) of each metric.
  Missing values are skipped; std needs at least two values. cpu_model lists
  the distinct models and cpu_model_flag counts flagged runs.
  --exclude-flagged leaves out runs with cpu_model_flag 1 before grouping.
"""


# ---------------------------------------------------------------------------
# Reading helpers
# ---------------------------------------------------------------------------
def warn(message: str) -> None:
    print(f"Warning: {message}", file=sys.stderr)


def load_json(path: Path) -> object:
    """Return the parsed file, or None (with a warning) if it is missing or invalid."""
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        warn(f"missing {path}")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        warn(f"cannot read {path}: {error}")
    return None


def dig(value: object, *keys: str) -> object:
    """Follow nested dict keys, returning None as soon as one is missing."""
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def number(value: object) -> float | int | None:
    """Return value if it is a real number (not a bool), else None."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    return None


def parse_time(value: str | None) -> float | None:
    """Return an ISO 8601 timestamp as epoch seconds, or None if it is empty."""
    return datetime.fromisoformat(value).timestamp() if value else None


# ---------------------------------------------------------------------------
# Thumbnails: steady rate, stage percentiles and completion curve
# ---------------------------------------------------------------------------
def load_timeline(path: Path) -> list[dict] | None:
    """Return photo and video rows with epoch-second times, or None if unreadable."""
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            return [
                {
                    "kind": KINDS[row["type"]],
                    **{column: parse_time(row[column]) for column in ("uploaded_at", "metadata_at", "preview_at")},
                }
                for row in csv.DictReader(handle)
                if row["type"] in KINDS
            ]
    except FileNotFoundError:
        warn(f"missing {path}")
    except (OSError, KeyError, ValueError) as error:
        warn(f"cannot read {path}: {error}")
    return None


def load_polls(path: Path, start: float, end: float) -> list[tuple[float, dict]]:
    """Return (time, queues) for each successful poll after start, up to end."""
    polls = []
    try:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                record = json.loads(line)
                at = parse_time(record.get("time"))
                if "queues" in record and at is not None and start < at <= end:
                    polls.append((at, record["queues"]))
    except FileNotFoundError:
        warn(f"missing {path}")
    except (OSError, ValueError) as error:
        warn(f"cannot read {path}: {error}")
    return polls


def has_backlog(queues: dict, name: str) -> bool:
    return name in queues and backlog(queues[name]) > 0


def steady_span(polls: list[tuple[float, dict]]) -> tuple[float, float, bool] | None:
    """Return (start, end, metadata_busy) for the thumbnail rate, or None if too short.

    The steady span has a thumbnail backlog and no metadata backlog, so the
    worker is limited by thumbnail work alone. If that span is too short, the
    span with any thumbnail backlog is used and flagged as metadata_busy.
    """
    thumbnail = [(at, queues) for at, queues in polls if has_backlog(queues, THUMBNAIL_QUEUE)]
    steady = [at for at, queues in thumbnail if not has_backlog(queues, METADATA_QUEUE)]
    if len(steady) > 1 and steady[-1] - steady[0] >= MIN_STEADY_SECONDS:
        return steady[0], steady[-1], False
    times = [at for at, _ in thumbnail]
    return (times[0], times[-1], True) if len(times) > 1 else None


def percentile_with_unfinished(durations: list[float | None], percent: float) -> float | None:
    """Nearest-rank percentile with unfinished assets (None) ranked last.

    Returns None when the rank falls on an unfinished asset, i.e. when fewer
    than percent % of the assets finished by the cut-off.
    """
    if not durations:
        return None
    ranked = sorted(durations, key=lambda duration: (duration is None, duration or 0.0))
    return ranked[max(0, math.ceil(percent / 100 * len(ranked)) - 1)]


def timeline_metrics(rows: list[dict], polls: list[tuple[float, dict]], cut_off: float) -> dict:
    """Return the thumbnail columns for one run."""

    def done(at: float | None) -> bool:
        return at is not None and at <= cut_off

    metrics: dict[str, object] = {}
    for kind in KINDS.values():
        assets = [row for row in rows if row["kind"] == kind]
        viewable = sum(done(row["preview_at"]) for row in assets)
        metrics[f"{kind}_viewable_pct"] = 100 * viewable / len(assets) if assets else None
        for stage, (start, end) in STAGES.items():
            durations = [
                row[end] - row[start] if row[start] is not None and done(row[end]) else None
                for row in assets
            ]
            for stat, percent in STAGE_PERCENTILES.items():
                metrics[f"{kind}_{stage}_{stat}_s"] = percentile_with_unfinished(durations, percent)

    remaining = sum(not done(row["preview_at"]) for row in rows)
    metrics["previews_remaining"] = remaining
    span = steady_span(polls)
    if span is None:
        return metrics
    start, end, metadata_busy = span
    metrics["steady_span_s"] = end - start
    metrics["metadata_busy"] = int(metadata_busy)
    for label, kinds in (("", KINDS.values()), ("photo_", ("photo",)), ("video_", ("video",))):
        assets = [row["preview_at"] for row in rows if row["kind"] in kinds]
        # Empty, not 0, when the run uploaded none of this kind.
        if assets:
            count = sum(at is not None and start < at <= end for at in assets)
            metrics[f"steady_{label}previews_per_s"] = count / (end - start)
    rate = metrics.get("steady_previews_per_s")
    metrics["projected_catch_up_s"] = remaining / rate if remaining and rate else None

    # Cross-check from a second source: the queue's backlog drop over the same span.
    queues_at = dict(polls)
    drop = backlog(queues_at[start][THUMBNAIL_QUEUE]) - backlog(queues_at[end][THUMBNAIL_QUEUE])
    queue_rate = drop / (end - start)
    metrics["queue_steady_thumbnails_per_s"] = queue_rate
    metrics["steady_rate_diff_pct"] = 100 * (queue_rate - rate) / rate if rate else None
    return metrics


def completion_curve(rows: list[dict], cut_off: float) -> list[dict]:
    """Return cumulative % viewable per kind every CURVE_STEP_SECONDS from the first upload."""
    uploads = [row["uploaded_at"] for row in rows if row["uploaded_at"] is not None]
    if not uploads:
        return []
    first = min(uploads)
    curve = []
    for kind in KINDS.values():
        previews = [row["preview_at"] for row in rows if row["kind"] == kind]
        if not previews:
            continue
        for seconds in range(0, math.floor(cut_off - first) + 1, CURVE_STEP_SECONDS):
            viewable = sum(at is not None and at <= first + seconds for at in previews)
            curve.append({"kind": kind, "seconds": seconds, "viewable_pct": 100 * viewable / len(previews)})
    return curve


# ---------------------------------------------------------------------------
# Runs: pair artifacts and read one run's metrics
# ---------------------------------------------------------------------------
def find_artifacts(root: Path) -> dict[str, dict[str, Path]]:
    """Map each run id to its client and server artifact folders."""
    runs: dict[str, dict[str, Path]] = {}
    for path in sorted(root.rglob("immich-load_run=*")):
        match = ARTIFACT_NAME.match(path.name)
        if not match or not path.is_dir():
            continue
        run_id, role = match.groups()
        roles = runs.setdefault(run_id, {})
        if role in roles:
            warn(f"ignoring duplicate {role} artifact {path}")
            continue
        roles[role] = path
    return runs


def load_run(run_id: str, folders: dict[str, Path]) -> tuple[dict, dict]:
    """Return (factors, metrics) for one run; anything unreadable is None."""
    client, server = folders.get("client"), folders.get("server")
    if client is None:
        warn(f"run {run_id} has no client artifact")
    if server is None:
        warn(f"run {run_id} has no server artifact")

    def read(folder: Path | None, name: str) -> object:
        return load_json(folder / name) if folder else None

    parameters = dig(read(client, "run-params.json"), "parameters")
    if not isinstance(parameters, dict):
        parameters = dig(read(server, "run-params.json"), "parameters")
    factors = {}
    if isinstance(parameters, dict):
        # Only scalar settings can be CSV cells and group keys.
        factors = {name: value for name, value in parameters.items() if isinstance(value, (str, int, float))}

    k6 = dig(read(client, "k6-summary.json"), "metrics")
    queues = read(client, "queue-summary.json")
    limits = read(server, "cpu-limits.json")

    metrics: dict[str, object] = {"run_id": run_id}
    for p, column in zip(PERCENTILES, LATENCY_COLUMNS):
        metrics[column] = number(dig(k6, "http_req_duration", "values", f"p({p})"))
    metrics["error_rate"] = number(dig(k6, "http_req_failed", "values", "rate"))
    metrics["uploads_per_s"] = number(dig(k6, "successful_uploads", "values", "rate"))
    byte_rate = number(dig(k6, "successful_upload_bytes", "values", "rate"))
    metrics["mb_per_s"] = byte_rate / MB if byte_rate is not None else None

    status = dig(queues, "status")
    metrics["queue_status"] = status if isinstance(status, str) else None
    metrics["catch_up_s"] = number(dig(queues, "catch_up_seconds"))
    backlog = dig(queues, "peak_backlog")
    peaks = {}
    if isinstance(backlog, dict):
        peaks = {name: number(peak) for name, peak in backlog.items()}
    metrics["peak_backlog"] = peaks
    present = [peak for peak in peaks.values() if peak is not None]
    metrics["peak_backlog_max"] = max(present) if present else None

    metrics["curve"] = []
    load_end = dig(queues, "load_end")
    drain_timeout = number(dig(queues, "drain_timeout_seconds"))
    timeline = load_timeline(server / TIMELINE_FILE) if server else None
    if client and timeline is not None and isinstance(load_end, str) and drain_timeout is not None:
        start = parse_time(load_end)
        cut_off = start + drain_timeout
        polls = load_polls(client / QUEUE_STATS_FILE, start, cut_off)
        metrics.update(timeline_metrics(timeline, polls, cut_off))
        metrics["curve"] = completion_curve(timeline, cut_off)

    phases = {}
    for name in (LATENCY_FILE, RESOURCE_FILE, WORKER_FILE):
        summary = read(client, name)
        if summary is not None and dig(summary, "status") != "ok":
            warn(f"run {run_id} {name} status is {dig(summary, 'status')!r}: {dig(summary, 'error')}")
        phases[name] = dig(summary, "phases")
    for column, (name, keys) in SERVICE_SOURCES.items():
        metrics[column] = number(dig(phases[name], *keys))

    model = dig(limits, "cpu", "model")
    metrics["cpu_model"] = model if isinstance(model, str) and model else None
    server_host = dig(read(server, "run-params.json"), "host")
    for field in ("cloud", "region"):
        value = dig(server_host, field)
        metrics[f"server_{field}"] = value if isinstance(value, str) else None
    pinned = {number(dig(limits, "services", service, "pinned_cores")) for service in SERVICES}
    pinned.discard(None)
    if len(pinned) > 1:
        warn(f"run {run_id} services disagree on pinned cores: {sorted(pinned)}")
    metrics["pinned_cores"] = pinned.pop() if len(pinned) == 1 else None
    metrics["expected_cores"] = number(dig(limits, "expected_cores"))
    return factors, metrics


# ---------------------------------------------------------------------------
# Runner CPU check
# ---------------------------------------------------------------------------
def flag_cpu_models(rows: list[dict]) -> None:
    """Set cpu_model_flag against the most common known model in the folder."""
    counts = Counter(row["cpu_model"] for row in rows if row["cpu_model"])
    if not counts:
        for row in rows:
            row["cpu_model_flag"] = None
        return
    top = max(counts.values())
    leaders = sorted(model for model, count in counts.items() if count == top)
    if len(leaders) > 1:
        warn(f"CPU models tie for most common; using {leaders[0]!r} of {leaders}")
    common = leaders[0]
    for row in rows:
        model = row["cpu_model"]
        row["cpu_model_flag"] = None if model is None else int(model != common)


# ---------------------------------------------------------------------------
# Grouping and CSV output
# ---------------------------------------------------------------------------
def group_rows(rows: list[dict], factor_columns: list[str], metric_columns: list[str]) -> list[dict]:
    """Collapse runs with identical factors into mean and standard deviation rows."""
    groups: dict[tuple, list[dict]] = {}
    for row in rows:
        key = tuple(row.get(factor) for factor in factor_columns)
        groups.setdefault(key, []).append(row)

    output = []
    for key, members in groups.items():
        grouped: dict[str, object] = dict(zip(factor_columns, key))
        grouped["n_runs"] = len(members)
        grouped["run_ids"] = ";".join(member["run_id"] for member in members)
        for column in metric_columns:
            values = [member[column] for member in members if member.get(column) is not None]
            grouped[f"{column}_mean"] = statistics.fmean(values) if values else None
            grouped[f"{column}_std"] = statistics.stdev(values) if len(values) > 1 else None
        grouped["cpu_model"] = ";".join(sorted({m["cpu_model"] for m in members if m["cpu_model"]})) or None
        grouped["cpu_model_flag"] = sum(1 for member in members if member["cpu_model_flag"] == 1)
        output.append(grouped)
    return output


def write_csv(rows: list[dict], columns: list[str], output: Path | None) -> None:
    def write(handle) -> None:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: "" if row.get(column) is None else row[column] for column in columns})

    if output is None:
        write(sys.stdout)
    else:
        with output.open("w", newline="") as handle:
            write(handle)


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, epilog=EPILOG, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("runs_dir", type=Path, help="folder of downloaded workflow artifacts")
    parser.add_argument("--group", action="store_true", help="aggregate repeats with identical factors")
    parser.add_argument(
        "--exclude-flagged", action="store_true", help="with --group, leave out runs with cpu_model_flag 1"
    )
    parser.add_argument("-o", "--output", type=Path, help="CSV file to write (default: stdout)")
    parser.add_argument("--curves", type=Path, help="also write per-run completion curves to this CSV")
    args = parser.parse_args()
    if args.exclude_flagged and not args.group:
        parser.error("--exclude-flagged requires --group")
    if not args.runs_dir.is_dir():
        parser.error(f"{args.runs_dir} is not a directory")

    artifacts = find_artifacts(args.runs_dir)
    if not artifacts:
        print(f"Error: no immich-load artifact folders found in {args.runs_dir}.", file=sys.stderr)
        return 1

    factor_columns: list[str] = []
    queue_names: set[str] = set()
    rows = []
    curves = []
    for run_id in sorted(artifacts, key=int):
        factors, metrics = load_run(run_id, artifacts[run_id])
        factor_columns += [name for name in factors if name not in factor_columns]
        queue_names.update(metrics["peak_backlog"])
        curves += [{"run_id": run_id, **point} for point in metrics.pop("curve")]
        rows.append({**factors, **metrics})
    backlog_columns = [f"peak_backlog_{name}" for name in sorted(queue_names)]
    for row in rows:
        peaks = row.pop("peak_backlog")
        for name in queue_names:
            row[f"peak_backlog_{name}"] = peaks.get(name)
    flag_cpu_models(rows)

    metric_columns = [
        *LATENCY_COLUMNS, "error_rate", "uploads_per_s", "mb_per_s", "catch_up_s",
        *backlog_columns, "peak_backlog_max", *SERVICE_COLUMNS, *TIMELINE_COLUMNS,
    ]
    if args.group:
        if args.exclude_flagged:
            rows = [row for row in rows if row["cpu_model_flag"] != 1]
        rows = group_rows(rows, factor_columns, metric_columns)
        columns = [
            *factor_columns, "n_runs", "run_ids",
            *(f"{column}_{stat}" for column in metric_columns for stat in ("mean", "std")),
            "cpu_model", "cpu_model_flag",
        ]
    else:
        columns = [
            "run_id", *factor_columns, *LATENCY_COLUMNS, "error_rate", "uploads_per_s", "mb_per_s",
            "queue_status", "catch_up_s", *backlog_columns, "peak_backlog_max", *SERVICE_COLUMNS,
            *TIMELINE_COLUMNS, "cpu_model", "server_cloud", "server_region", "pinned_cores", "expected_cores",
            "cpu_model_flag",
        ]
    write_csv(rows, columns, args.output)
    if args.curves:
        write_csv(curves, ["run_id", "kind", "seconds", "viewable_pct"], args.curves)
    return 0


if __name__ == "__main__":
    sys.exit(main())
