"""
src/features/feature_engineering.py
Generates physics-based and temporal features for grid load forecasting.
"""

import logging
import numpy as np
import pandas as pd
import holidays
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.preprocessing import RobustScaler
from sklearn.pipeline import Pipeline

logger = logging.getLogger(__name__)

class ISONETimeFeatureEngineer(BaseEstimator, TransformerMixin):
    """
    Creates temporal and thermodynamic features.
    Relies entirely on strict chronology to prevent data leakage.
    """
    def __init__(self, country_code: str = "US" , base_temp: float =  65.0):
        self.country_code = country_code
        self.base_temp = base_temp
        self.feature_names_ = []
    
    def fit(self, X, y=None):
        return self
    
    def transform(self, X):
        X_df = X.copy()
        
        # Ensure the index is a DatetimeIndex for chronological integrity
        #if not isinstance(X_df.index, pd.DatetimeIndex):
         #   raise ValueError("DataFrame index must be a DatetimeIndex for feature engineering.")
        X_df['Date'] = pd.to_datetime(X_df['Date'])
        # ========== 1. CALENDAR & HUMAN BEHAVIOR ==========
        #X_df['Month'] = X_df['Date'].dt.month
        X_df['Month'] = X_df['Date'].dt.month
        #X_df['DayOfWeek'] = X_df.index.dayofweek
        X_df['DayOfWeek'] = X_df['Date'].dt.dayofweek
        X_df['Is_Weekend'] = (X_df['DayOfWeek'] >= 5).astype(int)
        #X_df['Hour'] = X_df.index.hour
        X_df['Hour'] = X_df['Hr_End'].astype(int)

       
        #----------------------------------------------
        # Dynamic Holidays
        #dataset_years = X_df.index.year.unique().tolist()
        dataset_years = X_df['Date'].dt.year.unique().tolist()

        regional_holidays = holidays.country_holidays(self.country_code, years=dataset_years)
        #X_df['Is_Holiday'] = X_df.index.date.map(lambda x: x in regional_holidays).astype(int)
        X_df['Is_Holiday'] = X_df['Date'].dt.date.isin(regional_holidays).astype(int)

        # ========== 2. CYCLIC TIME ENCODING ==========
        X_df['Hour_Sin'] = np.sin(2 * np.pi * X_df['Hour'] / 24)
        X_df['Hour_Cos'] = np.cos(2 * np.pi * X_df['Hour'] / 24)
        
        X_df['Month_Sin'] = np.sin(2 * np.pi * X_df['Month'] / 12)
        X_df['Month_Cos'] = np.cos(2 * np.pi * X_df['Month'] / 12)
        
        # ========== 3. THERMODYNAMICS ==========
        X_df['CDH'] = np.maximum(0, X_df['Dry_Bulb'] - self.base_temp)
        X_df['HDH'] = np.maximum(0, self.base_temp - X_df['Dry_Bulb'])
        X_df['Temp_Squared'] = X_df['Dry_Bulb'] ** 2
        
        # Feels Like (Apparent Temperature)
        X_df['Feels_Like'] = -42.379 + (2.04901523 * X_df['Dry_Bulb']) + \
                             (10.14333127 * X_df['Dew_Point']) - \
                             (0.22475541 * X_df['Dry_Bulb'] * X_df['Dew_Point'])
        
        # ========== CLEANUP ==========
        # Drop transitional calendar columns to prevent multicollinearity
        cols_to_drop = ['Month', 'DayOfWeek', 'Hour', 'Date', 'Hr_End']
        X_df = X_df.drop(columns=[c for c in cols_to_drop if c in X_df.columns], errors='ignore')
        
        numeric_cols = X_df.select_dtypes(include=[np.number]).columns.tolist()
        self.feature_names_ = numeric_cols
        
        return X_df[numeric_cols].values

    def get_feature_names(self):
        return self.feature_names_


def build_preprocessor() -> Pipeline:
    """
    Builds the Scikit-Learn pipeline. 
    Omits outlier clipping to protect peak grid load signals.
    """
    return Pipeline([
        ('feature_engineer', ISONETimeFeatureEngineer(
            country_code= "US", 
            base_temp=65.0
        )),
        ('scaler', RobustScaler()),
    ])
