# Monitoring getting started

This directory contains the shared Prometheus and Grafana configuration used
by the root evaluation Compose stack. It collects container and cgroup metrics
from cAdvisor, PostgreSQL and Redis metrics from their exporters, per-process CPU
and memory from process-exporter, and Immich's own telemetry. It provisions an
**Immich Overview** dashboard with these measurements:

- container CPU usage, as a percentage of one core
- memory working set, which excludes reclaimable file cache
- memory usage including cache
- running container count
- API, PostgreSQL, and Redis latency
- CPU inside `immich-server` per process: the API, the background worker, and the
  ffmpeg and exiftool processes the worker starts
- background jobs completed per second, active jobs per queue, and the worker's
  slowest internal steps

The API and the background worker run in the same `immich-server` container, so
cAdvisor cannot tell them apart. process-exporter reads the host's process table and
groups processes as set in `process-exporter/config.yml`, and Prometheus scrapes it
every 5 seconds. Unlike cAdvisor, this also works on Docker Desktop.

ffmpeg and ffprobe usually exit within a second, before a scrape can see them, so
`child-cpu-exporter` measures them instead. When the worker collects a finished
child, Linux adds all of that child's CPU to the worker's own counters. The exporter
reads those counters, and once a second it follows the worker's longer-lived
children, such as exiftool, so their CPU can be subtracted when they exit.

`IMMICH_TELEMETRY_INCLUDE=all` makes Immich serve its metrics on port 8081 for the
API and 8082 for the worker, which Prometheus scrapes as the `immich-api` and
`immich-worker` jobs. Immich is set to listen on `0.0.0.0`, because with its default
address the metrics endpoints answer every request with 400. Prometheus moves the
job, queue, and step names Immich puts
inside metric names into labels; see `metric_relabel_configs` in
`prometheus/prometheus.yml`. Telemetry times each internal call, which adds a little
overhead, so runs before and after it was turned on are not strictly comparable.

The CPU, memory, and container count panels need cAdvisor to see individual
containers. This works on the Linux GitHub Actions runners. On Docker Desktop with
WSL2, cAdvisor reports only top-level groups such as `/docker`, so those panels are
empty. The latency panels do not depend on cAdvisor.

The PostgreSQL role and extension for query metrics come from
`config/postgres-init.sql`, which only runs on a new database. If an existing local
`data/postgres` predates them, the exporter cannot log in, so remove that database
with `docker compose down -v` and by deleting `data/postgres`.

## Prerequisites

- Docker Engine or Docker Desktop
- Docker Compose v2

## Start monitoring

From the repository root, start the complete Immich and monitoring stack:

```sh
cp .env.example .env
docker compose up -d
```

Open Grafana at <http://localhost:3000> and sign in with:

- Username: `admin`
- Password: `admin`

The Prometheus data source and dashboard are provisioned automatically. The
Prometheus expression browser is available at <http://localhost:9090>, and
cAdvisor exposes its metrics at <http://localhost:8080/metrics>.

## Stop monitoring

```sh
docker compose down
```

The named volumes retain Grafana configuration and Prometheus time-series data.
To remove those volumes as well, use:

```sh
docker compose down -v
```
