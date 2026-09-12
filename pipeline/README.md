

***

```markdown
# ⚡ GridCast: ISO-NE Energy Demand Forecasting Pipeline

[![Python](https://img.shields.io/badge/Python-3.11+-blue?logo=python&logoColor=white)](https://www.python.org/)
[![MLflow](https://img.shields.io/badge/Tracked%20with-MLflow-blue?logo=mlflow)](https://mlflow.org/)
[![Prefect](https://img.shields.io/badge/Orchestrated%20with-Prefect-ff4c4c?logo=prefect)](https://www.prefect.io/)
[![XGBoost](https://img.shields.io/badge/Model-XGBoost-orange?logo=xgboost)](https://xgboost.ai/)

A production-ready, modular MLOps pipeline for forecasting hourly electricity demand in the ISO New England (ISO-NE) grid. Because large-scale energy storage is difficult, grid operators must predict hourly power demand precisely to match generation and prevent blackouts. 

This pipeline focuses on **strict chronological data handling**, **thermodynamic feature engineering**, and **automated model benchmarking** to deliver highly accurate, drift-resistant forecasting models.

---

## 🏗️ Architecture & Directory Structure

The pipeline is built using a strict separation of concerns, ensuring that data, features, and models are completely decoupled.

```text
pipeline/
├── config/                 # 🧠 Centralized configuration (Hyperparams, paths, limits)
│   ├── __init__.py
│   └── config.py
├── src/                    # 📦 Core pipeline modules
│   ├── data/               # 📥 Data Acquisition & Preprocessing
│   ├── features/           # ⚙️ Feature Engineering (Thermodynamics, Cyclic Time)
│   └── models/             # 🤖 Model Training & Registry
├── flow.py                 # 🔄 Prefect orchestration flow
├── main.py                 # 🚀 CLI entry point
├── data_iso/               # 🗄️ Local data storage (Raw & Processed Parquet)
├── mlruns/                 # 📊 MLflow local tracking database
└── mlflow_gridcast.db      # 📊 MLflow SQLite backend
```

---

## 🛠️ Setup & Installation

> **Note:** The Python environment is managed via `uv` in the **root directory** (`~/GridCast`), not inside the `pipeline` folder.

1. **Navigate to the root directory and sync the environment:**
   ```bash
   cd ~/GridCast
   uv sync
   ```

2. **Activate the virtual environment:**
   ```bash
   source .venv/bin/activate
   ```

3. **Navigate into the pipeline directory:**
   ```bash
   cd pipeline
   ```

---

## 🚀 How to Run the Pipeline

The pipeline is controlled via a clean Command Line Interface (CLI) using `main.py`. 

### Basic Usage
Run the full pipeline (Data Acquisition → Preprocessing → Training → Evaluation):
```bash
python main.py
```

### Advanced Options
| Command | Description |
| :--- | :--- |
| `python main.py --no-tune` | **Fast Mode:** Skips hyperparameter tuning. Uses baseline models. Great for quick testing. |
| `python main.py --promote` | **Production Mode:** Automatically promotes the winning model to the `@champion` alias in MLflow. |
| `python main.py --no-tune --promote` | Fast execution with automatic production promotion. |

---

## 🔄 Pipeline Stages

When you run `python main.py`, the pipeline executes the following stages sequentially:

| Stage | Module | Description |
| :---: | :--- | :--- |
| **1️⃣** | **Data Acquisition** | Downloads historical ISO-NE Excel files, handles network retries, and converts them into highly compressed, lightning-fast **Parquet** files. |
| **2️⃣** | **Data Preprocessing** | Filters out impossible sensor glitches (e.g., < 5000 MW), handles Daylight Saving Time string artifacts, and drops financial leakage columns. |
| **3️⃣** | **Feature Engineering** | Transforms raw dates and weather into machine-readable physics. Calculates Heating/Cooling Degree Hours, cyclic sine/cosine waves for time, and holiday flags. |
| **4️⃣** | **Model Training** | Benchmarks multiple architectures (XGBoost, CatBoost, Polynomial Regression, Random Forest) using strict `TimeSeriesSplit` cross-validation to prevent future data leakage. |
| **5️⃣** | **Evaluation & Packaging** | Calculates grid-specific metrics (MAPE, MAE), generates visual error distributions, and packages the champion model into a versioned, production-ready deployment bundle. |

---

## 📊 Experiment Tracking (MLflow)

All experiments, hyperparameters, and model artifacts are automatically tracked using MLflow. 

To view the MLflow UI and compare your models (e.g., XGBoost vs. CatBoost):
```bash
# Make sure you are in the ~/GridCast/pipeline directory
mlflow ui --port 5000
```
Then, open your browser and navigate to `http://localhost:5000`.

---

## 🧠 Key Engineering Decisions

- **Why Parquet over CSV/Excel?** Excel parsing is slow and memory-heavy. We convert raw data to Parquet once, reducing load times from minutes to milliseconds during iterative training.
- **Why TimeSeriesSplit?** Standard K-Fold cross-validation randomly shuffles data, causing 2024 data to leak into 2022 training folds. We use `TimeSeriesSplit` to strictly train on the past and test on the future.
- **Why Thermodynamic Features?** Electricity demand follows a "U-shape" based on temperature (high demand when freezing, low when mild, high when hot). We engineer Heating/Cooling Degree Hours to explicitly teach this physics to the models.

---

## 📄 License

This project is developed for educational and research purposes in advanced MLOps practices.
```

***

### How to use this:
1. Open your terminal.
2. Navigate to the pipeline folder: `cd ~/GridCast/pipeline`
3. Create or open the README file: `nano README.md` (or use VS Code: `code README.md`).
4. Paste the Markdown content above.
5. Save and push to GitHub!

Let me know if you want to tweak any sections or if you are ready to move on to writing the `data_preprocessing.py` file!