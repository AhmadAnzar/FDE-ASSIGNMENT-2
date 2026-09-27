"""
Logging setup for dual console and file logging.
"""
import logging
import sys
from pathlib import Path

def setup_pipeline_logger(log_dir: Path, run_date: str) -> logging.Logger:
    """Configures structured pipeline logging to both console and a daily log file."""
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"pipeline_{run_date}.log"
    
    logger = logging.getLogger("flasheats_pipeline")
    logger.setLevel(logging.INFO)
    
    # Avoid duplicate handlers if re-initialized
    if logger.hasHandlers():
        logger.handlers.clear()
        
    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # File handler
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    return logger
