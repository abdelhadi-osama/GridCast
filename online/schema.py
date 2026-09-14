from pydantic import BaseModel, Field

class GridPredictionRequest(BaseModel):
    Date: str = Field(..., description="Date in YYYY-MM-DD format")
    Hr_End: int = Field(..., ge=1, le=24, description="Hour of the day ending (1-24)")
    Dry_Bulb: float = Field(..., description="Dry Bulb Temperature in Fahrenheit")
    Dew_Point: float = Field(..., description="Dew Point Temperature in Fahrenheit")

    model_config = {
        "json_schema_extra": {
            "example": {
                "Date": "2024-05-15",
                "Hr_End": 14,
                "Dry_Bulb": 72.5,
                "Dew_Point": 60.1
            }
        }
    }

class GridPredictionResponse(BaseModel):
    predicted_mw: float 
    model_version: str
    model_alias: str