"""
User-facing analytics for GridCast offline forecasts.

Consumes the structured forecast dataframe produced by core.py
and calculates operationally useful daily forecast statistics.

This module does NOT:
- load models
- call external APIs
- run preprocessing
- persist results
- calculate model-monitoring metrics
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def calculate_forecast_analytics(
    forecast: pd.DataFrame,
) -> dict:
    """
    Calculate daily analytics from a GridCast forecast.

    Required columns:
        Hr_End
        Predicted_Load_MW

    Returns
    -------
    dict
        Daily user-facing forecast statistics.
    """

    required_columns = {
        "Hr_End",
        "Predicted_Load_MW",
    }

    missing = required_columns - set(forecast.columns)

    if missing:
        raise ValueError(
            "Forecast dataframe is missing required columns: "
            f"{sorted(missing)}"
        )

    if forecast.empty:
        raise ValueError(
            "Cannot calculate analytics from an empty forecast."
        )

    df = forecast.copy()

    df["Predicted_Load_MW"] = pd.to_numeric(
        df["Predicted_Load_MW"],
        errors="coerce",
    )

    df["Hr_End"] = pd.to_numeric(
        df["Hr_End"],
        errors="coerce",
    )

    if df[
        [
            "Predicted_Load_MW",
            "Hr_End",
        ]
    ].isna().any().any():
        raise ValueError(
            "Forecast contains invalid load or hour values."
        )

    if not np.isfinite(
        df["Predicted_Load_MW"].to_numpy()
    ).all():
        raise ValueError(
            "Forecast contains NaN or infinite predictions."
        )

    df = (
        df
        .sort_values("Hr_End")
        .reset_index(drop=True)
    )

    # -------------------------------------------------------------------------
    # Peak demand
    # -------------------------------------------------------------------------

    peak_idx = df[
        "Predicted_Load_MW"
    ].idxmax()

    peak_load_mw = float(
        df.loc[
            peak_idx,
            "Predicted_Load_MW",
        ]
    )

    peak_hour = int(
        df.loc[
            peak_idx,
            "Hr_End",
        ]
    )

    # -------------------------------------------------------------------------
    # Minimum demand
    # -------------------------------------------------------------------------

    minimum_idx = df[
        "Predicted_Load_MW"
    ].idxmin()

    minimum_load_mw = float(
        df.loc[
            minimum_idx,
            "Predicted_Load_MW",
        ]
    )

    minimum_hour = int(
        df.loc[
            minimum_idx,
            "Hr_End",
        ]
    )

    # -------------------------------------------------------------------------
    # Average demand
    # -------------------------------------------------------------------------

    average_load_mw = float(
        df["Predicted_Load_MW"].mean()
    )

    # -------------------------------------------------------------------------
    # Daily energy
    #
    # Each prediction represents one hourly interval:
    #
    #     MWh = MW × 1 hour
    #
    # -------------------------------------------------------------------------

    daily_energy_mwh = float(
        df["Predicted_Load_MW"].sum()
    )

    # -------------------------------------------------------------------------
    # Load factor
    #
    # average load / peak load
    # -------------------------------------------------------------------------

    load_factor = (
        average_load_mw / peak_load_mw
        if peak_load_mw > 0
        else None
    )

    # -------------------------------------------------------------------------
    # Hour-to-hour ramps
    # -------------------------------------------------------------------------

    df["Ramp_MW"] = (
        df["Predicted_Load_MW"]
        .diff()
    )

    ramp_df = df.dropna(
        subset=["Ramp_MW"]
    ).copy()

    max_ramp_up_mw = None
    max_ramp_up_from_hour = None
    max_ramp_up_to_hour = None

    max_ramp_down_mw = None
    max_ramp_down_from_hour = None
    max_ramp_down_to_hour = None

    if not ramp_df.empty:

        # Largest positive ramp.
        ramp_up_idx = ramp_df[
            "Ramp_MW"
        ].idxmax()

        max_ramp_up_mw = float(
            df.loc[
                ramp_up_idx,
                "Ramp_MW",
            ]
        )

        max_ramp_up_to_hour = int(
            df.loc[
                ramp_up_idx,
                "Hr_End",
            ]
        )

        max_ramp_up_from_hour = int(
            df.loc[
                ramp_up_idx - 1,
                "Hr_End",
            ]
        )

        # Largest negative ramp.
        ramp_down_idx = ramp_df[
            "Ramp_MW"
        ].idxmin()

        max_ramp_down_mw = float(
            df.loc[
                ramp_down_idx,
                "Ramp_MW",
            ]
        )

        max_ramp_down_to_hour = int(
            df.loc[
                ramp_down_idx,
                "Hr_End",
            ]
        )

        max_ramp_down_from_hour = int(
            df.loc[
                ramp_down_idx - 1,
                "Hr_End",
            ]
        )

    # -------------------------------------------------------------------------
    # Return structured analytics
    # -------------------------------------------------------------------------

    return {
        "peak_load_mw": peak_load_mw,
        "peak_hour": peak_hour,

        "minimum_load_mw": minimum_load_mw,
        "minimum_hour": minimum_hour,

        "average_load_mw": average_load_mw,

        "daily_energy_mwh": daily_energy_mwh,

        "load_factor": (
            float(load_factor)
            if load_factor is not None
            else None
        ),

        "max_ramp_up_mw": max_ramp_up_mw,
        "max_ramp_up_from_hour": max_ramp_up_from_hour,
        "max_ramp_up_to_hour": max_ramp_up_to_hour,

        "max_ramp_down_mw": max_ramp_down_mw,
        "max_ramp_down_from_hour": max_ramp_down_from_hour,
        "max_ramp_down_to_hour": max_ramp_down_to_hour,
    }