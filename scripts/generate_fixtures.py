#!/usr/bin/env python3
"""Generate deterministic media fixtures using ffmpeg."""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("data/fixtures"))
    args = parser.parse_args()

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise SystemExit("ffmpeg is required to generate photo/video fixtures")

    args.output.mkdir(parents=True, exist_ok=True)
    photo = args.output / "photo.jpg"
    video = args.output / "video.mp4"

    subprocess.run(
        [
            ffmpeg, "-y", "-f", "lavfi", "-i", "color=c=blue:s=320x240",
            "-frames:v", "1", str(photo),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    subprocess.run(
        [
            ffmpeg, "-y", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=10",
            "-t", "1", "-pix_fmt", "yuv420p", str(video),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    print(f"Created {photo} and {video}")


if __name__ == "__main__":
    main()
