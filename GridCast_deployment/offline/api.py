"""
GridCast offline forecasting API.

HTTP interface around the offline forecasting pipeline.

Endpoints:
    GET  /health
    POST /forecast?origin_date=YYYY-MM-DD

    GET  /forecasts
    GET  /forecasts/{forecast_id}

    GET  /forecasts/target/{target_date}/latest

    GET  /forecasts/{forecast_id}/hourly
    GET  /forecasts/{forecast_id}/report

    GET  /running

Architecture:
    API
      ↓
    core.run_forecast()
      ↓
    forecast + analytics + HTML + persistence + MLflow
"""

from __future__ import annotations

import logging
import os

from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi import (
    BackgroundTasks,
    FastAPI,
    HTTPException,
)

from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse
from pydantic import BaseModel

import core

from config import (
    DB_PATH,
    FORECASTS_DIR,
    REPORTS_DIR,
    GRIDCAST_WEATHER_LATITUDE,
    GRIDCAST_WEATHER_LONGITUDE,
    GRIDCAST_TIMEZONE,
)

from data_sources import WeatherConfig

from persistence import (
    get_all_forecast_runs,
    get_forecast_run,
    get_latest_forecast_for_target,
    init_db,
    load_forecast_data,
)


logger = logging.getLogger(__name__)


# =============================================================================
# SERVER-SIDE WEATHER CONFIGURATION
# =============================================================================

# Do not let users choose arbitrary coordinates.
# The inference weather location must match the model's
# training/production weather contract.

WEATHER_CONFIG = WeatherConfig(
    latitude=GRIDCAST_WEATHER_LATITUDE,
    longitude=GRIDCAST_WEATHER_LONGITUDE,
    timezone=GRIDCAST_TIMEZONE,
)


# =============================================================================
# IN-MEMORY JOB STATE
# =============================================================================

# Fine for the current local/course implementation.
#
# Later orchestration can replace this with Prefect,
# Celery, Redis, etc.

_running_jobs: set[str] = set()

_failed_jobs: dict[str, str] = {}


# =============================================================================
# APPLICATION LIFESPAN
# =============================================================================

@asynccontextmanager
async def lifespan(
    app: FastAPI,
):
    """
    Initialize GridCast persistence when the API starts.
    """

    init_db()

    yield


# =============================================================================
# FASTAPI APPLICATION
# =============================================================================

app = FastAPI(
    title="GridCast Offline Forecast API",

    description=(
        "Generate day-ahead electricity-demand forecasts, "
        "retrieve forecast history, and download forecast reports."
    ),

    version="1.0.0",

    lifespan=lifespan,
     root_path=os.getenv("ROOT_PATH", ""),
)


# =============================================================================
# HELPERS
# =============================================================================

def _parse_date(
    value: str,
) -> date:
    """
    Parse and validate an ISO calendar date.
    """

    try:
        parsed = datetime.strptime(
            value,
            "%Y-%m-%d",
        ).date()

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="Date must use YYYY-MM-DD format.",
        ) from exc

    return parsed


def _target_from_origin(
    origin_date: str,
) -> str:
    """
    GridCast semantics:

        origin D
        target D + 1
    """

    origin = _parse_date(
        origin_date
    )

    return (
        origin
        + timedelta(days=1)
    ).isoformat()


# =============================================================================
# BACKGROUND FORECAST JOB
# =============================================================================

def _run_forecast_job(
    origin_date: str,
) -> None:
    """
    Execute one offline forecast in the background.
    """

    try:

        core.run_forecast(
            origin_date=origin_date,
            weather_config=WEATHER_CONFIG,
            log_to_mlflow=True,
        )

        # If a previous execution failed,
        # clear the old error after success.
        _failed_jobs.pop(
            origin_date,
            None,
        )

    except Exception as exc:

        logger.exception(
            "Offline forecast failed for origin_date=%s",
            origin_date,
        )

        _failed_jobs[
            origin_date
        ] = (
            f"{type(exc).__name__}: {exc}"
        )

    finally:

        _running_jobs.discard(
            origin_date
        )


# =============================================================================
# RESPONSE SCHEMAS
# =============================================================================

class ForecastTriggerResponse(
    BaseModel
):
    status: str

    origin_date: str
    target_date: str

    message: str


# =============================================================================
# HEALTH
# =============================================================================

@app.get("/health")
def health():
    """
    GridCast offline service health.
    """

    results = (
        get_all_forecast_runs()
    )

    return {
        "status": "ok",

        "forecasts_stored":
            len(results),

        "running_jobs":
            len(_running_jobs),

        "failed_jobs":
            len(_failed_jobs),

        "db":
            str(DB_PATH),

        "forecasts_dir":
            str(FORECASTS_DIR),

        "reports_dir":
            str(REPORTS_DIR),
    }


# =============================================================================
# TRIGGER FORECAST
# =============================================================================
@app.post(
    "/forecast",
    response_model=ForecastTriggerResponse,
)
async def trigger_forecast(
    origin_date: str,
    background_tasks: BackgroundTasks,
):

    origin = _parse_date(
        origin_date
    )

    # Previous Runs API generally starts around Jan 2024.
    if origin < date(2024, 1, 1):
        raise HTTPException(
            status_code=400,
            detail=(
                "Historical day-ahead replay requires "
                "Open-Meteo Previous Runs data. "
                "Use an origin_date from 2024-01-01 onward."
            ),
        )

    origin_date = origin.isoformat()

    target_date = (
        origin
        + timedelta(days=1)
    ).isoformat()

    if origin_date in _running_jobs:
        return ForecastTriggerResponse(
            status="already_running",
            origin_date=origin_date,
            target_date=target_date,
            message="A forecast for this origin date is already running.",
        )

    _running_jobs.add(
        origin_date
    )

    _failed_jobs.pop(
        origin_date,
        None,
    )

    background_tasks.add_task(
        _run_forecast_job,
        origin_date,
    )

    return ForecastTriggerResponse(
        status="started",
        origin_date=origin_date,
        target_date=target_date,
        message=(
            "GridCast forecast started. "
            f"Poll /forecasts/target/{target_date}/latest."
        ),
    )


# =============================================================================
# FORECAST HISTORY
# =============================================================================

@app.get("/forecasts")
def get_forecasts():
    """
    Return all completed GridCast forecast runs.
    """

    return get_all_forecast_runs()


# IMPORTANT:
# Define this static route before /forecasts/{forecast_id}.

@app.get(
    "/forecasts/target/{target_date}/latest"
)
def get_latest_target_forecast(
    target_date: str,
):

    parsed_target = _parse_date(
        target_date
    )

    normalized_target = (
        parsed_target.isoformat()
    )

    result = (
        get_latest_forecast_for_target(
            normalized_target
        )
    )

    if result is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "No forecast has been stored "
                f"for target_date={normalized_target}."
            ),
        )

    return result


@app.get(
    "/forecasts/{forecast_id}"
)
def get_forecast(
    forecast_id: str,
):
    """
    Retrieve one stored forecast-run summary.
    """

    result = get_forecast_run(
        forecast_id
    )

    if result is None:

        raise HTTPException(
            status_code=404,
            detail=(
                "Unknown forecast_id: "
                f"{forecast_id}"
            ),
        )

    return result


# =============================================================================
# HOURLY FORECAST DATA
# =============================================================================

@app.get(
    "/forecasts/{forecast_id}/hourly"
)
def get_hourly_forecast(
    forecast_id: str,
):
    """
    Return detailed hourly prediction records.
    """

    try:

        forecast = load_forecast_data(
            forecast_id
        )

    except KeyError as exc:

        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc

    except FileNotFoundError as exc:

        raise HTTPException(
            status_code=500,
            detail=str(exc),
        ) from exc

    return jsonable_encoder(
        forecast.to_dict(
            orient="records"
        )
    )


# =============================================================================
# HTML REPORT DOWNLOAD
# =============================================================================

@app.get(
    "/forecasts/{forecast_id}/report"
)
def download_report(
    forecast_id: str,
):
    """
    Download the generated GridCast HTML report.
    """

    result = get_forecast_run(
        forecast_id
    )

    if result is None:

        raise HTTPException(
            status_code=404,
            detail=(
                "Unknown forecast_id: "
                f"{forecast_id}"
            ),
        )

    report_path = Path(
        result["report_path"]
    )

    if not report_path.exists():

        raise HTTPException(
            status_code=404,
            detail=(
                "The report artifact no longer exists."
            ),
        )

    return FileResponse(
        path=report_path,

        media_type="text/html",

        filename=report_path.name,
    )

# =============================================================================
# parquet
# =============================================================================
@app.get(
    "/forecasts/{forecast_id}/parquet"
)
def download_forecast_parquet(
    forecast_id: str,
):
    """
    Download the persisted hourly forecast
    as a Parquet file.
    """

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
        media_type="application/vnd.apache.parquet",
        filename=forecast_path.name,
    )

# =============================================================================
# RUNNING / FAILED JOBS
# =============================================================================

@app.get("/running")
def get_running_jobs():
    """
    Forecast jobs currently executing.
    """

    return [
        {
            "origin_date": origin_date,

            "target_date":
                _target_from_origin(
                    origin_date
                ),
        }

        for origin_date
        in sorted(_running_jobs)
    ]


@app.get("/failures")
def get_failed_jobs():
    """
    Recent background-job failures.

    In-memory only.
    """

    return [
        {
            "origin_date":
                origin_date,

            "target_date":
                _target_from_origin(
                    origin_date
                ),

            "error":
                error,
        }

        for origin_date, error
        in _failed_jobs.items()
    ]