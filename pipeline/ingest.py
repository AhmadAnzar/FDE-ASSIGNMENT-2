"""
Data ingestion & retrieval module for NYC TLC Yellow Taxi pipeline.
Demonstrates two distinct retrieval modes:
  Mode 1: HTTP download via requests
  Mode 2: SQL query via sqlite3 in-memory database
"""

import hashlib
import logging
import sqlite3
import sys
from pathlib import Path

import pandas as pd
import requests

log = logging.getLogger("tlc_pipeline")

TLC_BASE_URL  = "https://d37ci6vzurychx.cloudfront.net/trip-data"
TLC_ZONES_URL = "https://d37ci6vzurychx.cloudfront.net/misc/taxi_zone_lookup.csv"


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
    log.info("[Retrieval-1] Saved %s (%d bytes, sha256=%s...)",
             dest.name, dest.stat().st_size, digest[:16])
    return digest


def load_zones_via_sql(zones_csv_path: Path) -> pd.DataFrame:
    """
    Retrieval Mode 2: SQL query via sqlite3 in-memory database.
    Loads the zone lookup CSV into an in-memory SQLite DB and retrieves
    it with a SQL SELECT.
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


def check_retrieval_completeness(trips: pd.DataFrame, year: int, month: int) -> None:
    """
    Assert that the downloaded trip file:
      (a) is non-empty
      (b) contains at least 90% of records within the target month
      (c) spans from the first day of the month to the last
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
