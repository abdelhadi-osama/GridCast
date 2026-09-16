# GridCast Monitoring

## Overview

GridCast monitoring provides visibility into three layers of the production forecasting system:

1. **Model monitoring** — evaluates forecast quality against actual ISO New England system load.
2. **Operational monitoring** — measures API availability, traffic, errors, latency, concurrency, and service health.
3. **Business / product monitoring** — measures how GridCast features are being used.

The monitoring stack uses **Prometheus** for metrics/time-series storage, **Grafana** for visualization, a custom **evaluator** service for actual-vs-predicted evaluation, and Prometheus instrumentation in the Online and Offline FastAPI services.

The current implementation intentionally does **not** use Evidently yet. Evidently is a planned improvement for feature-distribution drift, prediction drift, and residual-distribution monitoring.

---

## Architecture

```text
                              ┌──────────────────────┐
                              │        MLflow        │
                              │       :1010          │
                              └──────────┬───────────┘
                                         │
                          ┌──────────────┴──────────────┐
                          │                             │
                          ▼                             ▼
                 ┌────────────────┐            ┌────────────────┐
                 │   Online API   │            │  Offline API   │
                 │     :1011      │            │     :1012      │
                 │   /metrics     │            │   /metrics     │
                 └───────┬────────┘            └───────┬────────┘
                         │                              │
                         │                     ┌────────▼─────────┐
                         │                     │    Evaluator     │
                         │                     │      :8000       │
                         │                     │     /metrics     │
                         │                     └────────┬─────────┘
                         │                              │
                         └──────────────┬───────────────┘
                                        │
                                        ▼
                              ┌──────────────────────┐
                              │     Prometheus       │
                              │       :9090          │
                              │ host: 127.0.0.1:1014 │
                              └──────────┬───────────┘
                                         │
                                         ▼
                              ┌──────────────────────┐
                              │       Grafana        │
                              │       :3000          │
                              │ host: 127.0.0.1:1015 │
                              └──────────────────────┘
```

All services use the default Docker Compose network. Prometheus reaches services through Docker DNS names:

```text
evaluator:8000
online:1011
offline:1012
```

Grafana reaches Prometheus through:

```text
http://prometheus:9090
```

---

## Monitoring Directory

```text
GridCast_deployment/monitoring/
├── evaluator/
│   ├── Dockerfile
│   ├── evaluator.py
│   ├── metrics.py
│   └── .env
├── prometheus/
│   └── prometheus.yml
└── grafana/
    ├── datasources/
    │   └── prometheus.yml
    └── dashboards/
        ├── dashboards.yml
        ├── dashboard_model_monitoring.json
        ├── dashboard_operational.json
        └── dashboard_business.json
```

The evaluator `.env` file is secret and must not be committed. A second Compose-level secret file is used at:

```text
GridCast_deployment/.env
```

for the Grafana administrator password.

---

# 1. Model Monitoring

## Purpose

The model-monitoring pipeline measures GridCast forecast accuracy against actual ISO New England system load.

The evaluator:

1. Fetches forecast metadata from the Offline API.
2. Selects the latest forecast using `generated_at`.
3. Retrieves hourly predictions for that forecast.
4. Fetches actual ISO New England hourly load for the target date.
5. Matches prediction and actual rows using `Date` + `Hr_End`.
6. Calculates MAE, RMSE, and MAPE.
7. Publishes the latest evaluation through `/metrics` for Prometheus.

## Exported metrics

```text
gridcast_model_mae_mw
gridcast_model_rmse_mw
gridcast_model_mape_percent
gridcast_evaluation_matched_hours
gridcast_evaluator_last_success_timestamp_seconds
gridcast_evaluator_has_evaluation
```

### MAE

```text
MAE = mean(|actual - prediction|)
```

Unit: MW. MAE is the average absolute forecast error.

### RMSE

```text
RMSE = sqrt(mean((actual - prediction)^2))
```

Unit: MW. RMSE penalizes large errors more strongly than MAE.

### MAPE

```text
MAPE = mean(|actual - prediction| / |actual|) × 100
```

Unit: percent. MAPE is scale-independent.

## Validated production example

A validated evaluation produced approximately:

```text
Matched hours: 24
MAE:           494.70 MW
RMSE:          582.31 MW
MAPE:          3.33%
```

This confirms the end-to-end path from Offline API → evaluator → ISO-NE → Prometheus → Grafana.

## Latest-only evaluation design

The evaluator intentionally uses a **latest-only** V1 design. It keeps the latest successfully evaluated `forecast_id` in process memory.

```text
new forecast
    ↓
actuals available?
    ├── no  → retry next polling cycle
    └── yes → evaluate and publish metrics
```

If the same forecast is seen again, it is skipped.

### Limitations

- Evaluator state is not persisted.
- A restart can cause the latest forecast to be evaluated again once.
- If several forecasts are created between polling cycles, intermediate unevaluated forecasts can be skipped.
- Prometheus records monitoring samples from deployment forward; it does not backfill earlier historical forecast evaluations.
- Grafana model-history panels represent the **evaluation/monitoring timeline**, not historical `target_date` backfill.

---

# 2. ISO New England Actual Load

The evaluator retrieves actual hourly load from ISO New England.

Endpoint pattern:

```text
https://webservices.iso-ne.com/api/v1.1/hourlysysload/day/YYYYMMDD
```

Authentication uses HTTP Basic Authentication.

The evaluator filters for `NEPOOL AREA` and uses the `Load` field as `Actual_Load_MW`.

The current mapping is:

```text
BeginDate hour 00 → Hr_End 1
BeginDate hour 01 → Hr_End 2
...
BeginDate hour 23 → Hr_End 24
```

A future hardening task is explicit DST handling, especially fall-back days with repeated hours.

---

# 3. Evaluator Service

The evaluator runs as a dedicated Docker service.

Container command:

```text
python metrics.py
```

Internal endpoint:

```text
http://evaluator:8000/metrics
```

The evaluator does not need a host-published port because Prometheus scrapes it through the Compose network.

## Environment variables

Provided by Compose:

```text
GRIDCAST_OFFLINE_API_URL=http://offline:1012
METRICS_PORT=8000
POLL_INTERVAL_SECONDS=300
```

Secrets are loaded from:

```text
monitoring/evaluator/.env
```

Expected variables:

```text
ISONE_USERNAME=...
ISONE_PASSWORD=...
```

Never commit this file.

---

# 4. Online API Monitoring

The Online FastAPI service exposes `/metrics` and exports:

```text
gridcast_http_requests_total
gridcast_http_request_duration_seconds
gridcast_active_requests
```

with:

```text
service="online"
```

## Request counter

Metric:

```text
gridcast_http_requests_total
```

Labels:

```text
service
method
endpoint
status
```

Example:

```text
gridcast_http_requests_total{
  service="online",
  method="POST",
  endpoint="/predict",
  status="200"
}
```

## Request latency

Histogram:

```text
gridcast_http_request_duration_seconds
```

This supports P50/P95/P99 latency calculation.

## Active requests

Gauge:

```text
gridcast_active_requests{service="online"}
```

Prometheus scraping of `/metrics` is deliberately excluded from normal application traffic counters.

---

# 5. Offline API Monitoring

The Offline FastAPI service exports the same HTTP metric contract with:

```text
service="offline"
```

Current monitored routes include:

```text
GET  /health
POST /forecast
GET  /forecasts
GET  /forecasts/target/{target_date}/latest
GET  /forecasts/{forecast_id}
GET  /forecasts/{forecast_id}/hourly
GET  /forecasts/{forecast_id}/report
GET  /forecasts/{forecast_id}/parquet
GET  /running
GET  /failures
```

Prometheus labels use route templates such as:

```text
/forecasts/{forecast_id}/report
```

instead of raw IDs. This prevents unbounded label cardinality.

---

# 6. Prometheus

Configuration file:

```text
monitoring/prometheus/prometheus.yml
```

Current jobs:

```text
gridcast-evaluator
gridcast-online
gridcast-offline
prometheus
```

Example configuration:

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: "gridcast-evaluator"
    metrics_path: "/metrics"
    scrape_interval: 15s
    static_configs:
      - targets:
          - "evaluator:8000"

  - job_name: "gridcast-online"
    metrics_path: "/metrics"
    scrape_interval: 15s
    static_configs:
      - targets:
          - "online:1011"

  - job_name: "gridcast-offline"
    metrics_path: "/metrics"
    scrape_interval: 15s
    static_configs:
      - targets:
          - "offline:1012"

  - job_name: "prometheus"
    metrics_path: "/metrics"
    scrape_interval: 15s
    static_configs:
      - targets:
          - "localhost:9090"
```

Host binding:

```text
127.0.0.1:1014 → Prometheus :9090
```

Prometheus is intentionally not exposed publicly.

---

# 7. Grafana

Datasource file:

```text
monitoring/grafana/datasources/prometheus.yml
```

Current datasource:

```yaml
apiVersion: 1

datasources:
  - name: Prometheus
    uid: prometheus
    type: prometheus
    access: proxy
    url: http://prometheus:9090
    isDefault: true
    editable: false
```

The stable datasource UID `prometheus` is referenced by the dashboard JSON files.

---

# 8. Grafana Dashboards

## 8.1 Model Monitoring

File:

```text
dashboard_model_monitoring.json
```

Purpose:

```text
Is the forecasting model performing correctly?
```

Panels include:

```text
Current MAE
Current RMSE
Current MAPE
Matched Hours
Evaluator State
Seconds Since Last Evaluation
MAE and RMSE Over Time
MAPE Over Time
```

Example queries:

```promql
gridcast_model_mae_mw
```

```promql
gridcast_model_rmse_mw
```

```promql
gridcast_model_mape_percent
```

```promql
time() - gridcast_evaluator_last_success_timestamp_seconds
```

## 8.2 Operational Health

File:

```text
dashboard_operational.json
```

Purpose:

```text
Are production services healthy and responsive?
```

Panels include:

```text
Online API Status
Offline API Status
Total Requests
HTTP Error Rate
Request Rate
HTTP Response Time P95
HTTP Status Distribution
Active Requests
Top Endpoints
API Uptime
Online Prediction Latency P95
Online Prediction Volume
Service Health Score
```

Request rate:

```promql
sum by (service, method, endpoint) (
  rate(gridcast_http_requests_total[1m])
)
```

P95 latency:

```promql
histogram_quantile(
  0.95,
  sum by (le, service, endpoint) (
    rate(gridcast_http_request_duration_seconds_bucket[5m])
  )
)
```

5xx error rate:

```promql
100 *
sum(rate(gridcast_http_requests_total{status=~"5.."}[5m]))
/
clamp_min(
  sum(rate(gridcast_http_requests_total[5m])),
  0.000001
)
```

Service health score:

```promql
100 * (
  1 -
  (
    sum by (service) (
      rate(gridcast_http_requests_total{status=~"5.."}[5m])
    )
    /
    clamp_min(
      sum by (service) (
        rate(gridcast_http_requests_total[5m])
      ),
      0.000001
    )
  )
)
```

This is an **HTTP service health score**, not a model-health score.

## 8.3 Business & Product Usage

File:

```text
dashboard_business.json
```

Purpose:

```text
How is the GridCast platform being used?
```

Panels include:

```text
Successful Predictions
Offline Forecast Requests
Report Downloads
Parquet Downloads
Prediction Usage Over Time
Offline Forecast Usage Over Time
Artifact Downloads Over Time
Product Usage Mix
Most Used Product Endpoints
```

Successful predictions:

```promql
sum(
  increase(
    gridcast_http_requests_total{
      service="online",
      method="POST",
      endpoint="/predict",
      status=~"2.."
    }[24h]
  )
)
```

Offline forecast requests:

```promql
sum(
  increase(
    gridcast_http_requests_total{
      service="offline",
      method="POST",
      endpoint="/forecast",
      status=~"2.."
    }[24h]
  )
)
```

This measures successful acceptance of forecast requests. Because execution happens asynchronously, it does not by itself prove that the background forecast later completed successfully.

---

# 9. Docker Compose Integration

GridCast adds three monitoring services:

```text
evaluator
prometheus
grafana
```

Persistent volumes:

```yaml
volumes:
  prometheus_data:
  grafana_data:
```

Host mappings:

```text
127.0.0.1:1014 → Prometheus :9090
127.0.0.1:1015 → Grafana :3000
```

The evaluator is Docker-internal only:

```text
evaluator:8000
```

---

# 10. Accessing Grafana

Grafana remains private on the VPS and is accessed with an SSH tunnel.

From the local machine:

```bash
ssh -N \
  -L 11015:127.0.0.1:1015 \
  abdelhadi@<VPS_IP>
```

Then browse to:

```text
http://127.0.0.1:11015
```

The local port is above 1024 so a normal Linux user can bind it without elevated privileges.

Grafana credentials are configured through:

```text
GridCast_deployment/.env
```

Example:

```text
GRAFANA_ADMIN_PASSWORD=...
```

Do not commit this file.

---

# 11. Deployment Workflow

After monitoring changes are pushed:

```bash
git pull
```

Recreate secret files on the VPS if necessary:

```text
GridCast_deployment/.env
GridCast_deployment/monitoring/evaluator/.env
```

Protect them:

```bash
chmod 600 .env
chmod 600 monitoring/evaluator/.env
```

Validate Compose:

```bash
docker compose config -q
```

Build and deploy:

```bash
docker compose up -d --build
```

Inspect:

```bash
docker compose ps
```

Expected services:

```text
gridcast-mlflow
gridcast-online
gridcast-offline
gridcast-dashboard
gridcast-evaluator
gridcast-prometheus
gridcast-grafana
```

---

# 12. Validation Commands

## Container status

```bash
docker compose ps
```

## Prometheus health

```bash
curl http://127.0.0.1:1014/-/healthy
```

Expected:

```text
Prometheus Server is Healthy.
```

## Grafana health

```bash
curl http://127.0.0.1:1015/api/health
```

Expected to contain:

```json
{
  "database": "ok"
}
```

## Prometheus targets

```bash
curl -s http://127.0.0.1:1014/api/v1/targets \
  | python3 -m json.tool
```

Targets should include:

```text
gridcast-evaluator
gridcast-online
gridcast-offline
prometheus
```

and should normally report health `up`.

## Online metrics

```bash
curl -s http://127.0.0.1:1011/metrics | grep gridcast
```

## Offline metrics

```bash
curl -s http://127.0.0.1:1012/metrics | grep gridcast
```

## Evaluator metrics

Because the evaluator is not host-published:

```bash
docker exec gridcast-evaluator \
  python -c "
import urllib.request
print(
    urllib.request.urlopen(
        'http://localhost:8000/metrics'
    ).read().decode()
)
"
```

---

# 13. Security

Current security principles:

- Prometheus is not publicly exposed.
- Grafana is not publicly exposed.
- Grafana is accessed through an encrypted SSH tunnel.
- Monitoring ports bind only to `127.0.0.1`.
- ISO-NE credentials are stored outside Git.
- Grafana administrator credentials are stored outside Git.
- Secret `.env` files should use mode `600`.
- `/metrics` scraping is excluded from application-traffic counters.

Never commit:

```text
GridCast_deployment/.env
GridCast_deployment/monitoring/evaluator/.env
```

---

# 14. Known Limitations

## Latest-only evaluation

Only the latest unseen forecast is evaluated. If multiple forecasts arrive between polling cycles, intermediate forecasts can be skipped.

## Evaluator state is in memory

`last_evaluated_forecast_id` is not persisted. A restart can cause one duplicate evaluation.

## No historical evaluation backfill

Prometheus stores samples from the moment the stack starts. It does not automatically reconstruct historical model evaluations by target date.

## No explicit data-drift detection

The current system measures model-performance degradation but does not statistically compare feature distributions.

**Performance degradation and data drift are different concepts.**

## No prediction-distribution monitoring

The system does not yet compare the distribution of `predicted_mw` against a reference period.

## No alert rules yet

Dashboards visualize state, but production alert rules and notification routing have not yet been implemented.

## No external black-box monitoring

Prometheus currently observes services from inside the Docker network. It does not yet validate the complete external user path.

---

# 15. Future Improvements

## 15.1 Evidently for Data Drift

A strong next improvement is to add **Evidently** for statistical drift analysis.

Evidently should complement the current evaluator rather than replace it.

The current evaluator answers:

```text
How accurate is the model?
```

Evidently can help answer:

```text
Has the input or prediction distribution changed?
```

### Candidate drift features

GridCast raw model inputs include:

```text
Date
Hr_End
Dry_Bulb
Dew_Point
```

The serialized preprocessing pipeline creates additional model features. Drift monitoring should focus on meaningful stochastic features rather than treating identifiers or deterministic calendar values as ordinary continuous features.

Useful candidates include:

```text
Dry_Bulb
Dew_Point
hour-of-day derived features
selected calendar-derived features
prediction distribution
residual distribution
```

### Reference vs current windows

A practical design could use:

```text
Reference:
training validation period
or a stable historical production period

Current:
last 7 days
last 30 days
or last N forecasts
```

Evidently can then compute per-feature drift and overall dataset-level drift.

### Potential Prometheus metrics

```text
gridcast_data_drift_detected
gridcast_drifted_features_count
gridcast_drift_share
gridcast_prediction_drift_detected
gridcast_residual_drift_detected
```

Potential feature-level metric:

```text
gridcast_feature_drift_score{feature="Dry_Bulb"}
```

A bounded, intentionally small feature-label set is important to avoid high-cardinality metrics.

### Evidently pipeline concept

```text
Reference dataset
        +
Recent production inputs
        ↓
Evidently drift evaluation
        ↓
Drift report / summary
        ↓
Prometheus metrics
        ↓
Grafana model-monitoring dashboard
```

A daily schedule is more appropriate than running distribution-drift analysis on every HTTP request.

---

## 15.2 Prediction Drift

Monitor the distribution of:

```text
predicted_mw
```

against a reference period.

Potential signals:

```text
mean shift
variance change
quantile changes
statistical distribution drift
```

Prediction drift does not automatically mean model failure; it can reflect legitimate operating-condition changes.

---

## 15.3 Residual Drift and Bias

After actual load is available:

```text
residual = actual - prediction
```

Monitor:

```text
mean residual
median residual
residual standard deviation
P90 absolute error
P95 absolute error
bias
```

Bias is particularly useful:

```text
bias = mean(actual - prediction)
```

A persistent positive or negative bias can reveal systematic underprediction or overprediction even when MAE remains acceptable.

---

## 15.4 Segmented Model Performance

Current metrics summarize the whole evaluated forecast day. Future analysis should segment performance by:

```text
hour of day
weekday vs weekend
season
temperature range
high-load vs low-load periods
model version
```

Examples:

```text
MAE during peak hours
MAPE overnight
RMSE during high-temperature days
bias by hour
```

This can reveal failure modes hidden by daily aggregates.

---

## 15.5 Persistent Evaluation History

A V2 evaluator should persist evaluation records in SQLite, PostgreSQL, or another durable store.

Example schema:

```text
forecast_id
origin_date
target_date
model_version
generated_at
evaluated_at
matched_hours
mae_mw
rmse_mw
mape_percent
```

Benefits:

- no duplicate evaluation after restart;
- no skipped evaluation history;
- historical backfill;
- evaluation by target date;
- model-version comparisons;
- easier auditability.

Prometheus would still remain the operational metrics and alerting system.

---

## 15.6 Prometheus Alert Rules

Potential alerts:

```text
Online API down
Offline API down
Evaluator stale
high 5xx rate
high P95 latency
MAPE above threshold
MAE above threshold
matched-hour count below expectation
data drift detected
```

Evaluator-staleness concept:

```promql
time() - gridcast_evaluator_last_success_timestamp_seconds
```

Thresholds should be based on observed production behavior rather than arbitrary values.

---

## 15.7 Alertmanager

Prometheus Alertmanager can route alerts to:

```text
email
Slack
Discord
PagerDuty
webhooks
```

The current monitoring version focuses on metrics and dashboards, not notification routing.

---

## 15.8 Blackbox Exporter

Prometheus Blackbox Exporter could test complete HTTP availability for:

```text
GridCast dashboard
Online API
Offline API
MLflow
Grafana
```

This answers:

```text
Can a client actually reach the service?
```

rather than only:

```text
Can Prometheus scrape the service from inside Docker?
```

For true external availability, an external probe location is stronger than an internal Blackbox Exporter.

---

## 15.9 Infrastructure Metrics

Add Node Exporter and cAdvisor.

Node Exporter:

```text
CPU
memory
disk
filesystem
network
load average
```

cAdvisor:

```text
container CPU
container memory
container network
container resource pressure
```

This makes it possible to correlate application symptoms with infrastructure behavior.

---

## 15.10 SLOs and Error Budgets

Define explicit Service Level Objectives for:

```text
Online API availability
prediction latency
5xx error rate
evaluator freshness
```

Then add SLO and error-budget dashboards. This is more meaningful than a generic health score once production targets are defined.

---

## 15.11 Model-Version Monitoring

Persist or expose bounded model-version information so performance can be compared across versions:

```text
MAE by model version
RMSE by model version
MAPE by model version
```

Avoid uncontrolled Prometheus label cardinality.

---

# 16. Recommended Monitoring Maturity Roadmap

## V1 — Current

```text
Prometheus
Grafana
Online API metrics
Offline API metrics
latest actual-vs-prediction evaluation
MAE / RMSE / MAPE
Operational dashboard
Business dashboard
Model dashboard
```

## V2

```text
persistent evaluation history
bias and residual metrics
model-version comparisons
Prometheus alert rules
Alertmanager
```

## V3

```text
Evidently data drift
prediction drift
residual drift
segmented model performance
```

## V4

```text
Node Exporter
cAdvisor
Blackbox Exporter
external synthetic monitoring
SLOs
error budgets
```

---

# 17. Monitoring Design Principles

## Separate model health from service health

```text
MAE / RMSE / MAPE
```

measure model performance.

```text
latency / errors / availability
```

measure service performance.

They should not be collapsed into one concept.

## Separate drift from performance degradation

A model can experience:

```text
data drift without immediate accuracy degradation
```

or:

```text
accuracy degradation without detectable input drift
```

Both should eventually be monitored independently.

## Keep Prometheus labels bounded

Good labels:

```text
service
method
endpoint template
status
small fixed feature set
```

Avoid labels containing:

```text
forecast_id
raw URL
timestamp
user ID
arbitrary error text
```

Unbounded labels create high-cardinality time series.

## Keep secrets outside images and Git

Credentials should enter containers at runtime and should never be baked into:

```text
Dockerfiles
Docker images
dashboard JSON
Prometheus configuration
Git history
```

---

# 18. Current Status

The monitoring stack has been deployed successfully on the GridCast VPS.

Validated components:

```text
Online API /metrics                  ✓
Offline API /metrics                 ✓
Evaluator /metrics                   ✓
Prometheus health                    ✓
Grafana health                       ✓
Grafana datasource                   ✓
Model Monitoring dashboard           ✓
Operational Health dashboard         ✓
Business & Product Usage dashboard   ✓
SSH-tunneled Grafana access          ✓
```

This is the first complete production monitoring version of GridCast.
