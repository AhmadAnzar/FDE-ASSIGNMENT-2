"""
Data extraction from SQLite, flat CSV files, and paginated Dispatch REST API.
"""
import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Dict, Any, List
import pandas as pd
import requests

class NonRetryableAPIError(Exception):
    """Raised when an API error is permanent (e.g. 404, 401) and should not be retried."""
    pass

class APIExtractionError(Exception):
    """Raised when API extraction fails after all retry attempts."""
    pass

def extract_database_records(db_path: Path, logger: logging.Logger) -> Dict[str, pd.DataFrame]:
    """Reads core transactional tables from SQLite database."""
    logger.info(f"Connecting to SQLite database at {db_path.name}")
    if not db_path.exists():
        raise FileNotFoundError(f"Database file not found: {db_path}")
        
    with sqlite3.connect(db_path) as con:
        orders = pd.read_sql("SELECT * FROM orders", con)
        restaurants = pd.read_sql("SELECT * FROM restaurants", con)
        drivers = pd.read_sql("SELECT * FROM drivers", con)
        
    logger.info(f"Extracted {len(orders)} orders, {len(restaurants)} restaurants, {len(drivers)} drivers")
    return {
        "orders": orders,
        "restaurants": restaurants,
        "drivers": drivers
    }

def extract_csv_records(data_dir: Path, logger: logging.Logger) -> Dict[str, pd.DataFrame]:
    """Reads contextual CSV datasets."""
    logger.info(f"Loading CSV files from {data_dir.name}")
    
    actions = pd.read_csv(data_dir / "customer_app_actions.csv")
    interventions = pd.read_csv(data_dir / "order_interventions.csv")
    tickets = pd.read_csv(data_dir / "support_tickets.csv")
    
    # Outcomes is optional if already in data
    outcomes_path = data_dir / "order_outcomes.csv"
    outcomes = pd.read_csv(outcomes_path) if outcomes_path.exists() else None
    
    logger.info(f"Extracted {len(actions)} actions, {len(interventions)} interventions, {len(tickets)} support tickets")
    return {
        "actions": actions,
        "interventions": interventions,
        "tickets": tickets,
        "outcomes": outcomes
    }

def fetch_dispatch_orders_api(
    api_url: str,
    raw_dir: Path,
    page_size: int = 50,
    max_retries: int = 3,
    base_delay: float = 1.0,
    logger: logging.Logger = None
) -> List[Dict[str, Any]]:
    """
    Fetches paginated orders from Dispatch REST API.
    Handles retry for transient HTTP 500 and rate-limit HTTP 429.
    Saves each raw response page to raw_dir.
    """
    raw_dir.mkdir(parents=True, exist_ok=True)
    records = []
    page = 1
    total_expected = None
    
    if logger:
        logger.info(f"Beginning paginated extraction from {api_url} (page_size={page_size})")
        
    while True:
        success = False
        payload = None
        
        for attempt in range(1, max_retries + 1):
            try:
                resp = requests.get(api_url, params={"page": page, "page_size": page_size}, timeout=10)
                
                # Check for rate limiting
                if resp.status_code == 429:
                    retry_after = float(resp.headers.get("Retry-After", 1.0))
                    try:
                        err_json = resp.json()
                        retry_after = float(err_json.get("retry_after_seconds", retry_after))
                    except:
                        pass
                    if logger:
                        logger.warning(f"Page {page}: HTTP 429 Rate Limited. Sleeping {retry_after}s before retry (attempt {attempt}/{max_retries})")
                    time.sleep(retry_after)
                    continue
                    
                # Check for transient server failure
                if resp.status_code in [500, 502, 503, 504]:
                    delay = base_delay * (2 ** (attempt - 1))
                    if logger:
                        logger.warning(f"Page {page}: HTTP {resp.status_code} server error. Backing off {delay}s (attempt {attempt}/{max_retries})")
                    time.sleep(delay)
                    continue
                    
                # Check for permanent 4xx errors
                if 400 <= resp.status_code < 500:
                    raise NonRetryableAPIError(f"HTTP {resp.status_code} client error on page {page}: {resp.text}")
                    
                resp.raise_for_status()
                payload = resp.json()
                success = True
                break
                
            except requests.RequestException as exc:
                delay = base_delay * (2 ** (attempt - 1))
                if logger:
                    logger.warning(f"Page {page}: Connection error ({exc}). Backing off {delay}s (attempt {attempt}/{max_retries})")
                time.sleep(delay)
                
        if not success or payload is None:
            raise APIExtractionError(f"Failed to fetch page {page} after {max_retries} attempts.")
            
        # Save raw JSON page
        raw_page_path = raw_dir / f"dispatch_page_{page:03d}.json"
        raw_page_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        
        page_records = payload.get("data", [])
        records.extend(page_records)
        
        if total_expected is None:
            total_expected = payload.get("total_records")
            
        has_more = payload.get("has_more", False)
        if not has_more or len(page_records) == 0:
            break
            
        page += 1
        
    if logger:
        logger.info(f"Completed dispatch API extraction: {len(records)} records across {page} pages (reported total: {total_expected})")
        
    return records
