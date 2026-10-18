# Monitoring getting started

This directory contains the shared Prometheus and Grafana configuration for
the project. It collects container and cgroup metrics from cAdvisor and
provisions an **Immich Overview** dashboard with three basic measurements:

- container CPU usage
- container memory usage
- running container count

## Prerequisites

- Docker Engine or Docker Desktop
- Docker Compose v2

## Start monitoring

From the repository root, start the monitoring stack:

```sh
docker compose -f monitoring/docker-compose.yml up -d
```

Open Grafana at <http://localhost:3000> and sign in with:

- Username: `admin`
- Password: `admin`

The Prometheus data source and dashboard are provisioned automatically. The
Prometheus expression browser is available at <http://localhost:9090>, and
cAdvisor exposes its metrics at <http://localhost:8080/metrics>.

## Stop monitoring

```sh
docker compose -f monitoring/docker-compose.yml down
```

The named volumes retain Grafana configuration and Prometheus time-series data.
To remove those volumes as well, use:

```sh
docker compose -f monitoring/docker-compose.yml down -v
```
