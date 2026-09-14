"""
GridCast downloadable HTML forecast report.

Produces a fully self-contained HTML artifact:
- no CDN
- no JavaScript libraries
- no internet connection required

Visualizations are rendered as inline SVG.
"""

from __future__ import annotations

from html import escape
from pathlib import Path

import numpy as np
import pandas as pd

from config import (
    REPORTS_DIR,
    ensure_data_directories,
)


# =============================================================================
# SMALL HELPERS
# =============================================================================

def _safe_range(
    minimum: float,
    maximum: float,
) -> tuple[float, float]:
    """
    Prevent division-by-zero when all values are equal.
    """

    if maximum == minimum:
        padding = abs(maximum) * 0.05 or 1.0
        return minimum - padding, maximum + padding

    padding = (maximum - minimum) * 0.08

    return (
        minimum - padding,
        maximum + padding,
    )


def _format_number(
    value: float,
    decimals: int = 0,
) -> str:
    return f"{float(value):,.{decimals}f}"


# =============================================================================
# LOAD PROFILE CHART
# =============================================================================

def _build_load_chart(
    forecast: pd.DataFrame,
) -> str:

    values = (
        forecast["Predicted_Load_MW"]
        .astype(float)
        .to_numpy()
    )

    hours = (
        forecast["Hr_End"]
        .astype(int)
        .to_numpy()
    )

    width = 1100
    height = 420

    left = 80
    right = 30
    top = 35
    bottom = 60

    chart_width = width - left - right
    chart_height = height - top - bottom

    y_min, y_max = _safe_range(
        float(values.min()),
        float(values.max()),
    )

    def x_coord(index: int) -> float:
        if len(values) == 1:
            return left + chart_width / 2

        return (
            left
            + index
            * chart_width
            / (len(values) - 1)
        )

    def y_coord(value: float) -> float:
        return (
            top
            + (y_max - value)
            / (y_max - y_min)
            * chart_height
        )

    points = " ".join(
        f"{x_coord(i):.2f},{y_coord(v):.2f}"
        for i, v in enumerate(values)
    )

    first_x = x_coord(0)
    last_x = x_coord(len(values) - 1)
    baseline = top + chart_height

    area_points = (
        f"{first_x:.2f},{baseline:.2f} "
        f"{points} "
        f"{last_x:.2f},{baseline:.2f}"
    )

    # -------------------------------------------------------------------------
    # Y grid
    # -------------------------------------------------------------------------

    grid_lines = []

    for value in np.linspace(
        y_min,
        y_max,
        5,
    ):

        y = y_coord(value)

        grid_lines.append(
            f"""
            <line
                x1="{left}"
                y1="{y:.2f}"
                x2="{width - right}"
                y2="{y:.2f}"
                class="grid-line"
            />

            <text
                x="{left - 14}"
                y="{y + 5:.2f}"
                text-anchor="end"
                class="axis-label"
            >
                {_format_number(value)} MW
            </text>
            """
        )

    # -------------------------------------------------------------------------
    # X labels
    # -------------------------------------------------------------------------

    x_labels = []

    for i, hour in enumerate(hours):

        if (
            i == 0
            or i == len(hours) - 1
            or hour % 3 == 0
        ):
            x_labels.append(
                f"""
                <text
                    x="{x_coord(i):.2f}"
                    y="{height - 24}"
                    text-anchor="middle"
                    class="axis-label"
                >
                    HE {hour:02d}
                </text>
                """
            )

    # -------------------------------------------------------------------------
    # Peak and minimum
    # -------------------------------------------------------------------------

    peak_i = int(np.argmax(values))
    minimum_i = int(np.argmin(values))

    peak_x = x_coord(peak_i)
    peak_y = y_coord(values[peak_i])

    minimum_x = x_coord(minimum_i)
    minimum_y = y_coord(values[minimum_i])

    return f"""
    <svg
        viewBox="0 0 {width} {height}"
        class="chart-svg"
        role="img"
        aria-label="24 hour predicted electricity load profile"
    >

        <defs>

            <linearGradient
                id="loadGradient"
                x1="0"
                y1="0"
                x2="0"
                y2="1"
            >
                <stop
                    offset="0%"
                    stop-color="#38bdf8"
                    stop-opacity="0.30"
                />
                <stop
                    offset="100%"
                    stop-color="#38bdf8"
                    stop-opacity="0.01"
                />
            </linearGradient>

            <filter id="glow">
                <feGaussianBlur
                    stdDeviation="3"
                    result="blur"
                />
                <feMerge>
                    <feMergeNode in="blur"/>
                    <feMergeNode in="SourceGraphic"/>
                </feMerge>
            </filter>

        </defs>

        {''.join(grid_lines)}

        <polygon
            points="{area_points}"
            fill="url(#loadGradient)"
        />

        <polyline
            points="{points}"
            fill="none"
            stroke="#38bdf8"
            stroke-width="4"
            stroke-linejoin="round"
            stroke-linecap="round"
            filter="url(#glow)"
        />

        <circle
            cx="{peak_x:.2f}"
            cy="{peak_y:.2f}"
            r="7"
            fill="#fb7185"
        />

        <text
            x="{peak_x:.2f}"
            y="{peak_y - 16:.2f}"
            text-anchor="middle"
            class="peak-label"
        >
            Peak {_format_number(values[peak_i])} MW
        </text>

        <circle
            cx="{minimum_x:.2f}"
            cy="{minimum_y:.2f}"
            r="6"
            fill="#34d399"
        />

        <text
            x="{minimum_x:.2f}"
            y="{minimum_y + 26:.2f}"
            text-anchor="middle"
            class="minimum-label"
        >
            Min {_format_number(values[minimum_i])} MW
        </text>

        {''.join(x_labels)}

    </svg>
    """


# =============================================================================
# RAMP CHART
# =============================================================================

def _build_ramp_chart(
    forecast: pd.DataFrame,
) -> str:

    df = forecast[
        [
            "Hr_End",
            "Predicted_Load_MW",
        ]
    ].copy()

    df["Ramp_MW"] = (
        df["Predicted_Load_MW"]
        .astype(float)
        .diff()
    )

    df = df.dropna().reset_index(drop=True)

    if df.empty:
        return "<p>No ramp data available.</p>"

    values = df["Ramp_MW"].to_numpy()
    hours = df["Hr_End"].astype(int).to_numpy()

    width = 1100
    height = 340

    left = 70
    right = 25
    top = 25
    bottom = 55

    chart_width = width - left - right
    chart_height = height - top - bottom

    max_abs = max(
        abs(float(values.min())),
        abs(float(values.max())),
        1.0,
    )

    zero_y = (
        top + chart_height / 2
    )

    scale = (
        chart_height / 2
        / max_abs
    )

    bar_width = (
        chart_width / len(values) * 0.65
    )

    bars = []

    for i, value in enumerate(values):

        center_x = (
            left
            + (i + 0.5)
            * chart_width
            / len(values)
        )

        bar_height = abs(value) * scale

        if value >= 0:
            y = zero_y - bar_height
            css_class = "ramp-up"
        else:
            y = zero_y
            css_class = "ramp-down"

        bars.append(
            f"""
            <rect
                x="{center_x - bar_width / 2:.2f}"
                y="{y:.2f}"
                width="{bar_width:.2f}"
                height="{bar_height:.2f}"
                rx="3"
                class="{css_class}"
            />

            <text
                x="{center_x:.2f}"
                y="{height - 22}"
                text-anchor="middle"
                class="axis-label small"
            >
                {hours[i]:02d}
            </text>
            """
        )

    return f"""
    <svg
        viewBox="0 0 {width} {height}"
        class="chart-svg"
    >

        <line
            x1="{left}"
            y1="{zero_y}"
            x2="{width - right}"
            y2="{zero_y}"
            class="zero-line"
        />

        <text
            x="18"
            y="{zero_y - 8}"
            class="axis-label"
        >
            ↑ ramp
        </text>

        <text
            x="18"
            y="{zero_y + 23}"
            class="axis-label"
        >
            ↓ ramp
        </text>

        {''.join(bars)}

    </svg>
    """


# =============================================================================
# WEATHER CHART
# =============================================================================

def _build_weather_chart(
    forecast: pd.DataFrame,
) -> str:

    dry = forecast[
        "Dry_Bulb"
    ].astype(float).to_numpy()

    dew = forecast[
        "Dew_Point"
    ].astype(float).to_numpy()

    hours = forecast[
        "Hr_End"
    ].astype(int).to_numpy()

    width = 1100
    height = 330

    left = 65
    right = 25
    top = 25
    bottom = 55

    chart_width = width - left - right
    chart_height = height - top - bottom

    all_values = np.concatenate(
        [dry, dew]
    )

    y_min, y_max = _safe_range(
        float(all_values.min()),
        float(all_values.max()),
    )

    def x_coord(index: int) -> float:
        return (
            left
            + index
            * chart_width
            / max(len(dry) - 1, 1)
        )

    def y_coord(value: float) -> float:
        return (
            top
            + (y_max - value)
            / (y_max - y_min)
            * chart_height
        )

    dry_points = " ".join(
        f"{x_coord(i):.2f},{y_coord(v):.2f}"
        for i, v in enumerate(dry)
    )

    dew_points = " ".join(
        f"{x_coord(i):.2f},{y_coord(v):.2f}"
        for i, v in enumerate(dew)
    )

    labels = []

    for i, hour in enumerate(hours):

        if (
            i == 0
            or i == len(hours) - 1
            or hour % 3 == 0
        ):
            labels.append(
                f"""
                <text
                    x="{x_coord(i):.2f}"
                    y="{height - 20}"
                    text-anchor="middle"
                    class="axis-label"
                >
                    {hour:02d}
                </text>
                """
            )

    return f"""
    <svg
        viewBox="0 0 {width} {height}"
        class="chart-svg"
    >

        <polyline
            points="{dry_points}"
            fill="none"
            stroke="#fb923c"
            stroke-width="4"
            stroke-linecap="round"
            stroke-linejoin="round"
        />

        <polyline
            points="{dew_points}"
            fill="none"
            stroke="#818cf8"
            stroke-width="4"
            stroke-linecap="round"
            stroke-linejoin="round"
        />

        {''.join(labels)}

    </svg>
    """


# =============================================================================
# MAIN REPORT
# =============================================================================

def generate_html_report(
    forecast: pd.DataFrame,
    analytics: dict,
) -> Path:
    ensure_data_directories()
    if forecast.empty:
        raise ValueError(
            "Cannot generate report from an empty forecast."
        )

    required_columns = {
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
    }

    missing = (
        required_columns
        - set(forecast.columns)
    )

    if missing:
        raise ValueError(
            "Forecast is missing report columns: "
            f"{sorted(missing)}"
        )

    REPORTS_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    # -------------------------------------------------------------------------
    # Metadata
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

    weather_source = str(
        forecast["weather_source"].iloc[0]
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

    generated_at = str(
        forecast["generated_at"].iloc[0]
    )

    # -------------------------------------------------------------------------
    # Analytics
    # -------------------------------------------------------------------------

    peak_load = float(
        analytics["peak_load_mw"]
    )

    peak_hour = int(
        analytics["peak_hour"]
    )

    minimum_load = float(
        analytics["minimum_load_mw"]
    )

    minimum_hour = int(
        analytics["minimum_hour"]
    )

    average_load = float(
        analytics["average_load_mw"]
    )

    daily_energy = float(
        analytics["daily_energy_mwh"]
    )

    load_factor = float(
        analytics["load_factor"]
    )

    ramp_up = float(
        analytics["max_ramp_up_mw"]
    )

    ramp_up_from = int(
        analytics["max_ramp_up_from_hour"]
    )

    ramp_up_to = int(
        analytics["max_ramp_up_to_hour"]
    )

    ramp_down = float(
        analytics["max_ramp_down_mw"]
    )

    ramp_down_from = int(
        analytics["max_ramp_down_from_hour"]
    )

    ramp_down_to = int(
        analytics["max_ramp_down_to_hour"]
    )

    # -------------------------------------------------------------------------
    # Derived visual content
    # -------------------------------------------------------------------------

    load_chart = _build_load_chart(
        forecast
    )

    ramp_chart = _build_ramp_chart(
        forecast
    )

    weather_chart = _build_weather_chart(
        forecast
    )

    # -------------------------------------------------------------------------
    # Hourly table
    # -------------------------------------------------------------------------

    table_rows = []

    for _, row in forecast.iterrows():

        load = float(
            row["Predicted_Load_MW"]
        )

        # Relative load intensity for table visual bar.
        intensity = (
            load / peak_load * 100
            if peak_load > 0
            else 0
        )

        table_rows.append(
            f"""
            <tr>

                <td>
                    <strong>
                        HE {int(row["Hr_End"]):02d}
                    </strong>
                </td>

                <td>
                    {_format_number(load, 1)}
                </td>

                <td>
                    <div class="mini-bar-shell">
                        <div
                            class="mini-bar"
                            style="width:{intensity:.1f}%"
                        ></div>
                    </div>
                </td>

                <td>
                    {float(row["Dry_Bulb"]):.1f} °F
                </td>

                <td>
                    {float(row["Dew_Point"]):.1f} °F
                </td>

            </tr>
            """
        )

    table_html = "".join(
        table_rows
    )

    # -------------------------------------------------------------------------
    # Human-readable insight cards
    # -------------------------------------------------------------------------

    load_factor_pct = (
        load_factor * 100
    )

    spread = (
        peak_load - minimum_load
    )

    insight_text = f"""
        The forecast reaches its highest demand at
        <strong>HE {peak_hour:02d}</strong>
        with approximately
        <strong>{peak_load:,.0f} MW</strong>.

        The daily peak-to-minimum spread is
        <strong>{spread:,.0f} MW</strong>.

        The predicted load factor is
        <strong>{load_factor_pct:.1f}%</strong>,
        representing the relationship between average and peak system demand.
    """

    # -------------------------------------------------------------------------
    # HTML
    # -------------------------------------------------------------------------

    html = f"""
<!DOCTYPE html>

<html lang="en">

<head>

<meta charset="UTF-8">

<meta
    name="viewport"
    content="width=device-width, initial-scale=1.0"
>

<title>
    GridCast | {escape(target_date)}
</title>


<style>

:root {{
    --background: #07111f;
    --surface: #0d1b2a;
    --surface-2: #11263a;
    --border: rgba(148, 163, 184, 0.16);

    --text: #e8f0f8;
    --muted: #8ca3b8;

    --accent: #38bdf8;
    --accent-soft: rgba(56, 189, 248, 0.14);

    --positive: #34d399;
    --negative: #fb7185;

    --warning: #fbbf24;
}}


* {{
    box-sizing: border-box;
}}


body {{
    margin: 0;

    background:
        radial-gradient(
            circle at top left,
            rgba(56, 189, 248, 0.10),
            transparent 35%
        ),
        radial-gradient(
            circle at top right,
            rgba(129, 140, 248, 0.08),
            transparent 28%
        ),
        var(--background);

    color: var(--text);

    font-family:
        Inter,
        -apple-system,
        BlinkMacSystemFont,
        "Segoe UI",
        sans-serif;
}}


.page {{
    max-width: 1320px;
    margin: auto;
    padding: 48px 32px 70px;
}}


/* ------------------------------------------------------------------
   HEADER
------------------------------------------------------------------ */

.hero {{
    display: flex;
    justify-content: space-between;
    align-items: flex-end;
    gap: 30px;

    margin-bottom: 38px;
}}


.brand {{
    display: inline-flex;
    align-items: center;
    gap: 12px;

    font-size: 14px;
    font-weight: 700;
    letter-spacing: 0.16em;
    text-transform: uppercase;

    color: var(--accent);

    margin-bottom: 16px;
}}


.brand-mark {{
    width: 11px;
    height: 11px;

    background: var(--accent);

    border-radius: 50%;

    box-shadow:
        0 0 16px rgba(56, 189, 248, 0.85);
}}


.hero h1 {{
    margin: 0;

    font-size: clamp(36px, 5vw, 62px);
    line-height: 1.02;
    letter-spacing: -0.04em;
}}


.hero-subtitle {{
    margin-top: 14px;

    color: var(--muted);

    font-size: 18px;
}}


.target-badge {{
    background: var(--accent-soft);

    border: 1px solid rgba(56, 189, 248, 0.25);

    padding: 14px 18px;

    border-radius: 14px;

    color: var(--accent);

    white-space: nowrap;
}}


/* ------------------------------------------------------------------
   KPI CARDS
------------------------------------------------------------------ */

.kpi-grid {{
    display: grid;

    grid-template-columns:
        repeat(auto-fit, minmax(205px, 1fr));

    gap: 16px;

    margin-bottom: 24px;
}}


.kpi-card {{
    position: relative;

    overflow: hidden;

    background:
        linear-gradient(
            145deg,
            rgba(17, 38, 58, 0.96),
            rgba(10, 25, 40, 0.96)
        );

    border: 1px solid var(--border);

    border-radius: 18px;

    padding: 22px;

    min-height: 142px;
}}


.kpi-card::after {{
    content: "";

    position: absolute;

    width: 100px;
    height: 100px;

    right: -45px;
    top: -45px;

    border-radius: 50%;

    background: rgba(56, 189, 248, 0.07);
}}


.kpi-label {{
    color: var(--muted);

    font-size: 13px;

    text-transform: uppercase;

    letter-spacing: 0.08em;

    margin-bottom: 14px;
}}


.kpi-value {{
    font-size: 31px;

    font-weight: 750;

    letter-spacing: -0.03em;
}}


.kpi-detail {{
    margin-top: 9px;

    color: var(--muted);

    font-size: 14px;
}}


/* ------------------------------------------------------------------
   SECTIONS
------------------------------------------------------------------ */

.section {{
    background:
        linear-gradient(
            145deg,
            rgba(13, 27, 42, 0.94),
            rgba(9, 23, 36, 0.94)
        );

    border: 1px solid var(--border);

    border-radius: 20px;

    padding: 28px;

    margin-bottom: 22px;
}}


.section-header {{
    display: flex;

    justify-content: space-between;

    align-items: center;

    margin-bottom: 20px;
}}


.section h2 {{
    margin: 0;

    font-size: 21px;

    letter-spacing: -0.02em;
}}


.section-description {{
    color: var(--muted);

    margin-top: 6px;

    font-size: 14px;
}}


.chart-svg {{
    display: block;

    width: 100%;

    height: auto;
}}


.grid-line {{
    stroke: rgba(148, 163, 184, 0.12);

    stroke-width: 1;
}}


.zero-line {{
    stroke: rgba(148, 163, 184, 0.32);

    stroke-width: 1.5;
}}


.axis-label {{
    fill: #7890a6;

    font-size: 12px;
}}


.axis-label.small {{
    font-size: 10px;
}}


.peak-label {{
    fill: #fb7185;

    font-size: 13px;

    font-weight: 700;
}}


.minimum-label {{
    fill: #34d399;

    font-size: 13px;

    font-weight: 700;
}}


.ramp-up {{
    fill: #34d399;

    opacity: 0.82;
}}


.ramp-down {{
    fill: #fb7185;

    opacity: 0.82;
}}


/* ------------------------------------------------------------------
   TWO COLUMN ANALYTICS
------------------------------------------------------------------ */

.analytics-grid {{
    display: grid;

    grid-template-columns:
        repeat(2, minmax(0, 1fr));

    gap: 22px;
}}


.insight {{
    color: #b9c9d8;

    line-height: 1.8;

    font-size: 15px;
}}


.metric-row {{
    display: flex;

    justify-content: space-between;

    gap: 20px;

    padding: 13px 0;

    border-bottom: 1px solid var(--border);
}}


.metric-row:last-child {{
    border-bottom: 0;
}}


.metric-name {{
    color: var(--muted);
}}


.metric-value {{
    font-weight: 650;
}}


.positive {{
    color: var(--positive);
}}


.negative {{
    color: var(--negative);
}}


/* ------------------------------------------------------------------
   LEGEND
------------------------------------------------------------------ */

.legend {{
    display: flex;

    gap: 22px;

    color: var(--muted);

    font-size: 13px;
}}


.legend-item {{
    display: flex;

    align-items: center;

    gap: 7px;
}}


.legend-dot {{
    width: 9px;
    height: 9px;

    border-radius: 50%;
}}


/* ------------------------------------------------------------------
   TABLE
------------------------------------------------------------------ */

.table-wrapper {{
    overflow-x: auto;
}}


table {{
    width: 100%;

    border-collapse: collapse;
}}


thead {{
    color: var(--muted);

    font-size: 12px;

    text-transform: uppercase;

    letter-spacing: 0.06em;
}}


th,
td {{
    padding: 14px 12px;

    text-align: right;

    border-bottom: 1px solid var(--border);
}}


th:first-child,
td:first-child {{
    text-align: left;
}}


tbody tr:hover {{
    background: rgba(56, 189, 248, 0.035);
}}


.mini-bar-shell {{
    width: 110px;

    height: 7px;

    margin-left: auto;

    border-radius: 100px;

    overflow: hidden;

    background: rgba(148, 163, 184, 0.10);
}}


.mini-bar {{
    height: 100%;

    border-radius: 100px;

    background:
        linear-gradient(
            90deg,
            #38bdf8,
            #818cf8
        );
}}


/* ------------------------------------------------------------------
   METADATA
------------------------------------------------------------------ */

.metadata-grid {{
    display: grid;

    grid-template-columns:
        repeat(auto-fit, minmax(220px, 1fr));

    gap: 14px;
}}


.metadata-box {{
    padding: 15px 16px;

    border-radius: 12px;

    background: rgba(148, 163, 184, 0.045);

    border: 1px solid var(--border);
}}


.metadata-label {{
    color: var(--muted);

    font-size: 12px;

    text-transform: uppercase;

    letter-spacing: 0.06em;

    margin-bottom: 6px;
}}


.metadata-value {{
    font-size: 14px;

    word-break: break-word;
}}


/* ------------------------------------------------------------------
   FOOTER
------------------------------------------------------------------ */

.footer {{
    display: flex;

    justify-content: space-between;

    gap: 20px;

    margin-top: 36px;

    padding-top: 22px;

    border-top: 1px solid var(--border);

    color: var(--muted);

    font-size: 12px;
}}


@media (max-width: 800px) {{

    .page {{
        padding: 28px 16px 50px;
    }}

    .hero {{
        flex-direction: column;

        align-items: flex-start;
    }}

    .analytics-grid {{
        grid-template-columns: 1fr;
    }}

}}


@media print {{

    body {{
        background: #ffffff;

        color: #111827;
    }}

    .section,
    .kpi-card {{
        break-inside: avoid;
    }}

}}

</style>

</head>


<body>

<div class="page">


<!-- ===============================================================
     HERO
================================================================ -->

<header class="hero">

    <div>

        <div class="brand">

            <span class="brand-mark"></span>

            GridCast

        </div>

        <h1>
            Day-Ahead Electricity
            <br>
            Demand Intelligence
        </h1>

        <div class="hero-subtitle">

            24-hour system load forecast and operational analysis.

        </div>

    </div>


    <div class="target-badge">

        Target&nbsp;
        <strong>{escape(target_date)}</strong>

    </div>

</header>


<!-- ===============================================================
     KPI SUMMARY
================================================================ -->

<div class="kpi-grid">


    <div class="kpi-card">

        <div class="kpi-label">
            Peak Demand
        </div>

        <div class="kpi-value">
            {peak_load:,.0f}
            <small>MW</small>
        </div>

        <div class="kpi-detail">
            Expected at HE {peak_hour:02d}
        </div>

    </div>


    <div class="kpi-card">

        <div class="kpi-label">
            Minimum Demand
        </div>

        <div class="kpi-value">
            {minimum_load:,.0f}
            <small>MW</small>
        </div>

        <div class="kpi-detail">
            Expected at HE {minimum_hour:02d}
        </div>

    </div>


    <div class="kpi-card">

        <div class="kpi-label">
            Average Demand
        </div>

        <div class="kpi-value">
            {average_load:,.0f}
            <small>MW</small>
        </div>

        <div class="kpi-detail">
            Daily mean load
        </div>

    </div>


    <div class="kpi-card">

        <div class="kpi-label">
            Daily Energy
        </div>

        <div class="kpi-value">
            {daily_energy:,.0f}
            <small>MWh</small>
        </div>

        <div class="kpi-detail">
            Forecast energy requirement
        </div>

    </div>


    <div class="kpi-card">

        <div class="kpi-label">
            Load Factor
        </div>

        <div class="kpi-value">
            {load_factor_pct:.1f}%
        </div>

        <div class="kpi-detail">
            Average / peak demand
        </div>

    </div>


</div>


<!-- ===============================================================
     LOAD PROFILE
================================================================ -->

<section class="section">

    <div class="section-header">

        <div>

            <h2>
                24-Hour Demand Profile
            </h2>

            <div class="section-description">

                Forecasted system load throughout the target day.

            </div>

        </div>

    </div>

    {load_chart}

</section>


<!-- ===============================================================
     ANALYTICS
================================================================ -->

<div class="analytics-grid">


<section class="section">

    <h2>
        Operational Insights
    </h2>

    <p class="insight">

        {insight_text}

    </p>

    <div class="metric-row">

        <span class="metric-name">
            Peak-to-minimum spread
        </span>

        <span class="metric-value">
            {spread:,.0f} MW
        </span>

    </div>

    <div class="metric-row">

        <span class="metric-name">
            Largest upward ramp
        </span>

        <span class="metric-value positive">
            +{ramp_up:,.0f} MW
        </span>

    </div>

    <div class="metric-row">

        <span class="metric-name">
            Largest downward ramp
        </span>

        <span class="metric-value negative">
            {ramp_down:,.0f} MW
        </span>

    </div>

</section>


<section class="section">

    <h2>
        Ramp Summary
    </h2>

    <div class="metric-row">

        <span class="metric-name">
            Strongest pickup
        </span>

        <span class="metric-value">
            HE {ramp_up_from:02d}
            →
            HE {ramp_up_to:02d}
        </span>

    </div>

    <div class="metric-row">

        <span class="metric-name">
            Ramp magnitude
        </span>

        <span class="metric-value positive">
            +{ramp_up:,.1f} MW
        </span>

    </div>

    <div class="metric-row">

        <span class="metric-name">
            Strongest decline
        </span>

        <span class="metric-value">
            HE {ramp_down_from:02d}
            →
            HE {ramp_down_to:02d}
        </span>

    </div>

    <div class="metric-row">

        <span class="metric-name">
            Decline magnitude
        </span>

        <span class="metric-value negative">
            {ramp_down:,.1f} MW
        </span>

    </div>

</section>


</div>


<!-- ===============================================================
     RAMP CHART
================================================================ -->

<section class="section">

    <div class="section-header">

        <div>

            <h2>
                Hour-to-Hour Ramp Profile
            </h2>

            <div class="section-description">

                Change in predicted load between consecutive
                hourly intervals.

            </div>

        </div>

        <div class="legend">

            <div class="legend-item">

                <span
                    class="legend-dot"
                    style="background:#34d399"
                ></span>

                Ramp up

            </div>

            <div class="legend-item">

                <span
                    class="legend-dot"
                    style="background:#fb7185"
                ></span>

                Ramp down

            </div>

        </div>

    </div>

    {ramp_chart}

</section>


<!-- ===============================================================
     WEATHER
================================================================ -->

<section class="section">

    <div class="section-header">

        <div>

            <h2>
                Weather Drivers
            </h2>

            <div class="section-description">

                Temperature inputs used by GridCast for the
                target-day forecast.

            </div>

        </div>

        <div class="legend">

            <div class="legend-item">

                <span
                    class="legend-dot"
                    style="background:#fb923c"
                ></span>

                Dry Bulb

            </div>

            <div class="legend-item">

                <span
                    class="legend-dot"
                    style="background:#818cf8"
                ></span>

                Dew Point

            </div>

        </div>

    </div>

    {weather_chart}

</section>


<!-- ===============================================================
     HOURLY TABLE
================================================================ -->

<section class="section">

    <div class="section-header">

        <div>

            <h2>
                Hourly Forecast Detail
            </h2>

            <div class="section-description">

                Predicted demand and corresponding weather
                conditions for each hour ending.

            </div>

        </div>

    </div>


    <div class="table-wrapper">

        <table>

            <thead>

                <tr>

                    <th>
                        Hour
                    </th>

                    <th>
                        Load MW
                    </th>

                    <th>
                        Relative Load
                    </th>

                    <th>
                        Dry Bulb
                    </th>

                    <th>
                        Dew Point
                    </th>

                </tr>

            </thead>

            <tbody>

                {table_html}

            </tbody>

        </table>

    </div>

</section>


<!-- ===============================================================
     MODEL / DATA LINEAGE
================================================================ -->

<section class="section">

    <div class="section-header">

        <div>

            <h2>
                Forecast Provenance
            </h2>

            <div class="section-description">

                Reproducibility and model lineage for this
                forecast artifact.

            </div>

        </div>

    </div>


    <div class="metadata-grid">


        <div class="metadata-box">

            <div class="metadata-label">
                Forecast Origin
            </div>

            <div class="metadata-value">
                {escape(origin_date)}
            </div>

        </div>


        <div class="metadata-box">

            <div class="metadata-label">
                Target Date
            </div>

            <div class="metadata-value">
                {escape(target_date)}
            </div>

        </div>


        <div class="metadata-box">

            <div class="metadata-label">
                Weather Source
            </div>

            <div class="metadata-value">
                {escape(weather_source)}
            </div>

        </div>


        <div class="metadata-box">

            <div class="metadata-label">
                Model
            </div>

            <div class="metadata-value">
                {escape(model_alias)}
                ·
                {escape(model_version)}
            </div>

        </div>


        <div class="metadata-box">

            <div class="metadata-label">
                MLflow Run
            </div>

            <div class="metadata-value">
                {escape(model_run_id)}
            </div>

        </div>


        <div class="metadata-box">

            <div class="metadata-label">
                Generated At
            </div>

            <div class="metadata-value">
                {escape(generated_at)}
            </div>

        </div>


    </div>

</section>


<footer class="footer">

    <div>
        GridCast · Electricity Demand Forecasting System
    </div>

    <div>
        Forecast values are model estimates, not actual system load.
    </div>

</footer>


</div>

</body>

</html>
"""

    report_path = (
    REPORTS_DIR
    / f"gridcast_{target_date}_{forecast_id[:8]}.html"
    )

    report_path.write_text(
        html,
        encoding="utf-8",
    )

    return report_path