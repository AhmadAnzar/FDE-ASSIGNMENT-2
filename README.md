# REPO OVERVIEW
This repository brings together two main projects:

1. **[ASSIGNMENT-2](./ASSIGNMENT-2)**: An end-to-end data pipeline and analysis on NYC Yellow Taxi trip data, focusing on trip duration delays across pickup zones.
2. **[CLASSROOM EXERCISES](./CLASSROOM%20EXERCISES)**: A multi-part hands-on case study (FlashEats) covering data retrieval, validation gates, and business workflow modeling.

---

## Repository Structure

```text
.
├── ASSIGNMENT-2/                          # NYC TLC Yellow Taxi Pipeline Project
│   ├── data/                              # Lookup tables (e.g. taxi_zone_lookup.csv)
│   ├── docs/run_logs/                     # Execution logs for successful and failed pipeline runs
│   ├── notebooks/                         # NYC_TLC_Analysis.ipynb (EDA and KPI development)
│   ├── outputs/                           # Generated KPI CSVs, audit tables, and visual charts
│   ├── pipeline/                          # Modular pipeline package (ingest, validate, transform, metrics, cli)
│   ├── tests/                             # Automated test suite (unit and pipeline integration tests)
│   ├── pipeline.py                        # Standalone pipeline entrypoint
│   ├── requirements.txt                   # Pipeline dependencies
│   └── README.md                          # Detailed Assignment 2 project documentation
│
└── CLASSROOM EXERCISES/                   # FlashEats Classroom Case Study
    ├── class5/                            # Class 5: Retrieval, problem sizing, and mock dispatch API
    │   ├── api/                           # Mock dispatch Flask API service
    │   ├── data/                          # Support tickets, driver events JSON, restaurants
    │   ├── database/                      # flasheats.db SQLite database
    │   ├── FlashEats_Class5_Starter.ipynb # Starter investigation notebook with solutions
    │   └── FlashEats_Class5_Student.ipynb # Comprehensive student investigation notebook
    ├── class6/                            # Class 6: Data validation contracts & gate
    │   ├── data/                          # Metric definitions JSON, restaurant status CSV
    │   ├── database/                      # flasheats.db SQLite database
    │   └── FlashEats_Class6_Student.ipynb # Validation gate notebook with solutions
    ├── class7/                            # Class 7: Workflow-centric data modeling
    │   ├── data/                          # Customer app actions, interventions, outcomes CSVs
    │   ├── database/                      # flasheats.db SQLite database
    │   └── FlashEats_Class7_Challenge.ipynb # Workflow model notebook with solutions
    └── class8/                            # Class 8: Dependable pipeline & Data Readiness Review
        ├── pipeline/                      # Modular pipeline package (ingest, gate, cleanse, model, storage, logger)
        ├── run_pipeline.py                # Standalone pipeline CLI runner
        ├── FlashEats_Class8_Walkthrough.ipynb # Walkthrough notebook with solutions
        ├── GATE2_DATA_READINESS.md        # Gate 2 Data Readiness Review
        └── TROUBLESHOOTING.md             # Pipeline runbook and troubleshooting guide
```

---

## 1. Assignment 2: NYC TLC Yellow Taxi Delay Pipeline

### What it does
This project builds a reproducible data pipeline for NYC Yellow Taxi trip records. It ingests monthly trip data, validates each record against strict business and technical rules, computes clean trip durations, and produces the **Zone Delay Index** to highlight zones with abnormal delays compared to the citywide baseline.

### Primary KPI: Zone Delay Index
$$\text{Zone Delay Index} = \frac{\text{Zone Median Trip Duration (min)}}{\text{Citywide Non-Airport Median Trip Duration (min)}}$$

- **Baseline**: 13.60 minutes (citywide median for non-airport trips in June 2026).
- **Highest Delay Zone**: **East Elmhurst (2.36x baseline)** with a median trip duration of 32.13 minutes.
- **Airport Exclusion**: Airports (JFK, LaGuardia, Newark) are treated separately because long-distance highway travel naturally skews duration.

### Quick Start
```bash
# 1. Install dependencies
pip install -r ASSIGNMENT-2/requirements.txt

# 2. Run the pipeline for June 2026
python ASSIGNMENT-2/pipeline.py --month 2026-06

# 3. Run automated tests
pytest ASSIGNMENT-2/tests/ -v
```

All generated summary tables (`zone_kpi.csv`, `hourly_metrics.csv`, `quality_audit.csv`) and charts are saved inside `ASSIGNMENT-2/outputs/`. Detailed methodology and findings can be found in [ASSIGNMENT-2/README.md](./ASSIGNMENT-2/README.md).

---

## 2. Classroom Exercises: FlashEats Case Study

The FlashEats case study explores a food delivery company dealing with rising late deliveries. Leadership initially wants to build an "AI delay predictor." Across four classes, we investigate the data to see whether that makes sense or if other bottlenecks are at play.

### Class 5: Data Retrieval & Problem Sizing
- **Goal**: Ingest data from four distinct sources (SQLite database, CSV support tickets, nested JSON driver events, and a paginated REST API with rate limits) to size the late delivery problem.
- **Core Findings**:
  - Out of 1,495 delivered orders with recorded delivery timestamps, **56.4% are late** (median delay: 8.0 minutes).
  - Operations claimed traffic was the culprit, but data shows kitchen preparation time has a **0.83 correlation** with delivery delay, while traffic (0.21) and distance (0.07) are weak factors.
  - Driver arrival at the restaurant is **not directly observed** in `driver_events.json` (only GPS coordinates exist).
- **FDE Decision**: **Do not build an AI delay predictor.** The real issue is kitchen delays and missing timestamps, not traffic prediction.

### Class 6: Data Validation & The Validation Gate
- **Goal**: Move from simple retrieval to building a formal validation gate before leadership publishes any metric.
- **Core Findings**:
  - Dissected the leadership claim of "56% Late Delivery Rate". Stakeholders disagree on the definition: VP Ops counts any delay > 0 min (56.4%), while Support only counts delays > 10 min (23.3%).
  - Identified data defects: duplicate order rows, 37 delivered orders missing drop-off times, and timestamps recorded out of order (e.g. pickup after delivery).
  - Evaluated data freshness: restaurant status updates lag behind actual pickup times, making them unsafe for live customer ETAs or merchant penalties.
- **Validation Gate Outcome**: Set to **FAIL / WARN** on KPI definition and freshness. Advised leadership not to publish 56% until definitions are formally agreed upon.

### Class 7: Modeling the Business Workflow
- **Goal**: Reorganize raw, siloed source tables into a canonical workflow model that maps:
  $$\text{Customer Interactions} \longrightarrow \text{Operational Interventions} \longrightarrow \text{Delivery Outcomes}$$
- **Core Findings**:
  - Reconstructed full order lifecycle event timelines for on-time, late, and intervened orders.
  - Built an order-level unified table linking customer app friction (ETA views, support opens, cancellation attempts) with operational interventions (driver reassignment, restaurant contact, priority dispatch).
  - Discovered that late rates are identical with or without intervention (56.4%), proving interventions are currently triggered reactively after the order is already late. Priority dispatch performed best among interventions (51.2% late rate).

### Class 8: Building a Dependable Pipeline & Gate 2 Review
- **Goal**: Turn the exploratory analysis into an automated, production-ready pipeline and conduct the executive Gate 2 Review on AI readiness.
- **Core Findings**:
  - Built modular stages (`extract`, `validate`, `clean`, `transform`, `save`, `log`) running with a single CLI command: `python run_pipeline.py --run-date 2026-09-22`.
  - Implemented bounded retries with exponential backoff, recovering gracefully from Dispatch API rate limits (HTTP 429) and server errors (HTTP 500).
  - Proved idempotency: rerunning the pipeline overwrote partitions cleanly with atomic writes (`os.replace`), maintaining exactly 1,600 unique rows without duplication.
  - Tested controlled failure modes: breaking required columns or exceeding freshness SLAs triggered the Validation Gate to exit with code 2 and write zero output files.
- **Gate 2 Verdict**: **NOT READY FOR AI MODELING.** Daily reporting can run now, but AI delay prediction must wait until kitchen arrival/ready timestamps are instrumented and KPI ownership is formally resolved.

---

## Prerequisites & Installation

To run the projects locally, use a Python 3.10+ environment:

```bash
# Clone the repository
git clone https://github.com/AhmadAnzar/FDE-ASSIGNMENT-2.git
cd FDE-ASSIGNMENT-2

# Install common requirements
pip install pandas requests flask matplotlib pytest pyarrow
```

---
