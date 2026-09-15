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
But I would not do that now. Keep the images and persistent data; just use
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
If you also wanted to remove the built Docker images, that would be a different command:

```bash
docker compose down --rmi local

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




# GridCast CI/CD with GitHub Actions

This section documents the CI/CD configuration used to automatically deploy GridCast to a VPS whenever changes are pushed to the `main` branch.

No credentials, IP addresses, usernames, private keys, or server-specific paths are included in this guide. Replace placeholders with your own values when configuring another environment.

---

## 1. CI/CD Goal

The deployment flow is:

```text
Developer
   |
   | git push
   v
GitHub repository
   |
   | GitHub Actions
   v
GitHub-hosted runner
   |
   | SSH
   v
VPS
   |
   +--> git pull origin main
   |
   +--> docker compose up -d --build
   |
   +--> docker compose ps
```

The purpose is to avoid manually connecting to the VPS after every code change.

Once CI/CD is configured, a normal deployment becomes:

```bash
git add .
git commit -m "Describe the change"
git push origin main
```

A push to `main` automatically triggers the deployment workflow.

---

## 2. Prerequisites

Before creating the GitHub Actions workflow, verify that:

```text
The GridCast repository already exists on GitHub
The GridCast repository is already cloned on the VPS
The VPS can pull from GitHub
Docker is installed on the VPS
Docker Compose is installed on the VPS
The GridCast Docker deployment already works manually
SSH access to the VPS works
```

The VPS repository should already be connected to GitHub.

Run on the **VPS**:

```bash
cd /path/to/GridCast
git remote -v
```

Expected result:

```text
origin  git@github.com:<OWNER>/<REPOSITORY>.git (fetch)
origin  git@github.com:<OWNER>/<REPOSITORY>.git (push)
```

---

## 3. Understand the Two SSH Directions

There are two different SSH relationships involved in this deployment.

### VPS to GitHub

Used when the VPS runs:

```bash
git pull origin main
```

Flow:

```text
VPS
 |
 | SSH
 v
GitHub
```

The VPS must have a private key whose public key is accepted by GitHub.

### GitHub Actions to VPS

Used when GitHub Actions connects to the server to run deployment commands.

Flow:

```text
GitHub Actions
      |
      | SSH
      v
     VPS
```

The public key corresponding to the private key stored in GitHub Actions must exist in:

```text
~/.ssh/authorized_keys
```

on the VPS.

The same key pair can technically be reused for both directions, although using a dedicated CI/CD key is a cleaner security design.

---

## 4. Verify the SSH Key Is Authorized on the VPS

If the private key that will be stored in GitHub Actions corresponds to:

```text
~/.ssh/id_ed25519
```

then its public key is:

```text
~/.ssh/id_ed25519.pub
```

Display it on the VPS:

```bash
cat ~/.ssh/id_ed25519.pub
```

Check the authorized inbound SSH keys:

```bash
cat ~/.ssh/authorized_keys
```

The public key used by GitHub Actions must exist in `authorized_keys`.

If it is not present, add it:

```bash
cat ~/.ssh/id_ed25519.pub >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
```

Also make sure the `.ssh` directory has appropriate permissions:

```bash
chmod 700 ~/.ssh
```

Important:

```text
Private key  -> stored securely in GitHub Actions Secrets
Public key   -> stored in ~/.ssh/authorized_keys on the VPS
```

Never store the private key directly in the repository.

---

## 5. Create the GitHub Actions Workflow

Create the workflow file in the root of the repository.

Run on the **development machine**:

```bash
cd /path/to/GridCast
mkdir -p .github/workflows
nano .github/workflows/deploy.yml
```

Use:

```yaml
name: GridCast CI/CD

on:
  push:
    branches:
      - main

jobs:
  deploy:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Load SSH key
        uses: webfactory/ssh-agent@v0.9.0
        with:
          ssh-private-key: ${{ secrets.PRIVATE_KEY }}

      - name: Add VPS to known hosts
        run: |
          mkdir -p ~/.ssh
          ssh-keyscan -H "${{ secrets.HOST }}" >> ~/.ssh/known_hosts

      - name: Deploy GridCast to VPS
        run: |
          ssh ${{ secrets.USERNAME }}@${{ secrets.HOST }} << 'EOF'
            set -e

            cd ${{ secrets.PROJECT_PATH }}
            git pull origin main

            cd GridCast_deployment
            docker compose up -d --build

            docker compose ps
          EOF
```

---

## 6. Add GitHub Actions Secrets

In the GitHub repository, go to:

```text
Settings
-> Secrets and variables
-> Actions
-> Repository secrets
```

Create these secrets:

| Secret | Purpose |
|---|---|
| `PRIVATE_KEY` | SSH private key used by GitHub Actions to connect to the VPS |
| `HOST` | VPS IP address or hostname |
| `USERNAME` | VPS SSH login username |
| `PROJECT_PATH` | Absolute path to the GridCast repository on the VPS |

Do not put these values directly inside `deploy.yml`.

The workflow references them as:

```yaml
${{ secrets.PRIVATE_KEY }}
${{ secrets.HOST }}
${{ secrets.USERNAME }}
${{ secrets.PROJECT_PATH }}
```

---

## 7. Add the Private Key Secret

On the VPS, display the private key that corresponds to the authorized public key:

```bash
cat ~/.ssh/id_ed25519
```

Copy the complete key, including:

```text
-----BEGIN OPENSSH PRIVATE KEY-----
...
-----END OPENSSH PRIVATE KEY-----
```

Create the GitHub repository secret:

```text
Name:
PRIVATE_KEY
```

Paste the complete private key into the secret value.

Important:

```text
Do not paste id_ed25519.pub into PRIVATE_KEY.
Do not commit the private key to Git.
Do not include the private key in README files.
```

---

## 8. Add the HOST Secret

Create:

```text
Name:
HOST
```

The value should be:

```text
<VPS_IP_OR_HOSTNAME>
```

Use your real server value in GitHub Secrets, not in the repository.

---

## 9. Add the USERNAME Secret

Create:

```text
Name:
USERNAME
```

The value is the **VPS SSH login username**.

It is not:

```text
the local machine username
the GitHub username
```

It is the username used in a command such as:

```bash
ssh <USERNAME>@<HOST>
```

---

## 10. Add the PROJECT_PATH Secret

Create:

```text
Name:
PROJECT_PATH
```

The value is the absolute path to the GridCast Git repository on the VPS.

Example format:

```text
/home/<VPS_USER>/GridCast
```

The workflow uses it here:

```bash
cd ${{ secrets.PROJECT_PATH }}
git pull origin main
```

The path must point to the repository root, not directly to `GridCast_deployment`.

The workflow later runs:

```bash
cd GridCast_deployment
docker compose up -d --build
```

---

## 11. Keep Runtime Data Out of Git

GridCast creates persistent runtime directories such as:

```text
GridCast_deployment/mlflow/
GridCast_deployment/mlruns/
GridCast_deployment/offline_data/
```

These directories should not be committed to Git.

Add them to `.gitignore`:

```gitignore
GridCast_deployment/mlflow/
GridCast_deployment/mlruns/
GridCast_deployment/offline_data/
```

This keeps MLflow and forecast runtime state on the VPS.

---

## 12. Git Commit Identity

SSH authentication and Git commit identity are different.

An SSH key answers:

```text
"Are you allowed to connect?"
```

Git commit identity answers:

```text
"Who created this commit?"
```

If Git returns:

```text
Author identity unknown
```

configure the repository identity:

```bash
git config user.name "<GIT_AUTHOR_NAME>"
git config user.email "<GIT_AUTHOR_EMAIL>"
```

Verify:

```bash
git config user.name
git config user.email
```

A failed `git commit` means there is nothing new to push.

---

## 13. Commit the Workflow

After creating:

```text
.github/workflows/deploy.yml
```

run:

```bash
git status
```

Then:

```bash
git add .github/workflows/deploy.yml
git commit -m "Add GridCast CI/CD deployment workflow"
git push origin main
```

The push to `main` automatically triggers the workflow.

---

## 14. Monitor the First Deployment

Open the GitHub repository and go to:

```text
Actions
```

Select:

```text
GridCast CI/CD
```

Open the latest workflow run.

The expected steps are:

```text
Checkout repository
Load SSH key
Add VPS to known hosts
Deploy GridCast to VPS
```

The final deployment step should execute:

```text
git pull origin main
docker compose up -d --build
docker compose ps
```

---

## 15. Expected Successful Deployment

A successful Docker deployment should eventually show services similar to:

```text
gridcast-mlflow      healthy
gridcast-online      healthy
gridcast-offline     healthy
gridcast-dashboard   up
```

After the workflow finishes, verify the public application through the configured domain.

---

## 16. Test CI/CD Again

After the first successful deployment, make a small safe change on the development machine.

Then:

```bash
git add .
git commit -m "Test automatic GridCast deployment"
git push origin main
```

A new workflow run should start automatically.

If it succeeds, the CI/CD loop is working:

```text
Code change
   |
git push
   |
GitHub Actions
   |
SSH
   |
VPS git pull
   |
Docker rebuild/restart
   |
Updated GridCast deployment
```

---

## 17. Common Failure — SSH Permission Denied

If GitHub Actions reports:

```text
Permission denied (publickey)
```

check:

```text
The PRIVATE_KEY secret contains the correct private key
The matching public key exists in ~/.ssh/authorized_keys
The USERNAME secret is the correct VPS SSH username
The HOST secret points to the correct server
```

---

## 18. Common Failure — Git Pull Fails on the VPS

If:

```bash
git pull origin main
```

fails inside GitHub Actions, verify manually on the VPS:

```bash
cd /path/to/GridCast
git pull origin main
```

If this fails, fix the `VPS -> GitHub` authentication first.

---

## 19. Common Failure — Docker Permission Denied

If GitHub Actions connects successfully but Docker fails with a permissions error, test manually on the VPS:

```bash
docker ps
docker compose version
```

The SSH user used by GitHub Actions must be able to run Docker without requiring interactive authentication.

---

## 20. Security Rules

Do not commit:

```text
SSH private keys
GitHub tokens
VPS passwords
environment files containing secrets
MLflow runtime databases
production credentials
```

Use GitHub Actions Secrets for confidential deployment values.

The repository should contain only references such as:

```yaml
${{ secrets.HOST }}
${{ secrets.USERNAME }}
${{ secrets.PRIVATE_KEY }}
${{ secrets.PROJECT_PATH }}
```

---

## 21. Final CI/CD Architecture

```text
                         Developer
                            |
                         git push
                            |
                            v
                          GitHub
                            |
                      GitHub Actions
                            |
                   SSH using PRIVATE_KEY
                            |
                            v
                            VPS
                            |
                   /path/to/GridCast
                            |
                     git pull main
                            |
                            v
                 GridCast_deployment
                            |
              docker compose up -d --build
                            |
             +--------------+--------------+
             |              |              |
             v              v              v
          Online         Offline       Dashboard
             \              /
              \            /
                   MLflow
```

The CI/CD configuration is successful when:

```text
A push to main starts GitHub Actions automatically
GitHub Actions can authenticate to the VPS
The VPS can pull the repository from GitHub
Docker Compose rebuilds the services successfully
The containers return to a healthy state
The public GridCast application remains reachable after deployment
```
