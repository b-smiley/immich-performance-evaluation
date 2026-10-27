# Results replay and Grafana dashboards

This guide explains how to view a completed local or cloud run. The replay
stack restores the raw Prometheus TSDB archive and opens the existing Grafana
dashboards. It does not start Immich or modify the original results.

## Run a test locally

From Git Bash:

```bash
cp .env.example .env
./run.sh
VUS=1 DURATION=30s PHOTO_RATIO=0.5 ./scripts/run-load-test.sh
./scripts/collect-results.sh
```

The load test writes raw k6 output to `data/results/k6.json` and sends the k6
metrics to Prometheus through its remote-write receiver. The server metrics and
k6 metrics are archived in `data/results/prometheus-tsdb.tar.gz`.

## Replay a completed local run

Stop the live stack first if it is using the same ports:

```bash
docker compose down
./scripts/replay-results.sh data/results/prometheus-tsdb.tar.gz
```

## Replay a GitHub Actions run

The helper below downloads both artifacts into `data/results/cloud-<run-id>`,
starts the replay stack, and opens both Grafana dashboards:

```bash
./scripts/replay-cloud-results.sh 40266030076
```

It requires the GitHub CLI to be authenticated. The server artifact must
contain `prometheus-tsdb.tar.gz`; the client artifact is retained beside it
for raw k6 analysis.

For manual downloads, use the commands below.

Download the server and client artifacts from the completed **Immich load test**
workflow run. Place the extracted files in one directory, or point the helper
directly at the server artifact's Prometheus archive:

```bash
./scripts/replay-results.sh path/to/downloaded-artifacts/prometheus-tsdb.tar.gz
```

The client artifact contains the raw `k6.json` and `k6-summary.json`; keep it
with the replay archive for independent analysis. The server artifact contains
the Prometheus TSDB archive, Grafana dashboard definition, Compose status, and
logs. The same replay command and dashboards are used for local and cloud
results.

Sign in at <http://localhost:3001/login> with `admin` / `admin`, then use these
direct dashboard URLs:

- [Immich Overview](http://localhost:3001/d/immich-overview/immich-overview)
- [k6 Prometheus](http://localhost:3001/d/k6-prometheus/k6-prometheus)

Replay Prometheus is available at <http://localhost:9091>.

The dashboards default to a recent time range. Since replayed data may be from
an earlier local or GitHub Actions run, use Grafana's time picker and select an
absolute range covering the run. Prometheus can be used to find the data range
before opening the dashboard:

```text
http://localhost:9091/graph
```

For example, query `k6_http_reqs_total` and use the returned timestamp to set
the Grafana time range around the test.

Prometheus is a query interface, not a dashboard. Use the **Graph** page,
enter a query, select **Table** or **Graph**, and choose the test's absolute
time range. For example:

```text
http://localhost:9091/graph?g0.expr=k6_http_reqs_total&g0.tab=1&g0.range_input=1h
```

The default instant query evaluates at the current time. Archived series stop
being returned after their last sample becomes stale, even though historical
range queries still work. If the run occurred at 17:30 local time, select an
absolute range such as 17:29–17:32 rather than only querying "now".

## Available dashboard data

The **k6 Prometheus** dashboard can show:

- virtual users and maximum virtual users
- total HTTP requests and request rate
- HTTP request failures and failed-request rate
- request-duration p99 and waiting/sending/receiving timings
- iteration count, iteration duration, and dropped iterations
- bytes sent and received

The **Immich Overview** dashboard can show:

- container CPU usage
- container memory usage
- running container count

Raw Prometheus queries are also available for metrics such as
`k6_http_reqs_total`, `k6_vus`, `k6_http_req_duration_p99`,
`k6_http_req_failed_rate`, `container_cpu_usage_seconds_total`, and
`container_memory_usage_bytes`.

The replay stack uses separate ports so it can run alongside the live stack if
the ports are changed:

```bash
REPLAY_GRAFANA_PORT=3011 REPLAY_PROMETHEUS_PORT=9092 \
  ./scripts/replay-results.sh data/results/prometheus-tsdb.tar.gz
```

Use the Grafana time picker to select the time range containing the test. The
raw files remain available for independent analysis:

- `data/results/k6.json`
- `data/results/k6-summary.json`
- `data/results/prometheus-tsdb.tar.gz`
- `data/results/compose.log`
- `data/results/compose-ps.txt`

The official Grafana k6 dashboard is provisioned automatically as **k6
Prometheus**. It uses the k6 metrics written through Prometheus remote write;
no custom result conversion is required.

## Stop replay

```bash
docker compose -f monitoring/replay-compose.yml \
  -p immich-results-replay down
```
