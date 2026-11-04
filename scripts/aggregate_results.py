#!/usr/bin/env python3
"""Aggregate downloaded load-test workflow artifacts into one CSV row per run."""

from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
import sys
from collections import Counter
from pathlib import Path

ARTIFACT_NAME = re.compile(r"^immich-load_run=(\d+)_role=(client|server)_")
PERCENTILES = (50, 75, 90, 95, 99)
LATENCY_COLUMNS = [f"upload_p{p}_ms" for p in PERCENTILES]
SERVICES = ("immich-server", "database", "redis")
# Matches MB in generate_fixtures.py.
MB = 1_000_000

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
  cpu_model                  server cpu-limits.json cpu.model
  pinned_cores               services.*.pinned_cores, empty if services disagree
  expected_cores             cpu-limits.json expected_cores
  cpu_model_flag             1 if cpu_model differs from the most common model in
                             the folder, 0 if it matches, empty if unknown
  A missing file or field gives an empty cell.

--group:
  One row per set of identical factors, with n_runs, run_ids, and the sample
  mean and standard deviation (<metric>_mean, <metric>_std) of each metric.
  Missing values are skipped; std needs at least two values. cpu_model lists
  the distinct models and cpu_model_flag counts flagged runs.
  --exclude-flagged leaves out runs with cpu_model_flag 1 before grouping.
"""


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

    model = dig(limits, "cpu", "model")
    metrics["cpu_model"] = model if isinstance(model, str) and model else None
    pinned = {number(dig(limits, "services", service, "pinned_cores")) for service in SERVICES}
    pinned.discard(None)
    if len(pinned) > 1:
        warn(f"run {run_id} services disagree on pinned cores: {sorted(pinned)}")
    metrics["pinned_cores"] = pinned.pop() if len(pinned) == 1 else None
    metrics["expected_cores"] = number(dig(limits, "expected_cores"))
    return factors, metrics


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
    for run_id in sorted(artifacts, key=int):
        factors, metrics = load_run(run_id, artifacts[run_id])
        factor_columns += [name for name in factors if name not in factor_columns]
        queue_names.update(metrics["peak_backlog"])
        rows.append({**factors, **metrics})
    backlog_columns = [f"peak_backlog_{name}" for name in sorted(queue_names)]
    for row in rows:
        peaks = row.pop("peak_backlog")
        for name in queue_names:
            row[f"peak_backlog_{name}"] = peaks.get(name)
    flag_cpu_models(rows)

    metric_columns = [
        *LATENCY_COLUMNS, "error_rate", "uploads_per_s", "mb_per_s", "catch_up_s",
        *backlog_columns, "peak_backlog_max",
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
            "queue_status", "catch_up_s", *backlog_columns, "peak_backlog_max",
            "cpu_model", "pinned_cores", "expected_cores", "cpu_model_flag",
        ]
    write_csv(rows, columns, args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
