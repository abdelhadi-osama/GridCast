import os
import pandas as pd
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException

from schema import GridPredictionRequest, GridPredictionResponse
from model_loader import load_model, get_state

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