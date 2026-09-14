"""
External data acquisition for GridCast offline inference.

STEP 2 responsibility only:
    origin date D
        -> target date = D + 1 day
        -> obtain historical weather for target date

Current simplified mode:
    - GridCast uses Open-Meteo Historical Weather API only.
    - The target date must be a completed historical day.
    - Weather inputs are historical/reanalysis weather, NOT the
      weather forecast that was available on the origin date.

Known limitation:
    This is not a strict operational day-ahead backtest because
    historical realized/reanalysis weather contains information
    that was not available at forecast issuance time.

    A future version may replace this source with archived
    weather forecasts / single model runs.

This module does NOT:
- fetch System_Load
- perform feature engineering
- run the ML preprocessor
- run model prediction
- calculate monitoring metrics
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Union
from zoneinfo import ZoneInfo

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


# ── API endpoints ─────────────────────────────────────────────────────────────
'''
OPEN_METEO_FORECAST_URL = (
    "https://api.open-meteo.com/v1/forecast"
)

OPEN_METEO_PREVIOUS_RUNS_URL = (
    "https://previous-runs-api.open-meteo.com/v1/forecast"
)
'''
OPEN_METEO_HISTORICAL_URL = (
    "https://archive-api.open-meteo.com/v1/archive"
)

# ISO-NE operates in US Eastern time.
DEFAULT_TIMEZONE = "America/New_York"


# ── Configuration ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class WeatherConfig:
    latitude: float
    longitude: float

    timezone: str = DEFAULT_TIMEZONE
    temperature_unit: str = "fahrenheit"

    historical_model: str = "era5"
    historical_delay_days: int = 5

    connect_timeout: float = 5.0
    read_timeout: float = 60.0

    max_retries: int = 4
    backoff_factor: float = 1.0


# ── HTTP infrastructure ───────────────────────────────────────────────────────

def _build_session(
    config: WeatherConfig,
) -> requests.Session:
    """
    Create a reusable HTTP session with retry handling.

    Retries only transient/network/server failures.
    """

    retry = Retry(
        total=config.max_retries,
        connect=config.max_retries,
        read=config.max_retries,
        status=config.max_retries,
        backoff_factor=config.backoff_factor,

        # Retry common transient HTTP failures.
        status_forcelist=(
            429,
            500,
            502,
            503,
            504,
        ),

        allowed_methods=frozenset(["GET"]),

        # We call raise_for_status() ourselves.
        raise_on_status=False,
    )

    adapter = HTTPAdapter(
        max_retries=retry
    )

    session = requests.Session()

    session.mount(
        "https://",
        adapter,
    )

    return session


# ── Date handling ─────────────────────────────────────────────────────────────

def _parse_date(
    value: Union[str, date, datetime],
) -> date:
    """
    Normalize date input.

    Accepted:
        "2026-09-14"
        datetime.date
        datetime.datetime
    """

    if isinstance(value, datetime):
        return value.date()

    if isinstance(value, date):
        return value

    if isinstance(value, str):
        try:
            return datetime.strptime(
                value,
                "%Y-%m-%d",
            ).date()

        except ValueError as exc:
            raise ValueError(
                "origin_date must use YYYY-MM-DD format. "
                f"Received: {value!r}"
            ) from exc

    raise TypeError(
        "origin_date must be str, date, or datetime."
    )


# ── Response validation ───────────────────────────────────────────────────────

def _get_hourly_payload(
    response,
) -> dict:
    """
    Parse and validate an Open-Meteo response.
    """

    try:
        payload = response.json()

    except ValueError as exc:
        raise RuntimeError(
            "Open-Meteo returned invalid JSON. "
            f"status={response.status_code}, "
            f"body={response.text[:500]!r}"
        ) from exc

    if payload.get("error"):
        raise RuntimeError(
            "Open-Meteo Historical Weather API error: "
            f"{payload.get('reason', 'Unknown reason')}"
        )

    if "hourly" not in payload:
        raise RuntimeError(
            "Open-Meteo response does not contain 'hourly'. "
            f"Response keys: {list(payload.keys())}"
        )

    return payload["hourly"]

#------------------    Fetch historical hourly weather for one completed target day.

def _fetch_historical_weather(
    target_date: date,
    config: WeatherConfig,
    session: requests.Session,
) -> pd.DataFrame:
    """
    Fetch historical hourly weather for one completed target day.

    Important
    ---------
    These are historical/reanalysis weather conditions.
    They are NOT archived day-ahead weather forecasts.
    """

    params = {
    "latitude": config.latitude,
    "longitude": config.longitude,

    "start_date": target_date.isoformat(),
    "end_date": target_date.isoformat(),

    "hourly": (
        "temperature_2m,"
        "dew_point_2m"
    ),

    "models": config.historical_model,

    "temperature_unit": config.temperature_unit,
    "timezone": config.timezone,
}

    try:
        response = session.get(
            OPEN_METEO_HISTORICAL_URL,
            params=params,
            timeout=(
                config.connect_timeout,
                config.read_timeout,
            ),
        )

    except requests.RequestException as exc:
        raise ConnectionError(
            "Failed to connect to the Open-Meteo "
            "Historical Weather API."
        ) from exc

    hourly = _get_hourly_payload(
        response
    )

    required = {
        "time",
        "temperature_2m",
        "dew_point_2m",
    }

    missing = required - set(
        hourly
    )

    if missing:
        raise RuntimeError(
            "Open-Meteo Historical Weather API "
            "response is missing fields: "
            f"{sorted(missing)}"
        )

    lengths = {
        len(hourly["time"]),
        len(hourly["temperature_2m"]),
        len(hourly["dew_point_2m"]),
    }

    if len(lengths) != 1:
        raise RuntimeError(
            "Open-Meteo Historical Weather API "
            "returned inconsistent hourly array lengths."
        )

    df = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                hourly["time"]
            ),
            "Dry_Bulb": hourly[
                "temperature_2m"
            ],
            "Dew_Point": hourly[
                "dew_point_2m"
            ],
        }
    )

    if df[
        ["Dry_Bulb", "Dew_Point"]
    ].isna().any().any():
        raise RuntimeError(
            "Historical weather is not fully available "
            f"for {target_date.isoformat()}."
        )

    return df




def _validate_weather_dataframe(
    df: pd.DataFrame,
    target_date: date,
) -> pd.DataFrame:
    """
    Validate raw weather data before allowing
    the batch pipeline to continue.
    """

    if df.empty:
        raise RuntimeError(
            f"No weather data returned for "
            f"{target_date.isoformat()}."
        )

    required = {
        "timestamp",
        "Dry_Bulb",
        "Dew_Point",
    }

    missing = required - set(df.columns)

    if missing:
        raise RuntimeError(
            "Weather dataframe is missing columns: "
            f"{sorted(missing)}"
        )

    if df["timestamp"].isna().any():
        raise RuntimeError(
            "Weather data contains invalid timestamps."
        )

    if df["Dry_Bulb"].isna().any():
        raise RuntimeError(
            f"Dry_Bulb contains missing values for "
            f"{target_date.isoformat()}."
        )

    if df["Dew_Point"].isna().any():
        raise RuntimeError(
            f"Dew_Point contains missing values for "
            f"{target_date.isoformat()}."
        )

    if df["timestamp"].duplicated().any():
        raise RuntimeError(
            "Weather API returned duplicate timestamps "
            f"for {target_date.isoformat()}."
        )

    return (
        df
        .sort_values("timestamp")
        .reset_index(drop=True)
    )
# ── Public Step-2 function ────────────────────────────────────────────────────
def fetch_day_ahead_weather(
    origin_date: Union[str, date, datetime],
    config: WeatherConfig,
) -> pd.DataFrame:
    """
    Obtain historical weather inputs required by GridCast.

    Semantics
    ---------
    origin_date = D
    target_date = D + 1 day

    Current mode:
        target_date must be a completed historical day.

    Therefore:
        target_date < today

    Example
    -------
    If today is 2026-09-14:

        origin_date = 2026-09-12
        target_date = 2026-09-13
        -> allowed

        origin_date = 2026-09-13
        target_date = 2026-09-14
        -> rejected because today is not complete

        origin_date = 2026-09-14
        target_date = 2026-09-15
        -> rejected because target is in the future

    Limitation
    ----------
    Historical/reanalysis weather is used instead of the
    weather forecast that was available on origin_date.
    This is a simplified replay mode, not a strict
    operational backtest.

    Returns
    -------
    pd.DataFrame

    Columns:
        timestamp
        Dry_Bulb
        Dew_Point
        origin_date
        target_date
        weather_source
    """

    origin = _parse_date(
        origin_date
    )

    target = (
        origin
        + timedelta(days=1)
    )

    local_today = datetime.now(
        ZoneInfo(config.timezone)
    ).date()

    # ERA5 historical data has an availability delay.
    latest_available_target = (
        local_today
        - timedelta(
            days=config.historical_delay_days
        )
    )

    if target > latest_available_target:
        raise ValueError(
            "GridCast historical mode uses ERA5 data, "
            f"which has approximately a "
            f"{config.historical_delay_days}-day availability delay. "
            f"origin_date={origin.isoformat()}, "
            f"target_date={target.isoformat()}, "
            f"latest_available_target="
            f"{latest_available_target.isoformat()}."
        )

    session = _build_session(
        config
    )

    try:
        df = _fetch_historical_weather(
            target_date=target,
            config=config,
            session=session,
        )

    finally:
        session.close()

    df = _validate_weather_dataframe(
        df=df,
        target_date=target,
    )

    df["origin_date"] = origin
    df["target_date"] = target
    df["weather_source"] = (
    "open_meteo_era5"
    )

    return df