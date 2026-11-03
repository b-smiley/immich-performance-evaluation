#!/usr/bin/env python3
"""Record Immich queue depth and how long jobs take to catch up after a load test."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# Jobs in a paused queue are reported as paused, so they still count as backlog.
BACKLOG_FIELDS = ("active", "waiting", "delayed", "paused")
RECORDED_FIELDS = (*BACKLOG_FIELDS, "failed", "completed")


class UnexpectedResponse(Exception):
    """The API answered with JSON this script cannot interpret."""


def timestamp(seconds: float) -> str:
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat()


def parse_queues(payload: object) -> dict[str, dict[str, object]]:
    if not isinstance(payload, list) or not payload:
        raise UnexpectedResponse("expected a non-empty list of queues")
    queues: dict[str, dict[str, object]] = {}
    for queue in payload:
        try:
            statistics = queue["statistics"]
            counts = {field: statistics[field] for field in RECORDED_FIELDS}
            queues[queue["name"]] = {**counts, "isPaused": queue["isPaused"]}
        except (KeyError, TypeError) as error:
            raise UnexpectedResponse(f"queue is missing {error}") from error
        if not all(isinstance(count, int) for count in counts.values()):
            raise UnexpectedResponse(f"queue {queue['name']} has non-integer counts")
    return queues


def fetch_queues(url: str, api_key: str, timeout: float) -> dict[str, dict[str, object]]:
    request = urllib.request.Request(f"{url}/api/queues", headers={"x-api-key": api_key})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return parse_queues(json.loads(response.read()))


def backlog(queue: dict[str, object]) -> int:
    return sum(queue[field] for field in BACKLOG_FIELDS)


def progress_line(queues: dict[str, dict[str, object]], elapsed: float) -> str:
    remaining = {name: backlog(queue) for name, queue in queues.items() if backlog(queue)}
    largest_first = sorted(remaining.items(), key=lambda item: item[1], reverse=True)
    breakdown = ", ".join(f"{name} {count}" for name, count in largest_first)
    return (
        f"Catching up: {sum(remaining.values())} jobs remaining after {elapsed:.0f}s "
        f"({breakdown or 'confirming the queues stay empty'})"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--stop-file", type=Path, required=True, help="created when the load ends")
    parser.add_argument("--drain-timeout", type=float, default=1800)
    parser.add_argument("--interval", type=float, default=5)
    parser.add_argument("--stable-polls", type=int, default=3)
    parser.add_argument("--max-errors", type=int, default=12)
    parser.add_argument("--progress-interval", type=float, default=30)
    args = parser.parse_args()

    api_key = os.environ.get("IMMICH_API_KEY")
    if not api_key:
        print("Error: IMMICH_API_KEY is required.", file=sys.stderr)
        return 1

    url = args.url.rstrip("/")
    args.output_dir.mkdir(parents=True, exist_ok=True)

    load_end: float | None = None
    last_progress = 0.0
    empty_since: float | None = None
    empty_polls_after_load = 0
    consecutive_errors = 0
    peak_backlog: dict[str, int] = {}
    queues: dict[str, dict[str, object]] = {}
    status = ""
    detail = ""
    drained_at: float | None = None
    catch_up_seconds: float | None = None

    with open(args.output_dir / "queue-stats.jsonl", "w", encoding="utf-8") as stats:
        while not status:
            if load_end is None and args.stop_file.exists():
                load_end = args.stop_file.stat().st_mtime
                last_progress = time.time()
                # Flush progress so the wait does not look like a hang in CI logs.
                print(
                    "Load finished. Waiting for background jobs to catch up "
                    f"(limit {args.drain_timeout:g}s).",
                    flush=True,
                )

            polled_at = time.time()
            try:
                queues = fetch_queues(url, api_key, args.interval)
            except UnexpectedResponse as error:
                status, detail = "error", f"unexpected /api/queues response: {error}"
                stats.write(json.dumps({"time": timestamp(polled_at), "error": detail}) + "\n")
                break
            except (OSError, ValueError) as error:
                # URLError and timeouts are OSErrors; malformed JSON is a ValueError.
                detail = f"{type(error).__name__}: {error}"
                stats.write(json.dumps({"time": timestamp(polled_at), "error": detail}) + "\n")
                consecutive_errors += 1
                empty_since = None
                empty_polls_after_load = 0
                # A server busy with the load may stop answering, so only give up afterwards.
                if load_end is not None and consecutive_errors >= args.max_errors:
                    status = "error"
            else:
                consecutive_errors = 0
                stats.write(json.dumps({"time": timestamp(polled_at), "queues": queues}) + "\n")
                for name, queue in queues.items():
                    peak_backlog[name] = max(peak_backlog.get(name, 0), backlog(queue))

                if any(backlog(queue) for queue in queues.values()):
                    empty_since = None
                    empty_polls_after_load = 0
                else:
                    empty_since = empty_since if empty_since is not None else polled_at
                    if load_end is not None:
                        empty_polls_after_load += 1

                if empty_polls_after_load >= args.stable_polls:
                    status = "drained"
                    drained_at = empty_since
                    catch_up_seconds = round(max(0.0, empty_since - load_end), 1)
            stats.flush()

            if not status and load_end is not None and time.time() - load_end >= args.drain_timeout:
                status = "timeout"
            if not status and load_end is not None and time.time() - last_progress >= args.progress_interval:
                last_progress = time.time()
                elapsed = last_progress - load_end
                if consecutive_errors:
                    print(f"Catching up: latest poll failed after {elapsed:.0f}s ({detail})", flush=True)
                else:
                    print(progress_line(queues, elapsed), flush=True)
            if not status:
                time.sleep(max(0.0, polled_at + args.interval - time.time()))

    summary = {
        "status": status,
        "load_end": timestamp(load_end) if load_end is not None else None,
        "drained_at": timestamp(drained_at) if drained_at is not None else None,
        "catch_up_seconds": catch_up_seconds,
        "drain_timeout_seconds": args.drain_timeout,
        "peak_backlog": {name: peak for name, peak in peak_backlog.items() if peak},
        "failed": {name: queue["failed"] for name, queue in queues.items() if queue["failed"]},
        "remaining": {name: backlog(queue) for name, queue in queues.items() if backlog(queue)},
    }
    if status == "error":
        summary["error"] = detail
    (args.output_dir / "queue-summary.json").write_text(json.dumps(summary, indent=2) + "\n")

    if status == "drained":
        print(f"Background jobs caught up {catch_up_seconds} seconds after the load ended.")
    elif status == "timeout":
        print(
            f"::warning::Background jobs had not caught up after {args.drain_timeout:g} seconds; "
            f"remaining: {summary['remaining']}"
        )
    else:
        print(f"::warning::Queue tracking failed, so catch-up was not measured: {detail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
