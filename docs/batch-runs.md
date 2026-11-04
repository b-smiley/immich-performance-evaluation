# Batch load test runs

The `Immich load batch` workflow runs `Immich load test` once per row of a CSV, one
at a time and in file order. Each row is its own workflow run with its own run ID, so
artifacts and `scripts/aggregate_results.py` work the same as for a manual run.

## Running a batch

1. Add a CSV to `experiments/`.
2. Run the workflow with `matrix_file` set to the file name and `dry_run` left on.
3. Check the job summaries, then run it again with `dry_run` off.
4. A `loadtest` reviewer approves the batch once. The rows then run unattended.

```bash
gh workflow run immich-load-batch.yml --ref main -f matrix_file=smoke.csv -f dry_run=true
```

## CSV format

The first line names the columns, and each later line is one run. Columns can be:

- **Load-test inputs:** `duration`, `concurrent_uploads`, `users`,
  `think_time_seconds`, `cpu_cores`, `photo_ratio`, `size_level`, `resolution`,
  `iterations`, `fixture_seed`, `drain_timeout_seconds`.
- **Labels:** `run_order`, `replicate`, `workload_composition`, `notes`. These appear
  in the job summaries but are not sent to the load test.

Any other column fails validation, so a misspelled input cannot silently run at its
default. A blank cell uses the load test's default. Rows run in file order, whatever
`run_order` says, so sort the file into the order you want.

## What a dry run checks

A dry run validates the CSV, then runs the same matrix with each row logging its
inputs and timestamps instead of starting a load test. It needs no approval and uses
no load-test runners.

It does not test starting or waiting for a real load test, or whether a row's fixtures
fit in memory and on disk. Use `smoke.csv` for a real end-to-end check.

To see how many rows are running at once, compare the row timestamps in the logs.
`sequence-check.csv` has three rows for this, two of them identical.

## Time limits

| Limit | Value | Applies to |
|---|---|---|
| Workflow run | 35 days, including waiting (GitHub) | The whole batch |
| Job | 6 hours (GitHub) | Each job separately |
| Batch row | 3 hours (this repo) | One row, including waiting for its load test |
| Load-test job | 60 minutes (this repo) | `server` and `client` in each load test |

No job stays open for the whole batch, so the total length is limited only by the 35
days. If a row times out or the batch is cancelled, the row's load test is cancelled too.

## Repository setup

A repository admin needs to create the `loadtest-batch` environment once:

1. Create the environment with no required reviewers.
2. Add `TS_OAUTH_CLIENT_ID` and `TS_OAUTH_SECRET`, with the same values as `loadtest`.
3. Limit its deployment branches to `main`. Allow another branch only while testing
   changes to the workflow.

The branch limit keeps code on other branches from reading these secrets without
review. Anyone with write access can still start a load test on `main` against
`loadtest-batch` directly, without an approval.

## Known limits

- **Manual runs can overlap a batch.** Only batches block each other, so don't start
  load tests by hand during a batch.
- **Pushes affect later rows.** Each row starts from the latest commit on the branch,
  so a push during a batch means later rows run different code. Every run records its
  commit in `run-params.json`.
- **A failed row doesn't stop the batch.** The remaining rows still run, and the batch
  finishes as failed. Rows that fail preflight, such as ones over k6's memory budget,
  are reported this way.
- **Long fixture generation can fail a row.** The server waits 45 minutes for the
  client, and large videos can take up to about 30 of those to generate. See
  [background job catch-up](run-matrix.md#background-job-catch-up).
- **Row start order isn't guaranteed by GitHub.** GitHub documents the order matrix
  jobs are created, not the order they start. Check the recorded order after a batch.
