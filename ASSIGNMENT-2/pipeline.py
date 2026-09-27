"""
NYC TLC Yellow Taxi - Zone Trip Duration Delay Analysis Pipeline
================================================================
Root entry point. Delegate to modular pipeline package (pipeline.cli).

Usage:
  python pipeline.py                          # default: June 2026
  python pipeline.py --year 2026 --month 7   # specify month
  python pipeline.py --skip-download          # reuse existing raw files
  python pipeline.py --help                  # full options
"""

from pipeline.cli import main, run_assertions
from pipeline.validate import validate
from pipeline.transform import enrich
from pipeline.metrics import calculate_metrics

__all__ = [
    "main",
    "run_assertions",
    "validate",
    "enrich",
    "calculate_metrics",
]

if __name__ == "__main__":
    main()
