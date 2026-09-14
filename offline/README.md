# GridCast Offline Inference Service

[![Python](https://img.shields.io/badge/Python-3.11+-blue?logo=python&logoColor=white)](https://www.python.org/)
[![MLflow](https://img.shields.io/badge/Tracked%20with-MLflow-blue?logo=mlflow)](https://mlflow.org/)
[![Prefect](https://img.shields.io/badge/Orchestrated%20with-Prefect-ff4c4c?logo=prefect)](https://www.prefect.io/)
[![XGBoost](https://img.shields.io/badge/Model-XGBoost-orange?logo=xgboost)](https://xgboost.ai/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)


GridCast Offline is the batch/historical inference service for the GridCast electricity-demand forecasting project.

It accepts a **forecast origin date `D`**, derives the **target date `D + 1`**, obtains the weather inputs required by the trained model, generates hourly system-load predictions, calculates user-facing analytics, creates a downloadable HTML report, persists forecast artifacts, and records forecast execution lineage in MLflow.

> **Current operating mode**
>
> GridCast Offline currently uses **Open-Meteo ERA5 historical weather** for the target day. This is a practical historical replay mode, not a strict operational day-ahead backtest. ERA5 historical weather contains information that would not have been available at the original forecast issuance time. A future version can replace this input source with archived forecast/model-run weather without changing the rest of the inference pipeline.

---

## 1. What the service does

For an input such as:

```text
origin_date = 2025-06-06
```

GridCast computes:

```text
target_date = 2025-06-07
```

and executes:

```text
Origin date D
    ↓
Target date D + 1
    ↓
ERA5 historical weather
    ↓
Raw model features
    ↓
Serialized preprocessing pipeline
    ↓
Champion load-forecast model
    ↓
Hourly load predictions
    ↓
Forecast analytics
    ↓
HTML report
    ↓
Parquet + SQLite persistence
    ↓
MLflow execution tracking
```

On a normal day, the result contains **24 hourly predictions**. DST transition days may contain 23 or 25 hourly intervals.

---

## 2. Current architecture

```text
                    ┌──────────────────────┐
                    │      API / CLI       │
                    └──────────┬───────────┘
                               │
                 ┌─────────────┴─────────────┐
                 │                           │
          FastAPI api.py               main.py / flow.py
                 │                           │
                 │                    Prefect orchestration
                 │                           │
                 └─────────────┬─────────────┘
                               │
                        core.run_forecast()
                               │
       ┌───────────────────────┼────────────────────────┐
       │                       │                        │
 data_sources.py         analytics.py              report.py
 ERA5 weather            forecast KPIs            HTML report
       │                       │                        │
       └───────────────────────┼────────────────────────┘
                               │
                         persistence.py
                    Parquet + SQLite history
                               │
                          tracking.py
                              MLflow
```

`core.py` is the canonical forecasting operation. Other entry points should delegate to it rather than reimplementing the inference pipeline.

---

## 3. Directory structure

```text
offline/
├── analytics.py
├── api.py
├── batch_results.db
├── config.py
├── core.py
├── core_test.py
├── data_sources.py
├── Dockerfile
├── flow.py
├── forecasts/
├── __init__.py
├── main.py
├── mlruns/
├── persistence.py
├── README.md
├── report.py
├── reports/
├── requirements.txt
├── tracking.py
└── __pycache__/
```

### File responsibilities

| File | Responsibility |
|---|---|
| `core.py` | Canonical end-to-end offline forecast pipeline |
| `data_sources.py` | Historical weather acquisition and validation |
| `analytics.py` | Peak, minimum, average, energy, load factor, and ramp analytics |
| `report.py` | Self-contained downloadable HTML forecast report |
| `persistence.py` | Parquet persistence, SQLite run history, forecast retrieval |
| `tracking.py` | MLflow forecast-execution tracking |
| `api.py` | FastAPI interface for asynchronous forecast requests and retrieval |
| `flow.py` | Prefect orchestration, retry policy, and execution observability |
| `main.py` | CLI entry point for the Prefect flow |
| `config.py` | Offline storage and weather configuration |
| `requirements.txt` | Runtime dependencies |
| `Dockerfile` | Container definition for the offline API |

---

## 4. Forecast contract

The public batch operation is:

```python
core.run_forecast(
    origin_date=...,
    weather_config=...,
    log_to_mlflow=True,
)
```

The pipeline currently performs:

1. Load the MLflow model registered under the `champion` alias.
2. Derive `target_date = origin_date + 1 day`.
3. Fetch ERA5 historical weather for the target date.
4. Build the raw model input schema.
5. Transform features using the serialized training preprocessor.
6. Generate hourly load predictions.
7. Build the canonical forecast DataFrame.
8. Calculate forecast analytics.
9. Generate the HTML report.
10. Persist the forecast and metadata.
11. Log forecast execution to MLflow.

The expected raw inference columns are:

```text
Date
Hr_End
Dry_Bulb
Dew_Point
```

The canonical forecast output contains metadata such as:

```text
forecast_id
Date
Hr_End
Predicted_Load_MW
Dry_Bulb
Dew_Point
origin_date
target_date
weather_source
model_version
model_run_id
model_alias
generated_at
```

---

## 5. Historical weather mode

GridCast currently pins Open-Meteo historical weather to:

```text
model = ERA5
weather_source = open_meteo_era5
timezone = America/New_York
temperature_unit = fahrenheit
```

The latitude and longitude are application configuration. They are **not user inputs** because they must remain consistent with the weather semantics used by the trained model.

### Availability rule

ERA5 is treated as having an approximate historical availability delay:

```text
historical_delay_days = 5
```

The service calculates:

```text
latest_available_target = today - historical_delay_days
```

and rejects target dates newer than that.

Example, if local `today` is `2026-09-14`:

```text
target 2026-09-09  -> allowed
target 2026-09-10  -> rejected
target 2026-09-14  -> rejected
```

### Important limitation

ERA5 represents historical/reanalysis weather, not the weather forecast that was available on the origin date.

Therefore the current mode is useful for:

- pipeline validation,
- historical scenario generation,
- product demonstrations,
- batch inference testing,
- report generation,
- persistence and orchestration testing.

It should **not** be described as a strict point-in-time operational backtest.

A future weather-source implementation can use archived forecast runs while preserving the same `data_sources.py -> core.py` interface.

---

## 6. Install dependencies

Activate the GridCast virtual environment first.

From the repository root:

```bash
uv pip install -r offline/requirements.txt
```

If already inside `offline/`:

```bash
uv pip install -r requirements.txt
```

The runtime stack includes:

```text
FastAPI
Uvicorn
Pydantic
NumPy
Pandas
scikit-learn
XGBoost
CatBoost
MLflow
Prefect
PyArrow
Requests
holidays
```

Pinned versions belong in `requirements.txt` so the offline runtime remains compatible with the model/preprocessor serialization environment.

---

## 7. Run the FastAPI service

From:

```text
GridCast/offline/
```

run:

```bash
uvicorn api:app --host 0.0.0.0 --port 8001 --reload
```

Expected startup:

```text
Application startup complete.
```

### Browser access

Swagger UI:

```text
http://localhost:8001/docs
```

OpenAPI schema:

```text
http://localhost:8001/openapi.json
```

Health endpoint:

```text
http://localhost:8001/health
```

A request to:

```text
http://localhost:8001/
```

may return `404 Not Found` unless a `/` route is explicitly defined. That does not mean the API failed.

---

## 8. FastAPI endpoints

### Health

```http
GET /health
```

Used to verify that the offline service is running and persistence is accessible.

### Start a forecast

```http
POST /forecast?origin_date=2025-06-06
```

The API accepts the job and executes the forecast in the background.

```text
POST /forecast
    ↓
job accepted
    ↓
weather acquisition
    ↓
inference
    ↓
analytics/report/persistence
    ↓
forecast becomes retrievable
```

A successful HTTP response from `POST /forecast` means the job was accepted. It does **not** by itself guarantee that the background forecast has completed.

### List stored forecasts

```http
GET /forecasts
```

Returns persisted forecast summaries ordered by generation time.

### Latest forecast for a target date

```http
GET /forecasts/target/2025-06-07/latest
```

Use normalized ISO dates:

```text
YYYY-MM-DD
```

### Retrieve one forecast summary

```http
GET /forecasts/{forecast_id}
```

### Retrieve hourly predictions

```http
GET /forecasts/{forecast_id}/hourly
```

Returns the detailed persisted hourly forecast from the Parquet artifact.

### Download the HTML report

```http
GET /forecasts/{forecast_id}/report
```

The report contains peak/minimum/average demand, energy, load factor, load profile, ramps, weather drivers, hourly forecasts, and lineage.

### Running jobs

```http
GET /running
```

Shows currently running in-memory background jobs.

### Failed jobs

```http
GET /failures
```

Shows recent background-job failures captured by the API process.

The current failure store is in memory and is lost when the API process restarts.

---

## 9. Recommended Swagger workflow

Open:

```text
http://localhost:8001/docs
```

Then:

1. Execute `GET /health`.
2. Execute `POST /forecast?origin_date=2025-06-06`.
3. Check `GET /running`.
4. Check `GET /failures` if necessary.
5. Retrieve `GET /forecasts/target/2025-06-07/latest`.
6. Copy the returned `forecast_id`.
7. Retrieve `GET /forecasts/{forecast_id}/hourly`.
8. Open/download `GET /forecasts/{forecast_id}/report`.

---

## 10. Run through Prefect

`flow.py` wraps the canonical forecast operation with Prefect orchestration.

```text
gridcast_forecast_flow()
    ↓
run_forecast_task()
    ↓
core.run_forecast()
```

Run locally:

```bash
python flow.py
```

A healthy execution should finish with:

```text
Task run ... Finished in state Completed()
Flow run ... Finished in state Completed()
```

and log the forecast ID, dates, hourly count, KPIs, artifact paths, and MLflow execution run.

### Temporary Prefect server

When running Prefect locally without a dedicated server, messages such as:

```text
Starting temporary server on http://127.0.0.1:...
Stopping temporary server ...
```

are expected.

---

## 11. Run from the CLI

`main.py` is the command-line entry point.

```bash
python main.py --origin-date 2025-06-06
```

Execution path:

```text
main.py
    ↓
gridcast_forecast_flow()
    ↓
run_forecast_task()
    ↓
core.run_forecast()
```

The CLI intentionally accepts only:

```text
--origin-date
```

Weather configuration, model loading, persistence, and MLflow remain internal application concerns.

---

## 12. Forecast analytics

Current user-facing analytics:

```text
peak_load_mw
peak_hour

minimum_load_mw
minimum_hour

average_load_mw

daily_energy_mwh

load_factor

max_ramp_up_mw
max_ramp_up_from_hour
max_ramp_up_to_hour

max_ramp_down_mw
max_ramp_down_from_hour
max_ramp_down_to_hour
```

For a normal 24-hour day:

```text
daily_energy_mwh ≈ sum(hourly MW × 1 hour)
```

and:

```text
load_factor = average_load_mw / peak_load_mw
```

These are forecast analytics, not accuracy metrics.

MAE, RMSE, bias, and drift require actual ISO-NE load and belong to a later delayed-evaluation subsystem.

---

## 13. Persistence

### Parquet

Detailed hourly forecasts:

```text
offline/forecasts/
```

Naming:

```text
gridcast_{target_date}_{forecast_id_prefix}.parquet
```

### HTML reports

```text
offline/reports/
```

Naming:

```text
gridcast_{target_date}_{forecast_id_prefix}.html
```

### SQLite

Forecast-run summaries:

```text
offline/batch_results.db
```

Main table:

```text
forecast_runs
```

Multiple reruns for the same target date are retained because `forecast_id` is the primary key.

---

## 14. MLflow lineage

Two run IDs have different meanings.

### `model_run_id`

The training run that produced the current champion model.

### `mlflow_tracking_run_id`

The MLflow run created for this specific offline forecast execution.

Do not conflate them.

Tracking failure is non-critical: a valid forecast should still succeed even if MLflow execution logging fails.

---

## 15. Docker

The offline service has its own Dockerfile.

The current container command listens on:

```text
1012
```

Build from the **GridCast repository root** so the build context contains both `shared/` and `offline/`:

```bash
docker build   -f offline/Dockerfile   -t gridcast-offline .
```

The image should set:

```text
PYTHONPATH=/app
```

because the offline service imports shared infrastructure such as:

```python
from shared.model_loader import load_model
```

### Important: persistent model/storage access

The container needs access to:

- MLflow tracking database,
- registered-model artifacts,
- offline SQLite database,
- forecast Parquet artifacts,
- generated reports.

These should eventually be mounted/configured through Docker Compose rather than baked into the image.

---

## 16. Configuration

`config.py` centralizes offline storage and application configuration.

Useful deployment configuration includes:

```text
GRIDCAST_OFFLINE_DATA_DIR
MLFLOW_TRACKING_URI
MLFLOW_ARTIFACTS_ROOT
```

Weather latitude/longitude must remain fixed application configuration matching the training weather semantics.

---

## 17. Retry behavior

There are two retry layers.

### HTTP layer

`data_sources.py` handles transient upstream failures such as:

```text
connection reset
read timeout
429
500
502
503
504
```

### Prefect layer

Prefect provides an outer retry around the whole forecast task.

```text
Prefect attempt
    ↓
core.run_forecast()
    ↓
HTTP retries
```

Avoid excessive retry counts at both layers because retries multiply.

---

## 18. Known limitations

### Historical weather is not point-in-time forecast weather

ERA5 historical weather can make historical inference more informed than a true day-ahead operational forecast.

Future improvement:

```text
ERA5 historical weather
    ↓ replace with
archived weather forecast / model run
```

### ERA5 delay

Recent target dates are rejected because the application treats ERA5 as having approximately a five-day availability delay.

### DST handling

Normal days usually produce 24 rows.

`America/New_York` DST transition days may produce:

```text
23 hours
24 hours
25 hours
```

The current `Hr_End` logic still needs hardening for the repeated fall-back hour.

### FastAPI background jobs are in memory

Running-job and failure state is lost when the process restarts.

A future version should route API-triggered work through a durable Prefect deployment/worker.

### `/latest` can be stale during reruns

If a target already has a completed forecast and a new forecast for the same target is still running:

```http
GET /forecasts/target/{target_date}/latest
```

can temporarily return the previous run.

A stronger API design would return a `job_id` from `POST /forecast` and expose:

```text
GET /jobs/{job_id}
```

---

## 19. Current development status

Successfully tested:

```text
Historical ERA5 acquisition       ✓
Raw feature preparation           ✓
Serialized preprocessing          ✓
Champion model inference          ✓
Forecast analytics                ✓
HTML report generation            ✓
Parquet persistence               ✓
SQLite forecast history           ✓
MLflow execution tracking         ✓
FastAPI forecast submission       ✓
FastAPI forecast retrieval        ✓
Hourly forecast retrieval         ✓
HTML report endpoint              ✓
Prefect local orchestration       ✓
CLI execution                     ✓
```

Next infrastructure milestones:

```text
Docker image validation
    ↓
Docker Compose
    ↓
persistent MLflow/storage mounts
    ↓
API → durable Prefect execution
    ↓
Prometheus / Grafana monitoring
    ↓
delayed actual-load evaluation
```

---

## 20. Quick reference

### Start API

```bash
cd GridCast/offline

uvicorn api:app   --host 0.0.0.0   --port 8001   --reload
```

### Swagger

```text
http://localhost:8001/docs
```

### Trigger forecast

```text
POST /forecast?origin_date=2025-06-06
```

### List forecasts

```text
GET /forecasts
```

### Latest target forecast

```text
GET /forecasts/target/2025-06-07/latest
```

### Hourly data

```text
GET /forecasts/{forecast_id}/hourly
```

### HTML report

```text
GET /forecasts/{forecast_id}/report
```

### Prefect flow

```bash
python flow.py
```

### CLI

```bash
python main.py --origin-date 2025-06-06
```

### Docker build

From the GridCast repository root:

```bash
docker build   -f offline/Dockerfile   -t gridcast-offline .
```

---

## 21. Core design rule

GridCast Offline keeps orchestration, inference, persistence, reporting, and tracking separate:

```text
API / CLI
    ↓
orchestration
    ↓
core inference
    ↓
domain analytics
    ↓
artifacts + persistence
    ↓
execution tracking
```

The central rule is:

> **There should be one canonical forecast operation: `core.run_forecast()`.**

FastAPI, Prefect, CLI tools, Docker, and future UI components should invoke or orchestrate that operation rather than duplicate its business logic.
