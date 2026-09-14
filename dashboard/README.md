# ⚡ GridCast Dashboard

[![FastAPI](https://img.shields.io/badge/FastAPI-005571?logo=fastapi)](https://fastapi.tiangolo.com/)
[![Swagger UI](https://img.shields.io/badge/API%20Docs-Swagger%20UI-85EA2D?logo=swagger&logoColor=black)](https://swagger.io/tools/swagger-ui/)
[![Docker](https://img.shields.io/badge/Container-Docker-2496ED?logo=docker&logoColor=white)](https://www.docker.com/)
[![MLflow](https://img.shields.io/badge/Model%20Registry-MLflow-blue?logo=mlflow)](https://mlflow.org/)

A Streamlit-based user interface for the GridCast electricity-demand forecasting system.

The dashboard is the presentation layer of GridCast. It does **not** load models directly, read SQLite directly, or open Parquet files from the filesystem. Instead, it communicates with the GridCast APIs over HTTP:

```text
User
 │
 ▼
GridCast Dashboard
 │
 ├──► Online FastAPI  ──► single live prediction
 │
 └──► Offline FastAPI ──► day forecast, history, reports, downloads
```

This separation keeps the UI independent from the model-serving and offline-processing implementations and makes the system easier to run locally or later through Docker Compose.

---

## 1. Dashboard Responsibilities

The dashboard provides five main areas:

### Overview

The landing page gives a compact operational view of GridCast:

- Online API availability
- Offline API availability
- Number of stored forecasts
- Number of running jobs
- Latest forecast KPIs
- Latest 24-hour demand curve
- Recent forecast history

### Live Prediction

Runs one synchronous prediction through the online API.

The dashboard dynamically reads the online FastAPI OpenAPI schema and builds the form from the `/predict` request model.

The date field uses:

```text
YYYY-MM-DD
```

Example:

```text
2025-07-04
```

The returned prediction is shown as a formatted GridCast result card instead of raw JSON.

### Day Forecast

Allows a user to select an origin date and trigger the offline day-ahead forecasting pipeline.

Example:

```text
Origin date: 2025-06-06
Target date: 2025-06-07
```

The dashboard:

1. Checks whether a forecast already exists for the target date.
2. Calls `POST /forecast`.
3. Waits for a **new** persisted forecast result.
4. Checks the failure endpoint while waiting.
5. Avoids returning an older forecast during a rerun.
6. Displays forecast KPIs, charts, hourly data, and exports.

### Forecast History

Displays persisted forecasts without exposing unnecessary ML engineering metadata to normal users.

The user-facing history includes:

- Forecast date
- Peak demand
- Peak hour
- Average demand
- Daily energy
- Load factor
- Generation time

Users can open any stored forecast and inspect:

- KPI cards
- 24-hour load profile
- Weather drivers
- Hourly forecast table
- HTML report download
- Parquet data download

### System

Provides operational information for the dashboard:

- Online API health
- Offline API health
- Running offline jobs
- Recent offline failures
- API configuration

Model lineage remains available in MLflow and backend persistence but is intentionally not emphasized in the normal forecast-history UI.

---

## 2. Dashboard Directory

Recommended structure:

```text
dashboard/
├── app.py
├── Dockerfile
├── requirements.txt
├── README.md
└── .streamlit/
    └── config.toml
```

---

## 3. Runtime Architecture

For local development:

```text
┌────────────────────────────────────────────┐
│ Host machine                               │
│                                            │
│ Online API     http://127.0.0.1:8000       │
│ Offline API    http://127.0.0.1:8001       │
│ Dashboard      http://0.0.0.0:8501         │
└────────────────────────────────────────────┘
```

If another device on the same network accesses the dashboard:

```text
http://<HOST_LAN_IP>:8501
```

Example:

```text
http://192.168.1.101:8501
```

The browser connects to Streamlit through the LAN IP, while the Streamlit Python process itself calls the APIs through `127.0.0.1`.

---

## 4. Requirements

The dashboard directly depends on:

- Streamlit
- Pandas
- Requests
- urllib3

Generate the pinned requirements from the working virtual environment:

```bash
cd ~/GridCast/dashboard

uv pip freeze \
  | grep -E "^(streamlit|pandas|requests|urllib3)==" \
  > requirements.txt
```

Inspect the file:

```bash
cat requirements.txt
```

Example:

```text
pandas==3.0.5
requests==2.34.2
streamlit==<installed-version>
urllib3==<installed-version>
```

Using the versions already proven to work locally is preferable to guessing package versions.

---

## 5. Streamlit Configuration

Create:

```text
dashboard/.streamlit/config.toml
```

with:

```toml
[server]
address = "0.0.0.0"
port = 8501
headless = true
```

This means the normal startup command can remain simple:

```bash
streamlit run app.py
```

You do not need to repeatedly type:

```bash
--server.address 0.0.0.0
--server.port 8501
```

---

## 6. Environment Variables

The dashboard supports:

```text
ONLINE_API_URL
OFFLINE_API_URL
DASHBOARD_CONNECT_TIMEOUT
DASHBOARD_READ_TIMEOUT
DASHBOARD_POLL_SECONDS
DASHBOARD_MAX_WAIT_SECONDS
```

Defaults:

```text
ONLINE_API_URL=http://localhost:8000
OFFLINE_API_URL=http://localhost:8001
DASHBOARD_CONNECT_TIMEOUT=3
DASHBOARD_READ_TIMEOUT=30
DASHBOARD_POLL_SECONDS=2
DASHBOARD_MAX_WAIT_SECONDS=240
```

For normal local development, the defaults are sufficient if the APIs use ports `8000` and `8001`.

Explicit override example:

```bash
ONLINE_API_URL=http://127.0.0.1:8000 \
OFFLINE_API_URL=http://127.0.0.1:8001 \
streamlit run app.py
```

---

## 7. API Contract Used by the Dashboard

### Online API

Required:

```text
GET  /health
GET  /openapi.json
POST /predict
```

The dashboard uses `/openapi.json` to inspect the `/predict` request schema and create the live prediction form.

### Offline API

Required:

```text
GET  /health
POST /forecast?origin_date=YYYY-MM-DD
GET  /forecasts
GET  /forecasts/target/{target_date}/latest
GET  /forecasts/{forecast_id}
GET  /forecasts/{forecast_id}/hourly
GET  /forecasts/{forecast_id}/report
GET  /forecasts/{forecast_id}/parquet
GET  /running
GET  /failures
```

---

## 8. Required Parquet Download Endpoint

The dashboard expects:

```text
GET /forecasts/{forecast_id}/parquet
```

Add this endpoint to `offline/api.py` if it is not already present:

```python
from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import FileResponse


@app.get("/forecasts/{forecast_id}/parquet")
def download_forecast_parquet(
    forecast_id: str,
):
    result = get_forecast_run(
        forecast_id
    )

    if result is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Unknown forecast_id: "
                f"{forecast_id}"
            ),
        )

    forecast_path = Path(
        result["forecast_path"]
    )

    if not forecast_path.exists():
        raise HTTPException(
            status_code=404,
            detail=(
                "Stored Parquet forecast "
                "artifact does not exist."
            ),
        )

    return FileResponse(
        path=forecast_path,
        media_type=(
            "application/vnd.apache.parquet"
        ),
        filename=forecast_path.name,
    )
```

After adding the route, restart the offline API.

---

# 9. Direct Local Test

This is the recommended first test before Docker.

You need three running processes.

## Terminal 1 — Online API

```bash
cd ~/GridCast/online

uvicorn main:app \
  --host 0.0.0.0 \
  --port 8000 \
  --reload
```

Verify:

```bash
curl http://127.0.0.1:8000/health
```

Expected result:

```text
HTTP request succeeds and returns JSON.
```

---

## Terminal 2 — Offline API

```bash
cd ~/GridCast/offline

uvicorn api:app \
  --host 0.0.0.0 \
  --port 8001 \
  --reload
```

Verify:

```bash
curl http://127.0.0.1:8001/health
```

Expected result:

```text
HTTP request succeeds and returns JSON.
```

Check forecast history:

```bash
curl http://127.0.0.1:8001/forecasts
```

Check running jobs:

```bash
curl http://127.0.0.1:8001/running
```

Check recent failures:

```bash
curl http://127.0.0.1:8001/failures
```

---

## Terminal 3 — Dashboard

If `.streamlit/config.toml` exists:

```bash
cd ~/GridCast/dashboard

streamlit run app.py
```

Otherwise:

```bash
cd ~/GridCast/dashboard

streamlit run app.py \
  --server.address 0.0.0.0 \
  --server.port 8501
```

Open locally:

```text
http://127.0.0.1:8501
```

Or from another device on the same LAN:

```text
http://<HOST_LAN_IP>:8501
```

Example:

```text
http://192.168.1.101:8501
```

---

# 10. Manual Functional Test Checklist

Use this sequence after starting all three services.

## Test A — Service Status

Open the dashboard.

Expected:

```text
Online API  ● available
Offline API ● available
```

If either is unavailable, test the corresponding `/health` endpoint directly with `curl`.

---

## Test B — Live Prediction

Open:

```text
Live Prediction
```

Enter a valid date using:

```text
YYYY-MM-DD
```

Example:

```text
2025-07-04
```

Fill in the remaining fields.

Click:

```text
Run live prediction
```

Expected:

- No Streamlit exception
- No raw JSON as the primary output
- A formatted prediction card
- Prediction shown in MW
- Optional technical details in an expander

---

## Test C — Invalid Date

Enter something invalid:

```text
07/04/2025
```

Expected:

```text
Date must use YYYY-MM-DD format.
Example: 2025-07-04.
```

No request should be sent to the online API.

---

## Test D — Offline Forecast

Open:

```text
Day Forecast
```

Select a historical origin date that satisfies the current ERA5 delay restriction.

Example:

```text
Origin: 2025-06-06
Target: 2025-06-07
```

Click:

```text
Run day forecast
```

Expected sequence:

```text
Request accepted
      ↓
Processing
      ↓
New forecast detected
      ↓
Forecast completed
```

Then verify:

- Peak-demand card
- Minimum-demand card
- Average-demand card
- Daily-energy card
- Load-factor card
- 24-hour demand chart
- Weather chart
- Hourly table
- HTML download
- Parquet download

---

## Test E — Forecast Rerun

Run the same origin date again.

The dashboard must not immediately show the older stored forecast.

Its logic records the existing forecast ID before triggering a new job and waits until `/latest` returns a different forecast ID.

This protects against stale-rerun behavior.

---

## Test F — Forecast History

Open:

```text
Forecast History
```

Expected:

- Stored forecast table
- No model version in the normal user-facing table
- Forecast selector
- Forecast KPIs
- Load chart
- Weather chart
- Hourly table
- HTML download button
- Parquet download button

---

## Test G — HTML Download

Select a stored forecast and click:

```text
Download HTML report
```

Expected:

```text
HTTP 200
```

The browser should download a file similar to:

```text
gridcast_2025-06-07_<forecast-id-prefix>.html
```

---

## Test H — Parquet Download

Select a stored forecast and click:

```text
Download Parquet data
```

Expected offline API log:

```text
GET /forecasts/<forecast_id>/parquet HTTP/1.1 200 OK
```

If you see:

```text
404 Not Found
```

verify that the `/parquet` route was added and that the offline API was restarted.

Direct endpoint test:

```bash
curl -I \
  http://127.0.0.1:8001/forecasts/<forecast_id>/parquet
```

Expected:

```text
HTTP/1.1 200 OK
```

---

## Test I — Failure Handling

Stop the offline API.

Refresh the dashboard.

Expected:

```text
Offline API → unavailable
```

The dashboard should remain usable and should not crash.

Restart the API and refresh again.

Expected:

```text
Offline API → available
```

---

# 11. Error-Handling Strategy

The dashboard intentionally handles failures at the UI/API boundary.

## GET Requests

GET requests use a retry policy for transient failures:

```text
429
500
502
503
504
```

Retries also cover temporary connection/read failures.

## POST Requests

`POST /forecast` is **not automatically retried**.

This is intentional.

Retrying a forecast-trigger POST automatically could create duplicate jobs.

If the request times out, the user is instructed to inspect:

```text
/running
/failures
```

before submitting again.

## Forecast Polling

During an offline forecast, the dashboard:

1. Saves the previous latest forecast ID.
2. Sends the new forecast trigger.
3. Polls `/failures`.
4. Polls `/forecasts/target/{target_date}/latest`.
5. Waits until a different forecast ID appears.
6. Stops after the configured maximum wait time.

This prevents stale historical results from being mistaken for the newly requested forecast.

---

# 12. Dashboard Dockerfile

Recommended:

```dockerfile
FROM python:3.12-slim

RUN pip install --no-cache-dir uv

WORKDIR /app

COPY dashboard/ ./dashboard/

WORKDIR /app/dashboard

RUN uv pip install \
    --system \
    --no-cache \
    -r requirements.txt

EXPOSE 8501

CMD [
    "streamlit",
    "run",
    "app.py",
    "--server.address=0.0.0.0",
    "--server.port=8501",
    "--server.headless=true"
]
```

Build from the GridCast project root:

```bash
cd ~/GridCast

docker build \
  -f dashboard/Dockerfile \
  -t gridcast-dashboard .
```

---

# 13. Test the Dashboard Container Directly

If the APIs are still running directly on the host machine:

```bash
docker run \
  --rm \
  -p 8501:8501 \
  -e ONLINE_API_URL=http://host.docker.internal:8000 \
  -e OFFLINE_API_URL=http://host.docker.internal:8001 \
  --add-host=host.docker.internal:host-gateway \
  gridcast-dashboard
```

Open:

```text
http://127.0.0.1:8501
```

or from another LAN device:

```text
http://<HOST_LAN_IP>:8501
```

Example:

```text
http://192.168.1.101:8501
```

---

# 14. Why `localhost` Changes in Docker

When Streamlit runs directly on the host:

```text
localhost:8000
```

means:

```text
host machine → online API
```

When Streamlit runs inside a container:

```text
localhost
```

means:

```text
dashboard container itself
```

Therefore this is normally wrong inside the dashboard container:

```text
ONLINE_API_URL=http://localhost:8000
OFFLINE_API_URL=http://localhost:8001
```

For a standalone container talking to host services, use:

```text
host.docker.internal
```

For Docker Compose, use service names instead.

Example future Compose networking:

```text
dashboard
   │
   ├──► http://online:8000
   │
   └──► http://offline:<offline-container-port>
```

---

# 15. Future Docker Compose Configuration

The dashboard should eventually receive API URLs through Compose:

```yaml
dashboard:
  build:
    context: .
    dockerfile: dashboard/Dockerfile

  environment:
    ONLINE_API_URL: http://online:8000
    OFFLINE_API_URL: http://offline:1012

  ports:
    - "8501:8501"

  depends_on:
    - online
    - offline
```

The exact offline internal port must match the offline container configuration.

If the offline Dockerfile runs Uvicorn on:

```text
1012
```

then Compose should use:

```text
http://offline:1012
```

inside the Docker network.

The host can still map another external port if desired.

---

# 16. UI Design Principles

The GridCast dashboard intentionally does not duplicate the NYC Taxi reference UI.

The visual structure uses:

- Sidebar navigation
- Large GridCast hero panels
- Page-specific visual icons
- Equal-size forecast KPI cards
- Forecast curves
- Weather-driver curves
- Expandable technical details
- User-focused forecast history
- Direct report/data exports

The dashboard prioritizes:

```text
What is the forecast?
When is the peak?
How much energy is expected?
How does demand change through the day?
Can I inspect or export the result?
```

rather than exposing internal MLOps implementation details to normal users.

---

# 17. Current Forecast Analytics

The offline API currently provides:

```text
Peak load
Peak hour
Minimum load
Minimum hour
Average load
Daily energy
Load factor
Maximum ramp up
Maximum ramp down
```

These are forecast/business analytics.

They are not model-quality monitoring metrics.

Metrics such as:

```text
MAE
RMSE
Bias
Feature drift
Prediction drift
```

belong to the future monitoring/evaluation subsystem after actual ISO-NE load becomes available.

---

# 18. Current Weather Limitation

The current offline forecast replay uses Open-Meteo historical ERA5 weather.

This is useful for demonstrating the full historical forecast workflow, but it is not a strict point-in-time operational backtest because ERA5 is realized/reanalysis weather rather than archived forecast weather.

The UI should therefore be interpreted as:

```text
historical forecast replay
```

not:

```text
perfect reconstruction of what weather information was available at that historical origin time
```

The data-source implementation can later be replaced without changing the dashboard API contract.

---

# 19. Known Limitations

Current known limitations include:

- Offline jobs use in-process background execution.
- Running/failure state is held in memory by the API.
- Running/failure state disappears if the offline API process restarts.
- The offline API currently triggers the canonical forecast operation directly rather than a durable Prefect deployment.
- Historical weather currently uses ERA5 realized/reanalysis weather.
- DST transition days may contain 23 or 25 timestamps.
- Forecast polling currently relies on a changed forecast ID to distinguish reruns.
- The dashboard requires both APIs to expose stable HTTP contracts.

These are acceptable for the current project stage.

---

# 20. Development Rules

The following architectural rules should remain in place:

### Rule 1

The dashboard must not import:

```python
offline.core
offline.persistence
shared.model_loader
```

### Rule 2

The dashboard must not directly open:

```text
batch_results.db
forecasts/*.parquet
reports/*.html
```

### Rule 3

The dashboard communicates with backend services over HTTP.

### Rule 4

`offline/core.py::run_forecast()` remains the canonical offline forecast operation.

The dashboard must not reproduce forecast logic.

### Rule 5

Model loading and inference remain backend responsibilities.

The dashboard should only collect user inputs and render responses.

---

# 21. Troubleshooting

## Dashboard shows both APIs as unavailable

Test:

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8001/health
```

If either returns:

```text
Connection refused
```

that service is not listening on the expected port.

---

## Streamlit crashes with `StreamlitValueBelowMinError`

This means the generated numeric widget received a default value lower than the API schema's minimum.

The dynamic form must initialize bounded fields using:

```text
API default
    ↓ if absent
API minimum
    ↓ if absent
0
```

and then clamp the initial value to the declared minimum/maximum.

---

## Date validation fails

Use:

```text
YYYY-MM-DD
```

Example:

```text
2025-07-04
```

Do not use:

```text
07/04/2025
04-07-2025
July 4 2025
```

---

## HTML works but Parquet returns 404

Check:

```bash
curl -I \
  http://127.0.0.1:8001/forecasts/<forecast_id>/parquet
```

If it returns 404:

1. Confirm the route exists in `offline/api.py`.
2. Restart the offline API.
3. Confirm `forecast_path` exists in the stored forecast record.
4. Confirm the actual Parquet file still exists.

---

## Dashboard container cannot reach host APIs

Inside Docker, `localhost` points to the dashboard container.

Run with:

```bash
--add-host=host.docker.internal:host-gateway
```

and:

```text
ONLINE_API_URL=http://host.docker.internal:8000
OFFLINE_API_URL=http://host.docker.internal:8001
```

---

# 22. Quick Start

For the fastest local test:

```bash
# Terminal 1
cd ~/GridCast/online
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

```bash
# Terminal 2
cd ~/GridCast/offline
uvicorn api:app --host 0.0.0.0 --port 8001 --reload
```

```bash
# Terminal 3
cd ~/GridCast/dashboard
streamlit run app.py
```

Then open:

```text
http://127.0.0.1:8501
```

or from another device:

```text
http://<HOST_LAN_IP>:8501
```

---

# 23. Current Status

Dashboard functionality currently covers:

- [x] Online API health
- [x] Offline API health
- [x] Dynamic live prediction form
- [x] Date-format guidance
- [x] Numeric schema validation
- [x] Formatted live prediction result
- [x] Offline forecast triggering
- [x] Forecast completion polling
- [x] Failure checking
- [x] Stale-rerun protection
- [x] Forecast KPIs
- [x] Equal-size KPI cards
- [x] Demand profile visualization
- [x] Weather visualization
- [x] Hourly table
- [x] Forecast history
- [x] HTML report download
- [x] Parquet download
- [x] Running-job visibility
- [x] Failure visibility
- [x] Local execution
- [x] Standalone Docker image support
- [ ] Docker Compose integration
- [ ] Durable background job orchestration
- [ ] Production monitoring integration
- [ ] Delayed model-performance evaluation
- [ ] Authentication / authorization

---

## Summary

The GridCast dashboard is intentionally a thin API-driven presentation layer.

Its core boundary is:

```text
Dashboard
   ↓ HTTP
FastAPI services
   ↓
GridCast application logic
```

That boundary should remain intact as GridCast moves from local development to Docker Compose and later to monitoring, durable orchestration, and production deployment.
