"""
CLI entry point for the GridCast offline forecast flow.
"""

from __future__ import annotations

import argparse

from flow import gridcast_forecast_flow


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run a GridCast offline electricity-demand forecast."
        )
    )

    parser.add_argument(
        "--origin-date",
        required=True,
        help=(
            "Forecast origin date in YYYY-MM-DD format. "
            "GridCast predicts the following day."
        ),
    )

    args = parser.parse_args()

    gridcast_forecast_flow(
        origin_date=args.origin_date,
    )


if __name__ == "__main__":
    main()