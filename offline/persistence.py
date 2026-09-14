"""
Persistence layer for GridCast offline inference.

Stores:
    - detailed hourly forecast artifact as Parquet
    - forecast metadata and analytics in SQLite
    - path to downloadable HTML report

This module does NOT:
    - load models
    - call weather APIs
    - run inference
    - calculate analytics
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pandas as pd


from config import (
    DB_PATH,
    FORECASTS_DIR,
    ensure_data_directories,
)


# =============================================================================
# DATABASE INITIALIZATION
# =============================================================================

def init_db() -> None:
    """
    Initialize GridCast offline persistence.
    """

    ensure_data_directories()

    conn = sqlite3.connect(
        DB_PATH
    )

    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS forecast_runs (

                forecast_id        TEXT PRIMARY KEY,

                origin_date        TEXT NOT NULL,
                target_date        TEXT NOT NULL,

                generated_at       TEXT NOT NULL,

                model_version      TEXT NOT NULL,
                model_run_id       TEXT NOT NULL,
                model_alias        TEXT NOT NULL,

                weather_source     TEXT NOT NULL,

                total_hours        INTEGER NOT NULL,

                peak_load_mw       REAL,
                peak_hour          INTEGER,

                minimum_load_mw    REAL,
                minimum_hour       INTEGER,

                average_load_mw    REAL,
                daily_energy_mwh   REAL,
                load_factor        REAL,

                max_ramp_up_mw          REAL,
                max_ramp_up_from_hour   INTEGER,
                max_ramp_up_to_hour     INTEGER,

                max_ramp_down_mw        REAL,
                max_ramp_down_from_hour INTEGER,
                max_ramp_down_to_hour   INTEGER,

                forecast_path      TEXT NOT NULL,
                report_path        TEXT NOT NULL,

                analytics_json     TEXT NOT NULL,

                mlflow_tracking_run_id TEXT
            )
            """
        )

        # ---------------------------------------------------------------------
        # Migration for databases created before MLflow tracking was added.
        # CREATE TABLE IF NOT EXISTS does not modify existing tables.
        # ---------------------------------------------------------------------

        existing_columns = {
            row[1]
            for row in conn.execute(
                "PRAGMA table_info(forecast_runs)"
            ).fetchall()
        }

        if (
            "mlflow_tracking_run_id"
            not in existing_columns
        ):
            conn.execute(
                """
                ALTER TABLE forecast_runs
                ADD COLUMN mlflow_tracking_run_id TEXT
                """
            )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_forecast_runs_target_date
            ON forecast_runs(target_date)
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_forecast_runs_origin_date
            ON forecast_runs(origin_date)
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_forecast_runs_generated_at
            ON forecast_runs(generated_at)
            """
        )

        conn.commit()

    finally:
        conn.close()

# =============================================================================
# SAVE
# =============================================================================

def save_forecast(
    forecast: pd.DataFrame,
    analytics: dict,
    report_path: Path,
) -> dict:
    """
    Persist one completed GridCast forecast run.

    Detailed hourly data:
        Parquet

    Searchable summary:
        SQLite

    HTML report:
        Existing report artifact

    Returns
    -------
    dict
        Persistence metadata.
    """

    if forecast.empty:
        raise ValueError(
            "Cannot persist an empty forecast."
        )

    required_columns = {
        "forecast_id",
        "origin_date",
        "target_date",
        "generated_at",
        "weather_source",
        "model_version",
        "model_run_id",
        "model_alias",
    }

    missing = required_columns - set(
        forecast.columns
    )

    if missing:
        raise ValueError(
            "Forecast is missing persistence metadata: "
            f"{sorted(missing)}"
        )

    # -------------------------------------------------------------------------
    # Ensure one forecast run only
    # -------------------------------------------------------------------------

    metadata_columns = [
        "forecast_id",
        "origin_date",
        "target_date",
        "generated_at",
        "weather_source",
        "model_version",
        "model_run_id",
        "model_alias",
    ]

    metadata = {}

    for column in metadata_columns:

        values = (
            forecast[column]
            .dropna()
            .astype(str)
            .unique()
        )

        if len(values) != 1:
            raise ValueError(
                f"Forecast must contain exactly one "
                f"value for '{column}'. "
                f"Found {len(values)}."
            )

        metadata[column] = values[0]

    forecast_id = metadata[
        "forecast_id"
    ]

    target_date = metadata[
        "target_date"
    ]

    # -------------------------------------------------------------------------
    # Detailed hourly forecast artifact
    # -------------------------------------------------------------------------

    FORECASTS_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    forecast_path = (
        FORECASTS_DIR
        / (
            f"gridcast_"
            f"{target_date}_"
            f"{forecast_id[:8]}.parquet"
        )
    )

    forecast.to_parquet(
        forecast_path,
        index=False,
    )

    # -------------------------------------------------------------------------
    # Validate report
    # -------------------------------------------------------------------------

    report_path = Path(
        report_path
    )

    if not report_path.exists():
        raise FileNotFoundError(
            f"HTML report does not exist: "
            f"{report_path}"
        )

    # -------------------------------------------------------------------------
    # Analytics JSON
    # -------------------------------------------------------------------------

    analytics_json = json.dumps(
        analytics,
        allow_nan=False,
    )

    # -------------------------------------------------------------------------
    # SQLite summary
    # -------------------------------------------------------------------------

    init_db()

    conn = sqlite3.connect(
        DB_PATH
    )

    try:

        conn.execute(
            """
            INSERT INTO forecast_runs (

                forecast_id,

                origin_date,
                target_date,
                generated_at,

                model_version,
                model_run_id,
                model_alias,

                weather_source,

                total_hours,

                peak_load_mw,
                peak_hour,

                minimum_load_mw,
                minimum_hour,

                average_load_mw,
                daily_energy_mwh,
                load_factor,

                max_ramp_up_mw,
                max_ramp_up_from_hour,
                max_ramp_up_to_hour,

                max_ramp_down_mw,
                max_ramp_down_from_hour,
                max_ramp_down_to_hour,

                forecast_path,
                report_path,

                analytics_json
            )

            VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?,
                ?, ?, ?
            )
            """,

            (
                forecast_id,

                metadata["origin_date"],
                metadata["target_date"],
                metadata["generated_at"],

                metadata["model_version"],
                metadata["model_run_id"],
                metadata["model_alias"],

                metadata["weather_source"],

                len(forecast),

                analytics.get(
                    "peak_load_mw"
                ),

                analytics.get(
                    "peak_hour"
                ),

                analytics.get(
                    "minimum_load_mw"
                ),

                analytics.get(
                    "minimum_hour"
                ),

                analytics.get(
                    "average_load_mw"
                ),

                analytics.get(
                    "daily_energy_mwh"
                ),

                analytics.get(
                    "load_factor"
                ),

                analytics.get(
                    "max_ramp_up_mw"
                ),

                analytics.get(
                    "max_ramp_up_from_hour"
                ),

                analytics.get(
                    "max_ramp_up_to_hour"
                ),

                analytics.get(
                    "max_ramp_down_mw"
                ),

                analytics.get(
                    "max_ramp_down_from_hour"
                ),

                analytics.get(
                    "max_ramp_down_to_hour"
                ),

                str(
                    forecast_path
                ),

                str(
                    report_path
                ),

                analytics_json,
            ),
        )

        conn.commit()

    except Exception:

        conn.rollback()

        # Avoid leaving an orphan Parquet artifact
        # when metadata persistence fails.
        if forecast_path.exists():
            forecast_path.unlink()

        raise

    finally:
        conn.close()

    return {
        "forecast_id": forecast_id,
        "forecast_path": str(
            forecast_path
        ),
        "report_path": str(
            report_path
        ),
        "database_path": str(
            DB_PATH
        ),
    }


# =============================================================================
# READ OPERATIONS
# =============================================================================

def get_forecast_run(
    forecast_id: str,
) -> dict | None:
    """
    Retrieve one forecast-run summary.
    """

    if not DB_PATH.exists():
        return None

    conn = sqlite3.connect(
        DB_PATH
    )

    conn.row_factory = (
        sqlite3.Row
    )

    try:
        row = conn.execute(
            """
            SELECT *
            FROM forecast_runs
            WHERE forecast_id = ?
            """,
            (forecast_id,),
        ).fetchone()

    finally:
        conn.close()

    return (
        dict(row)
        if row
        else None
    )


def get_all_forecast_runs() -> list[dict]:
    """
    Retrieve all stored forecast runs,
    newest first.
    """

    if not DB_PATH.exists():
        return []

    conn = sqlite3.connect(
        DB_PATH
    )

    conn.row_factory = (
        sqlite3.Row
    )

    try:
        rows = conn.execute(
            """
            SELECT *
            FROM forecast_runs
            ORDER BY generated_at DESC
            """
        ).fetchall()

    finally:
        conn.close()

    return [
        dict(row)
        for row in rows
    ]
def get_latest_forecast_for_target(
    target_date: str,
) -> dict | None:
    """
    Return the newest stored forecast for a target date.
    """

    if not DB_PATH.exists():
        return None

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    try:
        row = conn.execute(
            """
            SELECT *
            FROM forecast_runs
            WHERE target_date = ?
            ORDER BY generated_at DESC
            LIMIT 1
            """,
            (target_date,),
        ).fetchone()

    finally:
        conn.close()

    return dict(row) if row else None

def get_all_forecast_runs(
    limit: int | None = None,
) -> list[dict]:
    """
    Retrieve stored forecast runs,
    newest first.
    """

    if not DB_PATH.exists():
        return []

    conn = sqlite3.connect(
        DB_PATH
    )

    conn.row_factory = (
        sqlite3.Row
    )

    try:

        if limit is None:

            rows = conn.execute(
                """
                SELECT *
                FROM forecast_runs
                ORDER BY generated_at DESC
                """
            ).fetchall()

        else:

            if limit <= 0:
                raise ValueError(
                    "limit must be greater than zero."
                )

            rows = conn.execute(
                """
                SELECT *
                FROM forecast_runs
                ORDER BY generated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

    finally:
        conn.close()

    return [
        dict(row)
        for row in rows
    ]

def load_forecast_data(
    forecast_id: str,
) -> pd.DataFrame:
    """
    Load the detailed hourly Parquet artifact
    belonging to one forecast run.
    """

    result = get_forecast_run(
        forecast_id
    )

    if result is None:
        raise KeyError(
            f"Unknown forecast_id: {forecast_id}"
        )

    forecast_path = Path(
        result["forecast_path"]
    )

    if not forecast_path.exists():
        raise FileNotFoundError(
            "Stored forecast artifact does not exist: "
            f"{forecast_path}"
        )

    return pd.read_parquet(
        forecast_path
    )

def set_mlflow_tracking_run_id(
    forecast_id: str,
    mlflow_tracking_run_id: str,
) -> None:
    """
    Link a stored forecast with its MLflow
    forecast-execution run.
    """

    init_db()

    conn = sqlite3.connect(
        DB_PATH
    )

    try:

        cursor = conn.execute(
            """
            UPDATE forecast_runs

            SET mlflow_tracking_run_id = ?

            WHERE forecast_id = ?
            """,
            (
                mlflow_tracking_run_id,
                forecast_id,
            ),
        )

        if cursor.rowcount != 1:
            raise KeyError(
                "Could not link MLflow run. "
                f"Unknown forecast_id: {forecast_id}"
            )

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()