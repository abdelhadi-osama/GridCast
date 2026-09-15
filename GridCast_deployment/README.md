# GridCast VPS Deployment Guide

This README documents the VPS deployment of GridCast step by step.

## Deployment logic

The goal is to reproduce on the VPS the same Dockerized architecture that was already validated locally.

```text
Local development machine
        |
        | git push
        v
      GitHub
        |
        | git clone / git pull
        v
       VPS
        |
        +--> MLflow
        +--> Online API
        +--> Offline API
        +--> Dashboard
```

The training pipeline remains on the local development machine. The VPS runs the deployment services.

Later, local training will communicate with the MLflow server on the VPS through an SSH tunnel.

```text
Local training machine
        |
        | SSH tunnel
        | MLFLOW_TRACKING_URI=http://127.0.0.1:1010
        v
       VPS
        |
        +--> MLflow :1010
        +--> Online API :1011
        +--> Offline API :1012
        +--> Dashboard :1013
```

---

## Assumptions

Before starting this guide, we assume that the VPS is already prepared.

This means:

```text
SSH access works
Docker is installed
Docker Compose is installed
Git is installed
required ports are available
basic VPS networking/firewall configuration is already done

```
for more info look here : > - Contabo VPS initial configuration: [vps-initial-configurations](https://github.com/context-community/vps-initial-configurations)


GridCast uses:

| Service | Port |
|---|---:|
| MLflow | 1010 |
| Online API | 1011 |
| Offline API | 1012 |
| Dashboard | 1013 |

This README focuses on deploying GridCast itself, not on provisioning the VPS.

---

# Step 1 — Configure SSH Access and Clone the Repository

The first objective is:

```text
Local machine --> VPS
VPS --> GitHub
```

These are two separate SSH relationships.

## 1.1 Create an SSH key on the local machine

Run on the **local machine**:

```bash
ssh-keygen -t ed25519 -C "your_email_or_label"
```

Accept the default location:

```text
~/.ssh/id_ed25519
```

This creates:

```text
~/.ssh/id_ed25519
~/.ssh/id_ed25519.pub
```

Important:

```text
id_ed25519      = private key
id_ed25519.pub  = public key
```

Never share the private key.

## 1.2 Copy the local public key

Run on the **local machine**:

```bash
cat ~/.ssh/id_ed25519.pub
```

Copy the complete line.

## 1.3 Add the local public key to the VPS

Connect to the VPS:

```bash
ssh <VPS_USER>@<VPS_IP>
```

On the **VPS**:

```bash
nano ~/.ssh/authorized_keys
```

Paste the local public key.

Then set permissions:

```bash
chmod 700 ~/.ssh
chmod 600 ~/.ssh/authorized_keys
```

Disconnect:

```bash
exit
```

Test again from the local machine:

```bash
ssh <VPS_USER>@<VPS_IP>
```

Expected result: the SSH connection succeeds using the key.

## 1.4 Create an SSH key on the VPS for GitHub

Connect to the VPS:

```bash
ssh <VPS_USER>@<VPS_IP>
```

Run on the **VPS**:

```bash
ssh-keygen -t ed25519 -C "gridcast-vps"
```

Display the VPS public key:

```bash
cat ~/.ssh/id_ed25519.pub
```

Copy the complete public key.

This key is used for:

```text
VPS --> GitHub
```

## 1.5 Add the VPS key as a GitHub Deploy Key

In the GridCast GitHub repository, go to:

```text
Settings
-> Deploy keys
-> Add deploy key
```

Use a name such as:

```text
GridCast VPS
```

Paste the VPS public key.

For a deployment server that only needs `git clone` and `git pull`, read-only access is sufficient.

Test GitHub access from the VPS:

```bash
ssh -T git@github.com
```

On the first connection, GitHub may ask whether you trust the host fingerprint. Type:

```text
yes
```

A successful response means GitHub recognizes the VPS SSH key.

## 1.6 Clone the repository

Run on the **VPS**:

```bash
cd ~
git clone git@github.com:<GITHUB_USERNAME>/<REPOSITORY>.git
```

Example:

```bash
git clone git@github.com:username/GridCast.git
```

Then:

```bash
cd ~/GridCast
git status
```

Expected result:

```text
On branch main
nothing to commit, working tree clean
```

Verify the deployment directory exists:

```bash
ls
```

You should see:

```text
GridCast_deployment
```

Enter it:

```bash
cd ~/GridCast/GridCast_deployment
```

Verify:

```bash
ls -la
```

Expected deployment files include:

```text
docker-compose.yml
.dockerignore
online/
offline/
dashboard/
shared/
```

---

## Step 1 result

At the end of this step:

```text
Local machine
    |
    | SSH key
    v
   VPS
    |
    | GitHub deploy key
    v
 GitHub
```

And the repository should exist on the VPS at:

```text
~/GridCast
```

with the deployment bundle at:

```text
~/GridCast/GridCast_deployment
```

Do not start the Docker services yet.

The next step is to validate the deployment files on the VPS before starting MLflow.




---

# Step 2 — Validate the Deployment Bundle on the VPS

Before starting any service, verify that the cloned deployment bundle is complete and that Docker Compose can parse it.

## 2.1 Enter the deployment directory

Run on the **VPS**:

```bash
cd ~/GridCast/GridCast_deployment
```

Verify the current path:

```bash
pwd
```

Expected:

```text
/home/<VPS_USER>/GridCast/GridCast_deployment
```

## 2.2 Check the deployment files

Run:

```bash
ls -la
```

Expected files and directories include:

```text
docker-compose.yml
.dockerignore
online/
offline/
dashboard/
shared/
```

The training pipeline is not required inside the deployment bundle.

## 2.3 Validate Docker Compose

Run:

```bash
docker compose config
```

This command parses `docker-compose.yml` and prints the resolved configuration.

Expected services:

```text
mlflow
online
offline
dashboard
```

There should be no YAML or Docker Compose syntax error.

## Step 2 result

At the end of this step, the repository is present on the VPS and the Compose configuration is valid.

Do not start the whole system yet. Start MLflow first.

---

# Step 3 — Start MLflow on the VPS

The Online and Offline services load the registered model from MLflow, so MLflow must be available first.

The GridCast deployment uses:

```text
MLflow port: 1010
```

The host binding is intentionally:

```text
127.0.0.1:1010
```

This means MLflow is not exposed directly to the public internet.

## 3.1 Start only MLflow

Run on the **VPS**:

```bash
cd ~/GridCast/GridCast_deployment
docker compose up -d mlflow
```

Expected output is similar to:

```text
Container gridcast-mlflow Started
```

## 3.2 Check MLflow status

Run:

```bash
docker compose ps
```

Initially, the status may be:

```text
health: starting
```

After a short delay, it should become:

```text
healthy
```

Expected port mapping:

```text
127.0.0.1:1010->1010/tcp
```

## 3.3 Verify MLflow health on the VPS

Run:

```bash
curl -i http://127.0.0.1:1010/health
```

Expected:

```text
HTTP/1.1 200 OK
...
OK
```

You can also inspect logs:

```bash
docker compose logs --tail=100 mlflow
```

A healthy MLflow service is required before continuing.

---

# Step 4 — Connect the Local Machine to MLflow on the VPS

The training pipeline runs on the **local development machine**, but the MLflow registry runs on the **VPS**.

We connect them using an SSH tunnel.

The logic is:

```text
Local training process
        |
        | MLFLOW_TRACKING_URI
        v
127.0.0.1:<LOCAL_TUNNEL_PORT>
        |
        | SSH tunnel
        v
VPS 127.0.0.1:1010
        |
        v
MLflow container
```

## Important note about `MLFLOW_TRACKING_URI` on the VPS

The GridCast Docker services already receive their MLflow address through Docker Compose:

```text
http://mlflow:1010
```

Therefore, running this in the VPS shell:

```bash
export MLFLOW_TRACKING_URI=http://localhost:1010
```

is not required for the already running containers.

The important tracking URI for training is set on the **local training machine** after the SSH tunnel is open.

## 4.1 Open the SSH tunnel from the local machine

Use a new terminal on your **local machine**.

Recommended command:

```bash
ssh -N -L <mlflow_port>:localhost:<mlflow_port> user@<server_ip_address>
```

Example:

```bash
ssh -N -L 5010:127.0.0.1:1010 abdelhadi@35.202.67.240
```

Explanation:

```text
-N
    Do not open a remote shell.
    Create only the SSH tunnel.

5010
    Local port on the development machine.

127.0.0.1:1010
    MLflow address on the VPS.
```

The terminal will appear idle after authentication.

That is expected.

Leave this terminal open while training.

### Why use local port 5010?

GridCast MLflow uses port `1010` on the VPS.

On some Linux systems, binding local ports below `1024` can require elevated privileges.

Using local port `5010` avoids that problem:

```text
Local 5010  --->  VPS 1010
```

If local port `1010` works on your machine, this is also valid:

```bash
ssh -N -L 1010:127.0.0.1:1010 <VPS_USER>@<VPS_IP>
```

In that case, use `1010` instead of `5010` in the following local commands.

## 4.2 Verify the tunnel

Open a **different local terminal**.

Run:

```bash
curl -i http://127.0.0.1:1010/health
```

Expected:

```text
HTTP/1.1 200 OK
...
OK
```

You can also open the MLflow UI locally:

```text
http://127.0.0.1:1010
```

If the MLflow HTML page appears, the tunnel is working.

## Step 4 result

At this point:

```text
Local machine
127.0.0.1:1010
        |
        | SSH tunnel
        v
VPS
127.0.0.1:1010
        |
        v
MLflow
```

The local training process can now communicate securely with the VPS MLflow server without exposing MLflow publicly.

---

# Step 5 — Train Locally Against the VPS MLflow Registry

Now the training pipeline should run on the **local machine** while logging everything to MLflow on the VPS.

This means that the following will be stored in the VPS MLflow instance:

```text
experiments
training runs
parameters
metrics
model artifacts
preprocessor artifact
registered model versions
model aliases
```

## 5.1 Open the local GridCast environment

Run in a **local terminal**, not on the VPS:

```bash
cd ~/GridCast
source .venv/bin/activate
```

## 5.2 Set the local MLflow tracking URI

If the SSH tunnel uses local port `5010`:

```bash
export MLFLOW_TRACKING_URI=http://127.0.0.1:1010
```

Verify:

```bash
echo $MLFLOW_TRACKING_URI
```

Expected:

```text
http://127.0.0.1:1010
```

Verify from Python:

```bash
python - <<'PY'
import os
import mlflow

print("Environment URI:", os.getenv("MLFLOW_TRACKING_URI"))
print("MLflow URI:", mlflow.get_tracking_uri())
PY
```

Expected:

```text
Environment URI: http://127.0.0.1:1010
MLflow URI: http://127.0.0.1:1010
```

## 5.3 Run the training pipeline

Run locally:

```bash
cd ~/GridCast/pipeline
python main.py --promote
```

The training pipeline should connect through the SSH tunnel and write to MLflow on the VPS.

The exact model version changes between runs.

What matters is that the registered model:

```text
grid_load_model
```

has a valid:

```text
@champion
```

alias.

## 5.4 Verify the champion model

Run on the **local machine** while the SSH tunnel is still open:

```bash
cd ~/GridCast

python - <<'PY'
from mlflow import MlflowClient

client = MlflowClient()

model = client.get_model_version_by_alias(
    "grid_load_model",
    "champion",
)

print("Champion version:", model.version)
print("Run ID:", model.run_id)
print("Status:", model.status)
PY
```

Expected output is similar to:

```text
Champion version: 16
Run ID: <MLFLOW_RUN_ID>
Status: READY
```

Do not depend on version `16`.

Future training runs may create version `17`, `18`, or higher.

The important requirement is:

```text
grid_load_model@champion exists
```

---

# Step 6 — Start the Full GridCast System on the VPS

Once MLflow is running and `grid_load_model@champion` exists, the serving system can start.

GridCast services are:

```text
mlflow
online
offline
dashboard
```

This differs from examples that use service names such as `api` and `batch`.

For GridCast:

```text
api   -> online
batch -> offline
```

## 6.1 Build and start the complete deployment

Run on the **VPS**:

```bash
cd ~/GridCast/GridCast_deployment
docker compose up -d --build
```

Docker Compose should:

```text
start MLflow
wait for MLflow health
start Online
start Offline
wait for Online/Offline health
start Dashboard
```

Expected output is similar to:

```text
Container gridcast-mlflow     Healthy
Container gridcast-online     Healthy
Container gridcast-offline    Healthy
Container gridcast-dashboard  Started
```

## 6.2 Check container status

Run:

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

## 6.3 Inspect logs if needed

All services:

```bash
docker compose logs --tail=100
```

Online only:

```bash
docker compose logs --tail=100 online
```

Offline only:

```bash
docker compose logs --tail=100 offline
```

Dashboard only:

```bash
docker compose logs --tail=100 dashboard
```

MLflow only:

```bash
docker compose logs --tail=100 mlflow
```

A clean restart may show messages such as:

```text
Application shutdown complete.
Finished server process.
exited with code 0
```

These are normal graceful shutdown messages, not application crashes.

---

# Step 7 — Access the Dashboard

GridCast Dashboard runs on:

```text
1013
```

From a browser outside the VPS, open:

```text
http://<VPS_IP>:1013
```

Example:

```text
http://35.202.67.240:1013
```

This requires port `1013` to be allowed by the VPS firewall or cloud firewall.

If the dashboard opens successfully, external access is working.

The dashboard communicates with the backend services over the internal Docker network:

```text
Dashboard
    |
    +--> http://online:1011
    |
    +--> http://offline:1012
```

It does not use the public VPS IP to communicate with the Online and Offline containers.

---

# Step 8 — End-to-End VPS Testing

After all containers are running, test the complete system from the **VPS**.

Run from:

```bash
cd ~/GridCast/GridCast_deployment
```

## 8.1 MLflow health

```bash
curl -s http://127.0.0.1:1010/health
```

Expected:

```text
OK
```

## 8.2 Online API health

```bash
curl -s http://127.0.0.1:1011/health
```

Expected JSON similar to:

```json
{
  "status": "ok",
  "model_version": "v16",
  "model_alias": "champion"
}
```

The exact version can change.

The important values are:

```text
status = ok
model_alias = champion
```

## 8.3 Offline API health

```bash
curl -s http://127.0.0.1:1012/health
```

Expected JSON similar to:

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

The number of stored forecasts can be greater than zero after previous runs.

## 8.4 Dashboard reachability

```bash
curl -s -o /dev/null -w "%{http_code}\n" \
  http://127.0.0.1:1013
```

Expected:

```text
200
```

## 8.5 Test a real online prediction

First inspect the Online API schema:

```bash
curl -s http://127.0.0.1:1011/openapi.json
```

For the current GridCast request schema, an example prediction request is:

```bash
curl -s -X POST http://127.0.0.1:1011/predict \
  -H "Content-Type: application/json" \
  -d '{
    "Date": "2025-06-06",
    "Hr_End": 14,
    "Dry_Bulb": 75.0,
    "Dew_Point": 60.0
  }'
```

Expected result:

```text
HTTP success with a GridCast predicted load value in MW
```

The exact prediction changes with the champion model.

If the request schema changes later, use `/openapi.json` as the source of truth.

## 8.6 Trigger a real offline forecast

Run:

```bash
curl -s -X POST \
  "http://127.0.0.1:1012/forecast?origin_date=2025-06-06"
```

Expected response is similar to:

```json
{
  "status": "started",
  "origin_date": "2025-06-06",
  "target_date": "2025-06-07",
  "message": "..."
}
```

The forecast runs asynchronously.

## 8.7 Check running jobs

Immediately after triggering:

```bash
curl -s http://127.0.0.1:1012/running
```

The job may appear here.

If the forecast completes quickly, this endpoint may already be empty.

That is normal.

## 8.8 Check forecast history

After the forecast completes:

```bash
curl -s http://127.0.0.1:1012/forecasts
```

Expected result: at least one forecast record containing values such as:

```text
origin_date
target_date
model_version
model_run_id
model_alias
weather_source
total_hours
peak_load_mw
minimum_load_mw
average_load_mw
daily_energy_mwh
forecast_path
report_path
mlflow_tracking_run_id
```

Important expected values include:

```text
model_alias = champion
weather_source = open_meteo_era5
```

For a normal non-DST day:

```text
total_hours = 24
```

## 8.9 Verify persistent forecast files

Run on the VPS:

```bash
ls -R offline_data
```

Expected structure:

```text
offline_data/
├── batch_results.db
├── forecasts/
│   └── gridcast_<target-date>_<forecast-id>.parquet
└── reports/
    └── gridcast_<target-date>_<forecast-id>.html
```

This proves that the Offline container is writing through the Docker bind mount to persistent VPS storage.

## 8.10 Verify the full deployment state

Run:

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

At this point the VPS deployment is validated end to end.

---

# Final Validated VPS Architecture

After all tests pass:

```text
                           VPS
                            |
                 +----------+----------+
                 |                     |
                 v                     v
          MLflow :1010          Dashboard :1013
                 |
           +-----+-----+
           |           |
           v           v
     Online :1011   Offline :1012
           |           |
           +-----+-----+
                 |
                 v
       grid_load_model@champion
```

Local training reaches MLflow through the SSH tunnel:

```text
Local training
      |
      | MLFLOW_TRACKING_URI
      v
127.0.0.1:5010
      |
      | SSH tunnel
      v
VPS 127.0.0.1:1010
      |
      v
MLflow
```

The VPS deployment is considered successful when:

```text
MLflow is healthy
@champion exists
Online is healthy
Offline is healthy
Dashboard returns HTTP 200
Online prediction succeeds
Offline forecast succeeds
SQLite persistence works
Parquet output is created
HTML report is created
Offline MLflow tracking run is created
containers restart cleanly
```

This is the baseline VPS deployment before adding later production infrastructure such as Nginx, TLS, CI/CD, Prometheus, or Grafana.



# Nginx Reverse Proxy and HTTPS for GridCast

This section documents only the Nginx and HTTPS configuration used for the GridCast VPS deployment.

The application was already running successfully with Docker Compose before Nginx was configured.

The internal services were:

```text
MLflow      -> 127.0.0.1:1010
Online API  -> 127.0.0.1:1011
Offline API -> 127.0.0.1:1012
Dashboard   -> 127.0.0.1:1013
```

The public domain used for the deployment was:

```text
gridcast.duckdns.org
```

The final public routing is:

```text
https://gridcast.duckdns.org/                 -> Streamlit Dashboard
https://gridcast.duckdns.org/online/...       -> Online FastAPI service
https://gridcast.duckdns.org/offline/...      -> Offline FastAPI service
```

MLflow is intentionally **not exposed through Nginx**. It remains private on `127.0.0.1:1010` and can be reached from the local development machine through an SSH tunnel when required.

---

## 1. Prerequisites


- A VPS with Docker and Docker Compose installed
- A domain name pointing to your VPS IP — use [DuckDNS](https://www.duckdns.org/domains) for a free subdomain if needed
- Your project cloned on the VPS

---
Before configuring Nginx, verify that the Docker services are healthy on the VPS.

Run on the **VPS**:

```bash
cd ~/GridCast/GridCast_deployment
docker compose ps
```

Expected state:

```text
gridcast-mlflow      healthy
gridcast-online      healthy
gridcast-offline     healthy
gridcast-dashboard   up
```

Verify the services directly from the VPS:

```bash
curl -s http://127.0.0.1:1010/health
echo

curl -s http://127.0.0.1:1011/health
echo

curl -s http://127.0.0.1:1012/health
echo

curl -s -o /dev/null -w "%{http_code}\n" \
  http://127.0.0.1:1013
```

Expected output is similar to:

```text
OK
{"status":"ok","model_version":"v8","model_alias":"champion"}
{"status":"ok", ...}
200
```

The exact model version can change.

---

## 2. Required FastAPI Reverse-Proxy Configuration

Before Nginx is used, the FastAPI applications must know their public URL prefixes.

GridCast uses:

```text
Online API  -> /online
Offline API -> /offline
```

In both FastAPI applications, add:

```python
root_path=os.getenv("ROOT_PATH", "")
```

The Docker Compose configuration provides:

```yaml
online:
  environment:
    MLFLOW_TRACKING_URI: http://mlflow:1010
    ROOT_PATH: /online

offline:
  environment:
    MLFLOW_TRACKING_URI: http://mlflow:1010
    GRIDCAST_OFFLINE_DATA_DIR: /app/offline/data
    ROOT_PATH: /offline
```

The Dashboard continues using Docker-internal API addresses:

```yaml
dashboard:
  environment:
    ONLINE_API_URL: http://online:1011
    OFFLINE_API_URL: http://offline:1012
```

The Dashboard does not need to call the public domain because the Streamlit process communicates with the APIs inside the Docker network.

---

## 3. Bind Application Ports to Localhost

Before exposing the system through Nginx, bind the application ports only to the VPS loopback interface.

The Compose port mappings should be:

```yaml
mlflow:
  ports:
    - "127.0.0.1:1010:1010"

online:
  ports:
    - "127.0.0.1:1011:1011"

offline:
  ports:
    - "127.0.0.1:1012:1012"

dashboard:
  ports:
    - "127.0.0.1:1013:1013"
```

This prevents direct public access to ports `1010` through `1013`.

The intended architecture becomes:

```text
Internet
   |
   | 80 / 443
   v
 Nginx
   |
   +----> 127.0.0.1:1013  Dashboard
   +----> 127.0.0.1:1011  Online API
   +----> 127.0.0.1:1012  Offline API

MLflow
   |
   +----> 127.0.0.1:1010  private / SSH tunnel only
```

After changing Compose, apply it:

```bash
cd ~/GridCast/GridCast_deployment
docker compose up -d --build
```

Then verify:

```bash
docker compose ps
```

The port mappings should show:

```text
127.0.0.1:1010->1010/tcp
127.0.0.1:1011->1011/tcp
127.0.0.1:1012->1012/tcp
127.0.0.1:1013->1013/tcp
```

---

## 4. Install or Verify Nginx

Run on the **VPS**:

```bash
sudo apt update
sudo apt install -y nginx
```

In this deployment, Nginx was already installed.

Verify the service:

```bash
sudo systemctl status nginx --no-pager
```

Expected:

```text
Active: active (running)
```

On some systems `/usr/sbin` is not in the normal user's `PATH`, so `nginx -v` may return `command not found` even though Nginx is installed and running.

Use:

```bash
sudo /usr/sbin/nginx -v
```

or:

```bash
sudo nginx -v
```

when required.

---

## 5. Create the GridCast Nginx Configuration

Create a dedicated Nginx site configuration:

```bash
sudo nano /etc/nginx/sites-available/gridcast
```

Use:

```nginx
server {
    listen 80;
    listen [::]:80;

    server_name gridcast.duckdns.org; #or your domain 

    # Online API
    location = /online {
        return 308 /online/;
    }

    location /online/ {
        proxy_pass http://127.0.0.1:1011/;
        proxy_http_version 1.1;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Offline API
    location = /offline {
        return 308 /offline/;
    }

    location /offline/ {
        proxy_pass http://127.0.0.1:1012/;
        proxy_http_version 1.1;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Streamlit Dashboard
    location / {
        proxy_pass http://127.0.0.1:1013;
        proxy_http_version 1.1;

        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        proxy_read_timeout 86400;
    }
}
```

### Why the trailing slash on `proxy_pass` matters

For example:

```nginx
location /online/ {
    proxy_pass http://127.0.0.1:1011/;
}
```

means:

```text
Public request:       /online/health
Forwarded internally: /health
```

The FastAPI application still knows that its public prefix is `/online` because `ROOT_PATH=/online`.

The same logic applies to `/offline/`.

---

## 6. Enable the Nginx Site

Create the symbolic link:

```bash
sudo ln -s \
  /etc/nginx/sites-available/gridcast \
  /etc/nginx/sites-enabled/gridcast
```

If the link already exists, do not create another one.

Validate the complete Nginx configuration:

```bash
sudo nginx -t
```

Expected:

```text
nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
nginx: configuration file /etc/nginx/nginx.conf test is successful
```

If validation succeeds, reload Nginx:

```bash
sudo systemctl reload nginx
```

Always run `nginx -t` before reloading after configuration changes.

---

## 7. Test the HTTP Reverse Proxy

Test the Online API:

```bash
curl -i http://gridcast.duckdns.org/online/health
```

Expected:

```text
HTTP/1.1 200 OK
```

with JSON similar to:

```json
{
  "status": "ok",
  "model_version": "v8",
  "model_alias": "champion"
}
```

Test the Offline API:

```bash
curl -i http://gridcast.duckdns.org/offline/health
```

Expected:

```text
HTTP/1.1 200 OK
```

Test the Dashboard:

```bash
curl -s -o /dev/null -w "%{http_code}\n" \
  http://gridcast.duckdns.org/
```

Expected:

```text
200
```

At this point the reverse proxy is working over HTTP.

---

## 8. Add HTTPS with Certbot

Install Certbot and the Nginx integration:

```bash
sudo apt update
sudo apt install -y certbot python3-certbot-nginx
```

Request a certificate for the GridCast domain:

```bash
sudo certbot --nginx -d gridcast.duckdns.org
```

A successful deployment reports something similar to:

```text
Successfully received certificate.
Successfully deployed certificate for gridcast.duckdns.org
Congratulations! You have successfully enabled HTTPS
```

Certbot stores the certificate under:

```text
/etc/letsencrypt/live/gridcast.duckdns.org/
```

and configures automatic renewal.

For this deployment, the certificate was successfully installed and HTTPS became available at:

```text
https://gridcast.duckdns.org
```

---

## 9. Verify HTTPS

Test the Dashboard:

```bash
curl -I https://gridcast.duckdns.org/
```

Expected:

```text
HTTP/1.1 200 OK
```

Test Online:

```bash
curl -i https://gridcast.duckdns.org/online/health
```

Expected:

```text
HTTP/1.1 200 OK
```

with JSON similar to:

```json
{
  "status": "ok",
  "model_version": "v8",
  "model_alias": "champion"
}
```

Test Offline:

```bash
curl -i https://gridcast.duckdns.org/offline/health
```

Expected:

```text
HTTP/1.1 200 OK
```

If all three succeed, HTTPS is working correctly.

---

## 10. Verify the HTTP-to-HTTPS Redirect Method

GridCast exposes POST endpoints such as:

```text
POST /online/predict
POST /offline/forecast
```

A redirect should preserve the HTTP method.

Check the redirect generated by Certbot:

```bash
sudo grep -R "return 30" /etc/nginx/sites-enabled/gridcast
```

If the HTTP-to-HTTPS redirect uses:

```nginx
return 301 https://$host$request_uri;
```

change it to:

```nginx
return 308 https://$host$request_uri;
```

Then validate and reload:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

`308 Permanent Redirect` preserves the original HTTP method and request body, which is safer for API POST requests.

---

## 11. Final Public URL Map

| Public URL | Service |
|---|---|
| `https://gridcast.duckdns.org/` | Streamlit Dashboard |
| `https://gridcast.duckdns.org/online/health` | Online API health |
| `https://gridcast.duckdns.org/online/predict` | Online prediction |
| `https://gridcast.duckdns.org/online/docs` | Online Swagger UI |
| `https://gridcast.duckdns.org/offline/health` | Offline API health |
| `https://gridcast.duckdns.org/offline/forecast` | Trigger offline forecast |
| `https://gridcast.duckdns.org/offline/docs` | Offline Swagger UI |

MLflow is intentionally omitted from the public URL map. It remains private on `127.0.0.1:1010` or through the SSH tunnel from the development machine.

---

## 12. Final Nginx Architecture

```text
                         Internet
                            |
                         HTTPS :443
                            |
                            v
                          Nginx
                            |
             +--------------+--------------+
             |              |              |
             v              v              v
             /          /online/       /offline/
             |              |              |
             v              v              v
        Dashboard        Online         Offline
        :1013            :1011          :1012
                            \              /
                             \            /
                              v          v
                                MLflow
                                :1010
                               private
```

The Nginx deployment is complete when:

```text
Nginx configuration passes nginx -t
Dashboard returns HTTP 200
Online health returns HTTP 200
Offline health returns HTTP 200
HTTPS certificate is valid
HTTP redirects to HTTPS
Online and Offline APIs work through their public prefixes
MLflow remains private
```
