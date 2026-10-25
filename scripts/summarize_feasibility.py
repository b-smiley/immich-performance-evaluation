#!/usr/bin/env python3
"""Parse feasibility artifacts into the workflow summary table."""

import json
import re
import sys
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def first_number(value: str) -> float | None:
    match = re.search(r"(\d+(?:\.\d+)?)", value)
    return float(match.group(1)) if match else None


def direct_or_relay(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8").lower()
    except OSError:
        return "unknown"
    if "via derp" in text or "relay" in text:
        return "relay"
    if "direct" in text or "via " in text:
        return "direct"
    return "unknown"


def hard_nat(path: Path) -> str:
    data = load_json(path)
    value = data.get("MappingVariesByDestIP") if data else None
    return str(value).lower() if value is not None else "unknown"


def average_rtt(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return "unknown"
    values = [float(match) for match in re.findall(r"time[=<]([0-9.]+)\s*ms", text)]
    return f"{sum(values) / len(values):.2f}" if values else "unknown"


def throughput(path: Path, received: bool = True) -> str:
    data = load_json(path)
    if not data:
        return "unknown"
    end = data.get("end", {})
    key = "sum_received" if received else "sum_sent"
    bits = end.get(key, {}).get("bits_per_second")
    return f"{bits / 1_000_000:.2f}" if isinstance(bits, (int, float)) else "unknown"


def cpu_percent(path: Path) -> str:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return "unknown"
    values = []
    for line in lines:
        if "tailscaled" not in line:
            continue
        fields = line.split()
        command_index = fields.index("tailscaled")
        if command_index >= 3:
            value = first_number(fields[command_index - 2])
            if value is not None:
                values.append(value)
    return f"{sum(values) / len(values):.2f}" if values else "unknown"


def attempt_row(root: Path, attempt: int) -> tuple[str, ...]:
    client = root / f"results-{attempt}-client"
    server = root / f"results-{attempt}-server"
    direct = direct_or_relay(client / "tailscale-ping.log")
    return (
        str(attempt),
        direct,
        hard_nat(server / "server-netcheck.json"),
        hard_nat(client / "client-netcheck.json"),
        average_rtt(client / "plain-ping.log"),
        throughput(client / "iperf3-single.json"),
        throughput(client / "iperf3-parallel.json"),
        throughput(client / "iperf3-reverse.json"),
        cpu_percent(server / "server-cpu.log"),
    )


def main() -> None:
    root = Path(sys.argv[1])
    attempts = int(sys.argv[2])
    rows = [attempt_row(root, attempt) for attempt in range(1, attempts + 1)]
    print("| attempt | direct/relay | server hard NAT | client hard NAT | avg RTT ms | Mbit/s single | Mbit/s 4-stream | Mbit/s reverse | tailscaled CPU % on server |")
    print("| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: |")
    for row in rows:
        print("| " + " | ".join(row) + " |")
    verdict = "FEASIBLE" if rows and all(row[1] == "direct" for row in rows) else "NOT FEASIBLE"
    print()
    print(f"**Verdict: {verdict}**")


if __name__ == "__main__":
    main()
