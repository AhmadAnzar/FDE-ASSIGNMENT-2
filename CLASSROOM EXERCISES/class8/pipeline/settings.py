"""
Pipeline configuration settings and environment handling.
"""
import os
from dataclasses import dataclass
from pathlib import Path

@dataclass
class PipelineConfig:
    # Execution dates & environment
    run_date: str = "2026-09-22"
    environment: str = "development"
    
    # Base paths
    base_dir: Path = Path(__file__).resolve().parent.parent
    data_dir: Path = None
    db_path: Path = None
    output_dir: Path = None
    log_dir: Path = None
    
    # Dispatch API settings
    api_url: str = os.getenv("DISPATCH_API_URL", "http://127.0.0.1:8000/dispatch/orders")
    api_health_url: str = os.getenv("DISPATCH_HEALTH_URL", "http://127.0.0.1:8000/health")
    max_retries: int = int(os.getenv("MAX_RETRIES", "3"))
    retry_base_delay: float = float(os.getenv("RETRY_BASE_DELAY", "1.0"))
    api_page_size: int = int(os.getenv("API_PAGE_SIZE", "50"))
    auto_start_mock_api: bool = os.getenv("AUTO_START_MOCK_API", "true").lower() == "true"
    
    # Validation thresholds
    max_data_age_days: int = int(os.getenv("MAX_DATA_AGE_DAYS", "60"))
    late_delay_threshold_min: float = float(os.getenv("LATE_DELAY_THRESHOLD_MIN", "0.0"))
    
    def __post_init__(self):
        if self.data_dir is None:
            self.data_dir = self.base_dir / "data"
        if self.db_path is None:
            self.db_path = self.base_dir / "database" / "flasheats.db"
        if self.output_dir is None:
            self.output_dir = self.base_dir / "data" / "processed" / f"run_date={self.run_date}"
        if self.log_dir is None:
            self.log_dir = self.base_dir / "logs"
            
        self.raw_dispatch_dir = self.base_dir / "data" / "raw" / "dispatch" / f"run_date={self.run_date}"
