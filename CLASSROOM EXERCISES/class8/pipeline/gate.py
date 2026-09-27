"""
Validation Gate module: acts as the quality firewall before any cleaning or publishing.
"""
import logging
from typing import Dict, Any, List
import pandas as pd

class ValidationError(Exception):
    """Raised when critical validation fails, preventing downstream processing."""
    pass

REQUIRED_ORDER_COLUMNS = [
    "order_id",
    "customer_id",
    "restaurant_id",
    "driver_id",
    "created_at",
    "promised_eta",
    "pickup_at",
    "actual_delivery_at",
    "final_status"
]

def run_validation_gate(
    orders_df: pd.DataFrame,
    dispatch_records: List[Dict[str, Any]],
    run_date_str: str,
    max_age_days: int = 60,
    logger: logging.Logger = None
) -> Dict[str, Any]:
    """
    Executes core validation contracts.
    Returns a structured validation dictionary.
    Raises ValidationError if any fatal check fails.
    """
    if logger:
        logger.info("Executing Validation Gate checks...")
        
    report = {
        "status": "PASS",
        "checks": {},
        "warnings": []
    }
    
    # 1. Required Columns Check (Fatal)
    missing_cols = [c for c in REQUIRED_ORDER_COLUMNS if c not in orders_df.columns]
    if missing_cols:
        msg = f"orders: missing required columns: {missing_cols}"
        if logger:
            logger.error(f"VALIDATION FAILED: {msg}")
        report["status"] = "FAIL"
        report["checks"]["required_columns"] = {"status": "FAIL", "missing": missing_cols}
        raise ValidationError(msg)
    else:
        report["checks"]["required_columns"] = {"status": "PASS"}
        
    # 2. Critical Nulls Check (Warning)
    delivered_mask = orders_df["final_status"].astype(str).str.lower() == "delivered"
    missing_dropoff = orders_df[delivered_mask]["actual_delivery_at"].isna().sum()
    if missing_dropoff > 0:
        warning_msg = f"{missing_dropoff} delivered orders lack completion timestamps (actual_delivery_at)."
        report["warnings"].append(warning_msg)
        report["checks"]["critical_nulls"] = {"status": "WARN", "missing_actual_delivery": int(missing_dropoff)}
        if logger:
            logger.warning(f"VALIDATION WARNING: {warning_msg}")
    else:
        report["checks"]["critical_nulls"] = {"status": "PASS"}
        
    # 3. Order ID Uniqueness (Warning)
    total_rows = len(orders_df)
    unique_orders = orders_df["order_id"].nunique()
    duplicate_rows = total_rows - unique_orders
    if duplicate_rows > 0:
        warning_msg = f"Found {duplicate_rows} duplicate rows across orders ({total_rows} total rows, {unique_orders} unique IDs)."
        report["warnings"].append(warning_msg)
        report["checks"]["order_uniqueness"] = {"status": "WARN", "duplicate_rows": int(duplicate_rows)}
        if logger:
            logger.warning(f"VALIDATION WARNING: {warning_msg}")
    else:
        report["checks"]["order_uniqueness"] = {"status": "PASS"}
        
    # 4. Data Freshness SLA (Fatal)
    try:
        created_series = pd.to_datetime(orders_df["created_at"], format="mixed", errors="coerce")
        latest_order_time = created_series.max()
        run_dt = pd.to_datetime(run_date_str)
        age_days = (run_dt - latest_order_time).days
        
        report["checks"]["freshness"] = {
            "latest_order_time": str(latest_order_time),
            "age_days": int(age_days),
            "max_allowed_days": max_age_days
        }
        
        if age_days > max_age_days:
            msg = f"Data is too stale: latest order is {age_days} days old (max allowed is {max_age_days} days)."
            if logger:
                logger.error(f"VALIDATION FAILED: {msg}")
            report["status"] = "FAIL"
            report["checks"]["freshness"]["status"] = "FAIL"
            raise ValidationError(msg)
        else:
            report["checks"]["freshness"]["status"] = "PASS"
    except Exception as exc:
        if isinstance(exc, ValidationError):
            raise
        if logger:
            logger.warning(f"Could not compute data freshness: {exc}")
        report["checks"]["freshness"] = {"status": "WARN", "error": str(exc)}
        
    # 5. Dispatch API Retrieval Completeness (Warning)
    if dispatch_records:
        api_count = len(dispatch_records)
        report["checks"]["api_retrieval"] = {"status": "PASS", "records_retrieved": api_count}
    else:
        warning_msg = "Dispatch API returned zero records."
        report["warnings"].append(warning_msg)
        report["checks"]["api_retrieval"] = {"status": "WARN", "records_retrieved": 0}
        
    if report["warnings"] and report["status"] == "PASS":
        report["status"] = "WARN"
        
    if logger:
        logger.info(f"Validation Gate completed with status: {report['status']}")
        
    return report
