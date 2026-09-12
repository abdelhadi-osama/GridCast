"""
Prefect-orchestrated ISO-NE Grid Load Forecasting Pipeline.
"""

import os
import mlflow
import numpy as np
from typing import Optional
from prefect import flow, task, get_run_logger
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_percentage_error


# ─── Project Imports ──────────────────────────────────────────────────────────
from config.config import config  
from src.data.data_acquisition import DataAcquisition
from src.data.data_preprocessing import DataPreprocessor
from src.features.feature_engineering import build_preprocessor
from src.models.model_training import ModelTrainer, build_model_portfolio
from src.models.model_registry import ModelRegistry


# =============================================================================
# TASK 1 — Data Acquisition
# =============================================================================
@task(name="acquire-grid-data", retries=3, retry_delay_seconds=15)
def acquire_data(config):
    """
    Download ISO-NE Excel workbooks, convert to Parquet, and assemble the dataset.
    Retries handle transient network drops during large Excel downloads.
    """
    logger = get_run_logger()
    logger.info("📥 Step 1: Data Acquisition (ISO-NE Grid Data)")

    acquisition = DataAcquisition(config.data)
    df = acquisition.run()

    logger.info(f"✅ Loaded {len(df):,} chronological rows, {df.shape[1]} columns")
    return df


# =============================================================================
# TASK 2 — Data Preprocessing
# =============================================================================
@task(name="preprocess-grid-data")
def preprocess_data(df_raw, config):
    """
    Clean ISO-NE data: fix DST artifacts, filter unrealistic MW demands, 
    remove target leakage, and extract features/target.
    
    No retries: Preprocessing is deterministic. A failure implies data corruption 
    or configuration errors that must be manually addressed.
    """
    logger = get_run_logger()
    logger.info("🧹 Step 2: Data Preprocessing (Strict Grid Cleaning)")

    preprocessor = DataPreprocessor(config.data)
    X, y = preprocessor.run(df_raw)

    stats = preprocessor.get_statistics()
    logger.info(
        f"✅ {stats['final_rows']:,} rows retained "
        f"({stats['retention_pct']:.1f}% of {stats['initial_rows']:,})"
    )
    return X, y



# =============================================================================
# TASK 3 — Data Splitting
# =============================================================================
@task(name="split-grid-data")
def split_data(X, y, config):
    """
    Split data into train, validation, and test sets.
    STRICT CHRONOLOGICAL SPLITTING (shuffle=False) to prevent data leakage.
    """
    logger = get_run_logger()
    logger.info("✂️  Step 3: Data Splitting (Strict Chronological — No Leakage)")

    # 1. First split: separate test set (Chronological, NO SHUFFLING)
    X_temp, X_test, y_temp, y_test = train_test_split(
        X, y,
        test_size=config.model.test_size,
        shuffle=False  # 🚨 CRITICAL: Prevents future data from leaking into the past
    )
    
    # 2. Second split: separate validation from training (Chronological, NO SHUFFLING)
    X_train, X_val, y_train, y_val = train_test_split(
        X_temp, y_temp,
        test_size=config.model.val_size,
        shuffle=False
    )

    total = len(X)
    logger.info("✅ Chronological Data Split COMPLETE:")
    logger.info(f"   Train: {len(X_train):,} ({len(X_train)/total*100:.1f}%)")
    logger.info(f"   Val:   {len(X_val):,}   ({len(X_val)/total*100:.1f}%)")
    logger.info(f"   Test:  {len(X_test):,}  ({len(X_test)/total*100:.1f}%)")
    
    logger.info("🎯 Target statistics by split (Megawatts):")
    logger.info(f"   Train: mean={y_train.mean():.1f}, std={y_train.std():.1f}")
    logger.info(f"   Val:   mean={y_val.mean():.1f}, std={y_val.std():.1f}")
    logger.info(f"   Test:  mean={y_test.mean():.1f}, std={y_test.std():.1f}")

    return X_train, X_val, X_test, y_train, y_val, y_test


# =============================================================================
# TASK 4 — Feature Engineering
# =============================================================================
@task(name="engineer-grid-features")
def engineer_features(X_train, X_val, X_test, config):
    """
    Fit the thermodynamic and calendar feature pipeline on training data,
    then transform train, validation, and test sets.
    """
    logger = get_run_logger()
    logger.info("⚙️  Step 4: Feature Engineering (Thermodynamics & Calendar)")

    # Build the pipeline (reads country_code and base_temp directly from config)
    pipeline = build_preprocessor()

    # 🚨 CRITICAL: Fit on TRAINING data only to prevent leakage of future distributions
    pipeline.fit(X_train)

    # Transform all splits
    X_train_p = pipeline.transform(X_train)
    X_val_p   = pipeline.transform(X_val)
    X_test_p  = pipeline.transform(X_test)

    # Extract dynamic feature names from the custom transformer
    feature_names = pipeline.named_steps['feature_engineer'].get_feature_names()

    logger.info(f"✅ {len(feature_names)} engineered features generated")
    logger.info(f"   Train: {X_train_p.shape}, Val: {X_val_p.shape}, Test: {X_test_p.shape}")

    return X_train_p, X_val_p, X_test_p, feature_names, pipeline



# =============================================================================
# TASK 5a — Train a SINGLE model
# =============================================================================
@task(name="train-grid-model", retries=1, retry_delay_seconds=30)
def train_single_model(model_name, model, X_train, y_train, X_val, y_val, config):
    """
    Train one model and log telemetry to MLflow. 
    Retries handle transient memory spikes during tree building.
    """
    logger = get_run_logger()
    logger.info(f"🎯 Training: {model_name}")

    client = mlflow.MlflowClient()
    trainer = ModelTrainer(config.model, config.mlflow, client)

    metrics, trained_model, run_id = trainer.train_single_model(
        model, X_train, y_train, X_val, y_val, model_name
    )

    logger.info(
        f"   Val MAPE: {metrics['val_mape']:.2f}% | "
        f"Val R²: {metrics['val_r2']:.4f} | "
        f"Time: {metrics['training_time']:.1f}s"
    )

    return {
        "model_name": model_name,
        "model": trained_model,
        "metrics": metrics,
        "run_id": run_id
    }


# =============================================================================
# TASK 5b — Select the best model from training results
# =============================================================================
@task(name="select-best-grid-model")
def select_best_model(results: dict):
    """
    Pick the champion model based on validation MAPE (lowest is best).
    """
    logger = get_run_logger()

    # 🚨 CRITICAL METRIC SHIFT: Minimize MAPE instead of maximizing R²
    best_name = min(results, key=lambda k: results[k]["metrics"]["val_mape"])
    best = results[best_name]

    logger.info("📊 Model Comparison (Val MAPE):")
    # Sort ascending so the lowest error is at the top
    for name, r in sorted(results.items(), key=lambda x: x[1]["metrics"]["val_mape"]):
        marker = " ← BEST" if name == best_name else ""
        logger.info(f"   {name:<25} {r['metrics']['val_mape']:.2f}%{marker}")

    logger.info(
        f"\n🏆 Best: {best_name} | "
        f"Val MAPE: {best['metrics']['val_mape']:.2f}% | "
        f"Val R²: {best['metrics']['val_r2']:.4f}"
    )
    return best




# =============================================================================
# TASK 6 — Hyperparameter Tuning (optional)
# =============================================================================
@task(name="tune-grid-model")
def tune_model(best_result, X_train, y_train, X_val, y_val, config):
    """
    Tune the champion model using TimeSeriesSplit and RandomizedSearchCV.
    No retries: tuning is deterministic. Failures require parameter inspection.
    """
    logger = get_run_logger()

    model_name = best_result['model_name']
    
    # Identify tunable models directly from the config grid definition
    tunable = list(config.model.tuning_param_grids.keys())

    if model_name not in tunable:
        logger.info(f"⏭️  {model_name} is not tunable — skipping.")
        return None

    logger.info(f"🔧 Step 6: Tuning {model_name} (Chronological CV)")

    # 🚨 CRITICAL: Extract the original MAPE to benchmark tuning success
    original_mape = best_result['metrics']['val_mape']

    # Use a fresh (unfitted) base model for the search space
    fresh_portfolio = build_model_portfolio(config.model)
    base_model = fresh_portfolio[model_name]

    client = mlflow.MlflowClient()
    trainer = ModelTrainer(config.model, config.mlflow, client)

    tuned_model, tuned_run_id, best_cv_mape = trainer.tune_model(
        model_name, base_model, X_train, y_train, original_mape
    )

    # Validate the newly tuned model against the strictly held-out validation set
    y_val_pred = tuned_model.predict(X_val)
    
    tuned_val_mape = mean_absolute_percentage_error(y_val, y_val_pred) * 100

    # Positive improvement means error (MAPE) decreased
    improvement = original_mape - tuned_val_mape
    
    logger.info(f"   Original Val MAPE: {original_mape:.2f}%")
    logger.info(f"   Tuned Val MAPE:    {tuned_val_mape:.2f}%")
    logger.info(f"   Improvement:       {improvement:+.2f}%")

    if tuned_val_mape < original_mape:
        logger.info("✅ Tuned model is better — adopting tuned version for test evaluation")
        return {
            "model_name": model_name,
            "model": tuned_model,
            "run_id": tuned_run_id,
            "metrics": {**best_result["metrics"], "val_mape": tuned_val_mape}
        }
    else:
        logger.info("⚠️  Original baseline performs better on validation — keeping original")
        return None

    # =============================================================================
# TASK 7 — Test Set Evaluation
# =============================================================================
@task(name="evaluate-grid-model")
def evaluate_model(best_result, X_test, y_test, config):
    """
    Evaluate the final champion model on the strictly held-out test set.
    Executes exactly once after all training and tuning are complete.
    """
    logger = get_run_logger()
    logger.info("🔬 Step 7: Test Set Evaluation (Chronological Held-out Data)")

    client = mlflow.MlflowClient()
    trainer = ModelTrainer(config.model, config.mlflow, client)

    test_metrics = trainer.evaluate_on_test(
        best_result['model'], X_test, y_test, best_result['run_id']
    )

    logger.info(f"   Test MAPE: {test_metrics['test_mape']:.2f}%")
    logger.info(f"   Test R²:   {test_metrics['test_r2']:.4f}")
    logger.info(f"   Test RMSE: {test_metrics['test_rmse']:.2f} MW")
    logger.info(f"   Test MAE:  {test_metrics['test_mae']:.2f} MW")

    return test_metrics


# =============================================================================
# TASK 8 — Model Registry
# =============================================================================
@task(name="register-grid-model", retries=2, retry_delay_seconds=5)
def register_model(best_result, test_metrics, promote_to_prod, config, preprocessor=None, train_stats=None):
    """
    Register the champion model in MLflow using @challenger and @champion aliases.
    Retries handle transient SQLite/MLflow server connectivity drops.
    """
    logger = get_run_logger()
    logger.info("📦 Step 8: Model Registry (Alias Promotion)")

    registry = ModelRegistry(config.mlflow, mlflow.MlflowClient())

    # Update description to prioritize grid metrics
    description = (
        f"Champion Model: {best_result['model_name']} | "
        f"Test MAPE: {test_metrics['test_mape']:.2f}% | "
        f"Test R²: {test_metrics['test_r2']:.4f} | "
        f"Orchestrated by Prefect"
    )
    
    # Metadata tags for grid operator visibility
    tags = {
        'algorithm': best_result['model_name'],
        'test_mape': str(round(test_metrics['test_mape'], 2)),
        'test_r2': str(round(test_metrics['test_r2'], 4)),
        'data_leakage': 'none',
        'orchestrator': 'prefect',
        'data_source': 'iso-ne',
        'schema_version': 'thermo-calendar'
    }

    # Register as @challenger initially
    version = registry.transition_to_staging(best_result['run_id'], description, tags)

    # Promote to @champion if requested
    if version and promote_to_prod:
        registry.transition_to_production(version)
        logger.info(f"✅ Model v{version} promoted to @champion (Active Grid Inference)")
    elif version:
        logger.info(f"✅ Model v{version} registered as @challenger (Pending Review)")
    else:
        logger.warning("⚠️  Could not register model — check MLflow connection")

    # Re-log test metrics to the specific model version's run
    if version:
        v_run_id = mlflow.MlflowClient().get_model_version(
            config.mlflow.model_name, version
        ).run_id
        if v_run_id != best_result.get('run_id'):
            with mlflow.start_run(run_id=v_run_id):
                mlflow.log_metrics({
                    'test_mape': test_metrics['test_mape'],
                    'test_r2':   test_metrics['test_r2'],
                    'test_rmse': test_metrics['test_rmse'],
                    'test_mae':  test_metrics['test_mae'],
                })
                mlflow.set_tag('final_model', 'true')
                mlflow.set_tag('deployment_ready', 'true')
            logger.info(f"   ✓ Grid test metrics successfully linked to v{version} run")

    # Save the standalone fitted preprocessor for inference
    if version and preprocessor is not None:
        import pickle, tempfile
        from pathlib import Path as _Path
        tmp = _Path(tempfile.mkdtemp())
        pkl = tmp / "preprocessor.pkl"
        
        # Serialization matches the JSON-safe Scikit-Learn logic implemented previously
        with open(pkl, "wb") as f:
            pickle.dump(preprocessor, f)
            
        v_run_id = mlflow.MlflowClient().get_model_version(
            config.mlflow.model_name, version
        ).run_id
        
        with mlflow.start_run(run_id=v_run_id):
            mlflow.log_artifact(str(pkl), artifact_path="preprocessor")
        logger.info("✅ Thermodynamic preprocessor saved as MLflow artifact")

    # Save training target stats (Megawatts) for future drift detection
    if version and train_stats is not None:
        v_run_id = mlflow.MlflowClient().get_model_version(
            config.mlflow.model_name, version
        ).run_id
        with mlflow.start_run(run_id=v_run_id):
            mlflow.log_metrics({
                'train_mw_mean': train_stats['mean'],
                'train_mw_std':  train_stats['std'],
            })
        logger.info(f"✅ Training baseline saved — mean: {train_stats['mean']:.1f} MW, std: {train_stats['std']:.1f} MW")

    registry.print_registry_status()
    return version


# =============================================================================
# TASK 9 — Feature Importance Logging
# =============================================================================
@task(name="log-grid-feature-importance")
def log_feature_importance(best_result, feature_names, model_version, config):
    """
    Log tree model feature importances to the registered version's MLflow run.
    Safely skips linear models (like Ridge or Polynomial) which lack this attribute.
    """
    logger = get_run_logger()

    model = best_result['model']
    if not hasattr(model, 'feature_importances_'):
        logger.info(f"⏭️  {best_result['model_name']} has no feature_importances_ (e.g., linear model) — skipping")
        return

    if model_version is None:
        logger.warning("⚠️  No model version — skipping feature importance logging")
        return

    importances = model.feature_importances_
    importance_dict = dict(zip(feature_names, importances.tolist()))
    ranked = sorted(importance_dict.items(), key=lambda x: x[1], reverse=True)

    # Log to the registered version's run
    v_run_id = mlflow.MlflowClient().get_model_version(
        config.mlflow.model_name, model_version
    ).run_id

    with mlflow.start_run(run_id=v_run_id):
        mlflow.log_dict(importance_dict, 'feature_importance.json')
        for name, score in ranked[:10]:
            mlflow.log_metric(f'imp_{name}', score)

    logger.info(f"📊 Top 5 thermodynamic & calendar features ({best_result['model_name']}):")
    for name, score in ranked[:5]:
        logger.info(f"   {name:<30} {score:.4f}")

# =============================================================================
# FLOW — The main orchestrator
# =============================================================================
@flow(
    name="gridcast-load-forecasting-pipeline",
    description="ISO-NE Grid Load Forecasting — Prefect Orchestrated",
    log_prints=True
)
def gridcast_pipeline(
    tune: bool = True,
    promote_to_prod: bool = False,
    experiment_name: Optional[str] = None
):
    """
    End-to-end ML pipeline for grid load prediction.
    Executes sequentially through the modular GridCast architecture.
    """
    logger = get_run_logger()

    if experiment_name:
        config.mlflow.experiment_name = experiment_name

    # ── Configure MLflow ──────────────────────────────────────────────────────
    mlflow.set_tracking_uri(config.mlflow.tracking_uri)
    
    artifact_location = os.getenv("MLFLOW_ARTIFACT_LOCATION")
    if artifact_location:
        try:
            mlflow.create_experiment(config.mlflow.experiment_name, artifact_location=artifact_location)
        except Exception:
            pass
    mlflow.set_experiment(config.mlflow.experiment_name)

    logger.info("=" * 60)
    logger.info("⚡ GRIDCAST PIPELINE — PREFECT ORCHESTRATED")
    logger.info(f"  Years Configured : {list(config.data.year_urls.keys())}")
    logger.info(f"  Tune Models      : {tune}")
    logger.info(f"  Promote to Prod  : {promote_to_prod}")
    logger.info(f"  MLflow Experiment: {config.mlflow.experiment_name}")
    logger.info("=" * 60)

    # ── Step 1: Data Acquisition ──────────────────────────────────────────────
    df_raw = acquire_data(config)

    # ── Step 2: Preprocessing ─────────────────────────────────────────────────
    X, y = preprocess_data(df_raw, config)

    # ── Step 3: Split (Strict Chronological) ──────────────────────────────────
    X_train, X_val, X_test, y_train, y_val, y_test = split_data(X, y, config)

    # ── Step 4: Feature Engineering ───────────────────────────────────────────
    X_train_p, X_val_p, X_test_p, feature_names, pipeline = engineer_features(
        X_train, X_val, X_test, config
    )

    # ── Step 5: Train Model Portfolio ─────────────────────────────────────────
    model_portfolio = build_model_portfolio(config.model)
    training_results = {}

    for model_name, model in model_portfolio.items():
        result = train_single_model(
            model_name, model,
            X_train_p, y_train,
            X_val_p, y_val,
            config
        )
        training_results[model_name] = result

    best_result = select_best_model(training_results)

    # ── Step 6: Hyperparameter Tuning (optional) ──────────────────────────────
    if tune:
        tuned = tune_model(best_result, X_train_p, y_train, X_val_p, y_val, config)
        if tuned is not None:
            best_result = tuned
    else:
        logger.info("⏭️  Step 6: Tuning skipped (--no-tune)")

    # ── Step 7: Evaluate on test set ──────────────────────────────────────────
    test_metrics = evaluate_model(best_result, X_test_p, y_test, config)

    # ── Step 8: Register in MLflow ────────────────────────────────────────────
    train_stats = {'mean': float(np.mean(y_train)), 'std': float(np.std(y_train))}
    model_version = register_model(
        best_result, test_metrics, promote_to_prod, config, pipeline, train_stats
    )

    # ── Step 9: Feature importance ────────────────────────────────────────────
    log_feature_importance(best_result, feature_names, model_version, config)

    # ── Summary ───────────────────────────────────────────────────────────────
    logger.info("")
    logger.info("=" * 60)
    logger.info("✅ PIPELINE COMPLETE")
    logger.info("=" * 60)
    logger.info(f"  Champion Model: {best_result['model_name']}")
    logger.info(f"  Test MAPE     : {test_metrics['test_mape']:.2f}%")
    logger.info(f"  Test RMSE     : {test_metrics['test_rmse']:.2f} MW")
    logger.info(f"  Model version : {model_version}")
    alias = 'champion' if promote_to_prod else 'challenger'
    logger.info(f"  Active Alias  : @{alias}")
    logger.info(f"\n  Load model for downstream inference:")
    logger.info(f"  mlflow.sklearn.load_model('models:/{config.mlflow.model_name}@{alias}')")
    logger.info("=" * 60)

    return {
        "model_name": best_result['model_name'],
        "run_id": best_result['run_id'],
        "model_version": model_version,
        "test_mape": test_metrics['test_mape'],
        "test_mae": test_metrics['test_mae'],
        "test_r2": test_metrics['test_r2'],
        "status": "success"
    }

