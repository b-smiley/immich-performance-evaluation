#!/usr/bin/env python3
"""Wait for one authenticated-by-network completion request."""

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class DoneHandler(BaseHTTPRequestHandler):
    output: Path

    def do_POST(self) -> None:
        if self.path != "/done":
            self.send_error(404)
            return
        self.output.touch()
        self.send_response(204)
        self.end_headers()
        self.server.shutdown()

    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    DoneHandler.output = args.output
    ThreadingHTTPServer(("0.0.0.0", args.port), DoneHandler).serve_forever()


if __name__ == "__main__":
    main()
