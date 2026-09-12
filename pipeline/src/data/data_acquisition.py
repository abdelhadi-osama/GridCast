import logging
import sys
from pathlib import Path
from typing import Dict, List, Optional
import pandas as pd
import requests

# Add project root to sys.path so this script can be run directly from any directory


from config import DataAcquisitionConfig, config

logger = logging.getLogger(__name__)


class DataAcquisition:
    """Download ISO-NE Excel workbooks and convert them to optimized Parquet files."""

    def __init__(self, config: DataAcquisitionConfig):
        self.config = config

    def download_year(self, year: int) -> Path:
        """Download a single year workbook from ISO-NE into raw_dir."""
        if year not in self.config.year_urls:
            raise KeyError(f"No URL mapped for year {year} in configuration.")

        url = self.config.year_urls[year]
        ext = url.rsplit(".", 1)[-1]
        dest_path = self.config.raw_dir / f"{year}_smd_hourly.{ext}"

        if dest_path.exists() and dest_path.stat().st_size > 0:
            logger.info(f"[{year}] Cache hit: {dest_path.name} already exists.")
            return dest_path

        logger.info(f"[{year}] Downloading from {url}...")
        with requests.get(
            url,
            headers=self.config.headers,
            timeout=self.config.timeout,
            stream=True,
        ) as response:
            response.raise_for_status()
            with open(dest_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=self.config.chunk_size):
                    f.write(chunk)

        if dest_path.stat().st_size == 0:
            dest_path.unlink(missing_ok=True)
            raise IOError(f"Downloaded file for {year} is empty.")

        logger.info(
            f"[{year}] Saved to {dest_path.name} "
            f"({dest_path.stat().st_size / (1024 * 1024):.1f} MB)"
        )
        return dest_path

    def convert_to_parquet(self, raw_file_path: Path) -> Path:
        """Parse raw workbook sheet and persist as a columnar Parquet file."""
        parquet_path = self.config.preprocessed_dir / f"{raw_file_path.stem}.parquet"

        if parquet_path.exists() and parquet_path.stat().st_size > 0:
            logger.info(f"Parquet cache hit: {parquet_path.name} already exists.")
            return parquet_path

        logger.info(f"Converting {raw_file_path.name} to Parquet...")
        engine = "xlrd" if raw_file_path.suffix == ".xls" else "openpyxl"

        df = pd.read_excel(
            raw_file_path,
            sheet_name=self.config.sheet_name,
            header=self.config.header_row,
            usecols=self.config.columns_to_keep,
            engine=engine,
        )

        df.to_parquet(
            parquet_path,
            engine=self.config.parquet_engine,
            compression=self.config.parquet_compression,
            index=False,
        )

        logger.info(f"Saved {parquet_path.name} ({len(df):,} rows)")
        return parquet_path

    def validate_dataframe(self, df: pd.DataFrame) -> bool:
        """Validate loaded data conforms to expected columns and non-empty state."""
        missing = set(self.config.columns_to_keep) - set(df.columns)
        if missing:
            logger.error(f"Missing required columns: {missing}")
            return False

        if df.empty:
            logger.error("Dataframe is empty.")
            return False

        logger.info(
            f"Schema valid — {len(df.columns)} columns, {len(df):,} rows, "
            f"{df.isnull().sum().sum():,} total null values."
        )
        return True

    def load_years(self, years: List[int]) -> pd.DataFrame:
        """Download, convert, and load an aggregate DataFrame for requested years."""
        frames: List[pd.DataFrame] = []

        for year in years:
            raw_file = self.download_year(year)
            parquet_file = self.convert_to_parquet(raw_file)
            df_year = pd.read_parquet(parquet_file)

            if not self.validate_dataframe(df_year):
                raise ValueError(f"Validation failed for year {year}")

            frames.append(df_year)

        combined_df = pd.concat(frames, ignore_index=True)
        logger.info(f"Successfully assembled {len(combined_df):,} records for years {years}")
        return combined_df

    def run(self) -> pd.DataFrame:
        """Execute end-to-end ingestion across all years defined in config."""
        all_years = sorted(list(self.config.year_urls.keys()))
        return self.load_years(all_years)

'''
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    acq = DataAcquisition(config)
    df = acq.run()
    print(df.head())
'''    