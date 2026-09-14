# GridCast Local Docker Deployment — End-to-End Test Guide

This document explains how to reproduce the complete local Docker deployment test for GridCast.

The purpose of this test is to prove that the deployment bundle works end to end before moving it to a VPS.

The validated deployment contains four services:

```text
MLflow       -> port 1010
Online API   -> port 1011
Offline API  -> port 1012
Dashboard    -> port 1013
```

The expected architecture is:

```text
                         +-------------------+
                         |      MLflow       |
                         |      :1010        |
                         +---------+---------+
                                   |
                      +------------+------------+
                      |                         |
                      v                         v
             +----------------+        +----------------+
             |   Online API   |        |  Offline API   |
             |     :1011      |        |     :1012      |
             +--------+-------+        +--------+-------+
                      |                         |
                      +------------+------------+
                                   |
                                   v
                         +-------------------+
                         |     Dashboard     |
                         |      :1013        |
                         +-------------------+
```

The complete test proves:

```text
MLflow server                 -> working
remote-style model registry   -> working
@champion alias               -> working
model artifact loading        -> working
preprocessor loading          -> working
online inference API          -> working
offline forecasting API       -> working
ERA5 historical weather       -> working
forecast persistence          -> working
Parquet generation            -> working
HTML report generation        -> working
MLflow forecast tracking      -> working
dashboard                     -> working
```

---

# 1. Prerequisites

Run all commands from the machine where the GridCast project exists.

The project used during this test was:

```text
~/GridCast
```

The deployment bundle was:

```text
~/GridCast/GridCast_deployment
```

Expected deployment structure:

```text
GridCast_deployment/
├── dashboard/
│   ├── app.py
│   ├── Dockerfile
│   └── requirements.txt
│
├── offline/
│   ├── analytics.py
│   ├── api.py
│   ├── config.py
│   ├── core.py
│   ├── data_sources.py
│   ├── Dockerfile
│   ├── flow.py
│   ├── __init__.py
│   ├── main.py
│   ├── persistence.py
│   ├── report.py
│   ├── requirements.txt
│   └── tracking.py
│
├── online/
│   ├── Dockerfile
│   ├── main.py
│   ├── model_loader.py
│   ├── requirements.txt
│   └── schema.py
│
├── shared/
│   ├── feature_engineering.py
│   ├── __init__.py
│   └── model_loader.py
│
├── docker-compose.yml
└── .dockerignore
```

Do not include the training pipeline inside this deployment bundle.

Training remains in the main GridCast project.

---

# 2. Service Ports

The deployment uses:

| Service | Port |
|---|---:|
| MLflow | 1010 |
| Online API | 1011 |
| Offline API | 1012 |
| Dashboard | 1013 |

The Dockerfiles and `docker-compose.yml` must agree with these ports.

---

# 3. Validate the Docker Compose File

## Where to run

```bash
cd ~/GridCast/GridCast_deployment
```

## Command

```bash
docker compose config
```

## Expected result

Docker Compose should print the fully resolved configuration.

You should see services similar to:

```text
mlflow
online
offline
dashboard
```

You should also see the generated default network:

```text
gridcast_deployment_default
```

You should not see:

```text
no configuration file provided
```

If you do, verify the filename is exactly:

```text
docker-compose.yml
```

not:

```text
docker-comose.yml
```

---

# 4. Start MLflow First

MLflow must be running before the model-serving containers start.

## Where to run

```bash
cd ~/GridCast/GridCast_deployment
```

## Command

```bash
docker compose up -d mlflow
```

## Expected output

Something similar to:

```text
[+] Running 2/2
 ✔ Network gridcast_deployment_default  Created
 ✔ Container gridcast-mlflow            Started
```

---

# 5. Check MLflow Container State

## Command

```bash
docker compose ps
```

## Expected output

Initially:

```text
gridcast-mlflow   Up ... (health: starting)
```

After the health check completes:

```text
gridcast-mlflow   Up ... (healthy)
```

The port mapping should look like:

```text
127.0.0.1:1010->1010/tcp
```

This is intentional.

MLflow is available locally on the host, but is not exposed to every external network interface.

---

# 6. Test MLflow Health

## Command

```bash
curl -i http://127.0.0.1:1010/health
```

## Expected output

```text
HTTP/1.1 200 OK
...
OK
```

A successful `200 OK` means the MLflow server is reachable.

---

# 7. Inspect MLflow Logs

## Command

```bash
docker compose logs mlflow
```

## Important expected messages

You should see messages similar to:

```text
Creating initial MLflow database tables...
Updating database tables
Uvicorn running on http://0.0.0.0:1010
Application startup complete.
```

Warnings such as:

```text
Accepting ALL hosts
```

are not blockers for this local validation because MLflow is bound on the host to:

```text
127.0.0.1:1010
```

---

# 8. Verify MLflow Persistence Directories

## Command

```bash
ls -la
```

## Expected result

The deployment folder should now contain:

```text
mlflow/
mlruns/
```

For example:

```text
GridCast_deployment/
├── mlflow/
├── mlruns/
├── dashboard/
├── offline/
├── online/
├── shared/
└── docker-compose.yml
```

The `mlflow/` directory stores the MLflow SQLite backend.

The `mlruns/` directory stores artifacts served by MLflow.

The directories may be owned by `root` because Docker created them.

That is not a runtime error.

---

# 9. Point the Training Environment to the New MLflow Server

The deployment MLflow instance starts empty.

A model must be trained and registered into this registry before the Online and Offline services can load `@champion`.

## Where to run

Open a normal host terminal, not inside a container.

```bash
cd ~/GridCast
source .venv/bin/activate
```

Set the MLflow tracking URI:

```bash
export MLFLOW_TRACKING_URI=http://127.0.0.1:1010
```

Verify:

```bash
echo $MLFLOW_TRACKING_URI
```

## Expected output

```text
http://127.0.0.1:1010
```

---

# 10. Verify Python Sees the Same MLflow URI

## Command

```bash
python - <<'PY'
import os
import mlflow

print("Tracking URI env:", os.getenv("MLFLOW_TRACKING_URI"))
print("MLflow tracking URI:", mlflow.get_tracking_uri())
PY
```

## Expected output

```text
Tracking URI env: http://127.0.0.1:1010
MLflow tracking URI: http://127.0.0.1:1010
```

If these do not match, do not start training yet.

---

# 11. Run the Training Pipeline Against the Deployment MLflow

## Where to run

```bash
cd ~/GridCast/pipeline
```

Make sure the same shell still contains:

```text
MLFLOW_TRACKING_URI=http://127.0.0.1:1010
```

## Command

```bash
python main.py
```

## Expected behavior

The training pipeline should:

```text
load data
preprocess data
split chronologically
engineer features
train multiple models
select the best model
tune the best model
evaluate on the test set
register the model in MLflow
save the preprocessor artifact
set model aliases
```

During the successful test, the deployment registry eventually contained:

```text
@champion   -> version 16
@challenger -> version 16
```

The exact version number will change on future runs.

Do not hard-code `v16`.

What matters is that `@champion` exists.

---

# 12. Verify MLflow Aliases

## Where to run

```bash
cd ~/GridCast
export MLFLOW_TRACKING_URI=http://127.0.0.1:1010
```

## Command

```bash
python - <<'PY'
from mlflow import MlflowClient

client = MlflowClient()
model_name = "grid_load_model"

for alias in ["champion", "challenger"]:
    try:
        mv = client.get_model_version_by_alias(
            model_name,
            alias,
        )

        print(
            f"@{alias}: "
            f"version={mv.version}, "
            f"run_id={mv.run_id}"
        )

    except Exception:
        print(f"@{alias}: NOT FOUND")
PY
```

## Expected output

The exact version and run ID will differ, but you must see:

```text
@champion: version=<some-version>, run_id=<run-id>
```

A valid example from the successful test was:

```text
@champion: version=16, run_id=05e830f6f32c4ac1930601355cf1da94
@challenger: version=16, run_id=05e830f6f32c4ac1930601355cf1da94
```

If `@champion` says:

```text
NOT FOUND
```

the serving services should not be started yet.

---

# 13. Verify the Shared Model Loader

Before building the serving container, verify that the same model loader used by GridCast can load the champion through HTTP MLflow.

## Where to run

```bash
cd ~/GridCast
```

## Command

```bash
python - <<'PY'
from shared.model_loader import load_model

champion = load_model()

print("version:", champion.version)
print("alias:", champion.alias)
print("run_id:", champion.run_id)
print("model type:", type(champion.model).__name__)
print("preprocessor type:", type(champion.preprocessor).__name__)
PY
```

## Expected output

The exact version and run ID can change.

The important values are:

```text
alias: champion
model type: XGBRegressor
preprocessor type: Pipeline
```

The successful test returned:

```text
version: v16
alias: champion
run_id: 05e830f6f32c4ac1930601355cf1da94
model type: XGBRegressor
preprocessor type: Pipeline
```

This proves that:

```text
shared/model_loader.py
        ->
MLflow HTTP server
        ->
grid_load_model@champion
        ->
model + preprocessor
```

works before Docker serving starts.

---

# 14. Build the Online API Image

## Where to run

```bash
cd ~/GridCast/GridCast_deployment
```

## Command

```bash
docker compose build --no-cache online
```

## Expected output

The build should end with something similar to:

```text
[online] exporting to image
naming to docker.io/library/gridcast_deployment-online
```

There must be no Dockerfile parsing error.

---

# 15. Important Online Runtime Dependency

During the first online-container test, the container failed with:

```text
ModuleNotFoundError: No module named 'holidays'
```

The reason was that the serialized preprocessing pipeline imports:

```python
shared.feature_engineering
```

and that module imports:

```python
holidays
```

Therefore `online/requirements.txt` must contain:

```text
holidays==0.103
```

This dependency is required even if `online/main.py` does not directly import `holidays`.

After changing requirements, rebuild with:

```bash
docker compose build --no-cache online
```

Do not retrain the model for this error.

It is an image dependency issue, not a model-registry issue.

---

# 16. Start the Online API

## Command

```bash
docker compose up -d online
```

## Expected output

```text
✔ Container gridcast-mlflow  Healthy
✔ Container gridcast-online  Started
```

---

# 17. Check Online Container Logs

## Command

```bash
docker compose logs --tail=100 online
```

## Expected output

```text
Started server process
Waiting for application startup.
Application startup complete.
Uvicorn running on http://0.0.0.0:1011
```

If the container keeps restarting, check:

```bash
docker compose ps
```

A restarting container indicates an application startup failure.

---

# 18. Test Online API Health

## Command

```bash
curl -i http://127.0.0.1:1011/health
```

## Expected output

```text
HTTP/1.1 200 OK
```

and JSON similar to:

```json
{
  "status": "ok",
  "model_version": "v16",
  "model_alias": "champion"
}
```

The model version can change.

The important checks are:

```text
status        -> ok
model_alias   -> champion
```

---

# 19. Build the Offline API Image

## Where to run

```bash
cd ~/GridCast/GridCast_deployment
```

## Command

```bash
docker compose build --no-cache offline
```

## Expected output

The build should complete with something similar to:

```text
[offline] exporting to image
naming to docker.io/library/gridcast_deployment-offline
```

---

# 20. Start the Offline API

## Command

```bash
docker compose up -d offline
```

## Expected output

```text
✔ Container gridcast-mlflow   Healthy
✔ Container gridcast-offline  Started
```

---

# 21. Inspect Offline Logs

## Command

```bash
docker compose logs --tail=150 offline
```

## Expected output

```text
Started server process
Waiting for application startup.
Application startup complete.
Uvicorn running on http://0.0.0.0:1012
```

---

# 22. Test Offline API Health

## Command

```bash
curl -i http://127.0.0.1:1012/health
```

## Expected output

```text
HTTP/1.1 200 OK
```

and JSON similar to:

```json
{
  "status": "ok",
  "forecasts_stored": 0,
  "running_jobs": 0,
  "failed_jobs": 0,
  "db": "/app/offline/data/batch_results.db",
  "forecasts_dir": "/app/offline/data/forecasts",
  "reports_dir": "/app/offline/data/reports"
}
```

The important part is that the persistence paths point to:

```text
/app/offline/data
```

That proves this environment variable is working:

```text
GRIDCAST_OFFLINE_DATA_DIR=/app/offline/data
```

---

# 23. Trigger a Real Offline Forecast

This is the most important functional test for the offline container.

## Command

```bash
curl -X POST   "http://127.0.0.1:1012/forecast?origin_date=2025-06-06"
```

## Expected response

Something similar to:

```json
{
  "status": "started",
  "origin_date": "2025-06-06",
  "target_date": "2025-06-07",
  "message": "..."
}
```

This means the background forecast operation was accepted.

---

# 24. Check Running Jobs

Immediately after triggering:

```bash
curl -s http://127.0.0.1:1012/running
```

Depending on timing, you may see the job listed.

If the job finishes quickly, the result may already be empty.

That is normal.

---

# 25. Check Forecast Results

After the forecast completes:

```bash
curl -s http://127.0.0.1:1012/forecasts
```

## Expected result

You should receive at least one stored forecast.

A successful example contained:

```text
origin_date       -> 2025-06-06
target_date       -> 2025-06-07
model_alias       -> champion
weather_source    -> open_meteo_era5
total_hours       -> 24
```

The tested forecast also generated analytics such as:

```text
peak_load_mw        -> 13936.3359375
peak_hour           -> 14
minimum_load_mw     -> 10587.5576171875
minimum_hour        -> 3
average_load_mw     -> 12491.30517578125
daily_energy_mwh    -> 299791.32421875
load_factor         -> 0.896312...
```

The exact values can differ if the model or weather source changes.

---

# 26. Verify Offline Persistence on the Host

## Command

```bash
ls -R offline_data
```

## Expected output

```text
offline_data:
batch_results.db  forecasts  reports

offline_data/forecasts:
gridcast_<target-date>_<id>.parquet

offline_data/reports:
gridcast_<target-date>_<id>.html
```

During the successful test:

```text
offline_data/
├── batch_results.db
├── forecasts/
│   └── gridcast_2025-06-07_a27a8c37.parquet
└── reports/
    └── gridcast_2025-06-07_a27a8c37.html
```

This proves the Docker bind mount is working:

```text
host:
./offline_data

container:
/app/offline/data
```

The forecast data survives container recreation.

---

# 27. Verify Offline MLflow Tracking

The forecast response should contain:

```text
mlflow_tracking_run_id
```

This is the MLflow run for the offline forecast execution.

Do not confuse it with:

```text
model_run_id
```

They represent different things.

```text
model_run_id
    -> training run that produced @champion

mlflow_tracking_run_id
    -> this particular offline forecast execution
```

---

# 28. Build the Dashboard Image

## Where to run

```bash
cd ~/GridCast/GridCast_deployment
```

## Command

```bash
docker compose build --no-cache dashboard
```

## Expected output

The build should end with:

```text
[dashboard] exporting to image
naming to docker.io/library/gridcast_deployment-dashboard
```

---

# 29. Start the Dashboard

## Command

```bash
docker compose up -d dashboard
```

## Expected output

```text
gridcast-mlflow     Healthy
gridcast-offline    Healthy
gridcast-online     Healthy
gridcast-dashboard  Started
```

---

# 30. Test Dashboard HTTP Reachability

## Command

```bash
curl -I http://127.0.0.1:1013
```

## Expected output

```text
HTTP/1.1 200 OK
```

The successful test returned a normal Streamlit HTML response.

---

# 31. Open the Dashboard in a Browser

On the same machine:

```text
http://127.0.0.1:1013
```

From another device on the same LAN:

```text
http://<HOST_LAN_IP>:1013
```

Example:

```text
http://192.168.1.101:1013
```

Inside Docker, the dashboard does not use `localhost` to contact the APIs.

It uses Docker service names:

```text
ONLINE_API_URL=http://online:1011
OFFLINE_API_URL=http://offline:1012
```

That is required because:

```text
localhost inside dashboard container
```

means:

```text
the dashboard container itself
```

not the Online or Offline containers.

---

# 32. Final Full-System Status Check

## Command

```bash
docker compose ps
```

## Expected state

You should see:

```text
gridcast-mlflow      healthy
gridcast-online      healthy
gridcast-offline     healthy
gridcast-dashboard   up
```

The Dashboard service does not currently require its own Compose health check.

---

# 33. Final Curl Smoke Test

Run:

```bash
curl -s http://127.0.0.1:1010/health
```

Expected:

```text
OK
```

Run:

```bash
curl -s http://127.0.0.1:1011/health
```

Expected:

```json
{
  "status": "ok",
  "model_version": "...",
  "model_alias": "champion"
}
```

Run:

```bash
curl -s http://127.0.0.1:1012/health
```

Expected:

```json
{
  "status": "ok",
  "forecasts_stored": 1
}
```

Run:

```bash
curl -s -o /dev/null -w "%{http_code}
"   http://127.0.0.1:1013
```

Expected:

```text
200
```

---

# 34. Stop the Deployment

To stop all containers:

```bash
cd ~/GridCast/GridCast_deployment

docker compose down
```

This removes the containers and Compose network.

It does not delete bind-mounted data.

The following remain on the host:

```text
mlflow/
mlruns/
offline_data/
```

---

# 35. Restart the Deployment

Because the model registry and offline forecast data are persistent, the stack can be restarted without retraining if the registry already contains a valid `@champion`.

## Command

```bash
cd ~/GridCast/GridCast_deployment

docker compose up -d
```

Then verify:

```bash
docker compose ps
```

Expected:

```text
mlflow     healthy
online     healthy
offline    healthy
dashboard  up
```

If application code or requirements changed, rebuild:

```bash
docker compose up -d --build
```

---

# 36. When to Use `--no-cache`

Use:

```bash
docker compose build --no-cache <service>
```

when you intentionally want to force a completely fresh image build.

This is useful after:

```text
requirements changes
dependency fixes
Dockerfile changes
suspected stale build cache
```

For normal repeated development builds, use:

```bash
docker compose build <service>
```

Docker layer caching makes this substantially faster.

---

# 37. Important Error Seen During Testing

## Error

```text
ModuleNotFoundError: No module named 'holidays'
```

The container then reported:

```text
RuntimeError: Preprocessor not found ...
```

The second message was misleading.

The real problem was that the preprocessor existed but could not be deserialized because the `holidays` dependency was missing.

## Fix

Add:

```text
holidays==0.103
```

to:

```text
online/requirements.txt
```

Then rebuild:

```bash
docker compose build --no-cache online
```

Restart:

```bash
docker compose up -d online
```

Verify:

```bash
docker compose logs --tail=100 online
```

and:

```bash
curl -i http://127.0.0.1:1011/health
```

Do not retrain the model for this dependency error.

---

# 38. Dockerfile CMD Syntax Error Seen During Testing

An earlier Dockerfile used a multi-line JSON `CMD` incorrectly and Docker returned:

```text
dockerfile parse error:
unknown instruction: "uvicorn",
```

Use JSON-form `CMD` on one Dockerfile line:

```dockerfile
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "1011"]
```

Offline:

```dockerfile
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "1012"]
```

Dashboard:

```dockerfile
CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=1013", "--server.headless=true"]
```

---

# 39. Why the Training Pipeline Is Not in the Deployment Bundle

The deployment package contains only runtime services:

```text
online
offline
dashboard
shared
```

The training pipeline remains on the development machine.

The connection is MLflow:

```text
training machine
      |
      | MLFLOW_TRACKING_URI
      v
MLflow registry
      |
      +----> Online
      |
      +----> Offline
```

The serving containers should not need access to:

```text
pipeline/
training datasets
Optuna studies
training scripts
```

Their model source of truth is MLflow.

---

# 40. What MLflow Stores

The deployment MLflow server uses:

```text
mlflow/mlflow.db
```

for metadata and registry state.

It uses:

```text
mlruns/
```

for artifacts.

Conceptually:

```text
MLflow
├── experiments
├── runs
├── metrics
├── parameters
├── registered models
├── model versions
├── aliases
└── artifacts
```

Applications should communicate with the MLflow server over HTTP.

They should not directly read the SQLite database.

---

# 41. Local Test vs VPS Test

The local test uses:

```text
Training -> http://127.0.0.1:1010
```

because MLflow is on the same machine.

On the VPS deployment, the training machine will normally use an SSH tunnel:

```text
local laptop localhost:1010
        |
        | SSH tunnel
        v
VPS localhost:1010
        |
        v
MLflow container
```

The training shell will still use:

```bash
export MLFLOW_TRACKING_URI=http://127.0.0.1:1010
```

but the traffic will be forwarded to the VPS.

Inside Docker on the VPS, Online and Offline will use:

```text
http://mlflow:1010
```

because `mlflow` is the Docker Compose service name.

---

# 42. Complete Repeatable Test Sequence

The shortest complete sequence is:

```bash
# Deployment directory
cd ~/GridCast/GridCast_deployment

docker compose config
docker compose up -d mlflow
curl -i http://127.0.0.1:1010/health
```

Then in the training environment:

```bash
cd ~/GridCast
source .venv/bin/activate
export MLFLOW_TRACKING_URI=http://127.0.0.1:1010

cd pipeline
python main.py
```

Verify champion:

```bash
cd ~/GridCast

python - <<'PY'
from mlflow import MlflowClient

client = MlflowClient()

mv = client.get_model_version_by_alias(
    "grid_load_model",
    "champion",
)

print("Champion version:", mv.version)
print("Run ID:", mv.run_id)
PY
```

Return to deployment:

```bash
cd ~/GridCast/GridCast_deployment
```

Build and start Online:

```bash
docker compose build online
docker compose up -d online
curl -i http://127.0.0.1:1011/health
```

Build and start Offline:

```bash
docker compose build offline
docker compose up -d offline
curl -i http://127.0.0.1:1012/health
```

Run a real offline forecast:

```bash
curl -X POST   "http://127.0.0.1:1012/forecast?origin_date=2025-06-06"
```

Verify:

```bash
curl -s http://127.0.0.1:1012/forecasts
ls -R offline_data
```

Build and start Dashboard:

```bash
docker compose build dashboard
docker compose up -d dashboard
curl -I http://127.0.0.1:1013
```

Final state:

```bash
docker compose ps
```

Expected:

```text
gridcast-mlflow      healthy
gridcast-online      healthy
gridcast-offline     healthy
gridcast-dashboard   up
```




To stop and remove all four GridCast containers cleanly, run::

```bash
cd ~/GridCast/GridCast_deployment

docker compose down
```
Then verify:

```bash
docker ps
```
You should no longer see:
```bash
gridcast-mlflow
gridcast-online
gridcast-offline
gridcast-dashboard
```
---

# 43. Success Criteria

The local deployment test is complete only when all of the following are true:

```text
MLflow health endpoint returns 200
@champion exists
shared model loader loads champion successfully
Online API health returns 200
Online API reports model_alias=champion
Offline API health returns 200
Offline forecast can be triggered
Forecast is persisted to SQLite
Parquet forecast is created
HTML report is created
Forecast appears through /forecasts
MLflow forecast tracking run is created
Dashboard returns HTTP 200
Dashboard can reach Online and Offline services
```

Once these conditions are satisfied, the local Dockerized deployment is validated and the project is ready for the next phase:

```text
VPS deployment
```

---

# 44. Final Validated State

The successful GridCast local Docker deployment demonstrated:

```text
MLflow                  ✅
Model registry           ✅
@champion                ✅
Online model loading     ✅
Online FastAPI           ✅
Offline model loading    ✅
ERA5 forecast replay     ✅
Forecast analytics       ✅
SQLite persistence       ✅
Parquet persistence      ✅
HTML reports             ✅
MLflow forecast tracking ✅
Streamlit dashboard      ✅
Docker Compose network   ✅
Persistent host volumes  ✅
```

This is the baseline that should be reproduced on the VPS before adding CI/CD, Nginx/domain routing, Prometheus/Grafana, or other production infrastructure.
