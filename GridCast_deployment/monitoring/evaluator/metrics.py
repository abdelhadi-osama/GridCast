"""
GridCast Prometheus metrics service.

Responsibilities:
    - poll the GridCast Offline API
    - select the newest forecast
    - avoid re-evaluating the same forecast repeatedly
    - wait until ISO-NE actual load is available
    - call evaluator.py for MAE / RMSE / MAPE
    - expose the latest evaluation through /metrics
"""

from __future__ import annotations

import os
import time

from prometheus_client import Gauge, start_http_server

from evaluator import (
    evaluate_forecast,
    get_actual_load,
    get_forecasts,
    get_hourly_forecast,
    get_latest_forecast,
    summarize_forecast,
)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

METRICS_PORT = int(
    os.getenv(
        "GRIDCAST_EVALUATOR_METRICS_PORT",
        "8000",
    )
)

POLL_INTERVAL_SECONDS = int(
    os.getenv(
        "GRIDCAST_EVALUATOR_POLL_SECONDS",
        "300",
    )
)


# ---------------------------------------------------------------------------
# Prometheus metrics
# ---------------------------------------------------------------------------

MODEL_MAE_MW = Gauge(
    "gridcast_model_mae_mw",
    "MAE of the latest successfully evaluated GridCast forecast in MW.",
)

MODEL_RMSE_MW = Gauge(
    "gridcast_model_rmse_mw",
    "RMSE of the latest successfully evaluated GridCast forecast in MW.",
)

MODEL_MAPE_PERCENT = Gauge(
    "gridcast_model_mape_percent",
    "MAPE of the latest successfully evaluated GridCast forecast.",
)

EVALUATION_MATCHED_HOURS = Gauge(
    "gridcast_evaluation_matched_hours",
    "Number of forecast hours matched with ISO-NE actual load.",
)

EVALUATOR_LAST_SUCCESS_TIMESTAMP = Gauge(
    "gridcast_evaluator_last_success_timestamp_seconds",
    "Unix timestamp of the latest successful GridCast model evaluation.",
)

EVALUATOR_HAS_EVALUATION = Gauge(
    "gridcast_evaluator_has_evaluation",
    "Whether the evaluator has completed at least one successful evaluation.",
)


# ---------------------------------------------------------------------------
# Metric publishing
# ---------------------------------------------------------------------------

def publish_metrics(
    evaluation: dict,
) -> None:
    """
    Update Prometheus metrics using the latest
    successful model evaluation.
    """

    MODEL_MAE_MW.set(
        evaluation["mae_mw"]
    )

    MODEL_RMSE_MW.set(
        evaluation["rmse_mw"]
    )

    MODEL_MAPE_PERCENT.set(
        evaluation["mape_percent"]
    )

    EVALUATION_MATCHED_HOURS.set(
        evaluation["matched_hours"]
    )

    EVALUATOR_LAST_SUCCESS_TIMESTAMP.set(
        time.time()
    )

    EVALUATOR_HAS_EVALUATION.set(
        1
    )


# ---------------------------------------------------------------------------
# Evaluation cycle
# ---------------------------------------------------------------------------

def evaluate_latest_forecast(
    last_evaluated_forecast_id: str | None,
) -> str | None:
    """
    Check the newest forecast and evaluate it
    only when necessary.

    Returns the latest successfully evaluated
    forecast_id.

    If evaluation cannot yet be completed,
    the previous forecast_id is returned so
    the new forecast will be retried later.
    """

    forecasts = get_forecasts()

    if not forecasts:
        print(
            "No stored forecasts available."
        )
        return last_evaluated_forecast_id

    forecast = get_latest_forecast(
        forecasts
    )

    if forecast is None:
        print(
            "No valid forecast found."
        )
        return last_evaluated_forecast_id

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

    if not forecast_id:
        print(
            "Latest forecast has no forecast_id."
        )
        return last_evaluated_forecast_id

    if not target_date:
        print(
            "Latest forecast has no target_date."
        )
        return last_evaluated_forecast_id

    # -----------------------------------------------------------------------
    # Already evaluated
    # -----------------------------------------------------------------------

    if (
        forecast_id
        == last_evaluated_forecast_id
    ):
        print(
            f"No new forecast. "
            f"Latest forecast remains {forecast_id}."
        )

        return last_evaluated_forecast_id

    print(
        "\n"
        "========================================"
    )

    print(
        "New forecast detected."
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

    # -----------------------------------------------------------------------
    # Retrieve predictions
    # -----------------------------------------------------------------------

    try:
        predictions = get_hourly_forecast(
            forecast_id
        )

    except RuntimeError as exc:
        print(
            f"Could not retrieve forecast: "
            f"{exc}"
        )

        return last_evaluated_forecast_id

    if not predictions:
        print(
            "Forecast contains no hourly predictions."
        )

        return last_evaluated_forecast_id

    # -----------------------------------------------------------------------
    # Retrieve ISO-NE actuals
    # -----------------------------------------------------------------------

    try:
        actuals = get_actual_load(
            target_date
        )

    except RuntimeError as exc:
        print(
            "Actual load is not available yet "
            f"or ISO-NE request failed: {exc}"
        )

        return last_evaluated_forecast_id

    if not actuals:
        print(
            "ISO-NE returned no actual-load rows. "
            "Will retry later."
        )

        return last_evaluated_forecast_id

    # -----------------------------------------------------------------------
    # Do not evaluate an incomplete target day
    # -----------------------------------------------------------------------

    if len(actuals) < len(predictions):
        print(
            "ISO-NE actual load is incomplete."
        )

        print(
            f"Predictions : {len(predictions)}"
        )

        print(
            f"Actuals     : {len(actuals)}"
        )

        print(
            "Will retry on the next polling cycle."
        )

        return last_evaluated_forecast_id

    # -----------------------------------------------------------------------
    # Evaluate
    # -----------------------------------------------------------------------

    try:
        evaluation = evaluate_forecast(
            predictions=predictions,
            actuals=actuals,
        )

    except RuntimeError as exc:
        print(
            f"Evaluation failed: {exc}"
        )

        return last_evaluated_forecast_id

    # Make sure every prediction was matched.
    if (
        evaluation["matched_hours"]
        != len(predictions)
    ):
        print(
            "Evaluation is incomplete."
        )

        print(
            f"Prediction rows : "
            f"{len(predictions)}"
        )

        print(
            f"Matched rows    : "
            f"{evaluation['matched_hours']}"
        )

        print(
            "Will retry later."
        )

        return last_evaluated_forecast_id

    # -----------------------------------------------------------------------
    # Publish successful result
    # -----------------------------------------------------------------------

    publish_metrics(
        evaluation
    )

    print(
        "\nEvaluation successful."
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

    print(
        "Prometheus metrics updated."
    )

    # Only mark the forecast as evaluated
    # after everything succeeded.
    return forecast_id


# ---------------------------------------------------------------------------
# Service loop
# ---------------------------------------------------------------------------

def main() -> None:
    """
    Start the Prometheus metrics endpoint and
    continuously monitor the newest forecast.
    """

    print(
        f"Starting GridCast evaluator metrics "
        f"server on port {METRICS_PORT}."
    )

    print(
        f"Polling every "
        f"{POLL_INTERVAL_SECONDS} seconds."
    )

    start_http_server(
        METRICS_PORT
    )

    last_evaluated_forecast_id = None

    while True:

        try:
            last_evaluated_forecast_id = (
                evaluate_latest_forecast(
                    last_evaluated_forecast_id
                )
            )

        except Exception as exc:
            # Keep the monitoring service alive
            # during transient API/network failures.
            print(
                f"Evaluator cycle failed: {exc}"
            )

        time.sleep(
            POLL_INTERVAL_SECONDS
        )


if __name__ == "__main__":
    main()