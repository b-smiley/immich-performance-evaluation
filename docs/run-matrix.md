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
| D: File size | Small (photo 0–1 MB; video 1–10 MB) | Large (photo 10–50 MB; video 100–1000 MB) | Fixed at the selected Phase 1 level |
| E: Resolution | 480p | 4k | Fixed at the selected Phase 1 level |
| F: CPU cores | 1 | 4 | Fixed at the selected Phase 1 level |

Phase 1 uses the endpoints of the proposed levels. The middle levels (5
concurrent users, 25 and 100 uploads, mixed workload, medium size (photo 1–10
MB; video 10–100 MB), 1080p, and intermediate core counts) are not represented
in this fraction. Size ranges are
per file type; see [the fixture decision](upload-fixture-decision.md) for
range definitions. Not all size-resolution cells are generatable: 480p large
photos are infeasible, 1080p large photos are clamped to about 10–12 MB, and
4k small videos start at about 2.7 MB (a few frames). Phase 2 focuses on all
three workload compositions and all four upload levels, as specified in the
proposal; it does not vary the other four factors.

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

## Feasibility of the Phase 1 runs

These are estimates, not run results. The table compares two provisional
readings because the harness has one `VUS` control: `VUS=A` (users) and
`VUS=B` (uploads). Neither reading tests A and B independently. Memory
estimates assume 16,000 MB of Docker memory (decimal MB), giving a
`0.75 × 16,000 = 12,000 MB` budget. Each run uses its workload's fixture pool.
Shared pool bytes use nominal range midpoints and pool sizes (10/5/3); the
largest fixture uses the nominal upper bound. These are conservative estimates;
the generated manifest determines the actual preflight values.

| Size | Photo pool memory ceiling | Video pool memory ceiling |
|---|---|---|
| Small | `floor((12,000 - 10 × 0.5) / (3 × 1))` = 3,998 VUS | `floor((12,000 - 10 × 5.5) / (3 × 10))` = 398 VUS |
| Medium | `floor((12,000 - 5 × 5.5) / (3 × 10))` = 399 VUS | `floor((12,000 - 5 × 55) / (3 × 100))` = 39 VUS |
| Large | `floor((12,000 - 3 × 30) / (3 × 50))` = 79 VUS | `floor((12,000 - 3 × 550) / (3 × 1,000))` = 3 VUS |

For disk, the five-minute estimate is
`2 × min(VUS × 300 × mean file size, 1,000 / 8 × 1 MB × 300)` and must be no
more than 90% of free upload-disk space. The thresholds below are the minimum
free space needed; actual free space is **to be measured**. The disk preflight
checks the Immich upload path (when local), not the load-generator disk.
The ceilings above are memory-only; a combined maximum VUS cannot be stated
until free upload-disk space is measured.

| Run | Phase 1 settings (A/B, workload, size/resolution, CPU) | `VUS=A` estimate | `VUS=B` estimate |
|---:|---|---|---|
| 1 | 1/1, photo-only, large/4k, 4 | Photo pool: 240/12,000 MB; disk needs ≥20,000 MB free. | Same as A (B=1). |
| 2 | 1/1, video-only, large/480p, 1 | Video pool: 4,650/12,000 MB; disk needs ≥83,334 MB free. | Same as A (B=1). |
| 3 | 1/1000, photo-only, small/4k, 1 | Photo pool: 8/12,000 MB; disk needs ≥334 MB free. | Photo pool: 3,005/12,000 MB (within budget); disk needs ≥83,334 MB free. |
| 4 | 1/1000, video-only, small/480p, 4 | Skipped: B=1000 uploads are over the memory budget (30,055 / 12,000 MB). The `VUS=A` reading alone would fit (85 / 12,000 MB) but does not test B=1000. | Infeasible, skipped (over memory budget). |
| 5 | 25/1, photo-only, small/480p, 4 | Photo pool: 80/12,000 MB; disk needs ≥8,334 MB free. | Photo pool: 8/12,000 MB; disk needs ≥334 MB free. |
| 6 | 25/1, video-only, small/4k, 1 | Video pool: 805/12,000 MB; disk needs ≥83,334 MB free. | Video pool: 85/12,000 MB; disk needs ≥3,667 MB free. |
| 7 | 25/1000, photo-only, large/480p, 1 | Infeasible, skipped (fixture cannot be generated). | Infeasible, skipped (fixture cannot be generated). |
| 8 | 25/1000, video-only, large/4k, 4 | Infeasible, skipped (over memory budget). | Infeasible, skipped (over memory budget). |

Disk thresholds assume a five-minute hold, 1,000 Mb/s, and midpoint means of
0.5/5.5 MB (small photo/video) and 30/550 MB (large photo/video). Rows pass
disk preflight only if measured free space meets the stated threshold. The
run table is consistent with `D=AB`, `E=AC`, and `F=BC`. The harness
must gain separate A/B controls before the matrix can test both factors.

Runs 7 and 8 are infeasible and skipped under both VUS readings. Run 4 is
skipped because its planned B=1000 uploads are over the memory budget. Skipped
runs are not executed. With runs 4, 7 and 8 skipped, the remaining five
settings no longer form the full fraction, so main effects are confounded more
heavily than the aliasing above describes.
Memory is within budget under both readings for runs 1, 2, 3, 5, and 6.

Run each feasible setting three times (up to 15 measured runs total).
Randomize the execution order of the feasible runs before testing and record
that order and the actual settings. Do not treat the three repeats as three
additional factor settings.

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

## Machine learning scope

Machine learning is disabled through `config/immich-config.json`, and the
machine-learning container is not part of the stack. Background processing in
these runs therefore covers non-ML jobs only. Earlier runs are not comparable
with later ones because they included failing ML jobs and an idle ML container.

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

Report throughput, p95 upload latency, and error rate.

## Open questions

- What exact database, asset, and job-queue reset procedure defines a clean
  Immich start while preserving comparable system configuration?
- How will the load generator implement and timestamp the ramp, five-minute
  hold, and measurement window? The current k6 script only accepts fixed
  concurrency and duration.
- What are the operational definitions of concurrent users versus concurrent
  uploads, and how will the harness control them independently? The current
  script exposes only one `VUS` setting.
- What fixed concurrent-user value should Phase 2 use while upload concurrency
  varies?
- What backlog metric and threshold determine that background processing has
  cleared, and how will metric collection continue through the drain period?
- What is the actual free disk space on the runners? The estimated disk
  thresholds (about 83 GB for some runs) are unverified and must be checked.
- How will fixtures be pregenerated instead of generated on every run, and
  where will they be stored? Large videos can take up to about 30 minutes to
  generate.
  See [the fixture decision](upload-fixture-decision.md) for fixture details.
- How will CPU core limits be set and verified consistently for each Phase 1
  run?
- How should the randomized order of Phase 1's 15 repeated runs be generated
  and preserved?
- How will throughput, p95 upload latency, and error rate be defined and
  summarized?
