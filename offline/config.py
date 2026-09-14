"""
Configuration for GridCast offline inference.

Centralizes filesystem paths so local development,
Docker, API, persistence, and report generation all
use the same locations.
"""

import os
from pathlib import Path


OFFLINE_DIR = Path(__file__).resolve().parent

GRIDCAST_WEATHER_LATITUDE =  42.3601
GRIDCAST_WEATHER_LONGITUDE = -71.0589
GRIDCAST_TIMEZONE = "America/New_York"
# Can be overridden inside Docker:
#
# GRIDCAST_OFFLINE_DATA_DIR=/data/gridcast
#
DATA_DIR = Path(
    os.getenv(
        "GRIDCAST_OFFLINE_DATA_DIR",
        str(OFFLINE_DIR),
    )
).expanduser()


DB_PATH = (
    DATA_DIR
    / "batch_results.db"
)

FORECASTS_DIR = (
    DATA_DIR
    / "forecasts"
)

REPORTS_DIR = (
    DATA_DIR
    / "reports"
)


def ensure_data_directories() -> None:
    """
    Ensure GridCast offline artifact directories exist.
    """

    DATA_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    FORECASTS_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    REPORTS_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )