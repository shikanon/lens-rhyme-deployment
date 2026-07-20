# ResourceFS P0 Prometheus rules

`resourcefs-p0-alerts.yaml` is a rule package for an existing Prometheus and
Alertmanager installation. It does not deploy a monitoring stack or define
notification routing.

Load the file through the deployment's normal Prometheus `rule_files` or
Prometheus Operator rule-discovery path. Keep the existing Alertmanager routes
for `severity` and `component` labels. The application exposes these metrics at
`/metrics`:

- PostgreSQL transaction, lock, connection, and pool gauges.
- `lens_rhyme_resourcefs_operation_duration_seconds` for the fixed ResourceFS
  external-I/O operation vocabulary.
- `lens_rhyme_http_request_duration_seconds` for route-level latency.

Before enabling alerts in production, confirm that Prometheus scrapes the
backend `/metrics` endpoint and run `promtool check rules
monitoring/resourcefs-p0-alerts.yaml` from an environment that has Prometheus
tools installed.
