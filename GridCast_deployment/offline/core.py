"""
Core offline inference workflow for GridCast.

No FastAPI.
No orchestration framework.

Pipeline:
    STEP 1  -> load production model
    STEP 2  -> obtain day-ahead weather
    STEP 3  -> prepare inference features
    STEP 4  -> transform features
    STEP 5  -> run predictions
    STEP 6  -> build structured forecast
    STEP 7  -> calculate user analytics
    STEP 8  -> generate HTML report
    STEP 9  -> persist forecast artifacts
    STEP 10 -> track forecast execution in MLflow
"""
import logging
from datetime import datetime, timezone
from uuid import uuid4

import numpy as np
import pandas as pd

from analytics import calculate_forecast_analytics
from data_sources import (
    WeatherConfig,
    fetch_day_ahead_weather,
)
from persistence import (
    save_forecast,
    set_mlflow_tracking_run_id,
)
from report import generate_html_report
from shared.model_loader import load_model
from tracking import log_forecast_run


logger = logging.getLogger(__name__)

# ── STEP 1: Production model ──────────────────────────────────────────────────
def load_champion():
    """
    Load the current GridCast production model bundle.

    Returns:
        Shared model state containing:
        - model
        - preprocessor
        - model version
        - MLflow run ID
        - alias
    """
    return load_model()

# ── STEP 2: Batch acquisition ─────────────────────────────────────────────────

def obtain_batch_data(
    origin_date: str,
    weather_config: WeatherConfig,
):
    """
    Obtain raw weather inputs for one GridCast
    day-ahead forecast.

    Semantics:
        origin_date = D
        target_date = D + 1

    No feature preparation or ML transformation
    occurs here.
    """

    return fetch_day_ahead_weather(
        origin_date=origin_date,
        config=weather_config,
    )

# ── STEP 3: Clean + prepare inference batch ───────────────────────────────────

INFERENCE_FEATURE_COLS = [
    "Date",
    "Hr_End",
    "Dry_Bulb",
    "Dew_Point",
]


def prepare_batch_data(df):
    """
    Convert the raw Step-2 weather batch into the same raw feature
    schema used during GridCast training.

    Input from Step 2:
        timestamp
        Dry_Bulb
        Dew_Point
        origin_date
        target_date
        weather_source

    Output for Step 4:
        Date
        Hr_End
        Dry_Bulb
        Dew_Point

    System_Load is intentionally absent because it is the target y.
    """

    df_clean = df.copy()

    # -------------------------------------------------------------------------
    # 1. Validate required raw columns
    # -------------------------------------------------------------------------
    required_raw_cols = {
        "timestamp",
        "Dry_Bulb",
        "Dew_Point",
    }

    missing = required_raw_cols - set(df_clean.columns)

    if missing:
        raise ValueError(
            f"Batch data is missing required columns: {sorted(missing)}"
        )

    # -------------------------------------------------------------------------
    # 2. Normalize timestamp
    # -------------------------------------------------------------------------
    df_clean["timestamp"] = pd.to_datetime(
        df_clean["timestamp"],
        errors="coerce",
    )

    # -------------------------------------------------------------------------
    # 3. Construct training-compatible temporal columns
    # -------------------------------------------------------------------------
    df_clean["Date"] = df_clean["timestamp"].dt.date

    # ISO-NE historical schema uses Hour Ending:
    # 00:00 -> HE 1
    # 01:00 -> HE 2
    # ...
    # 23:00 -> HE 24
    df_clean["Hr_End"] = (
        df_clean["timestamp"].dt.hour + 1
    ).astype("Int64")

    # -------------------------------------------------------------------------
    # 4. Ensure weather columns are numeric
    # -------------------------------------------------------------------------
    df_clean["Dry_Bulb"] = pd.to_numeric(
        df_clean["Dry_Bulb"],
        errors="coerce",
    )

    df_clean["Dew_Point"] = pd.to_numeric(
        df_clean["Dew_Point"],
        errors="coerce",
    )

    # -------------------------------------------------------------------------
    # 5. Keep only model-input columns
    # -------------------------------------------------------------------------
    X = df_clean[
        INFERENCE_FEATURE_COLS
    ].copy()

    # -------------------------------------------------------------------------
    # 6. Reject invalid/missing inference values
    # -------------------------------------------------------------------------
    if X.isna().any().any():

        bad_columns = (
            X.columns[
                X.isna().any()
            ]
            .tolist()
        )

        raise ValueError(
            "Prepared inference batch contains missing/invalid values "
            f"in columns: {bad_columns}"
        )

    # -------------------------------------------------------------------------
    # 7. Sort chronologically and reset index
    # -------------------------------------------------------------------------
    X = (
        X
        .sort_values(
            by=["Date", "Hr_End"]
        )
        .reset_index(drop=True)
    )

    return X

# ── STEP 4: Transform features ────────────────────────────────────────────────

def transform_features(
    X: pd.DataFrame,
    champion,
):
    """
    Apply the exact fitted preprocessing pipeline used during training.

    The saved preprocessor already contains:
        1. ISONETimeFeatureEngineer
        2. RobustScaler

    Input:
        Date
        Hr_End
        Dry_Bulb
        Dew_Point

    Output:
        model-ready transformed feature matrix
    """

    return champion.preprocessor.transform(X)


# ── STEP 5: Run predictions ───────────────────────────────────────────────────

def run_predictions(
    X_transformed,
    champion,
):
    """
    Run the production GridCast model on the transformed daily batch.

    Input:
        X_transformed:
            Output from STEP 4.

        champion:
            Production model bundle loaded in STEP 1.

    Returns:
        One System_Load prediction for each hourly input row.
    """

    predictions = champion.model.predict(
        X_transformed
    )

    if len(predictions) != len(X_transformed):
        raise RuntimeError(
            "Prediction count does not match input row count. "
            f"inputs={len(X_transformed)}, "
            f"predictions={len(predictions)}"
        )

    return predictions



# ── STEP 6: Build forecast result ─────────────────────────────────────────────



def build_forecast_result(
    X: pd.DataFrame,
    predictions,
    raw_batch: pd.DataFrame,
    champion,
) -> pd.DataFrame:
    """
    Build the final structured hourly forecast artifact.

    Combines:
        - target Date / Hr_End
        - weather inputs
        - model predictions
        - forecast timing metadata
        - model lineage
        - weather-source lineage

    This step performs NO analytics and NO persistence.

    Returns
    -------
    pd.DataFrame

    Columns:
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
    """

    if X.empty:
        raise ValueError(
            "Cannot build forecast result from an empty feature batch."
        )

    predictions = np.asarray(
        predictions,
        dtype=float,
    ).reshape(-1)

    # -------------------------------------------------------------------------
    # 1. Validate prediction count
    # -------------------------------------------------------------------------

    if len(predictions) != len(X):
        raise ValueError(
            "Prediction count does not match feature row count. "
            f"features={len(X)}, predictions={len(predictions)}"
        )

    # -------------------------------------------------------------------------
    # 2. Validate numerical predictions
    # -------------------------------------------------------------------------

    if not np.isfinite(predictions).all():
        raise ValueError(
            "Model produced NaN or infinite load predictions."
        )

    # Electricity demand should not be negative.
    if (predictions < 0).any():
        raise ValueError(
            "Model produced negative electricity-demand predictions."
        )

    # -------------------------------------------------------------------------
    # 3. Validate metadata from Step 2
    # -------------------------------------------------------------------------

    required_metadata = {
        "origin_date",
        "target_date",
        "weather_source",
    }

    missing_metadata = (
        required_metadata
        - set(raw_batch.columns)
    )

    if missing_metadata:
        raise ValueError(
            "Raw batch is missing forecast metadata: "
            f"{sorted(missing_metadata)}"
        )

    origin_dates = raw_batch[
        "origin_date"
    ].dropna().unique()

    target_dates = raw_batch[
        "target_date"
    ].dropna().unique()

    weather_sources = raw_batch[
        "weather_source"
    ].dropna().unique()

    if len(origin_dates) != 1:
        raise ValueError(
            "A forecast batch must contain exactly one origin_date."
        )

    if len(target_dates) != 1:
        raise ValueError(
            "A forecast batch must contain exactly one target_date."
        )

    if len(weather_sources) != 1:
        raise ValueError(
            "A forecast batch must contain exactly one weather_source."
        )

    origin_date = origin_dates[0]
    target_date = target_dates[0]
    weather_source = weather_sources[0]

    # -------------------------------------------------------------------------
    # 4. Build hourly forecast artifact
    # -------------------------------------------------------------------------

    forecast = X[
        [
            "Date",
            "Hr_End",
            "Dry_Bulb",
            "Dew_Point",
        ]
    ].copy()

    forecast["Predicted_Load_MW"] = predictions

    # -------------------------------------------------------------------------
    # 5. Add forecast lineage
    # -------------------------------------------------------------------------
    forecast_id = uuid4().hex
    forecast["forecast_id"] = forecast_id
    forecast["origin_date"] = origin_date
    forecast["target_date"] = target_date

    forecast["weather_source"] = (
        weather_source
    )

    forecast["model_version"] = (
        champion.version
    )

    forecast["model_run_id"] = (
        champion.run_id
    )

    forecast["model_alias"] = (
        champion.alias
    )

    forecast["generated_at"] = (
        datetime.now(
            timezone.utc
        ).isoformat()
    )

    # -------------------------------------------------------------------------
    # 6. Final ordering
    # -------------------------------------------------------------------------

    column_order = [
        "forecast_id",
        "Date",
        "Hr_End",
        "Predicted_Load_MW",
        "Dry_Bulb",
        "Dew_Point",
        "origin_date",
        "target_date",
        "weather_source",
        "model_version",
        "model_run_id",
        "model_alias",
        "generated_at",
    ]

    forecast = (
        forecast[column_order]
        .sort_values(
            by=[
                "Date",
                "Hr_End",
            ]
        )
        .reset_index(drop=True)
    )

    return forecast

# ── STEP 7: Forecast analytics ────────────────────────────────────────────────

def calculate_analytics(
    forecast: pd.DataFrame,
) -> dict:
    """
    Calculate user-facing analytics from the
    structured daily forecast.
    """

    return calculate_forecast_analytics(
        forecast
    )

# ── STEP 8: Generate HTML report ──────────────────────────────────────────────

def generate_report(
    forecast: pd.DataFrame,
    analytics: dict,
):
    """
    Generate the downloadable GridCast HTML report.
    """

    return generate_html_report(
        forecast=forecast,
        analytics=analytics,
    )

# ── STEP 9: Persist forecast artifacts ────────────────────────────────────────

def persist_forecast(
    forecast: pd.DataFrame,
    analytics: dict,
    report_path,
):
    """
    Persist the completed GridCast forecast,
    analytics and downloadable report metadata.
    """

    return save_forecast(
        forecast=forecast,
        analytics=analytics,
        report_path=report_path,
    )

# ── Complete offline forecast workflow ────────────────────────────────────────

def run_forecast(
    origin_date: str,
    weather_config: WeatherConfig,
    log_to_mlflow: bool = True,
) -> dict:
    """
    Execute one complete GridCast day-ahead forecast.

    Pipeline:
        1. Load champion model
        2. Obtain weather batch
        3. Prepare raw features
        4. Transform features
        5. Run prediction
        6. Build structured forecast
        7. Calculate analytics
        8. Generate HTML report
        9. Persist artifacts
       10. Track execution in MLflow

    MLflow tracking is intentionally non-critical:
    a tracking outage must not destroy a valid forecast.
    """

    # -------------------------------------------------------------------------
    # STEP 1 — Load model
    # -------------------------------------------------------------------------

    champion = load_champion()

    # -------------------------------------------------------------------------
    # STEP 2 — Obtain weather
    # -------------------------------------------------------------------------

    raw_batch = obtain_batch_data(
        origin_date=origin_date,
        weather_config=weather_config,
    )

    # -------------------------------------------------------------------------
    # STEP 3 — Prepare model input
    # -------------------------------------------------------------------------

    X = prepare_batch_data(
        raw_batch
    )

    # -------------------------------------------------------------------------
    # STEP 4 — Transform
    # -------------------------------------------------------------------------

    X_transformed = transform_features(
        X=X,
        champion=champion,
    )

    # -------------------------------------------------------------------------
    # STEP 5 — Predict
    # -------------------------------------------------------------------------

    predictions = run_predictions(
        X_transformed=X_transformed,
        champion=champion,
    )

    # -------------------------------------------------------------------------
    # STEP 6 — Build structured forecast
    # -------------------------------------------------------------------------

    forecast = build_forecast_result(
        X=X,
        predictions=predictions,
        raw_batch=raw_batch,
        champion=champion,
    )

    # -------------------------------------------------------------------------
    # STEP 7 — User analytics
    # -------------------------------------------------------------------------

    analytics = calculate_analytics(
        forecast
    )

    # -------------------------------------------------------------------------
    # STEP 8 — HTML report
    # -------------------------------------------------------------------------

    report_path = generate_report(
        forecast=forecast,
        analytics=analytics,
    )

    # -------------------------------------------------------------------------
    # STEP 9 — Local persistence
    # -------------------------------------------------------------------------

    artifacts = persist_forecast(
        forecast=forecast,
        analytics=analytics,
        report_path=report_path,
    )

    # -------------------------------------------------------------------------
    # STEP 10 — MLflow execution tracking
    #
    # Tracking is not allowed to invalidate an otherwise valid forecast.
    # -------------------------------------------------------------------------

    mlflow_tracking_run_id = None
    tracking_error = None

    if log_to_mlflow:

        try:

            mlflow_tracking_run_id = (
                log_forecast_run(
                    forecast=forecast,
                    analytics=analytics,
                    artifacts=artifacts,
                )
            )

            set_mlflow_tracking_run_id(
                forecast_id=artifacts[
                    "forecast_id"
                ],
                mlflow_tracking_run_id=(
                    mlflow_tracking_run_id
                ),
            )

        except Exception as exc:

            tracking_error = (
                f"{type(exc).__name__}: {exc}"
            )

            logger.exception(
                "MLflow tracking failed for forecast_id=%s",
                artifacts["forecast_id"],
            )

    # -------------------------------------------------------------------------
    # Final application-level result
    # -------------------------------------------------------------------------

    return {
        "forecast_id":
            artifacts["forecast_id"],

        "forecast":
            forecast,

        "analytics":
            analytics,

        "forecast_path":
            artifacts["forecast_path"],

        "report_path":
            artifacts["report_path"],

        "database_path":
            artifacts["database_path"],

        "mlflow_tracking_run_id":
            mlflow_tracking_run_id,

        "tracking_error":
            tracking_error,
    }