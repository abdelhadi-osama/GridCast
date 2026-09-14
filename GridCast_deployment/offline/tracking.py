"""
MLflow tracking for GridCast offline forecasts.

This records forecast executions and their artifacts.

It does NOT contain model-loading logic.
"""

from __future__ import annotations

import os
from pathlib import Path

import mlflow
import pandas as pd

from shared.model_loader import (
    MLFLOW_TRACKING_URI,
)


MLFLOW_FORECAST_EXPERIMENT = os.getenv(
    "GRIDCAST_MLFLOW_FORECAST_EXPERIMENT",
    "gridcast_offline_forecasts",
)


def log_forecast_run(
    forecast: pd.DataFrame,
    analytics: dict,
    artifacts: dict,
) -> str:
    """
    Log one completed GridCast forecast execution to MLflow.

    Returns
    -------
    str
        MLflow tracking run ID.
    """

    if forecast.empty:
        raise ValueError(
            "Cannot log an empty forecast to MLflow."
        )

    # -------------------------------------------------------------------------
    # Extract forecast metadata
    # -------------------------------------------------------------------------

    forecast_id = str(
        forecast["forecast_id"].iloc[0]
    )

    origin_date = str(
        forecast["origin_date"].iloc[0]
    )

    target_date = str(
        forecast["target_date"].iloc[0]
    )

    model_version = str(
        forecast["model_version"].iloc[0]
    )

    model_run_id = str(
        forecast["model_run_id"].iloc[0]
    )

    model_alias = str(
        forecast["model_alias"].iloc[0]
    )

    weather_source = str(
        forecast["weather_source"].iloc[0]
    )

    # -------------------------------------------------------------------------
    # MLflow setup
    # -------------------------------------------------------------------------

    mlflow.set_tracking_uri(
        MLFLOW_TRACKING_URI
    )

    mlflow.set_experiment(
        MLFLOW_FORECAST_EXPERIMENT
    )

    run_name = (
        f"forecast_"
        f"{target_date}_"
        f"{forecast_id[:8]}"
    )

    # -------------------------------------------------------------------------
    # Forecast execution run
    # -------------------------------------------------------------------------

    with mlflow.start_run(
        run_name=run_name
    ) as run:

        # Tags describe lineage/category.
        mlflow.set_tags(
            {
                "type": "offline_forecast",
                "forecast_id": forecast_id,

                "model_version": model_version,
                "model_alias": model_alias,

                # This is the training/model run,
                # not this forecast-execution run.
                "source_model_run_id": model_run_id,

                "weather_source": weather_source,
            }
        )

        # Parameters describe this execution.
        mlflow.log_params(
            {
                "origin_date": origin_date,
                "target_date": target_date,
                "total_hours": len(forecast),
            }
        )

        # ---------------------------------------------------------------------
        # Forecast statistics.
        #
        # These are NOT model-accuracy metrics.
        # No actual target exists yet.
        # ---------------------------------------------------------------------

        metrics = {
            "peak_load_mw":
                analytics["peak_load_mw"],

            "minimum_load_mw":
                analytics["minimum_load_mw"],

            "average_load_mw":
                analytics["average_load_mw"],

            "daily_energy_mwh":
                analytics["daily_energy_mwh"],

            "load_factor":
                analytics["load_factor"],

            "max_ramp_up_mw":
                analytics["max_ramp_up_mw"],

            "max_ramp_down_mw":
                analytics["max_ramp_down_mw"],
        }

        mlflow.log_metrics(
            {
                key: float(value)
                for key, value in metrics.items()
                if value is not None
            }
        )

        # ---------------------------------------------------------------------
        # Artifacts
        # ---------------------------------------------------------------------

        forecast_path = Path(
            artifacts["forecast_path"]
        )

        report_path = Path(
            artifacts["report_path"]
        )

        if forecast_path.exists():
            mlflow.log_artifact(
                str(forecast_path),
                artifact_path="forecast",
            )

        if report_path.exists():
            mlflow.log_artifact(
                str(report_path),
                artifact_path="report",
            )

        tracking_run_id = (
            run.info.run_id
        )

    return tracking_run_id