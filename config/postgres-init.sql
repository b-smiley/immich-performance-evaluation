CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

-- A separate role lets the exporter leave its own queries out of the latency
-- metrics. The database port is not published, and this role can only read stats.
CREATE ROLE metrics_exporter LOGIN PASSWORD 'metrics_exporter';
GRANT pg_monitor TO metrics_exporter;
