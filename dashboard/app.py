"""
GridCast Dashboard

A Streamlit UI for the GridCast online and offline APIs.

Run locally:
    ONLINE_API_URL=http://localhost:8000 \
    OFFLINE_API_URL=http://localhost:8001 \
    streamlit run app.py

Design principles:
    - UI talks to FastAPI services only.
    - No direct SQLite / Parquet / filesystem access.
    - Forecast reruns are protected against stale `/latest` results.
    - POST requests are not automatically retried to avoid duplicate jobs.
"""

from __future__ import annotations

import json
import os
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pandas as pd
import requests
import streamlit as st
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ONLINE_API = os.getenv("ONLINE_API_URL", "http://localhost:8000").rstrip("/")
OFFLINE_API = os.getenv("OFFLINE_API_URL", "http://localhost:8001").rstrip("/")

CONNECT_TIMEOUT = float(os.getenv("DASHBOARD_CONNECT_TIMEOUT", "3"))
READ_TIMEOUT = float(os.getenv("DASHBOARD_READ_TIMEOUT", "30"))
FORECAST_POLL_SECONDS = float(os.getenv("DASHBOARD_POLL_SECONDS", "2"))
FORECAST_MAX_WAIT_SECONDS = int(os.getenv("DASHBOARD_MAX_WAIT_SECONDS", "240"))

st.set_page_config(
    page_title="GridCast",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
        .stApp {
            background:
                radial-gradient(circle at top right, rgba(59,130,246,.08), transparent 28rem),
                radial-gradient(circle at bottom left, rgba(14,165,233,.06), transparent 28rem);
        }
        .block-container {
            padding-top: 1.8rem;
            padding-bottom: 3rem;
            max-width: 1500px;
        }
        [data-testid="stSidebar"] {
            border-right: 1px solid rgba(128,128,128,.18);
        }
        .gc-hero {
            position: relative;
            overflow: hidden;
            padding: 1.8rem 2rem;
            border-radius: 22px;
            background: linear-gradient(135deg, rgba(30,64,175,.96), rgba(2,132,199,.88));
            color: white;
            margin-bottom: 1.3rem;
            box-shadow: 0 16px 40px rgba(15,23,42,.14);
            min-height: 145px;
        }
        .gc-hero::before {
            content: "";
            position: absolute;
            width: 220px;
            height: 220px;
            border-radius: 50%;
            right: -65px;
            top: -95px;
            background: rgba(255,255,255,.10);
        }
        .gc-hero::after {
            content: "";
            position: absolute;
            width: 145px;
            height: 145px;
            border-radius: 50%;
            right: 90px;
            bottom: -95px;
            background: rgba(255,255,255,.08);
        }
        .gc-hero-copy {
            position: relative;
            z-index: 2;
            max-width: 74%;
        }
        .gc-hero h1 { margin: 0; font-size: 2rem; font-weight: 750; }
        .gc-hero p { margin: .45rem 0 0 0; opacity: .90; font-size: 1rem; }
        .gc-hero-icon {
            position: absolute;
            right: 42px;
            top: 22px;
            z-index: 2;
            font-size: 4.8rem;
            opacity: .94;
            filter: drop-shadow(0 8px 18px rgba(0,0,0,.16));
        }
        .gc-hero-spark {
            position: absolute;
            right: 128px;
            bottom: 22px;
            z-index: 2;
            opacity: .42;
            font-size: 1.55rem;
            letter-spacing: .08rem;
        }
        .gc-kpi-card {
            height: 150px;
            padding: 1rem;
            border: 1px solid rgba(128,128,128,.18);
            border-radius: 18px;
            background: rgba(255,255,255,.025);
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            box-sizing: border-box;
            overflow: hidden;
        }
        .gc-kpi-label {
            font-size: .84rem;
            opacity: .78;
            line-height: 1.25;
            min-height: 2.1rem;
        }
        .gc-kpi-value {
            font-size: 1.36rem;
            line-height: 1.1;
            font-weight: 760;
            letter-spacing: -.02em;
            white-space: nowrap;
        }
        .gc-kpi-note {
            font-size: .78rem;
            opacity: .68;
            min-height: 1.15rem;
        }
        .gc-prediction-card {
            padding: 1.45rem 1.6rem;
            border-radius: 20px;
            border: 1px solid rgba(34,197,94,.28);
            background: linear-gradient(135deg, rgba(22,163,74,.13), rgba(14,165,233,.08));
            margin-top: .85rem;
            margin-bottom: .6rem;
        }
        .gc-prediction-label {
            font-size: .95rem;
            opacity: .76;
            margin-bottom: .35rem;
        }
        .gc-prediction-value {
            font-size: 2.35rem;
            font-weight: 800;
            letter-spacing: -.03em;
            line-height: 1.05;
        }
        .gc-prediction-meta {
            margin-top: .65rem;
            opacity: .68;
            font-size: .88rem;
        }
        .gc-card {
            padding: 1.1rem 1.2rem;
            border: 1px solid rgba(128,128,128,.18);
            border-radius: 18px;
            background: rgba(255,255,255,.03);
        }
        .gc-muted { opacity: .68; font-size: .92rem; }
        .gc-pill-ok, .gc-pill-bad {
            display: inline-block;
            padding: .28rem .65rem;
            border-radius: 999px;
            font-size: .82rem;
            font-weight: 650;
        }
        .gc-pill-ok { background: rgba(34,197,94,.14); color: rgb(22,163,74); }
        .gc-pill-bad { background: rgba(239,68,68,.14); color: rgb(220,38,38); }
        div[data-testid="stMetric"] {
            border: 1px solid rgba(128,128,128,.17);
            padding: 1rem 1rem .75rem 1rem;
            border-radius: 18px;
            background: rgba(255,255,255,.025);
        }
        .stButton > button, .stDownloadButton > button {
            border-radius: 12px;
            min-height: 2.7rem;
        }
        .gc-section-title { font-size: 1.15rem; font-weight: 700; margin-bottom: .4rem; }
    </style>
    """,
    unsafe_allow_html=True,
)


class APIError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        detail: str | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail


def _get_session() -> requests.Session:
    retry = Retry(
        total=2,
        connect=2,
        read=2,
        status=2,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET"]),
        raise_on_status=False,
    )
    session = requests.Session()
    session.mount("http://", HTTPAdapter(max_retries=retry))
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def _extract_error_detail(response: requests.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        text = response.text.strip()
        return text[:500] if text else "No error body returned."

    if isinstance(payload, dict):
        for key in ("detail", "reason", "message"):
            if payload.get(key) is not None:
                return str(payload[key])

    return str(payload)[:500]


def api_get(
    base_url: str,
    path: str,
    *,
    timeout: tuple[float, float] | None = None,
    allow_404: bool = False,
) -> Any | None:
    session = _get_session()
    try:
        response = session.get(
            f"{base_url}{path}",
            timeout=timeout or (CONNECT_TIMEOUT, READ_TIMEOUT),
        )
    except requests.Timeout as exc:
        raise APIError(f"Request to {base_url} timed out.") from exc
    except requests.ConnectionError as exc:
        raise APIError(f"Could not connect to {base_url}.") from exc
    except requests.RequestException as exc:
        raise APIError(f"Request to {base_url} failed: {exc}") from exc
    finally:
        session.close()

    if response.status_code == 404 and allow_404:
        return None

    if not response.ok:
        raise APIError(
            f"API returned HTTP {response.status_code}.",
            status_code=response.status_code,
            detail=_extract_error_detail(response),
        )

    try:
        return response.json()
    except ValueError as exc:
        raise APIError(f"{base_url}{path} returned invalid JSON.") from exc


def api_post(
    base_url: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
) -> Any:
    try:
        response = requests.post(
            f"{base_url}{path}",
            params=params,
            json=json_body,
            timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
        )
    except requests.Timeout as exc:
        raise APIError(
            "The API trigger request timed out. The server may still have received "
            "the request; check running jobs before submitting it again."
        ) from exc
    except requests.ConnectionError as exc:
        raise APIError(f"Could not connect to {base_url}.") from exc
    except requests.RequestException as exc:
        raise APIError(f"Request failed: {exc}") from exc

    if not response.ok:
        raise APIError(
            f"API returned HTTP {response.status_code}.",
            status_code=response.status_code,
            detail=_extract_error_detail(response),
        )

    try:
        return response.json()
    except ValueError as exc:
        raise APIError("API accepted the request but returned invalid JSON.") from exc


def api_download(base_url: str, path: str) -> tuple[bytes, str, str]:
    session = _get_session()
    try:
        response = session.get(
            f"{base_url}{path}",
            timeout=(CONNECT_TIMEOUT, max(READ_TIMEOUT, 60)),
        )
    except requests.RequestException as exc:
        raise APIError(f"Artifact download failed: {exc}") from exc
    finally:
        session.close()

    if not response.ok:
        raise APIError(
            f"Artifact endpoint returned HTTP {response.status_code}.",
            status_code=response.status_code,
            detail=_extract_error_detail(response),
        )

    content_type = response.headers.get("content-type", "application/octet-stream")
    disposition = response.headers.get("content-disposition", "")
    filename = "download"
    if "filename=" in disposition:
        filename = disposition.split("filename=", 1)[1].strip().strip('"')

    return response.content, filename, content_type


@st.cache_data(ttl=5, show_spinner=False)
def cached_health(base_url: str) -> dict[str, Any]:
    try:
        payload = api_get(base_url, "/health")
        return payload if isinstance(payload, dict) else {}
    except APIError:
        return {}


@st.cache_data(ttl=30, show_spinner=False)
def cached_forecasts() -> list[dict[str, Any]]:
    payload = api_get(OFFLINE_API, "/forecasts")
    return payload if isinstance(payload, list) else []


@st.cache_data(ttl=60, show_spinner=False)
def cached_openapi(base_url: str) -> dict[str, Any]:
    payload = api_get(base_url, "/openapi.json")
    return payload if isinstance(payload, dict) else {}


def parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def format_number(value: Any, decimals: int = 0) -> str:
    try:
        return f"{float(value):,.{decimals}f}"
    except (TypeError, ValueError):
        return "—"


def format_percent(value: Any, decimals: int = 1) -> str:
    try:
        return f"{float(value) * 100:.{decimals}f}%"
    except (TypeError, ValueError):
        return "—"


def normalized_forecast_rows(forecasts: list[dict[str, Any]]) -> pd.DataFrame:
    if not forecasts:
        return pd.DataFrame()

    df = pd.DataFrame(forecasts)
    desired = [
        "forecast_id", "origin_date", "target_date", "generated_at",
        "peak_load_mw", "peak_hour", "minimum_load_mw", "minimum_hour",
        "average_load_mw", "daily_energy_mwh", "load_factor",
        "max_ramp_up_mw", "max_ramp_down_mw", "weather_source",
    ]
    for col in desired:
        if col not in df.columns:
            df[col] = None
    return df[desired]


def get_latest_forecast_for_target(target_date: str) -> dict[str, Any] | None:
    payload = api_get(
        OFFLINE_API,
        f"/forecasts/target/{target_date}/latest",
        allow_404=True,
    )
    return payload if isinstance(payload, dict) else None


def extract_failure_message(payload: Any, origin_date: str) -> str | None:
    if payload is None:
        return None

    if isinstance(payload, dict):
        if origin_date in payload:
            return str(payload[origin_date])

        for key in ("failed_jobs", "failures", "jobs"):
            nested = payload.get(key)
            found = extract_failure_message(nested, origin_date)
            if found:
                return found

        for value in payload.values():
            found = extract_failure_message(value, origin_date)
            if found:
                return found

    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict):
                item_origin = str(item.get("origin_date", item.get("date", "")))
                if item_origin == origin_date:
                    return str(
                        item.get("error", item.get("message", item.get("detail", "Forecast failed.")))
                    )

    return None


def wait_for_new_forecast(
    *,
    origin_date: str,
    target_date: str,
    previous_forecast_id: str | None,
) -> dict[str, Any]:
    started = time.monotonic()

    while time.monotonic() - started < FORECAST_MAX_WAIT_SECONDS:
        failures = api_get(OFFLINE_API, "/failures")
        failure = extract_failure_message(failures, origin_date)
        if failure:
            raise APIError("Forecast job failed.", detail=failure)

        latest = get_latest_forecast_for_target(target_date)
        if latest:
            latest_id = latest.get("forecast_id")
            if previous_forecast_id is None or latest_id != previous_forecast_id:
                return latest

        time.sleep(FORECAST_POLL_SECONDS)

    raise APIError(
        "The forecast is still not available through the API. "
        "Check Running Jobs and Failures before submitting another request."
    )


def forecast_label(row: dict[str, Any]) -> str:
    target = row.get("target_date", "unknown")
    generated_dt = parse_datetime(row.get("generated_at"))
    generated_text = (
        generated_dt.strftime("%Y-%m-%d %H:%M UTC")
        if generated_dt else "unknown generation time"
    )
    return f"{target}  ·  generated {generated_text}"


def render_hero(
    title: str,
    subtitle: str,
    icon: str = "⚡",
) -> None:
    st.markdown(
        f"""
        <div class="gc-hero">
            <div class="gc-hero-copy">
                <h1>{title}</h1>
                <p>{subtitle}</p>
            </div>
            <div class="gc-hero-icon">{icon}</div>
            <div class="gc-hero-spark">▁▃▅▇▆▄▅▇</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_api_error(title: str, exc: Exception) -> None:
    st.error(title)
    if isinstance(exc, APIError) and exc.detail:
        st.caption(exc.detail)
    else:
        st.caption(str(exc))


def render_forecast_metrics(
    forecast: dict[str, Any],
) -> None:
    cards = [
        (
            "⚡ Peak demand",
            f"{format_number(forecast.get('peak_load_mw'))} MW",
            f"Hour ending {forecast.get('peak_hour', '—')}",
        ),
        (
            "🌙 Minimum demand",
            f"{format_number(forecast.get('minimum_load_mw'))} MW",
            f"Hour ending {forecast.get('minimum_hour', '—')}",
        ),
        (
            "📊 Average demand",
            f"{format_number(forecast.get('average_load_mw'))} MW",
            "Daily average",
        ),
        (
            "🔋 Daily energy",
            f"{format_number(forecast.get('daily_energy_mwh'))} MWh",
            "Total forecast energy",
        ),
        (
            "📈 Load factor",
            format_percent(forecast.get("load_factor")),
            "Average ÷ peak",
        ),
    ]

    columns = st.columns(5)

    for column, (label, value, note) in zip(columns, cards):
        with column:
            st.markdown(
                f"""
                <div class="gc-kpi-card">
                    <div class="gc-kpi-label">{label}</div>
                    <div class="gc-kpi-value">{value}</div>
                    <div class="gc-kpi-note">{note}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )


def render_hourly_charts(forecast_id: str) -> None:
    try:
        hourly = api_get(OFFLINE_API, f"/forecasts/{forecast_id}/hourly")
    except APIError as exc:
        render_api_error("Could not load hourly forecast data.", exc)
        return

    if not isinstance(hourly, list) or not hourly:
        st.info("No hourly forecast data was returned.")
        return

    df = pd.DataFrame(hourly)
    required = {"Hr_End", "Predicted_Load_MW"}
    if not required.issubset(df.columns):
        st.warning("Hourly data is missing the columns required for the demand chart.")
        st.dataframe(df, use_container_width=True, hide_index=True)
        return

    demand = df[["Hr_End", "Predicted_Load_MW"]].copy().sort_values("Hr_End").set_index("Hr_End")
    st.subheader("24-hour demand profile")
    st.line_chart(demand, y="Predicted_Load_MW", height=360)

    weather_cols = [col for col in ("Dry_Bulb", "Dew_Point") if col in df.columns]
    if weather_cols:
        st.subheader("Weather drivers")
        weather = df[["Hr_End", *weather_cols]].copy().sort_values("Hr_End").set_index("Hr_End")
        st.line_chart(weather, y=weather_cols, height=300)

    with st.expander("Hourly forecast table"):
        display_cols = [
            col for col in ("Hr_End", "Predicted_Load_MW", "Dry_Bulb", "Dew_Point")
            if col in df.columns
        ]
        st.dataframe(df[display_cols], use_container_width=True, hide_index=True)


def render_downloads(forecast_id: str) -> None:
    st.subheader("Export forecast")
    col1, col2 = st.columns(2)

    with col1:
        try:
            html_bytes, html_name, html_type = api_download(
                OFFLINE_API,
                f"/forecasts/{forecast_id}/report",
            )
            st.download_button(
                "↓ Download HTML report",
                data=html_bytes,
                file_name=html_name,
                mime=html_type,
                use_container_width=True,
                key=f"html_{forecast_id}",
            )
        except APIError as exc:
            st.button("HTML report unavailable", disabled=True, use_container_width=True, key=f"html_disabled_{forecast_id}")
            if exc.detail:
                st.caption(exc.detail)

    with col2:
        try:
            parquet_bytes, parquet_name, parquet_type = api_download(
                OFFLINE_API,
                f"/forecasts/{forecast_id}/parquet",
            )
            st.download_button(
                "↓ Download Parquet data",
                data=parquet_bytes,
                file_name=parquet_name,
                mime=parquet_type,
                use_container_width=True,
                key=f"parquet_{forecast_id}",
            )
        except APIError as exc:
            st.button("Parquet download unavailable", disabled=True, use_container_width=True, key=f"parquet_disabled_{forecast_id}")
            if exc.status_code == 404:
                st.caption("Add the `/forecasts/{forecast_id}/parquet` endpoint to the offline API.")
            elif exc.detail:
                st.caption(exc.detail)


def render_forecast_detail(forecast: dict[str, Any], *, show_downloads: bool = True) -> None:
    forecast_id = str(forecast.get("forecast_id", ""))
    st.markdown(f"### Forecast for {forecast.get('target_date', '—')}")
    st.caption(
        f"Origin date: {forecast.get('origin_date', '—')} · "
        f"Generated: {forecast.get('generated_at', '—')}"
    )
    render_forecast_metrics(forecast)
    st.divider()

    if forecast_id:
        render_hourly_charts(forecast_id)
        if show_downloads:
            st.divider()
            render_downloads(forecast_id)



def render_online_prediction_result(
    result: dict[str, Any],
) -> None:
    prediction = result.get("predicted_mw")

    if prediction is None:
        prediction = result.get("predicted_load_mw")

    if prediction is None:
        prediction = result.get("prediction")

    if prediction is None:
        st.warning(
            "Prediction completed, but the response did not contain "
            "a recognized prediction field."
        )
        with st.expander("Raw response"):
            st.json(result)
        return

    st.markdown(
        f"""
        <div class="gc-prediction-card">
            <div class="gc-prediction-label">⚡ Predicted system load</div>
            <div class="gc-prediction-value">{format_number(prediction, 2)} MW</div>
            <div class="gc-prediction-meta">
                GridCast live inference completed successfully.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    model_version = result.get("model_version")
    model_alias = result.get("model_alias")

    if model_version or model_alias:
        with st.expander("Technical details"):
            if model_version:
                st.write(f"Model version: `{model_version}`")
            if model_alias:
                st.write(f"Model alias: `{model_alias}`")

def _resolve_schema_ref(document: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    ref = schema.get("$ref")
    if not ref or not ref.startswith("#/"):
        return schema

    current: Any = document
    for token in ref[2:].split("/"):
        if not isinstance(current, dict):
            return schema
        current = current.get(token)

    return current if isinstance(current, dict) else schema


def get_predict_request_schema() -> dict[str, Any] | None:
    try:
        spec = cached_openapi(ONLINE_API)
    except APIError:
        return None

    predict = spec.get("paths", {}).get("/predict", {}).get("post", {})
    body_schema = (
        predict.get("requestBody", {})
        .get("content", {})
        .get("application/json", {})
        .get("schema", {})
    )
    if not body_schema:
        return None
    return _resolve_schema_ref(spec, body_schema)


def render_dynamic_predict_form(
    schema: dict[str, Any],
) -> dict[str, Any] | None:
    properties = schema.get("properties", {})
    required = set(schema.get("required", []))

    if not isinstance(properties, dict) or not properties:
        return None

    values: dict[str, Any] = {}

    with st.form("online_predict_form"):
        columns = st.columns(2)

        for index, (name, raw_spec) in enumerate(properties.items()):
            spec = raw_spec if isinstance(raw_spec, dict) else {}

            field_type = spec.get("type", "string")
            description = spec.get("description", "")
            default = spec.get("default")
            enum = spec.get("enum")

            label = (
                f"{name} *"
                if name in required
                else name
            )

            with columns[index % 2]:

                # -------------------------------------------------------------
                # Date
                # -------------------------------------------------------------
                if name.lower() == "date":
                    values[name] = st.text_input(
                        label,
                        value="",
                        placeholder=(
                            "YYYY-MM-DD "
                            "(example: 2025-07-04)"
                        ),
                        help=(
                            description
                            or (
                                "Enter the date using "
                                "YYYY-MM-DD, "
                                "for example 2025-07-04."
                            )
                        ),
                    )

                # -------------------------------------------------------------
                # Enum
                # -------------------------------------------------------------
                elif enum:
                    values[name] = st.selectbox(
                        label,
                        options=enum,
                        help=description or None,
                    )

                # -------------------------------------------------------------
                # Integer
                # -------------------------------------------------------------
                elif field_type == "integer":
                    min_value = spec.get("minimum")
                    max_value = spec.get("maximum")

                    if default is not None:
                        initial_value = int(default)

                    elif min_value is not None:
                        initial_value = int(min_value)

                    else:
                        initial_value = 0

                    # Defensive bounds protection
                    if min_value is not None:
                        initial_value = max(
                            initial_value,
                            int(min_value),
                        )

                    if max_value is not None:
                        initial_value = min(
                            initial_value,
                            int(max_value),
                        )

                    kwargs: dict[str, Any] = {
                        "label": label,
                        "value": initial_value,
                        "step": 1,
                        "help": description or None,
                    }

                    if min_value is not None:
                        kwargs["min_value"] = int(
                            min_value
                        )

                    if max_value is not None:
                        kwargs["max_value"] = int(
                            max_value
                        )

                    values[name] = int(
                        st.number_input(
                            **kwargs
                        )
                    )

                # -------------------------------------------------------------
                # Float / number
                # -------------------------------------------------------------
                elif field_type == "number":
                    min_value = spec.get("minimum")
                    max_value = spec.get("maximum")

                    if default is not None:
                        initial_value = float(default)

                    elif min_value is not None:
                        initial_value = float(min_value)

                    else:
                        initial_value = 0.0

                    # Defensive bounds protection
                    if min_value is not None:
                        initial_value = max(
                            initial_value,
                            float(min_value),
                        )

                    if max_value is not None:
                        initial_value = min(
                            initial_value,
                            float(max_value),
                        )

                    kwargs = {
                        "label": label,
                        "value": initial_value,
                        "help": description or None,
                    }

                    if min_value is not None:
                        kwargs["min_value"] = float(
                            min_value
                        )

                    if max_value is not None:
                        kwargs["max_value"] = float(
                            max_value
                        )

                    values[name] = float(
                        st.number_input(
                            **kwargs
                        )
                    )

                # -------------------------------------------------------------
                # Boolean
                # -------------------------------------------------------------
                elif field_type == "boolean":
                    values[name] = st.checkbox(
                        label,
                        value=bool(
                            default
                            if default is not None
                            else False
                        ),
                        help=description or None,
                    )

                # -------------------------------------------------------------
                # OpenAPI date type
                # -------------------------------------------------------------
                elif spec.get("format") == "date":
                    chosen = st.date_input(
                        label,
                        value=date.today(),
                        help=description or None,
                    )

                    values[name] = (
                        chosen.isoformat()
                    )

                # -------------------------------------------------------------
                # Generic string
                # -------------------------------------------------------------
                else:
                    values[name] = st.text_input(
                        label,
                        value=(
                            ""
                            if default is None
                            else str(default)
                        ),
                        help=description or None,
                    )

        submitted = st.form_submit_button(
            "Run live prediction",
            type="primary",
            use_container_width=True,
        )

    if not submitted:
        return None

    # -------------------------------------------------------------------------
    # Required field validation
    # -------------------------------------------------------------------------

    missing = [
        field
        for field in required
        if values.get(field) in (
            None,
            "",
        )
    ]

    if missing:
        st.error(
            "Required fields are missing: "
            + ", ".join(
                sorted(missing)
            )
        )
        return None

    # -------------------------------------------------------------------------
    # Date validation
    # -------------------------------------------------------------------------

    for field_name in values:
        if field_name.lower() == "date":

            try:
                parsed_date = datetime.strptime(
                    str(
                        values[field_name]
                    ).strip(),
                    "%Y-%m-%d",
                ).date()

                values[field_name] = (
                    parsed_date.isoformat()
                )

            except ValueError:
                st.error(
                    "Date must use YYYY-MM-DD format. "
                    "Example: 2025-07-04."
                )
                return None

    return values

online_health = cached_health(ONLINE_API)
offline_health = cached_health(OFFLINE_API)

with st.sidebar:
    st.markdown("## ⚡ GridCast")
    st.caption("Electricity Demand Intelligence")
    st.divider()

    page = st.radio(
        "Navigation",
        ["Overview", "Live Prediction", "Day Forecast", "Forecast History", "System"],
        label_visibility="collapsed",
    )

    st.divider()
    st.markdown("**Service status**")
    st.markdown(
        '<span class="gc-pill-ok">● Online API</span>' if online_health
        else '<span class="gc-pill-bad">● Online API</span>',
        unsafe_allow_html=True,
    )
    st.write("")
    st.markdown(
        '<span class="gc-pill-ok">● Offline API</span>' if offline_health
        else '<span class="gc-pill-bad">● Offline API</span>',
        unsafe_allow_html=True,
    )


if page == "Overview":
    render_hero(
        "GridCast Control Center",
        "Explore demand forecasts, run historical day forecasts, and export forecast intelligence from one workspace.",
        icon="⚡",
    )

    try:
        forecasts = cached_forecasts()
    except APIError as exc:
        forecasts = []
        render_api_error("Could not load forecast history.", exc)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Online inference", "Available" if online_health else "Unavailable")
    c2.metric("Offline forecasting", "Available" if offline_health else "Unavailable")
    c3.metric("Stored forecasts", len(forecasts))

    running_count: Any = "—"
    if offline_health:
        try:
            running_payload = api_get(OFFLINE_API, "/running")
            if isinstance(running_payload, list):
                running_count = len(running_payload)
            elif isinstance(running_payload, dict):
                candidate = running_payload.get("running_jobs", running_payload.get("running", []))
                running_count = len(candidate) if isinstance(candidate, (list, dict)) else candidate
        except APIError:
            pass
    c4.metric("Running jobs", running_count)

    st.divider()

    if forecasts:
        latest = forecasts[0]
        st.markdown('<div class="gc-section-title">Latest forecast</div>', unsafe_allow_html=True)
        render_forecast_metrics(latest)

        latest_id = latest.get("forecast_id")
        if latest_id:
            st.divider()
            render_hourly_charts(str(latest_id))

        st.divider()
        st.markdown('<div class="gc-section-title">Recent forecasts</div>', unsafe_allow_html=True)
        recent = normalized_forecast_rows(forecasts[:8])
        if not recent.empty:
            display = recent[[
                "target_date", "peak_load_mw", "peak_hour",
                "average_load_mw", "daily_energy_mwh", "load_factor", "generated_at",
            ]].copy()
            display.columns = [
                "Forecast Date", "Peak MW", "Peak Hour",
                "Average MW", "Energy MWh", "Load Factor", "Generated",
            ]
            st.dataframe(display, use_container_width=True, hide_index=True)
    else:
        st.info("No stored forecasts yet. Open **Day Forecast** to create one.")


elif page == "Live Prediction":
    render_hero(
        "Live Load Prediction",
        "Send one inference request to the online GridCast service.",
        icon="🔮",
    )

    if not online_health:
        st.error(f"Online API is not reachable at {ONLINE_API}.")
    else:
        st.success("Online inference service is available.")
        schema = get_predict_request_schema()

        if schema:
            payload = render_dynamic_predict_form(schema)
            if payload is not None:
                try:
                    result = api_post(ONLINE_API, "/predict", json_body=payload)
                    st.success("Prediction completed.")
                    if isinstance(result, dict):
                        render_online_prediction_result(result)
                    else:
                        st.write(result)
                except APIError as exc:
                    render_api_error("Live prediction failed.", exc)
        else:
            st.warning(
                "The dashboard could not infer the `/predict` request schema from the online API OpenAPI document."
            )
            raw = st.text_area("JSON request body", value="{\n\n}", height=220)
            if st.button("Run live prediction", type="primary"):
                try:
                    payload = json.loads(raw)
                    if not isinstance(payload, dict):
                        raise ValueError("JSON request body must be an object.")
                    result = api_post(ONLINE_API, "/predict", json_body=payload)
                    st.success("Prediction completed.")
                    if isinstance(result, dict):
                        render_online_prediction_result(result)
                    else:
                        st.write(result)
                except json.JSONDecodeError as exc:
                    st.error(f"Invalid JSON: {exc}")
                except (APIError, ValueError) as exc:
                    render_api_error("Live prediction failed.", exc)


elif page == "Day Forecast":
    render_hero(
        "Day Forecast",
        "Choose an origin date. GridCast forecasts the following target day using the current historical ERA5 replay mode.",
        icon="📅",
    )

    if not offline_health:
        st.error(f"Offline API is not reachable at {OFFLINE_API}.")
    else:
        left, right = st.columns([1, 1.6])

        with left:
            default_origin = date.today() - timedelta(days=30)
            origin = st.date_input("Origin date", value=default_origin)
            target = origin + timedelta(days=1)

            st.markdown(
                f"""
                <div class="gc-card">
                    <div class="gc-muted">Target date</div>
                    <div style="font-size:1.35rem;font-weight:750;">{target.isoformat()}</div>
                    <div class="gc-muted" style="margin-top:.4rem;">Historical ERA5 weather replay</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            st.write("")
            run_clicked = st.button("Run day forecast", type="primary", use_container_width=True)

        with right:
            st.markdown("### What you will get")
            st.markdown(
                """
                - Hourly electricity-demand forecast
                - Peak and minimum demand
                - Daily energy and load factor
                - Ramp analysis
                - Weather-driver visualization
                - Downloadable HTML report
                - Downloadable Parquet forecast data
                """
            )

        if run_clicked:
            origin_iso = origin.isoformat()
            target_iso = target.isoformat()

            try:
                previous = get_latest_forecast_for_target(target_iso)
            except APIError:
                previous = None

            previous_id = (
                str(previous.get("forecast_id"))
                if previous and previous.get("forecast_id") else None
            )

            try:
                trigger = api_post(
                    OFFLINE_API,
                    "/forecast",
                    params={"origin_date": origin_iso},
                )

                st.info(
                    trigger.get("message", "Forecast request accepted.")
                    if isinstance(trigger, dict) else "Forecast request accepted."
                )

                with st.status("GridCast is processing the forecast...", expanded=True) as status:
                    st.write(f"Origin: `{origin_iso}`")
                    st.write(f"Target: `{target_iso}`")
                    st.write("Waiting for a new persisted forecast result...")

                    completed = wait_for_new_forecast(
                        origin_date=origin_iso,
                        target_date=target_iso,
                        previous_forecast_id=previous_id,
                    )

                    status.update(label="Forecast completed", state="complete", expanded=False)

                st.success(f"Forecast for {target_iso} is ready.")
                cached_forecasts.clear()
                render_forecast_detail(completed)

            except APIError as exc:
                render_api_error("Forecast did not complete.", exc)
                with st.expander("Diagnostic actions"):
                    st.markdown(
                        """
                        1. Check **System → Running Jobs**
                        2. Check **System → Recent Failures**
                        3. Do not repeatedly submit the same date if the trigger request itself timed out
                        """
                    )


elif page == "Forecast History":
    render_hero(
        "Forecast History",
        "Review previous target-day forecasts, inspect hourly behavior, and export reports or raw forecast data.",
        icon="🗂️",
    )

    try:
        forecasts = cached_forecasts()
    except APIError as exc:
        forecasts = []
        render_api_error("Could not retrieve forecast history.", exc)

    if not forecasts:
        st.info("No persisted forecasts are available.")
    else:
        df = normalized_forecast_rows(forecasts)

        display = df[[
            "target_date", "peak_load_mw", "peak_hour",
            "average_load_mw", "daily_energy_mwh", "load_factor", "generated_at",
        ]].copy()
        display.columns = [
            "Forecast Date", "Peak MW", "Peak Hour",
            "Average MW", "Energy MWh", "Load Factor", "Generated",
        ]
        st.dataframe(display, use_container_width=True, hide_index=True)

        st.divider()
        options = {forecast_label(row): row for row in forecasts}
        selected_label = st.selectbox("Open a forecast", list(options.keys()))
        selected = options[selected_label]

        try:
            selected_id = str(selected["forecast_id"])
            detail = api_get(OFFLINE_API, f"/forecasts/{selected_id}")
            if not isinstance(detail, dict):
                raise APIError("Forecast detail endpoint returned an unexpected response.")
            render_forecast_detail(detail)
        except (APIError, KeyError) as exc:
            render_api_error("Could not open the selected forecast.", exc)


elif page == "System":
    render_hero("System", "Operational visibility for the GridCast services.", icon="🛠️")

    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Online API")
        if online_health:
            st.success(f"Available at {ONLINE_API}")
            with st.expander("Health payload"):
                st.json(online_health)
        else:
            st.error(f"Unavailable at {ONLINE_API}")

    with c2:
        st.subheader("Offline API")
        if offline_health:
            st.success(f"Available at {OFFLINE_API}")
            with st.expander("Health payload"):
                st.json(offline_health)
        else:
            st.error(f"Unavailable at {OFFLINE_API}")

    st.divider()
    c1, c2 = st.columns(2)

    with c1:
        st.subheader("Running jobs")
        if offline_health:
            try:
                st.json(api_get(OFFLINE_API, "/running"))
            except APIError as exc:
                render_api_error("Could not retrieve running jobs.", exc)
        else:
            st.info("Offline API is unavailable.")

    with c2:
        st.subheader("Recent failures")
        if offline_health:
            try:
                st.json(api_get(OFFLINE_API, "/failures"))
            except APIError as exc:
                render_api_error("Could not retrieve failures.", exc)
        else:
            st.info("Offline API is unavailable.")

    st.divider()
    with st.expander("Technical configuration"):
        st.code(
            f"ONLINE_API_URL={ONLINE_API}\nOFFLINE_API_URL={OFFLINE_API}",
            language="text",
        )
        st.caption(
            "Model lineage remains available in backend persistence and MLflow. "
            "It is intentionally not shown in the normal Forecast History view."
        )
