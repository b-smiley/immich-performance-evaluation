#!/usr/bin/env python3
"""Generate the reproducible randomized Phase 2 run order."""

import csv
import random
import sys
from pathlib import Path

SEED = 5332026
OUTPUT = Path(__file__).resolve().parents[1] / "docs" / "phase2-run-order.csv"
WORKLOADS = (
    ("photo_only", 1.0),
    ("video_only", 0.0),
    ("mixed", 0.5),
)
UPLOAD_LEVELS = (1, 25, 100, 1000)
REPLICATES = (1, 2, 3)


def main() -> None:
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else OUTPUT
    runs = [
        (replicate, workload, photo_ratio, uploads)
        for replicate in REPLICATES
        for workload, photo_ratio in WORKLOADS
        for uploads in UPLOAD_LEVELS
    ]
    random.Random(SEED).shuffle(runs)

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.writer(csv_file, lineterminator="\n")
        writer.writerow(
            (
                "run_order",
                "replicate",
                "workload_composition",
                "photo_ratio",
                "concurrent_uploads",
            )
        )
        for run_order, (replicate, workload, photo_ratio, uploads) in enumerate(
            runs, start=1
        ):
            writer.writerow(
                (run_order, replicate, workload, photo_ratio, uploads)
            )


if __name__ == "__main__":
    main()
