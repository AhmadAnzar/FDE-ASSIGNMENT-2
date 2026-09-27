"""
Data profiling & validation module for NYC TLC Yellow Taxi pipeline.
Applies five business validation rules without silently dropping failed rows.
"""

import logging
import pandas as pd

log = logging.getLogger("tlc_pipeline")


def validate(trips: pd.DataFrame, zones: pd.DataFrame, year: int, month: int) -> pd.DataFrame:
    """
    Apply five business-oriented validation rules.
    Each rule is stored as a boolean column for full auditability.
    No rows are silently dropped here; all are flagged and counted.
    """
    log.info("[Validate] Applying validation rules to %d rows", len(trips))

    start = pd.Timestamp(year, month, 1)
    end   = pd.Timestamp(year + 1, 1, 1) if month == 12 else pd.Timestamp(year, month + 1, 1)

    trips = trips.copy()

    # Derived field required for validation
    trips["trip_duration_min"] = (
        trips["tpep_dropoff_datetime"] - trips["tpep_pickup_datetime"]
    ).dt.total_seconds() / 60

    valid_zone_ids = set(zones["LocationID"])

    # ── Validation rules ─────────────────────────────────────────────────────
    trips["valid_pickup_date"] = (
        (trips["tpep_pickup_datetime"] >= start) &
        (trips["tpep_pickup_datetime"] <  end)
    )
    trips["valid_timestamp_order"] = (
        trips["tpep_dropoff_datetime"] > trips["tpep_pickup_datetime"]
    )
    trips["valid_distance"] = trips["trip_distance"] > 0
    trips["valid_pickup_zone"]  = trips["PULocationID"].isin(valid_zone_ids)
    trips["valid_dropoff_zone"] = trips["DOLocationID"].isin(valid_zone_ids)

    trips["is_valid"] = (
        trips["valid_pickup_date"]    &
        trips["valid_timestamp_order"] &
        trips["valid_distance"]        &
        trips["valid_pickup_zone"]     &
        trips["valid_dropoff_zone"]
    )

    # ── Log per-rule failure counts ───────────────────────────────────────────
    rules = [
        ("valid_pickup_date",     "Pickup outside target month"),
        ("valid_timestamp_order", "Dropoff not after pickup (zero/negative duration)"),
        ("valid_distance",        "Zero or negative trip distance"),
        ("valid_pickup_zone",     "PULocationID not in zone lookup"),
        ("valid_dropoff_zone",    "DOLocationID not in zone lookup"),
    ]
    for col, label in rules:
        n_fail = (~trips[col]).sum()
        log.info("[Validate]   %-50s  %d failures", label, n_fail)

    n_valid     = trips["is_valid"].sum()
    valid_rate  = n_valid / len(trips) * 100
    log.info("[Validate] Core valid trip rate: %d / %d  (%.2f%%)",
             n_valid, len(trips), valid_rate)

    return trips
