"""
Shared production model loader for GridCast inference.

Used by both:
- online inference (FastAPI)  >>we will do it now online inference use his own file 
- offline/batch inference

The loader resolves the current MLflow model alias, loads the registered
production model and its fitted preprocessor, and exposes model lineage
metadata such as model version and MLflow run ID.

MLFLOW_ARTIFACTS_ROOT is used to remap absolute host artifact paths to
container paths when the pipeline runs locally and MLflow stores absolute
host paths in its SQLite backend.
"""

import os
import sys
import pickle
import sqlite3
import tempfile
from pathlib import Path

import mlflow
import mlflow.sklearn
from mlflow import MlflowClient


# ── Path setup ────────────────────────────────────────────────────────────────
_MODULE_DIR = Path(__file__).parent.parent
_PIPELINE_DIR = _MODULE_DIR / "pipeline"

# Required so MLflow/pickle can resolve GridCast modules when loading artifacts.
sys.path.insert(0, str(_MODULE_DIR))
sys.path.insert(0, str(_PIPELINE_DIR))


# ── Config ────────────────────────────────────────────────────────────────────
MLFLOW_TRACKING_URI = os.getenv(
    "MLFLOW_TRACKING_URI",
    f"sqlite:///{_PIPELINE_DIR / 'mlflow_gridcast.db'}",
)

MODEL_NAME = os.getenv("MODEL_NAME", "grid_load_model")
MODEL_ALIAS = os.getenv("MODEL_ALIAS", "champion")

# Optional remapping for Docker/container environments.
_ARTIFACTS_ROOT = os.getenv("MLFLOW_ARTIFACTS_ROOT")


# ── MLflow path helpers ───────────────────────────────────────────────────────
def _remap(path: str) -> str:
    """
    Remap a host-side MLflow artifact path to the container-mounted
    artifact root when MLFLOW_ARTIFACTS_ROOT is configured.
    """
    if not _ARTIFACTS_ROOT or not path:
        return path

    idx = path.find("/mlruns/")
    return _ARTIFACTS_ROOT + path[idx:] if idx >= 0 else path


def _get_storage_location(version: str) -> str | None:
    """
    Read the registered model storage location directly from the local
    MLflow SQLite backend.

    Used only for the host-path-remapping deployment case.
    """
    db_path = MLFLOW_TRACKING_URI.replace("sqlite:///", "")

    conn = sqlite3.connect(db_path)

    try:
        row = conn.execute(
            """
            SELECT storage_location
            FROM model_versions
            WHERE name=? AND version=?
            """,
            (MODEL_NAME, version),
        ).fetchone()
    finally:
        conn.close()

    return row[0] if row else None


def _get_artifact_uri(run_id: str) -> str | None:
    """
    Read the MLflow run artifact URI directly from the local SQLite backend.

    Used only for the host-path-remapping deployment case.
    """
    db_path = MLFLOW_TRACKING_URI.replace("sqlite:///", "")

    conn = sqlite3.connect(db_path)

    try:
        row = conn.execute(
            """
            SELECT artifact_uri
            FROM runs
            WHERE run_uuid=?
            """,
            (run_id,),
        ).fetchone()
    finally:
        conn.close()

    return row[0] if row else None


# ── Shared production model state ─────────────────────────────────────────────
class _State:
    model = None
    preprocessor = None

    version: str = "unknown"
    alias: str = MODEL_ALIAS
    run_id: str = "unknown"


_state = _State()


# ── Public loader ─────────────────────────────────────────────────────────────
def load_model() -> _State:
    """
    Resolve and load the current production model from MLflow.

    Loads:
    - registered model referenced by MODEL_ALIAS
    - fitted training preprocessor
    - model version
    - MLflow run ID

    Returns
    -------
    _State
        Shared production inference state.

    Notes
    -----
    Online serving can load this once during API startup.

    Offline inference can load this once when the batch job starts.
    """
    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)

    client = MlflowClient()

    # Resolve the production alias at runtime.
    mv = client.get_model_version_by_alias(
        MODEL_NAME,
        MODEL_ALIAS,
    )

    # Preserve model lineage.
    _state.version = f"v{mv.version}"
    _state.alias = MODEL_ALIAS
    _state.run_id = mv.run_id

    # ── Load estimator ────────────────────────────────────────────────────────
    if _ARTIFACTS_ROOT and mv.source:
        storage_location = _get_storage_location(mv.version)

        if not storage_location:
            raise RuntimeError(
                f"Storage location not found for "
                f"{MODEL_NAME} version {mv.version}."
            )

        model_path = _remap(storage_location)

        _state.model = mlflow.sklearn.load_model(model_path)

    else:
        _state.model = mlflow.sklearn.load_model(
            f"models:/{MODEL_NAME}@{MODEL_ALIAS}"
        )

    # ── Load fitted preprocessor ──────────────────────────────────────────────
    try:
        if _ARTIFACTS_ROOT:
            artifact_uri = _get_artifact_uri(mv.run_id)

            if not artifact_uri:
                raise RuntimeError(
                    f"Artifact URI not found for MLflow run {mv.run_id}."
                )

            preprocessor_path = (
                Path(_remap(artifact_uri))
                / "preprocessor"
                / "preprocessor.pkl"
            )

            with open(preprocessor_path, "rb") as f:
                _state.preprocessor = pickle.load(f)

        else:
            with tempfile.TemporaryDirectory() as dst:
                artifact_path = mlflow.artifacts.download_artifacts(
                    run_id=mv.run_id,
                    artifact_path="preprocessor/preprocessor.pkl",
                    dst_path=dst,
                )

                with open(artifact_path, "rb") as f:
                    _state.preprocessor = pickle.load(f)

    except Exception as exc:
        raise RuntimeError(
            f"Preprocessor not found in MLflow run {mv.run_id[:8]}. "
            "Re-run the pipeline with --promote to register a model "
            "that includes the fitted preprocessor."
        ) from exc

    return _state


def get_state() -> _State:
    """
    Return the currently loaded production model state.

    load_model() must be called before this function.
    """
    if _state.model is None or _state.preprocessor is None:
        raise RuntimeError(
            "Production model has not been loaded. "
            "Call load_model() before get_state()."
        )

    return _state