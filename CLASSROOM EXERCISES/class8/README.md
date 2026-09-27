# Class 8 — Dependable Data Pipeline & Data Readiness Review

## Objective

In Classes 5, 6, and 7, we explored FlashEats data inside Jupyter notebooks. We retrieved records, wrote validation contracts, and mapped the customer order journey.

Class 8 addresses the production question:

> **Can this analysis run every day automatically without manual intervention, and is the data ready to support an AI delay prediction system?**

This folder implements a modular, production-ready pipeline and performs the formal **Gate 2 Data Readiness Review**.

---

## Architecture

The pipeline is organized into explicit, decoupled stages:

```text
EXTRACT  ──▶  VALIDATE  ──▶  CLEAN  ──▶  TRANSFORM  ──▶  SAVE  ──▶  LOG
```

1. **`extract`**: Ingests orders from SQLite, CSV contextual tables, and paginated Dispatch REST API with bounded retries.
2. **`validate`**: Enforces schema contracts, critical null limits, uniqueness, and freshness SLAs. **Stops execution if contracts are breached.**
3. **`clean`**: Deduplicates records using agreed business rules (keeping first record) and standardizes text casing.
4. **`transform`**: Constructs the canonical `order_journey` dataset and computes daily business metrics.
5. **`save`**: Atomically persists outputs into date-partitioned folders (`data/processed/run_date=YYYY-MM-DD/`).
6. **`log`**: Emits structured logs to both terminal and `logs/pipeline_YYYY-MM-DD.log`.

---

## How to Run

### 1. Run the daily pipeline
```bash
python run_pipeline.py --run-date 2026-09-22
```
*Outputs generated:*
- `data/processed/run_date=2026-09-22/order_journey.csv`
- `data/processed/run_date=2026-09-22/metrics.json`
- `data/processed/run_date=2026-09-22/validation_report.json`
- `logs/pipeline_2026-09-22.log`

### 2. Test failure handling & validation gate (Chaos testing)
```bash
# Test schema violation: drops 'promised_eta' (exits with code 2, writes 0 files)
python run_pipeline.py --run-date 2026-09-22 --chaos missing_column

# Test freshness SLA violation: simulates data 400 days old (exits with code 2)
python run_pipeline.py --run-date 2026-09-22 --chaos stale_data

# Test duplicate handling: injects duplicate orders (warns and deduplicates cleanly)
python run_pipeline.py --run-date 2026-09-22 --chaos duplicate_order
```

---

## Key Deliverables

- **[FlashEats_Class8_Walkthrough.ipynb](./FlashEats_Class8_Walkthrough.ipynb)**: Interactive notebook walking through pipeline testing, idempotency verification, and engineering discussions.
- **[GATE2_DATA_READINESS.md](./GATE2_DATA_READINESS.md)**: Formal executive evaluation assessing whether FlashEats data is ready for AI delay prediction.
- **[TROUBLESHOOTING.md](./TROUBLESHOOTING.md)**: Operational runbook detailing exit codes, error handling, and recovery steps.
