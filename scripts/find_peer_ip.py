#!/usr/bin/env python3
"""Find a Tailscale peer's IPv4 address from status JSON."""

import json
import sys


def main() -> None:
    status = json.load(open(sys.argv[1], encoding="utf-8"))
    wanted = sys.argv[2].lower()
    peers = status.get("Peer", {}).values()
    for peer in peers:
        names = [
            str(peer.get("HostName", "")).lower(),
            str(peer.get("DNSName", "")).lower().rstrip("."),
        ]
        if wanted in names or any(name.startswith(wanted + ".") for name in names):
            for address in peer.get("TailscaleIPs", []):
                if ":" not in address:
                    print(address)
                    return
    raise SystemExit(f"peer not found: {sys.argv[2]}")


if __name__ == "__main__":
    main()
