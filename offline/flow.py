"""
Prefect orchestration for GridCast offline forecasting.

Responsibilities:
    - accept an origin date
    - execute the existing GridCast forecast pipeline
    - provide Prefect retries, logging, and observability

The forecasting business logic remains in core.py.

Current simplified weather mode:
    - historical ERA5 weather
    - target_date = origin_date + 1
    - target date must satisfy ERA5 availability constraints
"""

from __future__ import annotations

from prefect import flow, task, get_run_logger

import core

from data_sources import WeatherConfig
from config import (
    GRIDCAST_WEATHER_LATITUDE,
    GRIDCAST_WEATHER_LONGITUDE,
    GRIDCAST_TIMEZONE,
)


# =============================================================================
# CONFIGURATION
# =============================================================================

WEATHER_CONFIG = WeatherConfig(
    latitude=GRIDCAST_WEATHER_LATITUDE,
    longitude=GRIDCAST_WEATHER_LONGITUDE,
    timezone=GRIDCAST_TIMEZONE,
)


# =============================================================================
# PREFECT TASK
# =============================================================================

@task(
    name="run-gridcast-forecast",
    retries=2,
    retry_delay_seconds=30,
)
def run_forecast_task(
    origin_date: str,
) -> dict:
    """
    Execute one complete GridCast offline forecast.

    Prefect retries the full forecast operation if a
    retryable exception escapes from core.run_forecast().
    """

    logger = get_run_logger()

    logger.info(
        "Starting GridCast forecast for origin_date=%s",
        origin_date,
    )

    result = core.run_forecast(
        origin_date=origin_date,
        weather_config=WEATHER_CONFIG,
        log_to_mlflow=True,
    )

    forecast = result["forecast"]
    analytics = result["analytics"]

    target_date = str(
        forecast["target_date"].iloc[0]
    )

    logger.info(
        "Forecast completed: forecast_id=%s",
        result["forecast_id"],
    )

    logger.info(
        "Origin=%s Target=%s Hours=%d",
        origin_date,
        target_date,
        len(forecast),
    )

    logger.info(
        "Peak=%.2f MW at HE%d | "
        "Average=%.2f MW | "
        "Energy=%.2f MWh",
        analytics["peak_load_mw"],
        analytics["peak_hour"],
        analytics["average_load_mw"],
        analytics["daily_energy_mwh"],
    )

    logger.info(
        "Forecast artifact: %s",
        result["forecast_path"],
    )

    logger.info(
        "HTML report: %s",
        result["report_path"],
    )

    if result["mlflow_tracking_run_id"]:
        logger.info(
            "MLflow forecast run: %s",
            result["mlflow_tracking_run_id"],
        )

    if result["tracking_error"]:
        logger.warning(
            "Forecast succeeded but MLflow tracking failed: %s",
            result["tracking_error"],
        )

    # Avoid returning the entire DataFrame through Prefect.
    # Detailed forecast data already lives in Parquet.
    return {
        "forecast_id": result["forecast_id"],
        "origin_date": origin_date,
        "target_date": target_date,
        "total_hours": len(forecast),

        "forecast_path": result["forecast_path"],
        "report_path": result["report_path"],
        "database_path": result["database_path"],

        "mlflow_tracking_run_id": (
            result["mlflow_tracking_run_id"]
        ),

        "tracking_error": result["tracking_error"],
    }


# =============================================================================
# PREFECT FLOW
# =============================================================================

@flow(
    name="gridcast-offline-forecast",
    log_prints=True,
)
def gridcast_forecast_flow(
    origin_date: str,
) -> dict:
    """
    Orchestrate one GridCast historical forecast.

    Parameters
    ----------
    origin_date:
        Forecast origin date D in YYYY-MM-DD format.

    GridCast predicts:
        target_date = D + 1 day
    """

    logger = get_run_logger()

    logger.info("=" * 60)
    logger.info("GRIDCAST OFFLINE FORECAST")
    logger.info("Origin date: %s", origin_date)
    logger.info("Weather source: ERA5 historical weather")
    logger.info("=" * 60)

    result = run_forecast_task(
        origin_date
    )

    logger.info("=" * 60)
    logger.info("FORECAST COMPLETE")
    logger.info(
        "Forecast ID: %s",
        result["forecast_id"],
    )
    logger.info(
        "Target date: %s",
        result["target_date"],
    )
    logger.info("=" * 60)

    return result


# =============================================================================
# LOCAL EXECUTION
# =============================================================================

if __name__ == "__main__":
    gridcast_forecast_flow(
        origin_date="2025-04-2",
    )