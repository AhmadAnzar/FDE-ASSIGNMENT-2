"""
Lightweight unit tests for the NYC TLC Zone Delay Analysis Pipeline.
Tests validate data quality filters, zone enrichment, KPI calculations, and assertions.
"""

import sys
from pathlib import Path

# Ensure repository root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pandas as pd
import pytest

from pipeline.validate import validate
from pipeline.transform import enrich
from pipeline.metrics import calculate_metrics
from pipeline.cli import run_assertions


@pytest.fixture
def sample_zones():
    """Minimal zone lookup table fixture."""
    return pd.DataFrame({
        "LocationID": [1, 2, 132, 264],
        "Borough": ["Manhattan", "Queens", "Queens", None],
        "Zone": ["Midtown", "Astoria", "JFK Airport", None],
        "service_zone": ["Yellow", "Yellow", "Airports", None]
    })


@pytest.fixture
def valid_trip_row():
    """A single clean, valid trip."""
    return {
        "VendorID": 1,
        "tpep_pickup_datetime": pd.Timestamp("2026-06-15 12:00:00"),
        "tpep_dropoff_datetime": pd.Timestamp("2026-06-15 12:20:00"),
        "PULocationID": 1,
        "DOLocationID": 2,
        "trip_distance": 3.5,
        "total_amount": 25.0,
    }


def test_validation_removes_invalid_timestamps(sample_zones, valid_trip_row):
    """Verify that dropoff before/equal to pickup or outside month trips are flagged invalid."""
    trips = pd.DataFrame([
        valid_trip_row,
        # Dropoff before pickup (negative duration)
        {**valid_trip_row, "tpep_dropoff_datetime": pd.Timestamp("2026-06-15 11:50:00")},
        # Dropoff equal to pickup (zero duration)
        {**valid_trip_row, "tpep_dropoff_datetime": pd.Timestamp("2026-06-15 12:00:00")},
        # Pickup outside June 2026
        {**valid_trip_row, "tpep_pickup_datetime": pd.Timestamp("2026-05-31 23:59:59")},
    ])

    validated = validate(trips, sample_zones, year=2026, month=6)
    assert validated.loc[0, "is_valid"] == True
    assert validated.loc[1, "is_valid"] == False
    assert validated.loc[2, "is_valid"] == False
    assert validated.loc[3, "is_valid"] == False
    assert validated["is_valid"].sum() == 1


def test_validation_removes_nonpositive_distance(sample_zones, valid_trip_row):
    """Verify that zero or negative distances are flagged invalid."""
    trips = pd.DataFrame([
        valid_trip_row,
        {**valid_trip_row, "trip_distance": 0.0},
        {**valid_trip_row, "trip_distance": -2.5},
    ])

    validated = validate(trips, sample_zones, year=2026, month=6)
    assert validated.loc[0, "is_valid"] == True
    assert validated.loc[1, "is_valid"] == False
    assert validated.loc[2, "is_valid"] == False
    assert validated["is_valid"].sum() == 1


def test_total_amount_filter(sample_zones, valid_trip_row):
    """Verify that analytical filter removes total_amount <= 0 records."""
    trips = pd.DataFrame([
        valid_trip_row,
        {**valid_trip_row, "total_amount": 0.0},
        {**valid_trip_row, "total_amount": -15.5},
    ])

    validated = validate(trips, sample_zones, year=2026, month=6)
    enriched = enrich(validated, sample_zones)

    assert len(enriched) == 1
    assert enriched.iloc[0]["total_amount"] == 25.0


def test_zone_join_does_not_duplicate_rows(sample_zones, valid_trip_row):
    """Verify that zone enrichment maintains exact 1:1 cardinality with no row inflation."""
    trips = pd.DataFrame([
        valid_trip_row,
        {**valid_trip_row, "PULocationID": 2, "DOLocationID": 1},
        {**valid_trip_row, "PULocationID": 264, "DOLocationID": 2},  # Unknown zone
    ])

    validated = validate(trips, sample_zones, year=2026, month=6)
    enriched = enrich(validated, sample_zones)

    assert len(enriched) == len(trips)
    assert enriched.duplicated().sum() == 0
    assert "PU_Zone" in enriched.columns
    assert "DO_Zone" in enriched.columns
    # Unknown LocationID 264 gets filled with 'Unknown'
    unknown_row = enriched[enriched["PULocationID"] == 264].iloc[0]
    assert unknown_row["PU_Zone"] == "Unknown"


def test_zone_delay_index_calculation(sample_zones):
    """Verify Zone Delay Index = zone_median / baseline and airport exclusion."""
    # Construct synthetic trips:
    # Zone 1 (Midtown): 3,000 trips of duration 10 min
    # Zone 2 (Astoria): 3,000 trips of duration 20 min
    # Zone 132 (JFK Airport): 3,000 trips of duration 50 min (must be excluded from baseline)
    rows = []
    base_time = pd.Timestamp("2026-06-15 12:00:00")

    for i in range(3000):
        # Zone 1: 10 min
        rows.append({
            "VendorID": 1, "tpep_pickup_datetime": base_time,
            "tpep_dropoff_datetime": base_time + pd.Timedelta(minutes=10),
            "PULocationID": 1, "DOLocationID": 1, "trip_distance": 2.0, "total_amount": 15.0
        })
        # Zone 2: 20 min
        rows.append({
            "VendorID": 1, "tpep_pickup_datetime": base_time,
            "tpep_dropoff_datetime": base_time + pd.Timedelta(minutes=20),
            "PULocationID": 2, "DOLocationID": 2, "trip_distance": 4.0, "total_amount": 25.0
        })
        # Zone 132 (Airport): 50 min
        rows.append({
            "VendorID": 1, "tpep_pickup_datetime": base_time,
            "tpep_dropoff_datetime": base_time + pd.Timedelta(minutes=50),
            "PULocationID": 132, "DOLocationID": 1, "trip_distance": 15.0, "total_amount": 70.0
        })

    trips = pd.DataFrame(rows)
    validated = validate(trips, sample_zones, year=2026, month=6)
    enriched = enrich(validated, sample_zones)

    hourly, zone_kpi, final_kpis, quality_audit = calculate_metrics(
        enriched, raw_count=len(trips), validated_count=len(validated)
    )

    # Non-airport trips are Zone 1 (3000 @ 10m) and Zone 2 (3000 @ 20m) -> Non-airport median = 15.0m
    # Zone 2 delay_index = 20.0 / 15.0 = 1.33
    # Zone 1 delay_index = 10.0 / 15.0 = 0.67
    assert len(zone_kpi) == 2
    astoria = zone_kpi[zone_kpi["PU_Zone"] == "Astoria"].iloc[0]
    midtown = zone_kpi[zone_kpi["PU_Zone"] == "Midtown"].iloc[0]

    assert pytest.approx(astoria["delay_index"], rel=1e-2) == 1.33
    assert pytest.approx(midtown["delay_index"], rel=1e-2) == 0.67


def test_pipeline_assertions():
    """Verify that run_assertions catches corrupted datasets."""
    dummy_final = pd.DataFrame({
        "PU_Zone": ["Midtown", "Astoria"],
        "DO_Zone": ["Astoria", "Midtown"]
    })
    dummy_zone_kpi = pd.DataFrame({"PU_Zone": ["Astoria"], "delay_index": [1.5]})

    # Valid run should pass without raising
    run_assertions(raw_count=100, validated_count=90, final=dummy_final, zone_kpi=dummy_zone_kpi)

    # Corrupted: raw_count is 0 -> raises AssertionError
    with pytest.raises(AssertionError, match="zero rows"):
        run_assertions(raw_count=0, validated_count=0, final=dummy_final, zone_kpi=dummy_zone_kpi)

    # Corrupted: validated > raw -> raises AssertionError
    with pytest.raises(AssertionError, match="exceed raw rows"):
        run_assertions(raw_count=50, validated_count=60, final=dummy_final, zone_kpi=dummy_zone_kpi)
