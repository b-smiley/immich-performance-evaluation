#!/usr/bin/env python3
"""Record the Immich stack's CPU limits and fail if they differ from the requested count."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

SERVICES = ("immich-server", "database", "redis")


def compose(*args: str) -> str:
    return subprocess.run(
        ["docker", "compose", *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def cpuset_size(cpuset: str) -> int:
    """Count the cores in a cpuset such as `0`, `0-3`, or `0-1,3`."""
    size = 0
    for part in cpuset.split(","):
        first, _, last = part.partition("-")
        size += int(last or first) - int(first) + 1
    return size


def inspect_service(service: str) -> dict[str, object]:
    container = compose("ps", "-q", service)
    cpuset = subprocess.run(
        ["docker", "inspect", "--format", "{{.HostConfig.CpusetCpus}}", container],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    visible = int(compose("exec", "-T", service, "nproc"))
    return {"cpuset": cpuset, "pinned_cores": cpuset_size(cpuset) if cpuset else None, "nproc": visible}


def parse_cpuinfo(cpuinfo: str) -> dict[str, object]:
    """Describe the CPU from /proc/cpuinfo, grouping hardware threads by physical core."""
    processors = [
        {key.strip(): value.strip() for key, _, value in (line.partition(":") for line in block.splitlines())}
        for block in cpuinfo.strip().split("\n\n")
    ]
    cores: dict[tuple[str, str], list[int]] = {}
    for processor in processors:
        if "core id" in processor:
            core = (processor.get("physical id", "0"), processor["core id"])
            cores.setdefault(core, []).append(int(processor["processor"]))
    return {
        "vendor": processors[0].get("vendor_id"),
        "model": processors[0].get("model name"),
        "hardware_threads": len(processors),
        "physical_cores": len(cores) or None,
        "core_threads": sorted(cores.values()) or None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-cores", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    services = {service: inspect_service(service) for service in SERVICES}
    detected = re.search(r"Detected CPU Cores: (\d+)", compose("logs", "--no-color", "immich-server"))
    record = {
        "expected_cores": args.expected_cores,
        "host_cores": os.cpu_count(),
        "cpu": parse_cpuinfo(compose("exec", "-T", "redis", "cat", "/proc/cpuinfo")),
        "immich_detected_cores": int(detected.group(1)) if detected else None,
        "services": services,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(record, indent=2) + "\n")

    wrong = [
        f"{service} (pinned {values['pinned_cores']}, nproc {values['nproc']})"
        for service, values in services.items()
        if values["pinned_cores"] != args.expected_cores or values["nproc"] != args.expected_cores
    ]
    if wrong:
        print(
            f"Error: expected {args.expected_cores} CPU cores, but found: {', '.join(wrong)}.",
            file=sys.stderr,
        )
        return 1
    print(f"CPU limit verified: {args.expected_cores} core(s) for {', '.join(SERVICES)}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
