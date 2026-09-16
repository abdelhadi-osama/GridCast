import os
import pandas as pd
from contextlib import asynccontextmanager
from fastapi import (
    FastAPI,
    HTTPException,
    Request,
    Response,
)
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

from schema import GridPredictionRequest, GridPredictionResponse
from model_loader import load_model, get_state
import time
# ---------------------------------------------------------------------------
# Prometheus metrics
# ---------------------------------------------------------------------------

HTTP_REQUESTS_TOTAL = Counter(
    "gridcast_http_requests_total",
    "Total number of GridCast HTTP requests.",
    [
        "service",
        "method",
        "endpoint",
        "status",
    ],
)

HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "gridcast_http_request_duration_seconds",
    "GridCast HTTP request duration in seconds.",
    [
        "service",
        "method",
        "endpoint",
    ],
)

ACTIVE_REQUESTS = Gauge(
    "gridcast_active_requests",
    "Number of active GridCast HTTP requests.",
    [
        "service",
    ],
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    load_model()
    yield

app = FastAPI(
    title="GridCast Load Forecasting API",
    description="Predict single-hour electricity demand (MW) for ISO New England",
    version="1.0.0",
    lifespan=lifespan,
    root_path=os.getenv("ROOT_PATH", ""),  
)

# ---------------------------------------------------------------------------
# Prometheus HTTP instrumentation
# ---------------------------------------------------------------------------

@app.middleware("http")
async def prometheus_middleware(
    request: Request,
    call_next,
):
    """
    Track request count, request latency,
    status code, and active requests.
    """

    # Do not count Prometheus scraping itself
    # as application traffic.
    if request.url.path.endswith("/metrics"):
        return await call_next(request)

    service = "online"
    method = request.method

    ACTIVE_REQUESTS.labels(
        service=service,
    ).inc()

    start_time = time.perf_counter()
    status_code = 500

    try:
        response = await call_next(request)

        status_code = response.status_code

        return response

    finally:
        duration = (
            time.perf_counter()
            - start_time
        )

        route = request.scope.get(
            "route"
        )

        if route is not None:
            endpoint = route.path
        else:
            endpoint = "unmatched"

        HTTP_REQUESTS_TOTAL.labels(
            service=service,
            method=method,
            endpoint=endpoint,
            status=str(status_code),
        ).inc()

        HTTP_REQUEST_DURATION_SECONDS.labels(
            service=service,
            method=method,
            endpoint=endpoint,
        ).observe(duration)

        ACTIVE_REQUESTS.labels(
            service=service,
        ).dec()

# ---------------------------------------------------------------------------
# Prometheus endpoint
# ---------------------------------------------------------------------------

@app.get(
    "/metrics",
    include_in_schema=False,
)
def metrics():
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )

@app.get("/health")
def health():
    s = get_state()
    return {"status": "ok", "model_version": s.version, "model_alias": s.alias}

@app.post("/predict", response_model=GridPredictionResponse)
def predict(request: GridPredictionRequest):
    s = get_state()
    if s.model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")

    # 1. Convert the JSON payload into a 1-row Pandas DataFrame
    df = pd.DataFrame([request.model_dump()])
    
    # 2. Enforce the DatetimeIndex required by ISONETimeFeatureEngineer
    df.index = pd.to_datetime(df['Date'])
    
    # 3. Apply thermodynamic and cyclic calendar transformations
    X = s.preprocessor.transform(df)
    
    # 4. Generate the single Megawatt prediction
    demand_mw = float(s.model.predict(X)[0])

    return GridPredictionResponse(
        predicted_mw=round(demand_mw, 2),
        model_version=s.version,
        model_alias=s.alias,
    )