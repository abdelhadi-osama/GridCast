from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List , Any
import os

@dataclass
class DataAcquisitionConfig:
    """Configuration for ISO-NE data download, parsing, and Parquet conversion."""

    # 1. Project Anchor & Directory Paths
    # .parent gets the 'config' folder, the second .parent gets the project root
    base_dir: Path = field(default_factory=lambda: Path(__file__).resolve().parent.parent)
    raw_dir: Path = field(init=False)
    preprocessed_dir: Path = field(init=False)

    # 2. Network & Download Settings
    headers: Dict[str, str] = field(default_factory=lambda: {
        "User-Agent": "Mozilla/5.0 (GridCast MLOps Pipeline)"
    })
    timeout: int = 30
    chunk_size: int = 256 * 1024

    # 3. Excel Parsing & Parquet Settings
    sheet_name: str = "ISO NE CA"
    header_row: int = 0
    columns_to_keep: List[str] = field(default_factory=lambda: [
        "Date", "Hr_End", "Dry_Bulb", "Dew_Point", "System_Load"
    ])
    parquet_engine: str = "pyarrow"
    parquet_compression: str = "snappy"

    # 4. Target Variable
    target_col: str = "System_Load"
    
    # 5. Physical Grid Limits (Reality Filter for Sensor Glitches)
    # Grid demand in New England almost never drops below 5,000 MW, 
    # and the all-time record peak is ~28,130 MW.
    min_demand_mw: float = 5000.0
    max_demand_mw: float = 35000.0

# Feature Engineering Parameters
    country_code: str = "US"
    thermo_base_temp: float = 65.0


    # 6. URL Mapping
    year_urls: Dict[int, str] = field(default_factory=lambda: {
        2020: "https://www.iso-ne.com/static-assets/documents/2020/02/2020_smd_hourly.xlsx",
        2021: "https://www.iso-ne.com/static-assets/documents/2021/02/2021_smd_hourly.xlsx",
        2022: "https://www.iso-ne.com/static-assets/documents/2022/02/2022_smd_hourly.xlsx",
        2023: "https://www.iso-ne.com/static-assets/documents/2023/02/2023_smd_hourly.xlsx",
        2024: "https://www.iso-ne.com/static-assets/documents/100008/2024_smd_hourly.xlsx",
    })

    def __post_init__(self):
        """Resolve paths relative to project root and create directories."""
        self.raw_dir = self.base_dir / "data_iso" / "raw"
        self.preprocessed_dir = self.base_dir / "data_iso" / "preprocessed"

        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.preprocessed_dir.mkdir(parents=True, exist_ok=True)




@dataclass
class ModelConfig:
    """Model training and hyperparameter configuration."""
    random_state: int = 42
    test_size: float = 0.2
    val_size: float = 0.2
    cv_folds: int = 3  # Reduced for TimeSeriesSplit stability
    n_jobs: int = -1

    # Linear Baselines
    ridge_alpha: float = 10.0
    elastic_alpha: float = 1.0
    elastic_l1_ratio: float = 0.5

    # Random Forest
    rf_n_estimators: int = 100
    rf_max_depth: int = 20
    rf_min_samples_split: int = 10

    # Gradient Boosting
    gb_n_estimators: int = 100
    gb_learning_rate: float = 0.1
    gb_max_depth: int = 5

    # Advanced Boosting
    xgb_n_estimators: int = 300
    xgb_learning_rate: float = 0.05
    xgb_max_depth: int = 6

    cat_iterations: int = 300
    cat_learning_rate: float = 0.05
    cat_depth: int = 6

    # Tuning
    tuning_n_candidates: int = 10

    # hyperparameter search space definitions
    tuning_param_grids: Dict[str, Dict[str, List[Any]]] = field(default_factory=lambda: {
        'XGBoost': {
            'n_estimators': [200, 300, 400],
            'learning_rate': [0.01, 0.05, 0.1],
            'max_depth': [4, 5, 6],
            'subsample': [0.8, 0.9, 1.0],
            'colsample_bytree': [0.8, 0.9, 1.0],
            'min_child_weight': [1, 3, 5]
        },
        'CatBoost': {
            'iterations': [200, 300, 400],
            'learning_rate': [0.01, 0.05, 0.1],
            'depth': [4, 5, 6],
            'l2_leaf_reg': [1, 3, 5],
            'subsample': [0.8, 0.9, 1.0]
        },
        'Polynomial Regression': {
            'polynomialfeatures__degree': [1, 2, 3],
            'polynomialfeatures__interaction_only': [True, False],
            'ridge__alpha': [0.1, 1.0, 10.0, 50.0, 100.0]
        },
        'Random Forest': {
            'n_estimators': [100, 200, 300],
            'max_depth': [10, 15, 20, None],
            'min_samples_split': [2, 5, 10],
            'min_samples_leaf': [1, 2, 4],
            'max_features': ['sqrt', 'log2', 1.0]
        }
    })

    # Target models for the portfolio
    models_to_train: List[str] = field(default_factory=lambda: [
        'Ridge Regression', 'ElasticNet', 'Polynomial Regression',
        'Random Forest', 'Gradient Boosting', 'XGBoost', 
        'CatBoost', 'Voting Ensemble'
    ])


# Absolute path anchored to pipeline/
_PIPELINE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MLFLOW_DB_PATH = os.path.join(_PIPELINE_DIR, "mlflow_gridcast.db")
MLFLOW_TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", f"sqlite:///{_MLFLOW_DB_PATH}")

@dataclass
class MLflowConfig:
    """MLflow tracking and registry configuration.""" 
    experiment_name: str = "gridcast_load_forecasting"
    model_name: str = "grid_load_model"
    tracking_uri: str = MLFLOW_TRACKING_URI


@dataclass
class Config:
    """Main configuration container."""
    data: DataAcquisitionConfig = field(default_factory=DataAcquisitionConfig)
    model: ModelConfig = field(default_factory=ModelConfig)
    mlflow: MLflowConfig = field(default_factory=MLflowConfig)

# Global configuration instance
config = Config()

