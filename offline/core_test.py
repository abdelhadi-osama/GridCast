from core import run_forecast
from data_sources import WeatherConfig


def main():

    # Use the SAME coordinates used by your GridCast weather pipeline.
    weather_config = WeatherConfig(
        latitude= 42.3601,
        longitude=-71.0589,
    )

    result = run_forecast(
        origin_date="2025-01-15",
        weather_config=weather_config,
        log_to_mlflow=False,   # first test without MLflow
    )

    print("\n========== FORECAST ID ==========")
    print(result["forecast_id"])

    print("\n========== FORECAST ==========")
    print(result["forecast"])

    print("\n========== ANALYTICS ==========")
    print(result["analytics"])

    print("\n========== ARTIFACTS ==========")
    print("Parquet:", result["forecast_path"])
    print("HTML:", result["report_path"])
    print("Database:", result["database_path"])

    print("\n========== TRACKING ==========")
    print("MLflow run:", result["mlflow_tracking_run_id"])
    print("Tracking error:", result["tracking_error"])


if __name__ == "__main__":
    main()