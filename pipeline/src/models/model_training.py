"""
src/models/model_training.py
Handles chronological model training, hyperparameter tuning, and MLflow tracking.
"""

import time
import logging
import numpy as np
from typing import Dict, Tuple
import mlflow
import mlflow.sklearn
from mlflow.models import infer_signature
from sklearn.model_selection import RandomizedSearchCV, TimeSeriesSplit
from sklearn.metrics import mean_squared_error, r2_score, mean_absolute_error, mean_absolute_percentage_error
from sklearn.pipeline import make_pipeline

logger = logging.getLogger(__name__)

import xgboost as xgb
from catboost import CatBoostRegressor
from sklearn.linear_model import Ridge, ElasticNet
from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor, VotingRegressor
from sklearn.preprocessing import PolynomialFeatures
from sklearn.pipeline import make_pipeline
from typing import Dict
from config.config import ModelConfig, MLflowConfig 
from mlflow import MlflowClient


def build_model_portfolio(config) -> Dict:
    """
    Build the grid load forecasting model portfolio.
    Exposed as a module-level function for parallel orchestration.
    """
    # Pre-instantiate models used in the ensemble to avoid repetition
    ridge_base = Ridge(random_state=config.random_state, alpha=config.ridge_alpha)
    rf_base = RandomForestRegressor(
        random_state=config.random_state, 
        n_jobs=config.n_jobs, 
        n_estimators=config.rf_n_estimators,
        max_depth=config.rf_max_depth,
        min_samples_split=config.rf_min_samples_split
    )
    xgb_base = xgb.XGBRegressor(
        random_state=config.random_state,
        n_jobs=config.n_jobs,
        n_estimators=config.xgb_n_estimators,
        learning_rate=config.xgb_learning_rate,
        max_depth=config.xgb_max_depth,
        objective='reg:squarederror'
    )

    models = {
        'Ridge Regression': ridge_base,
        'ElasticNet': ElasticNet(
            random_state=config.random_state, 
            alpha=config.elastic_alpha, 
            l1_ratio=config.elastic_l1_ratio
        ),
        'Polynomial Regression': make_pipeline(
            PolynomialFeatures(degree=2, include_bias=False),
            Ridge(alpha=config.ridge_alpha, random_state=config.random_state)
        ),
        'Random Forest': rf_base,
        'Gradient Boosting': GradientBoostingRegressor(
            random_state=config.random_state,
            n_estimators=config.gb_n_estimators,
            learning_rate=config.gb_learning_rate,
            max_depth=config.gb_max_depth
        ),
        'XGBoost': xgb_base,
        'CatBoost': CatBoostRegressor(
            random_state=config.random_state,
            iterations=config.cat_iterations,
            learning_rate=config.cat_learning_rate,
            depth=config.cat_depth,
            verbose=False
        )
    }

    # Add the Voting Ensemble using the pre-instantiated base models
    '''
    models['Voting Ensemble'] = VotingRegressor([
        ('ridge', ridge_base),
        ('rf', rf_base),
        ('xgb', xgb_base)
    ])
    '''
    if config.models_to_train:
        models = {k: v for k, v in models.items() if k in config.models_to_train}

    return models

class ModelTrainer:
    """Trains and evaluates models using strict chronological bounds."""

    def __init__(self, model_config: ModelConfig, mlflow_config: MLflowConfig, client: MlflowClient):
        self.model_config = model_config
        self.mlflow_config = mlflow_config
        self.client = client

    def train_single_model(
            self,
            model,
            X_train: np.ndarray,
            y_train: np.ndarray,
            X_val: np.ndarray,
            y_val: np.ndarray,
            model_name: str
        ) -> Tuple[Dict, object, str]:
            
            with mlflow.start_run(run_name=model_name) as run:
                logger.info(f"   Training {model_name}...")

                start_time = time.time()
                model.fit(X_train, y_train)
                training_time = time.time() - start_time

                y_train_pred = model.predict(X_train)
                y_val_pred = model.predict(X_val)

                metrics = {
                    'train_r2': r2_score(y_train, y_train_pred),
                    'val_r2': r2_score(y_val, y_val_pred),
                    'train_rmse': np.sqrt(mean_squared_error(y_train, y_train_pred)),
                    'val_rmse': np.sqrt(mean_squared_error(y_val, y_val_pred)),
                    'train_mae': mean_absolute_error(y_train, y_train_pred),
                    'val_mae': mean_absolute_error(y_val, y_val_pred),
                    'train_mape': mean_absolute_percentage_error(y_train, y_train_pred) * 100,
                    'val_mape': mean_absolute_percentage_error(y_val, y_val_pred) * 100,
                    'training_time': training_time,
                    'overfitting_gap': r2_score(y_train, y_train_pred) - r2_score(y_val, y_val_pred)
                }
                # 1. Parameter logging
                try:
                    params = model.get_params()
                    params = {k: str(v) if callable(v) else v for k, v in params.items()}
                    mlflow.log_params(params)
                except Exception as e:
                    logger.warning(f"   Could not log parameters: {str(e)}")

                # 2. Metric and metadata logging
                mlflow.log_metrics(metrics)
                mlflow.set_tag('model_family', model_name)
                mlflow.set_tag('data_leakage', 'none')
                mlflow.set_tag('validation', 'chronological_split')
                mlflow.set_tag('orchestrator', 'prefect')
                mlflow.log_param('train_samples', X_train.shape[0])
                mlflow.log_param('val_samples', X_val.shape[0])
                mlflow.log_param('features', X_train.shape[1])

                # 3. Model signature & serialization safety
                signature = infer_signature(X_train, y_train_pred)
                
                trusted_types = [
                      # Boosting & Tree Models
                    'xgboost.core.Booster',
                    'xgboost.sklearn.XGBRegressor',
                    'catboost.core.CatBoostRegressor',
                    
                    # Sklearn Internal Links
                    'sklearn._loss.link.IdentityLink',
                    'sklearn._loss.link.Interval', 
                    'sklearn._loss.loss.HalfSquaredError',
                    
                    # Pipeline & Ensemble Components
                    'sklearn.utils.Bunch',  # <-- CORRECTED PATH AND COMMA
                    'sklearn.ensemble._voting.VotingRegressor',
                    'sklearn.pipeline.Pipeline',
                    'sklearn.preprocessing._polynomial.PolynomialFeatures',
                    'sklearn.linear_model._ridge.Ridge',
                    'sklearn.ensemble._forest.RandomForestRegressor',
                    
                    # Numpy types
                    'numpy.ndarray',
                    'numpy.dtype'
                ]
                
                mlflow.sklearn.log_model(
                    sk_model=model,
                    name='model',
                    signature=signature,
                    registered_model_name=self.mlflow_config.model_name,
                    skops_trusted_types=trusted_types
                )

                logger.info(
                    f"   ✓ {model_name} — Val MAPE: {metrics['val_mape']:.2f}%, "
                    f"Val R²: {metrics['val_r2']:.4f}, Time: {training_time:.1f}s"
                )

                return metrics, model, run.info.run_id
            
    def tune_model(
        self,
        model_name: str,
        base_model,
        X_train: np.ndarray,
        y_train: np.ndarray,
        original_score: float
    ) -> Tuple[object, str, float]:
        """
        Tune top estimators using TimeSeriesSplit and RandomizedSearchCV.
        Evaluates models using negative MAPE to align with grid operator standards.
        """
        logger.info(f"🔧 Tuning {model_name}...")

        # Fetch grid directly from config
        param_grids = self.model_config.tuning_param_grids

        if model_name not in param_grids:
            logger.warning(f"   {model_name} not tunable, skipping")
            return base_model, None, original_score

        # Forward-moving time splits
        tscv = TimeSeriesSplit(n_splits=self.model_config.cv_folds)

        with mlflow.start_run(run_name=f"{model_name}_tuned") as run:
            search = RandomizedSearchCV(
                estimator=base_model,
                param_distributions=param_grids[model_name],
                n_iter=self.model_config.tuning_n_candidates,
                cv=tscv,
                scoring='neg_mean_absolute_percentage_error',
                n_jobs=self.model_config.n_jobs,
                random_state=self.model_config.random_state,
                verbose=0
            )

            start_time = time.time()
            search.fit(X_train, y_train)
            tuning_time = time.time() - start_time

            # Convert negative Scikit-Learn MAPE back to positive percentage
            best_cv_mape = -search.best_score_ * 100
            improvement = original_score - best_cv_mape  # Positive if error decreased

            mlflow.log_params(search.best_params_)
            mlflow.log_metrics({
                'best_cv_mape': best_cv_mape,
                'mape_improvement': improvement,
                'tuning_time_seconds': tuning_time
            })
            mlflow.set_tag('tuned', 'true')
            mlflow.set_tag('validation', 'timeseries_split')
            mlflow.set_tag('orchestrator', 'prefect')

            signature = infer_signature(X_train, search.predict(X_train))

            trusted_types = [
                # Boosting & Tree Models
                'xgboost.core.Booster',
                'xgboost.sklearn.XGBRegressor',
                'catboost.core.CatBoostRegressor',
                
                # Sklearn Internal Links (for Gradient Boosting)
                'sklearn._loss.link.IdentityLink',
                'sklearn._loss.link.Interval', 
                'sklearn._loss.loss.HalfSquaredError',
                
                # Voting Ensemble & Pipeline Components (Fixes the Bunch error)
                'sklearn.utils._bunch.Bunch',
                'sklearn.ensemble._voting.VotingRegressor',
                'sklearn.pipeline.Pipeline',
                'sklearn.preprocessing._polynomial.PolynomialFeatures',
                'sklearn.linear_model._ridge.Ridge',
                'sklearn.ensemble._forest.RandomForestRegressor',
                'sklearn.utils.Bunch' ,

                # Numpy arrays (sometimes flagged inside pipelines)
                'numpy.ndarray',
                'numpy.dtype'
            ]

            # Register if it beats the baseline by the configured threshold
            if improvement > 0.1:  # Register if at least 0.1% MAPE improvement
                mlflow.sklearn.log_model(
                    sk_model=search.best_estimator_,
                    name='tuned_model',
                    signature=signature,
                    registered_model_name=self.mlflow_config.model_name,
                    skops_trusted_types=trusted_types
                )
                logger.info(f"   ✓ Tuned {model_name} registered (MAPE Improvement: -{improvement:.2f}%)")
            else:
                mlflow.sklearn.log_model(
                    sk_model=search.best_estimator_,
                    name='tuned_model',
                    signature=signature,
                    skops_trusted_types=trusted_types
                )
                logger.info(f"   ✓ Tuned {model_name} logged (Improvement: {improvement:.2f}% below threshold)")

            logger.info(f"   Best CV MAPE: {best_cv_mape:.2f}%, Time: {tuning_time:.1f}s")
            return search.best_estimator_, run.info.run_id, best_cv_mape


    def evaluate_on_test(
        self, 
        model, 
        X_test: np.ndarray, 
        y_test: np.ndarray, 
        run_id: str
    ) -> Dict[str, float]:
        """
        Evaluate the champion model on the strictly held-out chronological test set.
        Appends final test metrics and production readiness tags to the MLflow run.
        """
        logger.info("🔬 Evaluating champion model on held-out test set...")

        y_test_pred = model.predict(X_test)

        test_metrics = {
            'test_r2': r2_score(y_test, y_test_pred),
            'test_rmse': np.sqrt(mean_squared_error(y_test, y_test_pred)),
            'test_mae': mean_absolute_error(y_test, y_test_pred),
            'test_mape': mean_absolute_percentage_error(y_test, y_test_pred) * 100
        }

        logger.info(f"   Test MAPE: {test_metrics['test_mape']:.2f}%")
        logger.info(f"   Test R²:   {test_metrics['test_r2']:.4f}")
        logger.info(f"   Test RMSE: {test_metrics['test_rmse']:.2f} MW")
        logger.info(f"   Test MAE:  {test_metrics['test_mae']:.2f} MW")

        with mlflow.start_run(run_id=run_id):
            mlflow.log_metrics(test_metrics)
            mlflow.set_tag('final_model', 'true')
            mlflow.set_tag('deployment_ready', 'true')

        return test_metrics