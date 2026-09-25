# Workflow and Data Model

## 1. Pipeline Workflow Architecture

The pipeline processes monthly TLC Yellow Taxi trip data through six deterministic stages:

```mermaid
flowchart LR
    A["Raw Trip Parquet\n+ Zone CSV"] --> B["Ingest\nMode 1: HTTP\nMode 2: SQL"]
    B --> C["Profile &\nValidate\n5 validation rules\nis_valid flag"]
    C --> D["Analytical Filter\ntotal_amount > 0\nBilling filter"]
    D --> E["Zone Enrichment\nLeft-join PU + DO\nfill Unknown"]
    E --> F["KPI Calculation\nZone Delay Index\nHourly metrics"]
    F --> G["Output & Assert\nCSVs + Parquet\n7 Assertions"]
```

### Stage Summary
1. **Ingest (`pipeline/ingest.py`)**: Retrieves raw monthly parquet via streaming HTTP and loads taxi zone lookup CSV into an in-memory SQLite database, queried via SQL. Completeness checks verify record presence and month boundaries.
2. **Validate (`pipeline/validate.py`)**: Applies five business rules, flagging rows without silent dropping. Computes Core Valid Trip Rate.
3. **Filter (`pipeline/transform.py`)**: Filters out zero or negative `total_amount` records to eliminate non-revenue refunds and billing corrections.
4. **Enrich (`pipeline/transform.py`)**: Merges spatial zone metadata for pickup and drop-off locations (`PU_Zone`, `DO_Zone`). Unmatched or missing metadata is preserved as `"Unknown"`.
5. **KPI Calculation (`pipeline/metrics.py`)**: Calculates baseline non-airport median duration, Zone Delay Index, and hourly trip distributions.
6. **Save & Assert (`pipeline/cli.py`)**: Executes 7 data integrity assertions and writes outputs to disk.

---

## 2. Data Model (Entity Relationship Diagram)

```mermaid
erDiagram
    TRIPS {
        datetime tpep_pickup_datetime
        datetime tpep_dropoff_datetime
        int PULocationID
        int DOLocationID
        float trip_distance
        float total_amount
        float trip_duration_min
        bool is_valid
        float delay_index
    }
    ZONES {
        int LocationID PK
        string Borough
        string Zone
        string service_zone
    }
    HOURLY_METRICS {
        int pickup_hour PK
        int trips
        float median_duration
        float p90_duration
    }
    ZONE_KPI {
        int PULocationID PK
        string PU_Borough
        string PU_Zone
        int trips
        float median_duration
        float p90_duration
        float delay_index
    }

    TRIPS ||--o{ ZONES : "PULocationID -> LocationID"
    TRIPS ||--o{ ZONES : "DOLocationID -> LocationID"
    TRIPS }o--|| HOURLY_METRICS : "aggregated by pickup_hour"
    TRIPS }o--|| ZONE_KPI : "aggregated by PULocationID"
```

---

## 3. Trip Lifecycle & Event Model

```mermaid
stateDiagram-v2
    [*] --> RawRecord : Vendor logs metered trip
    RawRecord --> ValidRecord : Passes all 5 validation rules (95.39%)
    RawRecord --> Rejected : Fails >= 1 validation rule (4.61%)
    ValidRecord --> AnalyticalRecord : total_amount > 0 (revenue trip)
    ValidRecord --> Excluded : total_amount <= 0 (refund/adjustment, 0.35%)
    AnalyticalRecord --> ZoneEnriched : Joined to zone lookup (PU & DO)
    ZoneEnriched --> KPIOutput : Aggregated into Zone Delay Index & Hourly KPIs
```
