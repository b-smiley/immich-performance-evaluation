#!/usr/bin/env python3
"""Generate deterministic, size- and resolution-controlled media fixtures.

Each run generates one fixture pool for a single (size level, resolution)
combination and writes ``manifest.json`` describing every file. Target sizes
are drawn from a seeded RNG inside the level's range, so the same seed always
produces the same pool.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

GENERATOR_VERSION = 1
MB = 1_000_000
FPS = 30
VIDEO_NOISE = 25

RESOLUTIONS = {"480p": (854, 480), "1080p": (1920, 1080), "4k": (3840, 2160)}
VIDEO_BITRATES = {"480p": 2_500_000, "1080p": 16_000_000, "4k": 50_000_000}
SIZE_RANGES = {
    "photo": {"small": (0, 1 * MB), "medium": (1 * MB, 10 * MB), "large": (10 * MB, 50 * MB)},
    "video": {"small": (1 * MB, 10 * MB), "medium": (10 * MB, 100 * MB), "large": (100 * MB, 1000 * MB)},
}
POOL_SIZES = {"small": 10, "medium": 5, "large": 3}
CONTENT_TYPES = {"jpg": "image/jpeg", "png": "image/png", "mp4": "video/mp4"}

# Keep sampled targets away from the range edges so encoder variance cannot
# push a file into the neighbouring size level.
EDGE_MARGIN = 0.03
SIZE_TOLERANCE = 0.03
CLAMP_THRESHOLD = 0.05


class InfeasibleError(Exception):
    """Raised when a size level cannot be reached at a resolution."""


def run_ffmpeg(ffmpeg: str, args: list[str], stdin: bytes | None = None) -> bytes:
    result = subprocess.run(
        [ffmpeg, "-v", "error", "-y", *args],
        input=stdin,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout


def file_seed(seed: int, kind: str, resolution: str, size_level: str, index: int) -> int:
    return random.Random(f"{seed}:{kind}:{resolution}:{size_level}:{index}").randrange(2**31)


def sample_targets(
    seed: int, kind: str, resolution: str, size_level: str, low: float, high: float, count: int
) -> list[int]:
    rng = random.Random(f"{seed}:{kind}:{resolution}:{size_level}")
    margin = (high - low) * EDGE_MARGIN
    return [round(rng.uniform(low + margin, high - margin)) for _ in range(count)]


class PhotoEncoder:
    """Encode photos as JPEG for small targets and PNG for large ones."""

    def __init__(self, ffmpeg: str, resolution: str, work_dir: Path) -> None:
        self.ffmpeg = ffmpeg
        self.width, self.height = RESOLUTIONS[resolution]
        self.work_dir = work_dir

    def jpeg(self, output: Path, quality: int, noise: int, seed: int) -> int:
        source = (
            f"testsrc2=s={self.width}x{self.height},"
            f"noise=alls={noise}:allf=u:all_seed={seed}"
        )
        run_ffmpeg(self.ffmpeg, ["-f", "lavfi", "-i", source, "-frames:v", "1",
                                 "-q:v", str(quality), str(output)])
        return output.stat().st_size

    def reachable(self) -> tuple[int, int]:
        probe = self.work_dir / ".probe.jpg"
        low = self.jpeg(probe, 31, 0, 0)
        probe.unlink()
        # Fully random 16-bit rows are incompressible.
        return low, round(self.width * self.height * 6 * 0.99)

    def encode(self, output_stem: Path, target: int, seed: int) -> tuple[Path, dict[str, object]]:
        jpeg_path = output_stem.with_suffix(".jpg")
        if target <= self.jpeg(jpeg_path, 2, 100, seed):
            return jpeg_path, self._fit_jpeg(jpeg_path, target, seed)
        jpeg_path.unlink()
        bit_depth = 8 if target <= self.width * self.height * 3 * 0.97 else 16
        png_path = output_stem.with_suffix(".png")
        return png_path, self._fit_png(png_path, target, seed, bit_depth)

    def _fit_jpeg(self, output: Path, target: int, seed: int) -> dict[str, object]:
        # Size grows with noise at the best quality, and shrinks as the
        # quantiser rises at zero noise; search whichever axis brackets target.
        if target >= self.jpeg(output, 2, 0, seed):
            axis, low, high = "noise", 0, 100
            size_of = lambda value: self.jpeg(output, 2, value, seed)
        else:
            axis, low, high = "quality", 2, 31
            size_of = lambda value: -self.jpeg(output, value, 0, seed)
            target = -target
        best = None
        while low <= high:
            middle = (low + high) // 2
            size = size_of(middle)
            if best is None or abs(size - target) < abs(best[1] - target):
                best = (middle, size)
            if size < target:
                low = middle + 1
            else:
                high = middle - 1
        value = best[0]
        quality, noise = (2, value) if axis == "noise" else (value, 0)
        self.jpeg(output, quality, noise, seed)
        return {"format": "jpg", "jpeg_quality": quality, "noise": noise, "bit_depth": 8}

    def _fit_png(self, output: Path, target: int, seed: int, bit_depth: int) -> dict[str, object]:
        pixel_format = "rgb24" if bit_depth == 8 else "rgb48be"
        base = run_ffmpeg(self.ffmpeg, [
            "-f", "lavfi", "-i", f"testsrc2=s={self.width}x{self.height}",
            "-frames:v", "1", "-pix_fmt", pixel_format, "-f", "rawvideo", "-",
        ])
        row_bytes = len(base) // self.height
        rng = random.Random(seed)
        noise = rng.randbytes(len(base))
        row_order = rng.sample(range(self.height), self.height)

        def size_with(rows: int) -> int:
            frame = bytearray(base)
            for row in row_order[:rows]:
                start = row * row_bytes
                frame[start:start + row_bytes] = noise[start:start + row_bytes]
            run_ffmpeg(self.ffmpeg, [
                "-f", "rawvideo", "-pix_fmt", pixel_format,
                "-s", f"{self.width}x{self.height}", "-i", "-",
                "-frames:v", "1", str(output),
            ], stdin=bytes(frame))
            return output.stat().st_size

        # PNG size is close to linear in the number of random rows, so use
        # interpolation search between the bracketing row counts.
        low, high = (0, size_with(0)), (self.height, size_with(self.height))
        best = min(low, high, key=lambda point: abs(point[1] - target))
        for _ in range(8):
            if abs(best[1] - target) <= target * SIZE_TOLERANCE or high[0] - low[0] <= 1:
                break
            fraction = (target - low[1]) / max(high[1] - low[1], 1)
            rows = min(max(low[0] + round(fraction * (high[0] - low[0])), low[0] + 1), high[0] - 1)
            point = (rows, size_with(rows))
            if abs(point[1] - target) < abs(best[1] - target):
                best = point
            if point[1] < target:
                low = point
            else:
                high = point
        size_with(best[0])
        return {
            "format": "png",
            "bit_depth": bit_depth,
            "noise_rows": best[0],
            "noise_fraction": round(best[0] / self.height, 4),
        }


class VideoEncoder:
    """Encode H.264 MP4 at a fixed bitrate; duration controls the size."""

    def __init__(self, ffmpeg: str, resolution: str, work_dir: Path) -> None:
        self.ffmpeg = ffmpeg
        self.width, self.height = RESOLUTIONS[resolution]
        self.bitrate = VIDEO_BITRATES[resolution]
        self.work_dir = work_dir

    def mp4(self, output: Path, frames: int, seed: int) -> int:
        source = (
            f"testsrc2=s={self.width}x{self.height}:r={FPS},"
            f"noise=alls={VIDEO_NOISE}:allf=t+u:all_seed={seed}"
        )
        run_ffmpeg(self.ffmpeg, [
            "-f", "lavfi", "-i", source, "-frames:v", str(frames),
            # Multi-threaded x264 rate control is not reproducible; files are
            # encoded in parallel instead (see generate_pool).
            "-c:v", "libx264", "-preset", "veryfast", "-threads", "1",
            "-b:v", str(self.bitrate), "-maxrate", str(self.bitrate),
            "-bufsize", str(self.bitrate), "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", str(output),
        ])
        return output.stat().st_size

    def reachable(self) -> tuple[int, int]:
        probe = self.work_dir / ".probe.mp4"
        low = self.mp4(probe, 1, 0)
        probe.unlink()
        return low, sys.maxsize

    def encode(self, output_stem: Path, target: int, seed: int) -> tuple[Path, dict[str, object]]:
        output = output_stem.with_suffix(".mp4")
        frames = max(1, round(target * 8 / self.bitrate * FPS))
        for _ in range(4):
            size = self.mp4(output, frames, seed)
            if abs(size - target) <= target * SIZE_TOLERANCE:
                break
            frames = max(1, round(frames * target / size))
        return output, {
            "format": "mp4",
            "bitrate": self.bitrate,
            "fps": FPS,
            "frames": frames,
            "duration": round(frames / FPS, 3),
        }


def effective_range(kind: str, size_level: str, reachable: tuple[int, int]) -> tuple[int, int, bool]:
    low, high = SIZE_RANGES[kind][size_level]
    effective_low, effective_high = max(low, reachable[0]), min(high, reachable[1])
    if effective_low >= effective_high:
        raise InfeasibleError(
            f"{kind} fixtures at size level '{size_level}' ({low / MB:g}-{high / MB:g}MB) "
            f"cannot be produced at this resolution (reachable "
            f"{reachable[0] / MB:.2f}-{reachable[1] / MB:.2f}MB)."
        )
    # Ignore trivial losses such as a 0-byte floor becoming the smallest JPEG.
    clamped = (effective_high - effective_low) < (high - low) * (1 - CLAMP_THRESHOLD)
    return effective_low, effective_high, clamped


def generate_pool(
    ffmpeg: str,
    kind: str,
    size_level: str,
    resolution: str,
    seed: int,
    count: int,
    output_dir: Path,
    cached: dict[str, dict[str, object]],
) -> list[dict[str, object]]:
    encoder_type = PhotoEncoder if kind == "photo" else VideoEncoder
    encoder = encoder_type(ffmpeg, resolution, output_dir)
    low, high, clamped = effective_range(kind, size_level, encoder.reachable())
    targets = sample_targets(seed, kind, resolution, size_level, low, high, count)
    nominal_low, nominal_high = SIZE_RANGES[kind][size_level]
    width, height = RESOLUTIONS[resolution]

    def build(index: int, target: int) -> dict[str, object]:
        stem = f"{kind}-{resolution}-{size_level}-s{seed}-{index:02d}"
        spec = {
            "generator_version": GENERATOR_VERSION,
            "kind": kind,
            "resolution": resolution,
            "size_level": size_level,
            "seed": seed,
            "index": index,
            "target_bytes": target,
        }
        previous = cached.get(stem)
        if previous and all(previous.get(key) == value for key, value in spec.items()):
            path = output_dir / str(previous["file"])
            if path.is_file() and path.stat().st_size == previous["bytes"]:
                print(f"Reusing {path.name}", flush=True)
                return previous

        print(f"Generating {stem} (target {target / MB:.2f}MB)", flush=True)
        path, details = encoder.encode(output_dir / stem, target, file_seed(seed, kind, resolution, size_level, index))
        size = path.stat().st_size
        if not nominal_low <= size < nominal_high:
            raise SystemExit(
                f"{path.name} is {size / MB:.2f}MB, outside the {size_level} range "
                f"({nominal_low / MB:g}-{nominal_high / MB:g}MB)."
            )
        return {
            **spec,
            "id": stem,
            "file": path.name,
            "content_type": CONTENT_TYPES[path.suffix[1:]],
            "bytes": size,
            "width": width,
            "height": height,
            "range_bytes": [nominal_low, nominal_high],
            "effective_range_bytes": [low, high],
            "range_clamped": clamped,
            **details,
        }

    with ThreadPoolExecutor(max_workers=os.cpu_count() or 1) as executor:
        return list(executor.map(build, range(len(targets)), targets))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("data/fixtures"))
    parser.add_argument("--size-level", choices=list(POOL_SIZES), default="small")
    parser.add_argument("--resolution", choices=list(RESOLUTIONS), default="1080p")
    parser.add_argument("--kinds", choices=["photo", "video", "both"], default="both")
    parser.add_argument("--seed", type=int, default=533)
    parser.add_argument("--pool-size", type=int, help="files per kind (default depends on size level)")
    args = parser.parse_args()

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise SystemExit("ffmpeg is required to generate photo/video fixtures")

    args.output.mkdir(parents=True, exist_ok=True)
    manifest_path = args.output / "manifest.json"
    cached: dict[str, dict[str, object]] = {}
    if manifest_path.is_file():
        cached = {entry["id"]: entry for entry in json.loads(manifest_path.read_text())["files"]}

    kinds = ["photo", "video"] if args.kinds == "both" else [args.kinds]
    count = args.pool_size or POOL_SIZES[args.size_level]
    files = []
    try:
        for kind in kinds:
            files += generate_pool(ffmpeg, kind, args.size_level, args.resolution,
                                   args.seed, count, args.output, cached)
    except InfeasibleError as error:
        raise SystemExit(f"Error: {error} Use PHOTO_RATIO=0 for a video-only run.")

    # Remove fixtures from earlier selections so the directory stays bounded.
    kept = {entry["file"] for entry in files}
    for entry in cached.values():
        if entry["file"] not in kept:
            (args.output / str(entry["file"])).unlink(missing_ok=True)

    manifest = {
        "generator_version": GENERATOR_VERSION,
        "size_level": args.size_level,
        "resolution": args.resolution,
        "kinds": kinds,
        "seed": args.seed,
        "files": files,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    total = sum(int(entry["bytes"]) for entry in files)
    print(f"Wrote {len(files)} fixtures ({total / MB:.1f}MB) and {manifest_path}")


if __name__ == "__main__":
    main()
