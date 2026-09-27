#!/usr/bin/env python3
"""
FlashEats Dependable Pipeline Runner.
CLI entrypoint to run the end-to-end data pipeline for a specific logical run date.
"""
import argparse
import subprocess
import sys
import time
from pathlib import Path
import pandas as pd
import requests

# Ensure pipeline package is importable
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from pipeline.settings import PipelineConfig
from pipeline.logger import setup_pipeline_logger
from pipeline.ingest import extract_database_records, extract_csv_records, fetch_dispatch_orders_api
from pipeline.gate import run_validation_gate, ValidationError
from pipeline.cleanse import clean_and_normalize_data
from pipeline.model import build_order_journey_model, compute_pipeline_metrics
from pipeline.storage import persist_pipeline_outputs

def check_or_start_mock_api(config: PipelineConfig, logger) -> subprocess.Popen:
    """Verifies if the dispatch API service is responsive; starts it if not."""
    try:
        resp = requests.get(config.api_health_url, timeout=1.5)
        if resp.status_code == 200:
            logger.info("Dispatch API is already running and healthy.")
            return None
    except requests.RequestException:
        pass
        
    if not config.auto_start_mock_api:
        logger.warning("Mock API is offline and auto-start is disabled.")
        return None
        
    api_script = config.base_dir / "api" / "mock_dispatch_api.py"
    if not api_script.exists():
        logger.warning(f"Mock API script not found at {api_script}")
        return None
        
    logger.info("Starting local mock Dispatch API process...")
    proc = subprocess.Popen(
        [sys.executable, str(api_script)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    
    # Wait for service readiness
    for _ in range(10):
        time.sleep(0.5)
        try:
            r = requests.get(config.api_health_url, timeout=1.0)
            if r.status_code == 200:
                logger.info("Mock Dispatch API successfully started.")
                return proc
        except requests.RequestException:
            pass
            
    logger.warning("Mock Dispatch API started but healthcheck timed out.")
    return proc

def apply_chaos_mode(raw_tables: dict, chaos_mode: str, logger) -> dict:
    """Deliberately injects data defects to test validation firewall robustness."""
    logger.warning(f"!!! INJECTING CHAOS DEFECT: {chaos_mode} !!!")
    
    if chaos_mode == "missing_column":
        # Drop a critical column required by business SLA
        if "promised_eta" in raw_tables["orders"].columns:
            raw_tables["orders"] = raw_tables["orders"].drop(columns=["promised_eta"])
            logger.warning("Dropped required column 'promised_eta' from orders dataset.")
            
    elif chaos_mode == "stale_data":
        # Shift order created_at timestamps far into the past (e.g. 400 days old)
        created_dt = pd.to_datetime(raw_tables["orders"]["created_at"])
        stale_dt = created_dt - pd.Timedelta(days=400)
        raw_tables["orders"]["created_at"] = stale_dt.astype(str)
        logger.warning("Shifted order creation timestamps back by 400 days to violate freshness SLA.")
        
    elif chaos_mode == "duplicate_order":
        # Inject extra duplicate order rows
        dupe_sample = raw_tables["orders"].head(5).copy()
        raw_tables["orders"] = pd.concat([raw_tables["orders"], dupe_sample], ignore_index=True)
        logger.warning("Injected 5 extra duplicate rows into orders dataset.")
        
    else:
        logger.warning(f"Unrecognized chaos mode '{chaos_mode}'; skipping defect injection.")
        
    return raw_tables

def main():
    parser = argparse.ArgumentParser(description="FlashEats Dependable Order Pipeline")
    parser.add_argument("--run-date", default="2026-09-22", help="Logical run date in YYYY-MM-DD format")
    parser.add_argument("--chaos", default=None, choices=["missing_column", "stale_data", "duplicate_order"],
                        help="Chaos mode to test failure handling")
    parser.add_argument("--data-dir", default=None, help="Path to raw data directory")
    parser.add_argument("--output-dir", default=None, help="Path to write processed outputs")
    args = parser.parse_args()
    
    # 1. Setup Configuration & Logging
    config = PipelineConfig(
        run_date=args.run_date,
        data_dir=Path(args.data_dir).resolve() if args.data_dir else None,
        output_dir=Path(args.output_dir).resolve() if args.output_dir else None
    )
    logger = setup_pipeline_logger(config.log_dir, config.run_date)
    
    logger.info("=" * 60)
    logger.info(f"STARTING FLASHEATS PIPELINE RUN (run_date={config.run_date})")
    logger.info("=" * 60)
    
    mock_api_proc = None
    try:
        # Check/Start Mock API service
        mock_api_proc = check_or_start_mock_api(config, logger)
        
        # --------------------------------------------------------
        # STAGE 1: EXTRACT
        # --------------------------------------------------------
        logger.info(">>> STAGE 1: EXTRACT")
        db_tables = extract_database_records(config.db_path, logger)
        csv_tables = extract_csv_records(config.data_dir, logger)
        
        # Combine all extracted raw datasets
        raw_tables = {**db_tables, **csv_tables}
        
        # Ingest Dispatch API orders
        dispatch_records = fetch_dispatch_orders_api(
            api_url=config.api_url,
            raw_dir=config.raw_dispatch_dir,
            page_size=config.api_page_size,
            max_retries=config.max_retries,
            base_delay=config.retry_base_delay,
            logger=logger
        )
        
        # Apply intentional chaos if requested
        if args.chaos:
            raw_tables = apply_chaos_mode(raw_tables, args.chaos, logger)
            
        # --------------------------------------------------------
        # STAGE 2: VALIDATE
        # --------------------------------------------------------
        logger.info(">>> STAGE 2: VALIDATE")
        try:
            validation_report = run_validation_gate(
                orders_df=raw_tables["orders"],
                dispatch_records=dispatch_records,
                run_date_str=config.run_date,
                max_age_days=config.max_data_age_days,
                logger=logger
            )
        except ValidationError as val_err:
            logger.error("Pipeline stopped at validation gate. Critical data quality contract violated!")
            logger.error(f"Reason: {val_err}")
            logger.info("No processed output written. Halting execution with exit code 2.")
            sys.exit(2)
            
        # --------------------------------------------------------
        # STAGE 3: CLEAN
        # --------------------------------------------------------
        logger.info(">>> STAGE 3: CLEAN")
        cleaned_tables = clean_and_normalize_data(raw_tables, logger)
        
        # --------------------------------------------------------
        # STAGE 4: TRANSFORM
        # --------------------------------------------------------
        logger.info(">>> STAGE 4: TRANSFORM")
        journey_df = build_order_journey_model(cleaned_tables, logger)
        metrics_dict = compute_pipeline_metrics(journey_df, config.run_date, logger)
        
        # --------------------------------------------------------
        # STAGE 5: SAVE (ATOMIC PERSISTENCE)
        # --------------------------------------------------------
        logger.info(">>> STAGE 5: SAVE")
        saved_paths = persist_pipeline_outputs(
            order_journey_df=journey_df,
            metrics_dict=metrics_dict,
            validation_report_dict=validation_report,
            output_dir=config.output_dir,
            logger=logger
        )
        
        logger.info("=" * 60)
        logger.info("PIPELINE COMPLETED SUCCESSFULLY (Exit Code 0)")
        logger.info(f"Published order journey: {saved_paths['order_journey']}")
        logger.info(f"Published daily KPIs:    {saved_paths['metrics']}")
        logger.info("=" * 60)
        sys.exit(0)
        
    except Exception as exc:
        logger.exception(f"Unexpected pipeline execution error: {exc}")
        sys.exit(1)
        
    finally:
        if mock_api_proc:
            try:
                mock_api_proc.terminate()
            except:
                pass

if __name__ == "__main__":
    main()
