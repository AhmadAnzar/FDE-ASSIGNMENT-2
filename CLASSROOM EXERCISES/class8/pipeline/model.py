"""
Transformation module: builds the unified order journey and calculates core business KPIs.
"""
import logging
from typing import Dict, Any, Tuple
import pandas as pd

def build_order_journey_model(
    cleaned_tables: Dict[str, pd.DataFrame],
    logger: logging.Logger = None
) -> pd.DataFrame:
    """
    Transforms extracted and cleaned tables into a canonical order_journey dataset:
    - Calculates stage durations (prep time, transit time, delay).
    - Aggregates customer app interactions (ETA views, support opens, cancel attempts).
    - Aggregates operational interventions.
    - Determines on-time vs. late delivery outcome.
    """
    orders = cleaned_tables["orders"].copy()
    actions = cleaned_tables["actions"].copy()
    tickets = cleaned_tables["tickets"].copy()
    interventions = cleaned_tables["interventions"].copy()
    
    # 1. Parse order timestamps
    for col in ["created_at", "promised_eta", "pickup_at", "actual_delivery_at"]:
        if col in orders.columns:
            orders[col] = pd.to_datetime(orders[col], format="mixed", errors="coerce")
            
    # Durations in minutes
    orders["kitchen_prep_min"] = (orders["pickup_at"] - orders["created_at"]).dt.total_seconds() / 60
    orders["transit_min"] = (orders["actual_delivery_at"] - orders["pickup_at"]).dt.total_seconds() / 60
    orders["delay_min"] = (orders["actual_delivery_at"] - orders["promised_eta"]).dt.total_seconds() / 60
    
    # Delivery outcome flag
    orders["is_delivered"] = (orders["final_status_clean"] == "delivered").astype(int)
    orders["has_delivery_timestamp"] = orders["actual_delivery_at"].notna().astype(int)
    
    # Late flag: delay > 0 min among delivered with timestamps
    orders["late_flag"] = None
    measurable_mask = (orders["is_delivered"] == 1) & (orders["has_delivery_timestamp"] == 1)
    orders.loc[measurable_mask, "late_flag"] = (orders.loc[measurable_mask, "delay_min"] > 0).astype(int)
    
    # 2. Aggregate customer app actions by order
    actions_summary = actions.groupby("order_id").agg(
        eta_views_count=("action_type_clean", lambda s: int((s == "ETA_VIEWED").sum())),
        app_support_opened=("action_type_clean", lambda s: int((s == "SUPPORT_OPENED").any())),
        cancel_attempted=("action_type_clean", lambda s: int((s == "CANCEL_ATTEMPTED").any()))
    ).reset_index()
    
    # 3. Aggregate support tickets
    ticket_orders = set(tickets["order_id"].dropna().unique())
    orders["support_ticket_opened"] = orders["order_id"].isin(ticket_orders).astype(int)
    
    # 4. Aggregate operational interventions
    interv_summary = interventions.groupby("order_id").agg(
        intervention_count=("intervention_id", "count"),
        intervention_types=("intervention_type_clean", lambda s: "; ".join(sorted(set(s))))
    ).reset_index()
    
    # 5. Join everything to base orders
    journey = orders.merge(actions_summary, on="order_id", how="left")
    journey["eta_views_count"] = journey["eta_views_count"].fillna(0).astype(int)
    journey["app_support_opened"] = journey["app_support_opened"].fillna(0).astype(int)
    journey["cancel_attempted"] = journey["cancel_attempted"].fillna(0).astype(int)
    journey["has_customer_friction"] = (
        (journey["app_support_opened"] == 1) | 
        (journey["support_ticket_opened"] == 1) | 
        (journey["cancel_attempted"] == 1)
    ).astype(int)
    
    journey = journey.merge(interv_summary, on="order_id", how="left")
    journey["intervention_count"] = journey["intervention_count"].fillna(0).astype(int)
    journey["intervention_types"] = journey["intervention_types"].fillna("NONE")
    journey["has_intervention"] = (journey["intervention_count"] > 0).astype(int)
    
    # Categorize outcome bucket
    def categorize_outcome(row):
        if row["final_status_clean"] == "cancelled":
            return "cancelled"
        if row["has_delivery_timestamp"] == 0:
            return "unrecorded_delivery"
        if row["late_flag"] == 1:
            return "delivered_late"
        return "delivered_on_time"
        
    journey["outcome_bucket"] = journey.apply(categorize_outcome, axis=1)
    
    if logger:
        logger.info(f"Built unified order journey table: {len(journey)} rows")
        
    return journey

def compute_pipeline_metrics(
    journey_df: pd.DataFrame,
    run_date_str: str,
    logger: logging.Logger = None
) -> Dict[str, Any]:
    """Computes daily summary business KPIs from the order journey model."""
    total_orders = len(journey_df)
    measurable = journey_df[journey_df["late_flag"].notna()]
    late_orders = measurable[measurable["late_flag"] == 1]
    
    late_rate = float(len(late_orders) / len(measurable)) if len(measurable) > 0 else 0.0
    median_delay = float(late_orders["delay_min"].median()) if len(late_orders) > 0 else 0.0
    friction_rate = float(journey_df["has_customer_friction"].mean())
    intervention_rate = float(journey_df["has_intervention"].mean())
    
    intervened_measurable = measurable[measurable["has_intervention"] == 1]
    recovery_rate = float((intervened_measurable["late_flag"] == 0).mean()) if len(intervened_measurable) > 0 else 0.0
    
    metrics = {
        "run_date": run_date_str,
        "total_unique_orders": total_orders,
        "cancelled_orders": int((journey_df["outcome_bucket"] == "cancelled").sum()),
        "unrecorded_delivery_orders": int((journey_df["outcome_bucket"] == "unrecorded_delivery").sum()),
        "measurable_delivered_orders": len(measurable),
        "late_delivered_orders": len(late_orders),
        "late_delivery_rate_pct": round(late_rate * 100, 2),
        "median_late_delay_min": round(median_delay, 2),
        "customer_friction_rate_pct": round(friction_rate * 100, 2),
        "operational_intervention_rate_pct": round(intervention_rate * 100, 2),
        "intervention_recovery_rate_pct": round(recovery_rate * 100, 2)
    }
    
    if logger:
        logger.info(
            f"Computed KPIs for {run_date_str}: Late Rate={metrics['late_delivery_rate_pct']}%, "
            f"Median Delay={metrics['median_late_delay_min']}m, Friction={metrics['customer_friction_rate_pct']}%"
        )
        
    return metrics
