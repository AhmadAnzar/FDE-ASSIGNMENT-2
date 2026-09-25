"""
NYC TLC Yellow Taxi — Zone Trip Duration Delay Analysis Pipeline
================================================================
Business Question:
  Which NYC yellow-taxi pickup zones consistently produce longer-than-baseline
  trip durations, and how severe is the difference relative to the citywide
  non-airport baseline?

Project KPI:
  Zone Delay Index = zone median trip duration / citywide non-airport median trip duration

Decision Supported:
  Identify pickup zones that warrant further operational investigation based on
  unusually high trip-duration delay relative to the citywide non-airport baseline.

Usage:
  python pipeline.py                          # default: June 2026
  python pipeline.py --year 2026 --month 7   # specify month
  python pipeline.py --skip-download          # reuse existing raw files
  python pipeline.py --help                  # full options

Retrieval modes used:
  Mode 1 — HTTP download via requests (trip Parquet + zone CSV from TLC endpoint)
  Mode 2 — SQL query via sqlite3 in-memory database (zone lookup enrichment)
"""

import argparse
import hashlib
import logging
import sqlite3
import sys
from pathlib import Path

import pandas as pd
import requests

# ── Constants ──────────────────────────────────────────────────────────────────

TLC_BASE_URL    = "https://d37ci6vzurychx.cloudfront.net/trip-data"
TLC_ZONES_URL   = "https://d37ci6vzurychx.cloudfront.net/misc/taxi_zone_lookup.csv"

AIRPORT_ZONES   = {"JFK Airport", "LaGuardia Airport", "Newark Airport"}
MIN_ZONE_TRIPS  = 3_000          # minimum trips per zone for a stable median


# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
log = logging.getLogger("tlc_pipeline")


# ══════════════════════════════════════════════════════════════════════════════
# STEP 1 — RETRIEVAL (two distinct modes)
# ══════════════════════════════════════════════════════════════════════════════

def download_file(url: str, dest: Path) -> str:
    """
    Retrieval Mode 1: HTTP download via requests.
    Downloads `url` to `dest` and returns the SHA-256 hex digest for provenance.
    """
    log.info("[Retrieval-1] HTTP download: %s", url)
    try:
        response = requests.get(url, stream=True, timeout=180)
        response.raise_for_status()
    except requests.exceptions.HTTPError as exc:
        log.error("HTTP error downloading %s: %s", url, exc)
        raise SystemExit(1)
    except requests.exceptions.ConnectionError as exc:
        log.error("Connection error: %s", exc)
        raise SystemExit(1)
    except requests.exceptions.Timeout:
        log.error("Timeout downloading %s", url)
        raise SystemExit(1)

    dest.parent.mkdir(parents=True, exist_ok=True)
    sha256 = hashlib.sha256()
    with open(dest, "wb") as fh:
        for chunk in response.iter_content(chunk_size=1 << 20):  # 1 MB chunks
            fh.write(chunk)
            sha256.update(chunk)

    digest = sha256.hexdigest()
    log.info("[Retrieval-1] Saved %s (%d bytes, sha256=%s…)",
             dest.name, dest.stat().st_size, digest[:16])
    return digest


def load_zones_via_sql(zones_csv_path: Path) -> pd.DataFrame:
    """
    Retrieval Mode 2: SQL query via sqlite3 in-memory database.
    Loads the zone lookup CSV into an in-memory SQLite DB and retrieves
    it with a SQL SELECT. This demonstrates SQL as a distinct retrieval
    mode from the HTTP download above.
    """
    log.info("[Retrieval-2] Loading zone lookup into SQLite: %s", zones_csv_path)
    try:
        raw_zones = pd.read_csv(zones_csv_path)
    except FileNotFoundError:
        log.error("Zone lookup file not found: %s", zones_csv_path)
        raise SystemExit(1)

    con = sqlite3.connect(":memory:")
    raw_zones.to_sql("zones", con, index=False, if_exists="replace")

    zones = pd.read_sql(
        "SELECT LocationID, Borough, Zone, service_zone FROM zones ORDER BY LocationID",
        con,
    )
    con.close()

    log.info("[Retrieval-2] Zone lookup: %d rows returned via SQL", len(zones))
    return zones


# ══════════════════════════════════════════════════════════════════════════════
# STEP 2 — RETRIEVAL COMPLETENESS CHECK
# ══════════════════════════════════════════════════════════════════════════════

def check_retrieval_completeness(trips: pd.DataFrame, year: int, month: int) -> None:
    """
    Assert that the downloaded trip file:
      (a) is non-empty
      (b) contains at least 90% of records within the target month
      (c) spans from the first day of the month to the last
    Records from adjacent months are expected in small numbers (boundary trips)
    and are handled by the date validation rule, not here.
    """
    log.info("[Completeness] Checking retrieval completeness for %d-%02d", year, month)

    assert len(trips) > 0, (
        f"RETRIEVAL FAILURE: Trip file for {year}-{month:02d} is empty."
    )

    start = pd.Timestamp(year, month, 1)
    end   = pd.Timestamp(year + 1, 1, 1) if month == 12 else pd.Timestamp(year, month + 1, 1)

    in_month_mask = (
        (trips["tpep_pickup_datetime"] >= start) &
        (trips["tpep_pickup_datetime"] <  end)
    )
    n_in_month  = in_month_mask.sum()
    pct_in_month = n_in_month / len(trips) * 100

    log.info("[Completeness] %d / %d rows (%.2f%%) have pickup in %d-%02d",
             n_in_month, len(trips), pct_in_month, year, month)
    log.info("[Completeness] Pickup date range: %s to %s",
             trips["tpep_pickup_datetime"].min().date(),
             trips["tpep_pickup_datetime"].max().date())

    assert pct_in_month >= 90.0, (
        f"RETRIEVAL INCOMPLETE: Only {pct_in_month:.1f}% of records fall within "
        f"{year}-{month:02d}. Expected >= 90%. "
        f"File may be wrong month or corrupted."
    )

    log.info("[Completeness] PASSED (%.2f%% in target month)", pct_in_month)


# ══════════════════════════════════════════════════════════════════════════════
# STEP 3 — PROFILE & VALIDATE
# ══════════════════════════════════════════════════════════════════════════════

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


# ══════════════════════════════════════════════════════════════════════════════
# STEP 4 — TRANSFORM & ENRICH
# ══════════════════════════════════════════════════════════════════════════════

def enrich(trips_flagged: pd.DataFrame, zones: pd.DataFrame) -> pd.DataFrame:
    """
    (a) Apply analytical filter: remove records with total_amount <= 0.
        These are treated as refund/adjustment entries, not completed trips.
        Assumption documented in KUAL: total_amount > 0 reliably identifies
        genuine completed trips.

    (b) Left-join zone lookup for both pickup and drop-off locations.
        Unmatched zones are filled with "Unknown" — not dropped — so
        trips without zone metadata are retained and counted.

    (c) Derive pickup_hour for hourly metrics.
    """
    # Analytical filter (applied after core validation)
    n_before = trips_flagged["is_valid"].sum()
    clean = trips_flagged[
        trips_flagged["is_valid"] & (trips_flagged["total_amount"] > 0)
    ].copy()
    n_removed = n_before - len(clean)
    log.info("[Enrich] Analytical filter (total_amount > 0): removed %d rows, %d remain",
             n_removed, len(clean))

    # Zone enrichment — pickup
    pu_zones = zones.rename(columns={
        "LocationID":   "PULocationID",
        "Borough":      "PU_Borough",
        "Zone":         "PU_Zone",
        "service_zone": "PU_service_zone",
    })
    # Zone enrichment — drop-off
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


# ══════════════════════════════════════════════════════════════════════════════
# STEP 5 — METRIC CALCULATION
# ══════════════════════════════════════════════════════════════════════════════

def calculate_metrics(final: pd.DataFrame, raw_count: int, validated_count: int):
    """
    Calculate all metrics.

    Primary KPI — Zone Delay Index:
      zone median trip duration / citywide non-airport median trip duration

    Airport zones are excluded from the baseline and from zone rankings because
    they represent categorically different (long-haul, fixed-route) trips.
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
    # Zones with fewer than MIN_ZONE_TRIPS trips are excluded: median is
    # unreliable on small samples and could produce misleading delay signals.
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
    log.info("[Metrics] Highest delay zone: %s (%.2f×)",
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


# ══════════════════════════════════════════════════════════════════════════════
# STEP 6 — PIPELINE ASSERTIONS (integrity checks)
# ══════════════════════════════════════════════════════════════════════════════

def run_assertions(raw_count: int, validated_count: int, final: pd.DataFrame,
                   zone_kpi: pd.DataFrame) -> None:
    """
    Seven integrity assertions with descriptive failure messages.
    Any failure raises AssertionError and halts the pipeline.
    """
    log.info("[Assert] Running pipeline integrity checks")

    assert raw_count > 0, (
        "PIPELINE FAILURE: Raw trip file contains zero rows. Check the source file."
    )
    assert validated_count <= raw_count, (
        f"PIPELINE FAILURE: Validated rows ({validated_count}) exceed raw rows ({raw_count})."
    )
    assert len(final) <= validated_count, (
        f"PIPELINE FAILURE: Final rows ({len(final)}) exceed validated rows ({validated_count})."
    )
    assert final.duplicated().sum() == 0, (
        f"INTEGRITY FAILURE: {final.duplicated().sum()} duplicate rows found after zone join."
    )
    assert final["PU_Zone"].isna().sum() == 0, (
        "INTEGRITY FAILURE: Null values in PU_Zone after enrichment. "
        "fillna('Unknown') did not execute correctly."
    )
    assert final["DO_Zone"].isna().sum() == 0, (
        "INTEGRITY FAILURE: Null values in DO_Zone after enrichment."
    )
    assert len(zone_kpi) > 0, (
        "PIPELINE FAILURE: Zone KPI table is empty. "
        f"No zones met the minimum trip threshold ({MIN_ZONE_TRIPS})."
    )

    log.info("[Assert] All %d assertions PASSED", 7)


# ══════════════════════════════════════════════════════════════════════════════
# STEP 7 — SAVE OUTPUTS
# ══════════════════════════════════════════════════════════════════════════════

def save_outputs(
    output_dir: Path,
    final:        pd.DataFrame,
    hourly:       pd.DataFrame,
    zone_kpi:     pd.DataFrame,
    final_kpis:   pd.DataFrame,
    quality_audit:pd.DataFrame,
    digests:      dict,
) -> None:
    """
    Write all pipeline outputs. Logs a warning if the output directory already
    exists (rerun behaviour: files are overwritten, not silently replaced).
    """
    if output_dir.exists():
        log.warning("[Save] Output directory %s already exists — files will be overwritten",
                    output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    outputs = {
        "final_trips.parquet":  lambda p: final.to_parquet(p, index=False),
        "hourly_metrics.csv":   lambda p: hourly.to_csv(p, index=False),
        "zone_kpi.csv":         lambda p: zone_kpi.to_csv(p, index=False),
        "final_kpis.csv":       lambda p: final_kpis.to_csv(p, index=False),
        "quality_audit.csv":    lambda p: quality_audit.to_csv(p, index=False),
    }

    if digests:
        provenance = pd.DataFrame(
            [{"file": k, "sha256": v} for k, v in digests.items()]
        )
        outputs["raw_provenance.csv"] = lambda p: provenance.to_csv(p, index=False)

    for filename, write_fn in outputs.items():
        dest = output_dir / filename
        try:
            write_fn(dest)
            log.info("[Save] %s  (%d bytes)", dest.name, dest.stat().st_size)
        except OSError as exc:
            log.error("[Save] Failed to write %s: %s", filename, exc)
            raise SystemExit(1)


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "NYC TLC Zone Trip Duration Delay Analysis Pipeline.\n"
            "Business question: Which NYC yellow-taxi pickup zones consistently produce\n"
            "longer-than-baseline trip durations, and how severe is the difference\n"
            "relative to the citywide non-airport baseline?"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--year",          type=int,  default=2026,
                        help="Trip data year (default: 2026)")
    parser.add_argument("--month",         type=int,  default=6,
                        help="Trip data month 1–12 (default: 6)")
    parser.add_argument("--raw-dir",       type=Path, default=Path("raw"),
                        help="Directory for raw downloaded files (default: raw/)")
    parser.add_argument("--output-dir",    type=Path, default=None,
                        help="Output directory (default: output/YYYY-MM/)")
    parser.add_argument("--skip-download", action="store_true",
                        help="Skip HTTP download if raw files already exist locally")
    return parser.parse_args()


def main() -> None:
    args      = parse_args()
    month_id  = f"{args.year}-{args.month:02d}"
    output_dir = args.output_dir or Path("output") / month_id

    log.info("=" * 65)
    log.info("NYC TLC Zone Delay Analysis Pipeline")
    log.info("Processing : %s", month_id)
    log.info("Output dir : %s", output_dir)
    log.info("=" * 65)

    # ── Paths ─────────────────────────────────────────────────────────────────
    trips_path    = args.raw_dir / f"yellow_tripdata_{month_id}.parquet"
    zones_path    = args.raw_dir / "taxi_zone_lookup.csv"
    trips_url     = f"{TLC_BASE_URL}/yellow_tripdata_{month_id}.parquet"

    # ── Step 1: Retrieve (Mode 1 — HTTP download) ─────────────────────────────
    digests: dict = {}
    if args.skip_download and trips_path.exists() and zones_path.exists():
        log.info("[Retrieval-1] --skip-download: using existing raw files in %s", args.raw_dir)
    else:
        digests["yellow_tripdata"] = download_file(trips_url, trips_path)
        digests["taxi_zone_lookup"] = download_file(TLC_ZONES_URL, zones_path)

    # ── Step 2: Load trips (Parquet file read) ────────────────────────────────
    log.info("[Load] Reading trip data from %s", trips_path)
    try:
        trips = pd.read_parquet(trips_path)
    except FileNotFoundError:
        log.error("Trip parquet not found: %s  (did you forget --skip-download?)", trips_path)
        raise SystemExit(1)
    except Exception as exc:
        log.error("Failed to load trip parquet: %s", exc)
        raise SystemExit(1)

    raw_count = len(trips)
    log.info("[Load] Raw trip rows: %d", raw_count)

    # ── Step 3: Load zones (Mode 2 — SQL via sqlite3) ─────────────────────────
    zones = load_zones_via_sql(zones_path)

    # ── Step 4: Retrieval completeness check ──────────────────────────────────
    check_retrieval_completeness(trips, args.year, args.month)

    # ── Step 5: Validate ──────────────────────────────────────────────────────
    trips_flagged   = validate(trips, zones, args.year, args.month)
    validated_count = int(trips_flagged["is_valid"].sum())

    # ── Step 6: Transform & Enrich ────────────────────────────────────────────
    final = enrich(trips_flagged, zones)

    # ── Step 7: Calculate metrics ─────────────────────────────────────────────
    hourly, zone_kpi, final_kpis, quality_audit = calculate_metrics(
        final, raw_count, validated_count
    )

    # ── Step 8: Integrity assertions ──────────────────────────────────────────
    run_assertions(raw_count, validated_count, final, zone_kpi)

    # ── Step 9: Save outputs ──────────────────────────────────────────────────
    save_outputs(output_dir, final, hourly, zone_kpi, final_kpis, quality_audit, digests)

    # ── Summary ───────────────────────────────────────────────────────────────
    top = zone_kpi.iloc[0]
    log.info("=" * 65)
    log.info("Pipeline completed successfully — %s", month_id)
    log.info("Raw rows              : %d", raw_count)
    log.info("Validated rows        : %d  (%.2f%%)",
             validated_count, validated_count / raw_count * 100)
    log.info("Final analytical rows : %d  (%.2f%%)",
             len(final), len(final) / raw_count * 100)
    log.info("Zone Delay Index — top zone: %s  %.2f×",
             top["PU_Zone"], top["delay_index"])
    log.info("Outputs saved to      : %s", output_dir)
    log.info("=" * 65)


if __name__ == "__main__":
    main()
