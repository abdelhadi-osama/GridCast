"""
GridCast model evaluator.

STEP 1:
    Read persisted forecasts from the GridCast Offline API.

STEP 2:
    Retrieve hourly predictions for one stored forecast.

Later steps will:
    - identify forecasts ready for evaluation
    - fetch ISO-NE actual load
    - match forecast vs actual
    - calculate MAE / RMSE / MAPE
    - expose metrics to Prometheus
"""

from __future__ import annotations

import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import urlopen
import base64
from datetime import datetime
from urllib.request import Request, urlopen
import math

ISONE_USERNAME = os.getenv(
    "ISONE_USERNAME"
)

ISONE_PASSWORD = os.getenv(
    "ISONE_PASSWORD"
)

ISONE_API_URL = (
    "https://webservices.iso-ne.com/api/v1.1"
)
OFFLINE_API_URL = os.getenv(
    "GRIDCAST_OFFLINE_API_URL",
    "http://127.0.0.1:1012",
).rstrip("/")


def get_forecasts() -> list[dict]:
    """
    Read all persisted GridCast forecasts
    through the Offline API.
    """

    url = f"{OFFLINE_API_URL}/forecasts"

    try:
        with urlopen(url, timeout=10) as response:
            payload = response.read().decode("utf-8")

    except HTTPError as exc:
        raise RuntimeError(
            f"Offline API returned HTTP {exc.code}: {url}"
        ) from exc

    except URLError as exc:
        raise RuntimeError(
            f"Could not connect to GridCast Offline API: {url}"
        ) from exc

    data = json.loads(payload)

    if not isinstance(data, list):
        raise RuntimeError(
            "Expected /forecasts to return a JSON list."
        )

    return data


def summarize_forecast(
    forecast: dict,
) -> dict:
    """
    Keep only the fields needed by the evaluator.
    """

    return {
        "forecast_id": forecast.get("forecast_id"),
        "origin_date": forecast.get("origin_date"),
        "target_date": forecast.get("target_date"),
        "model_version": forecast.get("model_version"),
        "generated_at": forecast.get("generated_at"),
    }


def get_hourly_forecast(
    forecast_id: str,
) -> list[dict]:
    """
    Retrieve hourly predictions for one
    persisted GridCast forecast.
    """

    url = (
        f"{OFFLINE_API_URL}"
        f"/forecasts/{forecast_id}/hourly"
    )

    try:
        with urlopen(
            url,
            timeout=10,
        ) as response:
            payload = (
                response
                .read()
                .decode("utf-8")
            )

    except HTTPError as exc:
        raise RuntimeError(
            f"Offline API returned HTTP "
            f"{exc.code}: {url}"
        ) from exc

    except URLError as exc:
        raise RuntimeError(
            f"Could not connect to "
            f"GridCast Offline API: {url}"
        ) from exc

    data = json.loads(payload)

    if not isinstance(data, list):
        raise RuntimeError(
            "Expected hourly forecast "
            "endpoint to return a JSON list."
        )

    return data

def get_actual_load(
    target_date: str,
) -> list[dict]:
    """
    Retrieve actual ISO-NE hourly system load
    for one GridCast target date.

    Parameters
    ----------
    target_date:
        YYYY-MM-DD

    Returns
    -------
    list[dict]
        Hourly actual-load records using the
        same Date / Hr_End convention as GridCast.
    """

    if not ISONE_USERNAME or not ISONE_PASSWORD:
        raise RuntimeError(
            "ISONE_USERNAME and ISONE_PASSWORD "
            "must be configured."
        )

    parsed_date = datetime.strptime(
        target_date,
        "%Y-%m-%d",
    )

    api_date = parsed_date.strftime(
        "%Y%m%d"
    )

    url = (
        f"{ISONE_API_URL}"
        f"/hourlysysload/day/{api_date}"
    )

    credentials = (
        f"{ISONE_USERNAME}:{ISONE_PASSWORD}"
    )

    encoded_credentials = (
        base64.b64encode(
            credentials.encode("utf-8")
        )
        .decode("ascii")
    )

    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "Authorization": (
                f"Basic {encoded_credentials}"
            ),
        },
    )

    try:
        with urlopen(
            request,
            timeout=20,
        ) as response:
            payload = (
                response
                .read()
                .decode("utf-8")
            )

    except HTTPError as exc:
        raise RuntimeError(
            f"ISO-NE returned HTTP "
            f"{exc.code}: {url}"
        ) from exc

    except URLError as exc:
        raise RuntimeError(
            f"Could not connect to ISO-NE: {url}"
        ) from exc

    data = json.loads(
        payload
    )

    try:
        records = (
            data["HourlySystemLoads"]
                ["HourlySystemLoad"]
        )

    except (
        KeyError,
        TypeError,
    ) as exc:
        raise RuntimeError(
            "Unexpected ISO-NE response structure."
        ) from exc

    actuals = []

    for record in records:

        location = (
            record.get("Location")
            or {}
        )

        # GridCast forecasts the New England
        # system-level load.
        if location.get("$") != "NEPOOL AREA":
            continue

        begin_date = datetime.fromisoformat(
            record["BeginDate"]
        )

        load = record.get(
            "Load"
        )

        if load is None:
            continue

        actuals.append(
            {
                "Date":
                    begin_date.date().isoformat(),

                "Hr_End":
                    begin_date.hour + 1,

                "Actual_Load_MW":
                    float(load),

                "ISO_NE_BeginDate":
                    record["BeginDate"],
            }
        )

    actuals.sort(
        key=lambda row: row["Hr_End"]
    )

    return actuals

def evaluate_forecast(
    predictions: list[dict],
    actuals: list[dict],
) -> dict:
    """
    Match GridCast predictions with ISO-NE actual load
    using Date + Hr_End and calculate evaluation metrics.
    """

    # -------------------------------------------------------------------------
    # Build actual-load lookup
    # -------------------------------------------------------------------------

    actual_lookup = {
        (
            row["Date"],
            int(row["Hr_End"]),
        ): float(row["Actual_Load_MW"])
        for row in actuals
    }

    matched = []

    # -------------------------------------------------------------------------
    # Match predictions to actuals
    # -------------------------------------------------------------------------

    for row in predictions:

        key = (
            str(row["Date"]),
            int(row["Hr_End"]),
        )

        if key not in actual_lookup:
            continue

        predicted = float(
            row["Predicted_Load_MW"]
        )

        actual = actual_lookup[key]

        error = predicted - actual

        matched.append(
            {
                "Date": key[0],
                "Hr_End": key[1],
                "Predicted_Load_MW": predicted,
                "Actual_Load_MW": actual,
                "Error_MW": error,
                "Absolute_Error_MW": abs(error),
            }
        )

    if not matched:
        raise RuntimeError(
            "No forecast rows matched ISO-NE actual rows."
        )

    # -------------------------------------------------------------------------
    # Metrics
    # -------------------------------------------------------------------------

    n = len(matched)

    mae = sum(
        row["Absolute_Error_MW"]
        for row in matched
    ) / n

    rmse = math.sqrt(
        sum(
            row["Error_MW"] ** 2
            for row in matched
        ) / n
    )

    percentage_errors = [
        (
            row["Absolute_Error_MW"]
            / abs(row["Actual_Load_MW"])
        )
        for row in matched
        if row["Actual_Load_MW"] != 0
    ]

    mape = (
        sum(percentage_errors)
        / len(percentage_errors)
        * 100
    )

    return {
        "matched_hours": n,
        "mae_mw": mae,
        "rmse_mw": rmse,
        "mape_percent": mape,
        "rows": matched,
    }

def get_latest_forecast(
    forecasts: list[dict],
) -> dict | None:
    """
    Select the newest GridCast forecast
    using generated_at.
    """

    valid_forecasts = [
        forecast
        for forecast in forecasts
        if forecast.get("generated_at")
    ]

    if not valid_forecasts:
        return None

    return max(
        valid_forecasts,
        key=lambda forecast: datetime.fromisoformat(
            forecast["generated_at"]
        ),
    )


def main() -> None:
    """
    Evaluate only the newest GridCast forecast.
    """

    # -------------------------------------------------------------
    # Read forecast metadata
    # -------------------------------------------------------------

    forecasts = get_forecasts()

    print(
        f"Found {len(forecasts)} "
        "stored forecast run(s)."
    )

    if not forecasts:
        print(
            "No stored forecasts available."
        )
        return

    # -------------------------------------------------------------
    # Select newest forecast only
    # -------------------------------------------------------------

    forecast = get_latest_forecast(
        forecasts
    )

    if forecast is None:
        print(
            "No valid forecast found."
        )
        return

    summary = summarize_forecast(
        forecast
    )

    forecast_id = summary[
        "forecast_id"
    ]

    target_date = summary[
        "target_date"
    ]

    model_version = summary[
        "model_version"
    ]

    generated_at = summary[
        "generated_at"
    ]

    if not forecast_id:
        raise RuntimeError(
            "Latest forecast has no forecast_id."
        )

    if not target_date:
        raise RuntimeError(
            "Latest forecast has no target_date."
        )

    print(
        "\nLatest forecast:"
    )

    print(
        f"Forecast ID   : {forecast_id}"
    )

    print(
        f"Target date   : {target_date}"
    )

    print(
        f"Model version : {model_version}"
    )

    print(
        f"Generated at  : {generated_at}"
    )

    # -------------------------------------------------------------
    # Retrieve GridCast predictions
    # -------------------------------------------------------------

    try:
        predictions = get_hourly_forecast(
            forecast_id
        )

    except RuntimeError as exc:
        print(
            f"\nEvaluation failed: {exc}"
        )
        return

    print(
        f"\nRetrieved "
        f"{len(predictions)} prediction rows."
    )

    # -------------------------------------------------------------
    # Retrieve ISO-NE actual load
    # -------------------------------------------------------------

    try:
        actuals = get_actual_load(
            target_date
        )

    except RuntimeError as exc:
        print(
            "\nEvaluation not ready."
        )

        print(
            f"ISO-NE actual load "
            f"is unavailable: {exc}"
        )

        return

    if not actuals:
        print(
            "\nEvaluation not ready: "
            "no ISO-NE actual rows returned."
        )
        return

    print(
        f"Retrieved "
        f"{len(actuals)} ISO-NE actual rows."
    )

    # -------------------------------------------------------------
    # Evaluate newest forecast
    # -------------------------------------------------------------

    try:
        evaluation = evaluate_forecast(
            predictions=predictions,
            actuals=actuals,
        )

    except RuntimeError as exc:
        print(
            f"\nEvaluation failed: {exc}"
        )
        return

    print(
        "\nModel evaluation:"
    )

    print(
        f"Forecast ID   : {forecast_id}"
    )

    print(
        f"Target date   : {target_date}"
    )

    print(
        f"Model version : {model_version}"
    )

    print(
        f"Matched hours : "
        f"{evaluation['matched_hours']}"
    )

    print(
        f"MAE           : "
        f"{evaluation['mae_mw']:.2f} MW"
    )

    print(
        f"RMSE          : "
        f"{evaluation['rmse_mw']:.2f} MW"
    )

    print(
        f"MAPE          : "
        f"{evaluation['mape_percent']:.2f}%"
    )  

if __name__ == "__main__":
    main()