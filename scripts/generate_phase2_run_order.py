#!/usr/bin/env python3
"""Generate the reproducible randomized Phase 2 run order.

Writes the run record to docs/phase2-run-order.csv and the matching batch file
for the Immich load batch workflow to experiments/phase2.csv.
"""

import argparse
import csv
import random
from pathlib import Path

SEED = 5332026
ROOT = Path(__file__).resolve().parents[1]
RUN_ORDER_OUTPUT = ROOT / "docs" / "phase2-run-order.csv"
BATCH_OUTPUT = ROOT / "experiments" / "phase2.csv"

WORKLOADS = {
    "photo_only": "1.0",
    "video_only": "0.0",
    "mixed": "0.5",
}
UPLOAD_LEVELS = (1, 25, 100, 1000)
REPLICATES = (1, 2, 3)
BASELINE_CPU_CORES = 1
COMPARISON_CPU_CORES = 4
# Over the k6 memory budget at every size level; see docs/run-matrix.md.
DROPPED = {("video_only", 1000), ("mixed", 1000)}
# Baseline conditions repeated at COMPARISON_CPU_CORES.
CORES_COMPARISON = (("photo_only", 1000), ("mixed", 100))

# Held constant for every run.
CONSTANTS = {
    "duration": "5m",
    "users": "1",
    "think_time_seconds": "0",
    "size_level": "small",
    "resolution": "4k",
    # Caps background catch-up; see docs/run-matrix.md.
    "drain_timeout_seconds": "600",
}

RUN_ORDER_COLUMNS = (
    "run_order",
    "replicate",
    "workload_composition",
    "photo_ratio",
    "concurrent_uploads",
    "cpu_cores",
)
BATCH_COLUMNS = (
    "run_order",
    "replicate",
    "workload_composition",
    "notes",
    "duration",
    "concurrent_uploads",
    "users",
    "think_time_seconds",
    "cpu_cores",
    "photo_ratio",
    "size_level",
    "resolution",
    "drain_timeout_seconds",
)


def conditions() -> list[tuple[str, int, int, str]]:
    """Return (workload, uploads, cpu_cores, notes) for every condition."""
    baseline = [
        (workload, uploads, BASELINE_CPU_CORES, "baseline")
        for workload in WORKLOADS
        for uploads in UPLOAD_LEVELS
        if (workload, uploads) not in DROPPED
    ]
    comparison = [
        (workload, uploads, COMPARISON_CPU_CORES, "cores-comparison")
        for workload, uploads in CORES_COMPARISON
    ]
    return baseline + comparison


def shuffled_runs() -> list[dict[str, str]]:
    runs = [
        (replicate, *condition)
        for replicate in REPLICATES
        for condition in conditions()
    ]
    random.Random(SEED).shuffle(runs)
    return [
        {
            **CONSTANTS,
            "run_order": str(run_order),
            "replicate": str(replicate),
            "workload_composition": workload,
            "notes": notes,
            "concurrent_uploads": str(uploads),
            "cpu_cores": str(cpu_cores),
            "photo_ratio": WORKLOADS[workload],
        }
        for run_order, (replicate, workload, uploads, cpu_cores, notes) in enumerate(
            runs, start=1
        )
    ]


def write_csv(path: Path, columns: tuple[str, ...], runs: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.writer(csv_file, lineterminator="\n")
        writer.writerow(columns)
        for run in runs:
            writer.writerow(run[column] for column in columns)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-order-output", type=Path, default=RUN_ORDER_OUTPUT)
    parser.add_argument("--batch-output", type=Path, default=BATCH_OUTPUT)
    args = parser.parse_args()

    runs = shuffled_runs()
    write_csv(args.run_order_output, RUN_ORDER_COLUMNS, runs)
    write_csv(args.batch_output, BATCH_COLUMNS, runs)


if __name__ == "__main__":
    main()
