#!/usr/bin/env python3
"""Refuse load-test runs that would exhaust client memory or server disk."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from generate_fixtures import MB, SIZE_RANGES

# k6 holds the upload body, its Go copy, and the multipart body per VU.
K6_COPIES_PER_UPLOAD = 3
MEMORY_BUDGET_FRACTION = 0.75
# Originals plus thumbnails, previews, and transcoded videos.
STORAGE_AMPLIFICATION = 2
DISK_BUDGET_FRACTION = 0.9
DURATION_UNITS = {"ms": 0.001, "s": 1, "m": 60, "h": 3600}


def parse_duration(value: str) -> float:
    if re.fullmatch(r"\d+(\.\d+)?", value):
        return float(value)
    parts = re.findall(r"(\d+(?:\.\d+)?)(ms|s|m|h)", value)
    if not parts or "".join(number + unit for number, unit in parts) != value:
        raise SystemExit(f"Error: unsupported k6 duration '{value}'.")
    return sum(float(number) * DURATION_UNITS[unit] for number, unit in parts)


def load_manifest(path: Path) -> list[dict[str, object]]:
    return json.loads(path.read_text())["files"]


def weighted_mean(photo_mean: float | None, video_mean: float | None, photo_ratio: float) -> float:
    if photo_mean is None or photo_ratio <= 0:
        return float(video_mean or 0)
    if video_mean is None or photo_ratio >= 1:
        return float(photo_mean)
    return photo_ratio * photo_mean + (1 - photo_ratio) * video_mean


def docker_memory() -> int | None:
    try:
        output = subprocess.run(
            ["docker", "info", "--format", "{{.MemTotal}}"],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        return int(output)
    except (OSError, subprocess.CalledProcessError, ValueError):
        return None


def check_memory(args: argparse.Namespace) -> int:
    files = load_manifest(args.manifest)
    largest = max(int(entry["bytes"]) for entry in files)
    shared = sum(int(entry["bytes"]) for entry in files)
    budget = args.budget
    if budget is None:
        total = docker_memory()
        if total is None:
            print("Error: could not read Docker memory; set K6_MEMORY_BUDGET_BYTES.", file=sys.stderr)
            return 1
        budget = int(total * MEMORY_BUDGET_FRACTION)

    per_vu = largest * K6_COPIES_PER_UPLOAD
    required = shared + args.vus * per_vu
    if required > budget:
        max_vus = max((budget - shared) // per_vu, 0)
        print(
            f"Error: {args.vus} VUs need about {required / MB:,.0f}MB of k6 memory "
            f"(largest fixture {largest / MB:,.1f}MB), but the budget is {budget / MB:,.0f}MB. "
            f"At most {max_vus} VUs fit; reduce VUS or set K6_MEMORY_BUDGET_BYTES.",
            file=sys.stderr,
        )
        return 1
    print(f"Memory check passed: ~{required / MB:,.0f}MB of {budget / MB:,.0f}MB budget.")
    return 0


def check_disk(args: argparse.Namespace) -> int:
    if args.manifest:
        files = load_manifest(args.manifest)
        means = {}
        for kind in ("photo", "video"):
            sizes = [int(entry["bytes"]) for entry in files if entry["kind"] == kind]
            means[kind] = sum(sizes) / len(sizes) if sizes else None
    else:
        means = {kind: sum(SIZE_RANGES[kind][args.size_level]) / 2 for kind in ("photo", "video")}
    mean = weighted_mean(means["photo"], means["video"], args.photo_ratio)

    if args.iterations:
        uploaded = args.iterations * mean
        basis = f"{args.iterations} iterations"
    else:
        seconds = parse_duration(args.duration)
        # Every iteration sleeps at least one second, and uploads cannot
        # outrun the network link.
        by_iterations = args.vus * seconds * mean
        by_bandwidth = args.upload_mbps / 8 * MB * seconds
        uploaded = min(by_iterations, by_bandwidth)
        basis = f"{args.vus} VUs for {args.duration} at <= {args.upload_mbps:g}Mb/s"

    path = args.path.resolve()
    while not path.exists():
        path = path.parent
    free = shutil.disk_usage(path).free
    estimate = uploaded * STORAGE_AMPLIFICATION
    if estimate > free * DISK_BUDGET_FRACTION:
        print(
            f"Error: {basis} could write about {estimate / MB:,.0f}MB to {path}, "
            f"but only {free / MB:,.0f}MB is free. Set ITERATIONS, shorten DURATION, "
            "or reduce VUS (raise UPLOAD_MBPS only if the link is really faster).",
            file=sys.stderr,
        )
        return 1
    print(f"Disk check passed: ~{estimate / MB:,.0f}MB estimated, {free / MB:,.0f}MB free at {path}.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    memory = commands.add_parser("memory", help="check k6 memory for the fixture pool")
    memory.add_argument("--manifest", type=Path, required=True)
    memory.add_argument("--vus", type=int, required=True)
    memory.add_argument("--budget", type=int, help="bytes available to k6 (default: 75%% of Docker memory)")
    memory.set_defaults(handler=check_memory)

    disk = commands.add_parser("disk", help="check server disk for the expected upload volume")
    source = disk.add_mutually_exclusive_group(required=True)
    source.add_argument("--manifest", type=Path)
    source.add_argument("--size-level", choices=list(SIZE_RANGES["photo"]))
    disk.add_argument("--path", type=Path, required=True)
    disk.add_argument("--vus", type=int, required=True)
    disk.add_argument("--duration", default="30s")
    disk.add_argument("--iterations", type=int, default=0)
    disk.add_argument("--photo-ratio", type=float, default=0.5)
    disk.add_argument("--upload-mbps", type=float, default=1000)
    disk.set_defaults(handler=check_disk)

    args = parser.parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
