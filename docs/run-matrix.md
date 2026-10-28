# Immich experiment run plan

## Purpose and factors

The study screens six factors in Phase 1, then examines workload composition
and concurrent uploads in Phase 2. Phase 1 deliberately includes each factor's
highest proposed level: an effect not visible at low levels is not grounds for
excluding that factor. The complete Phase 1 factorial over all proposed factor
levels would require 972 combinations (3x4x3x3x3x3). A full two-level design of
six factors has 64 combinations (2^6); the selected 8-run design is a 1/8
fraction of that two-level design.

| Factor | Phase 1 low (-1) | Phase 1 high (+1) | Phase 2 |
|---|---|---|---|
| A: Concurrent users | 1 | 25 | Held constant (value to be confirmed); requires an independent user-count control |
| B: Concurrent uploads | 1 | 1000 | 1, 25, 100, 1000 |
| C: Workload composition | Photo-only (`PHOTO_RATIO=1.0`) | Video-only (`PHOTO_RATIO=0.0`) | Photo-only, video-only, mixed (`PHOTO_RATIO=0.5`) |
| D: File size | < 50 MB | < 5 GB | Fixed at the selected Phase 1 level |
| E: Asset quality | Original | 4k | Fixed at the selected Phase 1 level |
| F: CPU cores | 1 | 4 | Fixed at the selected Phase 1 level |

Phase 1 uses the endpoints of the proposed levels. The middle levels (5
concurrent users, 25 and 100 uploads, mixed workload, and intermediate sizes,
quality, and core counts) are not represented in this fraction. Phase 2 focuses
on all three workload compositions and all four upload levels, as specified in
the proposal; it does not vary the other four factors.

The Phase 1 factors A and B are distinct in the design. The current load-test
harness has only one concurrency control (`VUS`), so it cannot independently
set concurrent users and concurrent uploads. Execution of this matrix requires
an operational definition and separate control for those factors; do not map
both columns to `VUS` and claim they were independently tested.

## Phase 1: 8-run fractional factorial, three repeats

Use the regular two-level `2^(6-3)` design with A, B, and C as the basic
factors, and generators:

```text
D = AB
E = AC
F = BC
```

In coded levels, multiplication means multiplying the signs. The defining
relation is:

```text
I = ABD = ACE = BCF = DEF = BCDE = ACDF = ABEF
```

The shortest defining words have length three, so this is a **Resolution III**
design. Main effects are aliased with two-factor interactions (for example,
`A = BD = CE = ...`); the design cannot distinguish those effects. Some
two-factor interactions are also aliased with each other. Treat main-effect
results as screening evidence, not proof that a factor acts independently.
The eight distinct settings are:

| Design row | A | B | C | D=AB | E=AC | F=BC |
|---:|:---:|:---:|:---:|:---:|:---:|:---:|
| 1 | - | - | - | + | + | + |
| 2 | - | - | + | + | - | - |
| 3 | - | + | - | - | + | - |
| 4 | - | + | + | - | - | + |
| 5 | + | - | - | - | - | + |
| 6 | + | - | + | - | + | - |
| 7 | + | + | - | + | - | - |
| 8 | + | + | + | + | + | + |

Run each setting three times (24 measured runs total). Randomize the execution
order of the 24 runs before testing and record that order and the actual
settings. Do not treat the three repeats as three additional factor settings.

**Upgrade option:** a `2^(6-2)` 16-run fraction can use `E=ABC` and `F=ABD`.
Its defining relation is `I=ABCE=ABDF=CDEF`, giving Resolution IV. Main
effects are not aliased with two-factor interactions, although two-factor
interactions remain aliased with each other. This doubles the unique settings
from 8 to 16 (48 runs with three repeats) and provides stronger interaction
separation than the selected Resolution III screen.

## Phase 2: 36 randomized runs

Cross the three workload compositions (photo-only, video-only, mixed) with the
four concurrent-upload levels (1, 25, 100, 1000), with three replicates per
combination: 12 conditions and 36 runs total. Use the fixed randomized order
in [`phase2-run-order.csv`](phase2-run-order.csv). Regenerate it with:

```bash
python3 scripts/generate_phase2_run_order.py
```

The generator uses Python's `random.Random` with fixed seed `5332026`; it
shuffles the 36 individual runs, not condition-sized blocks. Keep the checked-in
CSV as the run record and follow its `run_order` sequence. Map each `concurrent_uploads` value to `VUS` in
`scripts/run-load-test.sh`, and set `PHOTO_RATIO` from the row (`1.0`
photo-only, `0.0` video-only, `0.5` mixed). Keep concurrent users constant at a
value selected before testing; the current harness cannot independently enforce
that while varying `VUS`, so resolve this execution gap before treating Phase 2
as a controlled test of upload concurrency alone.

## Procedure for each run

1. Apply the run's factor settings and clean/reset Immich to the same defined
   starting state. Record the reset procedure and verify the prior run's
   background-job backlog has cleared.
2. Perform a small, consistent set of warm-up uploads before the measurement
   window. Do not include them in the reported load-test results; allow their
   processing backlog to clear before measurement.
3. Begin result collection, ramp load to the target concurrency, and hold the
   target load for five minutes. Continue recording system metrics after load
   generation stops until the background-job backlog clears.
4. Save each run's k6 output, monitoring data, configuration, run order, start
   and end times, and any errors under a distinct results directory. Do not
   overwrite a prior run's artifacts.

The current `scripts/run-load-test.sh` passes a constant `VUS` and `DURATION`
to k6; it does not implement a ramping profile or provide an automated
backlog-clear signal. Its single `VUS` control also cannot independently vary
concurrent users and concurrent uploads. The procedure above therefore
describes the required protocol, but concurrency controls, ramping, and the
measurement/drain boundaries need operational support before execution.

## Open questions

- What exact database, asset, and job-queue reset procedure defines a clean
  Immich start while preserving comparable system configuration?
- How will the load generator implement and timestamp the ramp, five-minute
  hold, and measurement window? The current k6 script only accepts fixed
  concurrency and duration.
- What are the operational definitions of concurrent users versus concurrent
  uploads, and how will the harness control them independently? The current
  script exposes only one `VUS` concurrency setting.
- What fixed concurrent-user value should Phase 2 use while upload concurrency
  varies?
- What backlog metric and threshold determine that background processing has
  cleared, and how will metric collection continue through the drain period?
- Which fixture-generation or acquisition method will provide the required
  file-size and asset-quality levels? The current load test uses fixed photo
  and video fixtures.
- How will CPU core limits be set and verified consistently for each Phase 1
  run?
- How should the randomized order of Phase 1's 24 repeated runs be generated
  and preserved?
- Are the proposed endpoint levels (including < 5 GB files) feasible for the
  test environment and the existing load-test client?
- Asset quality is a server-side transcoding setting. Do our fixtures and transcode policy let "4k" vs "original" differ?
- Is the 50/50 mix by upload count or by bytes?
- How do we verify uploads are processed and not skipped as duplicates of the same fixture?
