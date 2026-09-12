#!/usr/bin/env python3
"""
main.py — Entry point for the Prefect-orchestrated GridCast Load Forecasting Pipeline

Usage:
  python main.py                                  # full run, defaults (tuning enabled)
  python main.py --no-tune                        # quick test without hyperparameter tuning
  python main.py --promote                        # full run + auto-promote best model to prod
  python main.py --experiment-name grid_v2        # custom MLflow experiment name

What happens when you run this:
  1. Imports and calls the @flow from flow.py
  2. Prefect creates a local FlowRun (stored in ~/.prefect/)
  3. Each @task inside the flow gets its own TaskRun with state tracking
  4. If you have the Prefect UI running (prefect server start), you can watch
     the pipeline execute in real time at http://127.0.0.1:4200
"""
import sys
import argparse
from pathlib import Path

# Ensure the project root is in the Python path so imports resolve correctly
sys.path.insert(0, str(Path(__file__).parent))

from flow import gridcast_pipeline


def parse_args():
    parser = argparse.ArgumentParser(
        description="GridCast Load Forecasting Pipeline — Prefect Orchestrated",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Quick test run (no tuning, no promotion)
  python main.py --no-tune

  # Full run with tuning
  python main.py --tune

  # Full run with auto-promotion to production
  python main.py --tune --promote

  # Custom experiment name in MLflow
  python main.py --tune --experiment-name gridcast_prod_v1

  # Start Prefect UI first, then run
  prefect server start &
  python main.py --tune


  #to use prefect ui in new terminal write : "where you venv exist and active"
   prefect server start 

 # open mlflow  From inside either pipeline folder
mlflow ui --backend-store-uri sqlite:///mlflow_gridcast.db --host 127.0.0.1 --port 5000
# Open http://127.0.0.1:5000
        """
    )

    parser.add_argument(
        '--tune', action='store_true', default=True,
        help='Enable hyperparameter tuning (default: True)'
    )
    parser.add_argument(
        '--no-tune', action='store_false', dest='tune',
        help='Disable hyperparameter tuning for faster execution'
    )
    parser.add_argument(
        '--promote', action='store_true', default=False,
        help='Auto-promote best model to Production (@champion) in MLflow (default: False)'
    )
    parser.add_argument(
        '--experiment-name', type=str, default=None,
        help='Override MLflow experiment name (default: from config)'
    )

    return parser.parse_args()


if __name__ == '__main__':
    args = parse_args()

    print("\n" + "=" * 70)
    print("⚡ GRIDCAST PIPELINE — PREFECT ORCHESTRATED")
    print("=" * 70)
    print(f"  tune        : {args.tune}")
    print(f"  promote     : {args.promote}")
    if args.experiment_name:
        print(f"  experiment  : {args.experiment_name}")
    print("=" * 70 + "\n")

    # Execute the Prefect flow
    result = gridcast_pipeline(
        tune=args.tune,
        promote_to_prod=args.promote,
        experiment_name=args.experiment_name
    )

       # ==========================================
    # FINAL PIPELINE EXECUTION RESULT
    # ==========================================
    print("\n" + "=" * 70)
    print("✅ PIPELINE EXECUTION RESULT")
    print("=" * 70)
    
    # 1. Model Metadata
    print(f"  {'Model Name':<15}: {result['model_name']}")
    print(f"  {'Run ID':<15}: {result['run_id']}")
    print(f"  {'Model Version':<15}: {result['model_version']}")
    
    # 2. Performance Metrics (Formatted for readability)
    print("-" * 70)
    print("  📊 TEST SET PERFORMANCE:")
    
    mape = result.get('test_mape')
    mae = result.get('test_mae')
    r2 = result.get('test_r2')

    if mape is not None:
        print(f"  {'Test MAPE':<15}: {mape:.2f} %")      # 2 decimal places
    if mae is not None:
        print(f"  {'Test MAE':<15}: {mae:.2f} MW")       # 2 decimal places
    if r2 is not None:
        print(f"  {'Test R²':<15}: {r2:.4f}")            # 4 decimal places
        
    # 3. Status
    print("-" * 70)
    print(f"  {'Status':<15}: {result['status'].upper()}")
    print("=" * 70 + "\n")