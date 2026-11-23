#!/usr/bin/env python3
"""Export the CPU used by processes the Immich background worker started and that have exited.

ffmpeg and ffprobe usually run for well under a second, too briefly for
process-exporter to measure. When the worker collects a child's exit status, Linux
adds that child's whole CPU time to the worker's cutime and cstime, so those
counters measure every finished child exactly.

The worker also starts long-lived children, such as the exiftool perl processes
that Immich replaces after 500 tasks each, which process-exporter already measures
while they run. This exporter follows the worker's children every second and, when
one other than ffmpeg or ffprobe exits, records its CPU as last seen, so that

    ffmpeg CPU = finished children CPU - finished tracked children CPU

CPU a tracked child used after its last sample is counted as ffmpeg.
"""

from __future__ import annotations

import argparse
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

WORKER_COMM = "immich"
# Short-lived children, whose CPU is what the finished-children counters are for.
UNTRACKED_COMMS = {"ffmpeg", "ffprobe"}
TICKS = os.sysconf("SC_CLK_TCK")


def read_stat(proc: Path, pid: str) -> dict | None:
    try:
        stat = (proc / pid / "stat").read_text()
        comm = (proc / pid / "comm").read_text().strip()
    except OSError:
        return None
    # The command name in stat can contain spaces, so split after its closing parenthesis.
    fields = stat[stat.rindex(")") + 2 :].split()
    return {
        "comm": comm,
        "ppid": fields[1],
        "cpu": (int(fields[11]) + int(fields[12])) / TICKS,
        "children_cpu": (int(fields[13]) + int(fields[14])) / TICKS,
        "start": fields[19],
    }


class Tracker:
    def __init__(self, proc: Path) -> None:
        self.proc = proc
        self.lock = threading.Lock()
        self.up = 0
        self.finished = 0.0
        self.tracked: dict[str, float] = {}
        self._worker: tuple[str, str] | None = None
        self._children_cpu = 0.0
        self._children: dict[tuple[str, str], dict] = {}

    def sample(self) -> None:
        processes = {}
        for entry in self.proc.iterdir():
            if entry.name.isdigit():
                stat = read_stat(self.proc, entry.name)
                if stat:
                    processes[entry.name] = stat
        workers = [pid for pid, stat in processes.items() if stat["comm"] == WORKER_COMM]
        with self.lock:
            if len(workers) != 1:
                self.up = 0
                return
            pid = workers[0]
            worker = processes[pid]
            identity = (pid, worker["start"])
            if identity != self._worker:
                # A new worker starts its counters from zero, and the old worker's
                # children were never collected by it, so start afresh.
                self._worker = identity
                self._children_cpu = worker["children_cpu"]
                self._children = {}
            self.up = 1
            self.finished += max(0.0, worker["children_cpu"] - self._children_cpu)
            self._children_cpu = worker["children_cpu"]

            children = {
                (child, stat["start"]): stat for child, stat in processes.items() if stat["ppid"] == pid
            }
            for key, last in self._children.items():
                if key not in children and last["comm"] not in UNTRACKED_COMMS:
                    self.tracked[last["comm"]] = self.tracked.get(last["comm"], 0.0) + last["cpu"]
            self._children = children

    def render(self) -> str:
        with self.lock:
            lines = [
                "# HELP immich_worker_up Whether exactly one Immich worker process was found.",
                "# TYPE immich_worker_up gauge",
                f"immich_worker_up {self.up}",
                "# HELP immich_worker_finished_children_cpu_seconds_total CPU of all exited children of the worker.",
                "# TYPE immich_worker_finished_children_cpu_seconds_total counter",
                f"immich_worker_finished_children_cpu_seconds_total {self.finished:.3f}",
                "# HELP immich_worker_finished_tracked_children_cpu_seconds_total Last-seen CPU of exited "
                "children other than ffmpeg and ffprobe.",
                "# TYPE immich_worker_finished_tracked_children_cpu_seconds_total counter",
            ]
            lines += [
                f'immich_worker_finished_tracked_children_cpu_seconds_total{{comm="{comm}"}} {cpu:.3f}'
                for comm, cpu in sorted(self.tracked.items())
            ]
        return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--procfs", type=Path, default=Path("/proc"))
    parser.add_argument("--port", type=int, default=9257)
    parser.add_argument("--interval", type=float, default=1.0)
    args = parser.parse_args()

    tracker = Tracker(args.procfs)

    def run() -> None:
        while True:
            started = time.monotonic()
            try:
                tracker.sample()
            except OSError as error:
                print(f"Sampling failed: {error}", flush=True)
            time.sleep(max(0.0, args.interval - (time.monotonic() - started)))

    threading.Thread(target=run, daemon=True).start()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path != "/metrics":
                self.send_error(404)
                return
            body = tracker.render().encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_: object) -> None:
            pass

    print(f"Serving worker child CPU on port {args.port}", flush=True)
    ThreadingHTTPServer(("", args.port), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
