"""
CLI runner, assertions & orchestration entry point for NYC TLC Yellow Taxi pipeline.
"""

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd

from pipeline.ingest import (
    TLC_BASE_URL,
    TLC_ZONES_URL,
    download_file,
    load_zones_via_sql,
    check_retrieval_completeness,
)
from pipeline.validate import validate
from pipeline.transform import enrich
from pipeline.metrics import calculate_metrics, MIN_ZONE_TRIPS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
log = logging.getLogger("tlc_pipeline")


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
    Write all pipeline outputs. Logs a warning if output directory already exists.
    """
    if output_dir.exists():
        log.warning("[Save] Output directory %s already exists - files will be overwritten",
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
                        help="Trip data month 1-12 (default: 6)")
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

    # ── Step 1: Retrieve (Mode 1 - HTTP download) ─────────────────────────────
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

    # ── Step 3: Load zones (Mode 2 - SQL via sqlite3) ─────────────────────────
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
    log.info("Pipeline completed successfully - %s", month_id)
    log.info("Raw rows              : %d", raw_count)
    log.info("Validated rows        : %d  (%.2f%%)",
             validated_count, validated_count / raw_count * 100)
    log.info("Final analytical rows : %d  (%.2f%%)",
             len(final), len(final) / raw_count * 100)
    log.info("Zone Delay Index - top zone: %s  %.2fx",
             top["PU_Zone"], top["delay_index"])
    log.info("Outputs saved to      : %s", output_dir)
    log.info("=" * 65)


if __name__ == "__main__":
    main()
