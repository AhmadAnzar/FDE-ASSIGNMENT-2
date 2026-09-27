"""
Transformation & zone enrichment module for NYC TLC Yellow Taxi pipeline.
"""

import logging
import pandas as pd

log = logging.getLogger("tlc_pipeline")


def enrich(trips_flagged: pd.DataFrame, zones: pd.DataFrame) -> pd.DataFrame:
    """
    (a) Apply analytical filter: remove records with total_amount <= 0.
        These are treated as refund/adjustment entries, not completed trips.
    (b) Left-join zone lookup for both pickup and drop-off locations.
        Unmatched zones are filled with "Unknown" - not dropped.
    (c) Derive pickup_hour for hourly metrics.
    """
    n_before = trips_flagged["is_valid"].sum()
    clean = trips_flagged[
        trips_flagged["is_valid"] & (trips_flagged["total_amount"] > 0)
    ].copy()
    n_removed = n_before - len(clean)
    log.info("[Enrich] Analytical filter (total_amount > 0): removed %d rows, %d remain",
             n_removed, len(clean))

    # Zone enrichment - pickup
    pu_zones = zones.rename(columns={
        "LocationID":   "PULocationID",
        "Borough":      "PU_Borough",
        "Zone":         "PU_Zone",
        "service_zone": "PU_service_zone",
    })
    # Zone enrichment - drop-off
    do_zones = zones.rename(columns={
        "LocationID":   "DOLocationID",
        "Borough":      "DO_Borough",
        "Zone":         "DO_Zone",
        "service_zone": "DO_service_zone",
    })

    final = (
        clean
        .merge(pu_zones, on="PULocationID", how="left")
        .merge(do_zones, on="DOLocationID", how="left")
    )

    zone_cols = [
        "PU_Borough", "PU_Zone", "PU_service_zone",
        "DO_Borough", "DO_Zone", "DO_service_zone",
    ]
    final[zone_cols] = final[zone_cols].fillna("Unknown")
    final["pickup_hour"] = final["tpep_pickup_datetime"].dt.hour

    log.info("[Enrich] Unknown pickup zones: %d", (final["PU_Zone"] == "Unknown").sum())
    log.info("[Enrich] Unknown drop-off zones: %d", (final["DO_Zone"] == "Unknown").sum())
    log.info("[Enrich] Final analytical rows: %d", len(final))

    return final
