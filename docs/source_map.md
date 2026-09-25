# Source Map

## 1. Business Question
> **Which NYC yellow-taxi pickup zones consistently produce longer-than-baseline trip durations, and how severe is the difference relative to the citywide non-airport baseline?**

---

## 2. Information Required

To answer this question rigorously, the pipeline requires:
1. **Metered trip records** with pickup and drop-off timestamps to calculate trip durations.
2. **Spatial identifiers** (`PULocationID`, `DOLocationID`) for pickup and drop-off taxi zones.
3. **Trip distance and financial fields** (`trip_distance`, `total_amount`) to validate trip authenticity and filter billing anomalies.
4. **Authoritative taxi zone spatial metadata** (`LocationID`, `Borough`, `Zone`, `service_zone`) to aggregate metrics by geographical zone and isolate airport versus non-airport trips.

---

## 3. Data Sources

| Source | Owner | Grain | Format | Retrieval Method | Purpose |
|---|---|---|---|---|---|
| **NYC TLC Yellow Trip Data** (`yellow_tripdata_YYYY-MM.parquet`) | NYC Taxi & Limousine Commission (Public) | 1 row = 1 metered taxi trip | Apache Parquet | **Retrieval Mode 1**: Automated HTTP download via `requests` directly from CloudFront distribution | Core operational trip data for duration and distance profiling |
| **NYC TLC Taxi Zone Lookup** (`taxi_zone_lookup.csv`) | NYC Taxi & Limousine Commission (Public) | 1 row = 1 TLC Taxi Zone ID | CSV -> SQLite | **Retrieval Mode 2**: Ingested into in-memory SQLite table and queried via SQL `SELECT` | Dimensional zone reference to map LocationIDs to Borough/Zone names |

---

## 4. Source Details & Entity Grain

- **Yellow Trip Data**:
  - Grain: Individual metered trips recorded by taxicab in-vehicle technology systems (TPEP vendors: Creative Mobile Technologies, LLC or VeriFone Inc.).
  - Coverage: Monthly batches (June 2026 contains 3,837,248 raw rows).
  - Key fields: `tpep_pickup_datetime`, `tpep_dropoff_datetime`, `PULocationID`, `DOLocationID`, `trip_distance`, `total_amount`.

- **Taxi Zone Lookup**:
  - Grain: 265 unique spatial zones covering New York City boroughs plus Newark Airport.
  - Key fields: `LocationID` (Primary Key, 1 to 265), `Borough`, `Zone`, `service_zone`.

---

## 5. Known Gaps and Source Constraints

1. **Publication Latency**: TLC publishes data monthly with an approximate 2-month reporting lag; data cannot support real-time traffic dispatching.
2. **No Route or Congestion Data**: The dataset records only start and end timestamps/locations. Intermediate waypoints, routes taken, and localized street speeds are absent.
3. **No Driver or Vehicle Attribution**: Vehicle medallions and driver license numbers are anonymized or omitted, preventing fleet- or driver-level variance analysis.
4. **Missing Vendor Optional Fields**: Optional fields (`passenger_count`, `RatecodeID`, `store_and_fwd_flag`, `congestion_surcharge`, `Airport_fee`) are absent in ~26% of records due to vendor system differences. These do not affect core duration and zone metrics.
5. **Lookup Null Zones**: LocationIDs 264 and 265 represent "Unknown" / "N/A" areas. Trips associated with these IDs are retained in the analytical dataset with zone names explicitly populated as `"Unknown"`.
