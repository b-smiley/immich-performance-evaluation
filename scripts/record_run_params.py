#!/usr/bin/env python3
"""Validate load-test parameters and record them beside the run's results."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

# Artifact-name key and the workflow input it records.
PARAMETERS = {
    "uploads": "concurrent_uploads",
    "users": "users",
    "think": "think_time_seconds",
    "dur": "duration",
    "photo": "photo_ratio",
    "size": "size_level",
    "res": "resolution",
    "iters": "iterations",
    "seed": "fixture_seed",
}
# Artifact names split on "_" and "=", so values cannot contain either.
VALUE_PATTERN = re.compile(r"[A-Za-z0-9.]+")


def parse_params(value: str) -> dict[str, str]:
    params: dict[str, str] = {}
    for field in value.split("_"):
        key, separator, field_value = field.partition("=")
        if not separator:
            raise ValueError(f"'{field}' is not a key=value pair; values cannot contain '_'")
        if key not in PARAMETERS:
            raise ValueError(f"unknown parameter '{key}'")
        if key in params:
            raise ValueError(f"duplicate parameter '{key}'")
        if not VALUE_PATTERN.fullmatch(field_value):
            raise ValueError(
                f"{PARAMETERS[key]} value '{field_value}' may only contain letters, digits, and '.'"
            )
        params[key] = field_value
    missing = [key for key in PARAMETERS if key not in params]
    if missing:
        raise ValueError(f"missing parameters: {', '.join(missing)}")
    return params


def summary_table(params: dict[str, str]) -> str:
    rows = "".join(f"| `{PARAMETERS[key]}` | `{params[key]}` |\n" for key in PARAMETERS)
    return f"## Run parameters\n\n| Input | Value |\n|---|---|\n{rows}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", choices=["server", "client"], required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary", action="store_true", help="append a table to $GITHUB_STEP_SUMMARY")
    args = parser.parse_args()

    try:
        params = parse_params(os.environ.get("RUN_PARAMS", ""))
    except ValueError as error:
        print(f"Error: invalid run parameters: {error}.", file=sys.stderr)
        return 1

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if args.summary and not summary_path:
        print("Error: --summary requires GITHUB_STEP_SUMMARY.", file=sys.stderr)
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "run_id": os.environ.get("GITHUB_RUN_ID"),
        "role": args.role,
        "commit": os.environ.get("GITHUB_SHA"),
        "ref": os.environ.get("GITHUB_REF_NAME"),
        "parameters": {PARAMETERS[key]: params[key] for key in PARAMETERS},
    }
    args.output.write_text(json.dumps(record, indent=2) + "\n")

    if args.summary:
        with open(summary_path, "a", encoding="utf-8") as summary:
            summary.write(summary_table(params))
    print(f"Recorded run parameters in {args.output}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
