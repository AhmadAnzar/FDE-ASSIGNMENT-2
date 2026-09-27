"""
Data cleaning and deduplication module.
"""
import logging
from typing import Dict
import pandas as pd

def clean_and_normalize_data(
    raw_tables: Dict[str, pd.DataFrame],
    logger: logging.Logger = None
) -> Dict[str, pd.DataFrame]:
    """
    Applies agreed business cleaning rules:
    - Deduplicates orders table keeping the first occurrence.
    - Normalizes status and category casing and strips whitespace.
    """
    cleaned = {}
    
    # 1. Clean Orders
    orders = raw_tables["orders"].copy()
    initial_rows = len(orders)
    orders = orders.drop_duplicates(subset=["order_id"], keep="first")
    dropped_dupes = initial_rows - len(orders)
    if logger and dropped_dupes > 0:
        logger.info(f"Cleaned orders: removed {dropped_dupes} duplicate rows ({initial_rows} -> {len(orders)})")
        
    orders["final_status_clean"] = orders["final_status"].astype(str).str.strip().str.lower()
    if "traffic_bucket" in orders.columns:
        orders["traffic_bucket_clean"] = orders["traffic_bucket"].astype(str).str.strip().str.lower()
    cleaned["orders"] = orders
    
    # 2. Clean Customer Actions
    actions = raw_tables["actions"].copy()
    actions["action_type_clean"] = actions["action_type"].astype(str).str.strip().str.upper()
    cleaned["actions"] = actions
    
    # 3. Clean Support Tickets
    tickets = raw_tables["tickets"].copy()
    tickets["category_clean"] = tickets["category"].astype(str).str.strip().str.lower().replace({
        "late delivery": "late_delivery",
        "eta issue": "eta_changed"
    })
    cleaned["tickets"] = tickets
    
    # 4. Clean Interventions
    interventions = raw_tables["interventions"].copy()
    interventions["intervention_type_clean"] = interventions["intervention_type"].astype(str).str.strip().str.upper()
    cleaned["interventions"] = interventions
    
    # Keep restaurants and drivers
    cleaned["restaurants"] = raw_tables.get("restaurants")
    cleaned["drivers"] = raw_tables.get("drivers")
    
    return cleaned
