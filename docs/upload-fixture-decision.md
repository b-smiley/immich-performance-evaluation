# Upload Fixtures

## Scope and Goal

The load test needs uploads that vary along two factors from the test plan: file size and resolution. The original proof of concept uploaded one 673-byte JPEG and one 7KB MP4, and every upload had identical bytes. Immich deduplicates uploads by checksum, so after the first upload of each file the server returned `duplicate` and skipped thumbnailing, metadata extraction, and transcoding. The measurements therefore described the duplicate check, not real ingestion.

## Factors

Size ranges differ between photos and videos. MB means 10^6 bytes.

| Size level | Photo | Video |
|---|---|---|
| `small` | 0–1MB | 1–10MB |
| `medium` | 1–10MB | 10–100MB |
| `large` | 10–50MB | 100–1000MB |

Resolution levels are `480p` (854×480), `1080p` (1920×1080), and `4k` (3840×2160).

One test run uses one combination, selected with `SIZE_LEVEL` and `RESOLUTION`. `PHOTO_RATIO` controls the workload mix.

## Solution - Seeded Synthetic Fixtures

`scripts/generate_fixtures.py` generates a pool of files for the selected combination: 10 files per kind at `small`, 5 at `medium`, and 3 at `large` (override with `POOL_SIZE`). Each file's target size is drawn uniformly from the level's range using a seeded random number generator (`FIXTURE_SEED`, default 533). The same seed always produces byte-identical files and an identical `manifest.json`. For this reason x264 runs single-threaded, since its multi-threaded rate control is not reproducible; files in a pool are encoded in parallel instead.

The content is synthetic (ffmpeg's `testsrc2` pattern plus seeded noise). Synthetic content avoids licensing and download steps, and the noise stops the encoders from compressing frames away, which makes file size controllable.

- **Videos** are H.264 MP4 at a fixed bitrate per resolution, modelled on phone recordings: 2.5Mb/s at 480p, 16Mb/s at 1080p, and 50Mb/s at 4K. Size is set by clip length, so size and duration are linked by design. A 1GB clip is about 53 minutes at 480p and 2.7 minutes at 4K.
- **Photos** use real encoder settings only, with no padding. The generator chooses JPEG for small targets, then 8-bit PNG, then 16-bit PNG, and searches the JPEG quality, noise strength, or proportion of noisy rows until the file size is within about 3% of the target.

### Combinations that cannot be produced

A photo cannot exceed its uncompressed size (width × height × 6 bytes at 16 bits per channel), and a video cannot be shorter than one frame. The generator measures these limits on each run and samples only inside the reachable range.

| Combination | Result |
|---|---|
| Photo 480p × large (10–50MB) | **Infeasible** (max ~2.4MB). The run is refused unless `PHOTO_RATIO=0`. |
| Photo 480p × medium (1–10MB) | Clamped to ~1–2.4MB |
| Photo 1080p × large (10–50MB) | Clamped to ~10–12.3MB |
| Video 4K × small (1–10MB) | Clamped to ~2.7–10MB (one noisy 4K frame is ~2.7MB) |

Each manifest entry records `range_clamped` and the `effective_range_bytes` actually used. The photo design is therefore not a full 3×3 grid, and the analysis must handle the missing combination.

## Solution - Unique Uploads

k6 changes every upload by inserting a 16-byte random marker in a form each format's parsers accept:

- MP4: a top-level `free` box appended to the file
- PNG: a `tEXt` chunk (with a valid CRC) before `IEND`
- JPEG: a `COM` segment after `SOI`

Plain trailing bytes were rejected because ffmpeg treats data after a PNG's `IEND` as a second, corrupt image. Each upload has a new checksum, so Immich processes it fully. The `asset created (not duplicate)` check and the `duplicate_uploads` counter confirm this in every run.

## Client Memory and Server Disk

k6 can only upload a body held fully in memory. Fixtures are opened through `k6/experimental/fs`, which loads each file once and shares it across virtual users. Each upload still needs about three copies of the file per virtual user. `scripts/preflight.py memory` refuses a run when the pool plus `VUS × largest file × 3` exceeds 75% of the memory available to Docker (override with `K6_MEMORY_BUDGET_BYTES`). With 1GB videos, the 16GB ARM client fits about 4–5 virtual users.

Large uploads also fill the server's disk quickly, since Immich stores originals plus thumbnails and transcodes. The workflow first removes preinstalled toolchains from both runners. `scripts/preflight.py disk` then estimates the bytes written as 2 × min(VUS × seconds × mean size, link bandwidth × seconds), or 2 × `ITERATIONS` × mean size, and refuses the run when that exceeds 90% of free disk. `ITERATIONS` (a fixed number of uploads) is optional at every level. The link bandwidth assumption (`UPLOAD_MBPS`, default 1000) should be updated from the feasibility workflow's iperf3 result.

## Alternatives Considered

- **Padding files to the target size** with metadata. This would fill every combination, but processing cost would not grow with the padded bytes, mixing the size factor with an artefact.
- **A pool of distinct files instead of per-upload markers.** Avoids modifying uploads, but needs many large files on disk and still repeats once the pool is exhausted.
- **Deleting assets after each upload.** Also defeats deduplication, but adds delete traffic and background work to the measurements.
- **Real sample media.** More realistic content for the ML services, but not reproducible without a download step and licence checks.

## Threats to Validity

- Synthetic noise is harder to compress than typical photos, and its content is meaningless to Immich's ML models.
- Video size and duration are linked by design.
- At the large level, concurrency is limited by client memory.
- Tailscale bandwidth between runners may cap large-upload throughput; check it with the feasibility workflow before interpreting those runs.
- With Immich's default transcode policy (`required`), H.264 MP4 uploads are not transcoded, so video conversion load does not appear unless the policy changes.

# AI Usage Statement

- Validation: Ran various tests with different file sizes and concurrent user loads.  Reviewed performance through Grafana and noted that the behaviour matches what the AI predicted.  Also discussed various limitations with the current factor set up with the team and made changes accordingly.
- Input prompts: Asked the agent to explain the test setup, then to plan and implement varying fixture sizes and resolutions. Team decisions (size ranges, resolutions, infeasible-combination handling, uniqueness approach, memory and disk limits) were made through the agent's planning questionnaire.
- Output prompts: The agent produced the fixture generator, k6 changes, preflight checks, workflow inputs, and this document's first draft.
- Tool identification: Claude Code (VS Code extension), model Claude Opus 5.5 (`claude-opus-5-5`), used for planning, implementation, validation, and drafting this document.
