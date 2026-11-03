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

The Phase 1 factors A and B are distinct in the design, and the harness sets
them separately:

- **Concurrent uploads (`CONCURRENT_UPLOADS`)** is the total number of uploads in
  flight, which is the k6 virtual user count. With `THINK_TIME_SECONDS=0`, the
  default, each virtual user starts its next upload as soon as the last one
  finishes.
- **Concurrent users (`USERS`)** is the number of Immich accounts those uploads
  rotate through. For example, 25 users with 1 upload means one upload at a time,
  cycling evenly across 25 accounts. Users only upload; they do not browse.

Runs from before these controls are not comparable with later ones. Earlier runs
paused for 1 second after each upload, so far fewer uploads were in flight than
their `VUS` setting suggests.

### Feasible upload levels

k6 holds each in-flight file in memory, so `scripts/preflight.py` refuses runs
that do not fit. This table applies its limit of about 3x the largest possible
file per upload to the 12,537 MB budget seen on the client runner. It uses each
size level's upper bound, so actual fixtures may fit slightly more.

| Size level | Workload | 1 | 25 | 100 | 1000 |
|---|---|:---:|:---:|:---:|:---:|
| small | photo-only | Yes | Yes | Yes | Yes |
| small | video-only or mixed | Yes | Yes | Yes | No |
| medium | photo-only | Yes | Yes | Yes | No |
| medium | video-only or mixed | Yes | Yes | No | No |
| large | photo-only | Yes | Yes | No | No |
| large | video-only or mixed | Yes | No | No | No |

Phase 2's 1000-upload video and mixed runs therefore cannot run as designed on this
client at any size level. For Phase 1, see
[the feasibility of each run](#feasibility-of-the-phase-1-runs).

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
CSV as the run record and follow its `run_order` sequence. Map each
`concurrent_uploads` value to `CONCURRENT_UPLOADS` in
`scripts/run-load-test.sh`, and set `PHOTO_RATIO` from the row (`1.0` photo-only,
`0.0` video-only, `0.5` mixed). Keep `USERS` constant at a value selected before
testing.

## Machine learning scope

Machine learning is disabled through `config/immich-config.json`, and the
machine-learning container is not part of the stack. Background processing in
these runs therefore covers non-ML jobs only. Earlier runs are not comparable
with later ones because they included failing ML jobs and an idle ML container.

## CPU cores

`immich-server`, `database`, and `redis` share `cpu_cores` hardware threads, as if
Immich ran on a machine of that size. Any whole number up to the server runner's thread
count works, currently 4, so levels beyond this matrix only need the input changed;
counts above 4 also need a larger runner. The workflow fails if the applied limit does not
match, and records it in `cpu-limits.json`.

Keep these limits in mind when comparing levels:

- `cpu_cores` counts hardware threads, not physical cores. The server runner has 4
  threads on 2 physical cores, with threads 0 and 1 sharing a core and 2 and 3 sharing
  the other. `cpu_cores=2` is therefore one physical core, and `cpu_cores=4` is two.
- Runners of the same type can have different CPUs: one of seven checked runs was Intel
  and the rest AMD. `cpu-limits.json` records the CPU for each run.
- Monitoring, Tailscale, and system work are not limited. They can use the other
  cores at lower levels, but compete with Immich at the runner's full core count.
- Immich runs the same number of concurrent jobs at every level, so jobs compete more
  heavily at lower levels than they would on a server tuned for that size.
- Immich's `Detected CPU Cores` log line, recorded as `immich_detected_cores`, reports
  the host's core count at every level because it does not read the pinned cores. Use
  `pinned_cores` and `nproc` to confirm the limit. Immich only uses this value to enlarge
  its thread pool above 4 cores, so it has no effect on the current 4-core runner, but a
  larger runner would need checking.

## Monitoring overhead

Service latency adds `pg_stat_statements` and two exporter containers to the stack.
Treat runs from before and after these additions as separate sets, because their
overhead has not been measured reliably. See
[service latency results](results-replay.md).

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

The current `scripts/run-load-test.sh` passes constant `CONCURRENT_UPLOADS` and
`DURATION` values to k6; it does not implement a ramping profile. The procedure
above therefore describes the required protocol, but ramping and the measurement
boundaries need operational support before execution.

Report throughput, p95 upload latency, and error rate.

## Background job catch-up

`scripts/run-load-test.sh` polls Immich's `GET /api/queues` every 5 seconds and
keeps the run open after k6 exits, so server metrics continue through catch-up.
Background processing has caught up when every queue has no active, waiting,
delayed, or paused jobs for 3 consecutive polls. Catch-up time runs from k6's exit
to the first of those polls, with a resolution of about 5 seconds.

Tracking stops `DRAIN_TIMEOUT_SECONDS` (default 1800) after k6 exits. The server
job waits 45 minutes for the client, and fixture generation, k6, and catch-up all
share that time, so the default fits runs of up to about 10 minutes. For longer
runs, lower the limit with the workflow's `drain_timeout_seconds` input or raise
the wait in `.github/workflows/immich-load-test.yml`.

## Open questions

- What exact database, asset, and job-queue reset procedure defines a clean
  Immich start while preserving comparable system configuration?
- How will the load generator implement and timestamp the ramp, five-minute
  hold, and measurement window? The current k6 script only accepts fixed
  concurrency and duration.
- What fixed `USERS` value should Phase 2 use while upload concurrency varies?
  It currently defaults to 1.
- What is the actual free disk space on the runners? The estimated disk
  thresholds (about 83 GB for some runs) are unverified and must be checked.
- How will fixtures be pregenerated instead of generated on every run, and
  where will they be stored? Large videos can take up to about 30 minutes to
  generate.
  See [the fixture decision](upload-fixture-decision.md) for fixture details.
- How should the randomized order of Phase 1's 15 repeated runs be generated
  and preserved?
- How will throughput, p95 upload latency, and error rate be defined and
  summarized?
