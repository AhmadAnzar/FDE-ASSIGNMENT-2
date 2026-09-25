"""
Metric & KPI calculation module for NYC TLC Yellow Taxi pipeline.
Primary KPI: Zone Delay Index = zone median / citywide non-airport median.
"""

import logging
import pandas as pd

log = logging.getLogger("tlc_pipeline")

AIRPORT_ZONES   = {"JFK Airport", "LaGuardia Airport", "Newark Airport"}
MIN_ZONE_TRIPS  = 3_000          # minimum trips per zone for a stable median


def calculate_metrics(final: pd.DataFrame, raw_count: int, validated_count: int):
    """
    Calculate all metrics.

    Primary KPI - Zone Delay Index:
      zone median trip duration / citywide non-airport median trip duration

    Airport zones are excluded from the baseline and from zone rankings.
    """
    log.info("[Metrics] Calculating KPIs")

    non_airport = final[~final["PU_Zone"].isin(AIRPORT_ZONES)]
    airport     = final[ final["PU_Zone"].isin(AIRPORT_ZONES)]

    # Citywide non-airport baseline (denominator for Zone Delay Index)
    baseline = non_airport["trip_duration_min"].median()
    log.info("[Metrics] Citywide non-airport median trip duration: %.2f min", baseline)

    # ── Hourly metrics ────────────────────────────────────────────────────────
    hourly = (
        final
        .groupby("pickup_hour")
        .agg(
            trips=          ("VendorID", "size"),
            median_duration=("trip_duration_min", "median"),
            p90_duration=   ("trip_duration_min", lambda x: x.quantile(0.90)),
        )
        .reset_index()
    )

    # ── Zone Delay Index (Project KPI) ────────────────────────────────────────
    zone_kpi = (
        non_airport
        .groupby(["PULocationID", "PU_Borough", "PU_Zone"])
        .agg(
            trips=          ("VendorID", "size"),
            median_duration=("trip_duration_min", "median"),
            p90_duration=   ("trip_duration_min", lambda x: x.quantile(0.90)),
        )
        .reset_index()
    )
    zone_kpi = zone_kpi[zone_kpi["trips"] >= MIN_ZONE_TRIPS].copy()
    zone_kpi["delay_index"] = zone_kpi["median_duration"] / baseline
    zone_kpi = zone_kpi.sort_values("delay_index", ascending=False).reset_index(drop=True)

    log.info("[Metrics] Zone KPI table: %d qualifying zones (>= %d trips)",
             len(zone_kpi), MIN_ZONE_TRIPS)
    log.info("[Metrics] Highest delay zone: %s (%.2fx)",
             zone_kpi.iloc[0]["PU_Zone"], zone_kpi.iloc[0]["delay_index"])

    # ── Summary KPI table ─────────────────────────────────────────────────────
    peak_row = hourly.loc[hourly["trips"].idxmax()]
    top_zone = zone_kpi.iloc[0]

    final_kpis = pd.DataFrame({
        "Metric": [
            "Core Valid Trip Rate (%)",
            "Final Analytical Retention (%)",
            "Citywide Non-Airport Median Duration (min)",
            "Citywide Median Trip Duration (min)",
            "P90 Trip Duration (min)",
            "Airport Median Duration (min)",
            "Non-Airport Median Duration (min)",
            "Peak Demand Hour",
            "Peak Hour Trips",
            "Highest Delay Zone",
            "Highest Zone Delay Index",
        ],
        "Value": [
            round(validated_count / raw_count * 100, 2),
            round(len(final) / raw_count * 100, 2),
            round(baseline, 2),
            round(final["trip_duration_min"].median(), 2),
            round(final["trip_duration_min"].quantile(0.90), 2),
            round(airport["trip_duration_min"].median(), 2) if len(airport) > 0 else "N/A",
            round(non_airport["trip_duration_min"].median(), 2),
            f"{int(peak_row['pickup_hour']):02d}:00",
            int(peak_row["trips"]),
            top_zone["PU_Zone"],
            round(top_zone["delay_index"], 2),
        ],
    })

    # ── Quality audit ─────────────────────────────────────────────────────────
    quality_audit = pd.DataFrame({
        "Check": [
            "Raw rows",
            "Core validation failures (any rule)",
            "Non-positive total amount removed",
            "Final analytical rows",
            "Duplicate rows after zone join",
            "Unknown pickup zone",
            "Unknown drop-off zone",
        ],
        "Value": [
            raw_count,
            raw_count - validated_count,
            validated_count - len(final),
            len(final),
            int(final.duplicated().sum()),
            int((final["PU_Zone"] == "Unknown").sum()),
            int((final["DO_Zone"] == "Unknown").sum()),
        ],
    })

    return hourly, zone_kpi, final_kpis, quality_audit
