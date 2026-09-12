"""
src/data/data_preprocessing.py

Handles strict data cleaning: removes target leakage, fixes DST artifacts,
filters sensor glitches, and separates features from target.
NO feature engineering happens here.
"""

import logging
import sys
from pathlib import Path
from typing import Tuple, Dict

import numpy as np
import pandas as pd



from config.config import config, DataAcquisitionConfig

logger = logging.getLogger(__name__)


class DataPreprocessor:
    """Clean ISO-NE grid data and separate features from target."""

    def __init__(self, config: DataAcquisitionConfig):
        self.config = config
        self.initial_rows = 0
        self.final_rows = 0

    def clean_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Strict cleaning: purge leakage, fix DST, filter glitches, drop NaNs.
        """
        logger.info("🧹 Cleaning data...")
        self.initial_rows = len(df)
        df_clean = df.copy()

        # Step 1: Prevent Target Leakage (The Purge)
        logger.info("   🛡️ Removing target leakage columns...")
        cols_to_keep = self.config.columns_to_keep
        available = [c for c in cols_to_keep if c in df_clean.columns]
        df_clean = df_clean[available]
        dropped = len(df.columns) - len(available)
        logger.info(f"     Kept {len(available)} physical columns. Dropped {dropped} leakage columns.")

        # Step 2: Fix DST artifacts in Hr_End (The Fix)
        logger.info("   🕒 Cleaning Daylight Saving Time artifacts in 'Hr_End'...")
        df_clean["Hr_End"] = (
            df_clean["Hr_End"]
            .astype(str)
            .str.replace(r"\D", "", regex=True)
            .astype(int)
        )

        # Step 3: Filter unrealistic System_Load (The Reality Filter)
        logger.info("   🎯 Filtering unrealistic grid demands...")
        before = len(df_clean)
        mask = (
            (df_clean[self.config.target_col] >= self.config.min_demand_mw)
            & (df_clean[self.config.target_col] <= self.config.max_demand_mw)
        )
        df_clean = df_clean[mask]
        logger.info(
            f"     Removed {before - len(df_clean):,} rows outside "
            f"{self.config.min_demand_mw}–{self.config.max_demand_mw} MW"
        )

        # Step 4: Drop missing values
        logger.info("   🔍 Removing rows with missing values...")
        before = len(df_clean)
        df_clean = df_clean.dropna()
        logger.info(f"     Removed {before - len(df_clean):,} rows with NaN values")

        # Step 5: Reset index
        df_clean = df_clean.reset_index(drop=True)
        self.final_rows = len(df_clean)

        logger.info(
            f"✅ Cleaning complete: {self.final_rows:,} rows "
            f"({self.final_rows / self.initial_rows * 100:.1f}% retained)"
        )
        return df_clean

    def prepare_features_target(
        self, df: pd.DataFrame
    ) -> Tuple[pd.DataFrame, np.ndarray]:
        """Separate features (X) from target (y). No transformations here."""
        logger.info("🎯 Preparing features and target...")

        target = self.config.target_col
        feature_cols = [c for c in df.columns if c != target]

        X = df[feature_cols].copy()
        y = df[target].values

        logger.info(f"   Features: {X.shape[1]} columns, {len(X):,} rows")
        logger.info(f"   Target '{target}': min={y.min():.1f}, max={y.max():.1f}, "
                     f"mean={y.mean():.1f}, std={y.std():.1f}")
        return X, y

    def get_statistics(self) -> Dict[str, float]:
        """Return cleaning statistics for logging/model card."""
        return {
            "initial_rows": self.initial_rows,
            "final_rows": self.final_rows,
            "retention_pct": (
                self.final_rows / self.initial_rows * 100
                if self.initial_rows > 0
                else 0
            ),
        }

    def run(self, df: pd.DataFrame) -> Tuple[pd.DataFrame, np.ndarray]:
        """Execute full preprocessing: clean → features/target."""
        # We now receive the DataFrame directly instead of loading from disk
        df_clean = self.clean_data(df)
        return self.prepare_features_target(df_clean)
'''
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )
    
    # 1. Get the DataFrame directly from DataAcquisition
    from src.data.data_acquisition import DataAcquisition
    
    logger.info("🚀 Starting Data Acquisition...")
    acq = DataAcquisition(config)
    df_raw = acq.run()
    
    # 2. Pass the DataFrame directly to DataPreprocessor
    logger.info("🚀 Starting Data Preprocessing...")
    preprocessor = DataPreprocessor(config)
    X, y = preprocessor.run(df_raw)
    
    print("\nFeatures shape:", X.shape)
    print("Target shape:", y.shape)
    print("\nStats:", preprocessor.get_statistics())
    '''
