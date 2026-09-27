"""
Storage module: handles atomic file writes to date-partitioned directories.
"""
import json
import logging
import os
from pathlib import Path
from typing import Dict, Any
import pandas as pd

def atomic_save_csv(df: pd.DataFrame, target_path: Path, logger: logging.Logger = None) -> Path:
    """
    Writes DataFrame to a temporary file first, then atomically renames it.
    Prevents readers from ever observing a partially written file.
    """
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = target_path.with_suffix(".csv.tmp")
    
    try:
        df.to_csv(temp_path, index=False, encoding="utf-8")
        os.replace(temp_path, target_path)
        if logger:
            logger.info(f"Atomically saved CSV to {target_path} ({len(df)} rows)")
        return target_path
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except:
                pass

def save_json_file(data: Dict[str, Any], target_path: Path, logger: logging.Logger = None) -> Path:
    """Writes formatted JSON dictionary to target file."""
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = target_path.with_suffix(".json.tmp")
    
    try:
        temp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(temp_path, target_path)
        if logger:
            logger.info(f"Atomically saved JSON to {target_path}")
        return target_path
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except:
                pass

def persist_pipeline_outputs(
    order_journey_df: pd.DataFrame,
    metrics_dict: Dict[str, Any],
    validation_report_dict: Dict[str, Any],
    output_dir: Path,
    logger: logging.Logger = None
) -> Dict[str, Path]:
    """Persists all final pipeline outputs into the partitioned output directory."""
    journey_file = output_dir / "order_journey.csv"
    metrics_file = output_dir / "metrics.json"
    validation_file = output_dir / "validation_report.json"
    
    atomic_save_csv(order_journey_df, journey_file, logger=logger)
    save_json_file(metrics_dict, metrics_file, logger=logger)
    save_json_file(validation_report_dict, validation_file, logger=logger)
    
    return {
        "order_journey": journey_file,
        "metrics": metrics_file,
        "validation_report": validation_file
    }
