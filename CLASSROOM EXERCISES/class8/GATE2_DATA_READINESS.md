# Gate 2: Data Readiness Review for Machine Learning & Reporting

**Evaluation Date:** 2026-09-22  
**Subject:** FlashEats Order Data Foundation & Automated Pipeline  
**Assessor:** Forward Data Engineering (FDE) Team  

---

## Executive Summary

FlashEats leadership proposed building an **AI-driven delay prediction model** to estimate delivery times and address customer complaints about shifting ETAs.

This Gate 2 review evaluates two separate questions:
1. **Pipeline Dependability**: Can our data pipeline reliably ingest, validate, and process daily orders without manual intervention?
2. **Data Foundation Readiness**: Is the underlying data rich, accurate, and semantically grounded enough to train a machine learning model?

### Final Verdict: **NOT READY FOR AI MODELING** (APPROVED FOR INTERNAL REPORTING)

* **Pipeline Status: PASS.** The modular batch pipeline is dependable, idempotent, and protected by an automated validation gate.
* **Data Readiness: FAIL.** The current data lacks critical operational timestamps, has missing completion records, and lacks an executive-approved definition of "late."

---

## 1. Technical Pipeline Evaluation

| Capability | Status | Evidence from Test Runs |
|---|---|---|
| **Single-Command Execution** | **PASS** | Complete pipeline runs via `python run_pipeline.py --run-date 2026-09-22` with return code 0. |
| **Idempotent Reruns** | **PASS** | Running the same date twice produces the exact same 1,600 rows. No duplicated rows, no orphaned temp files. |
| **Atomic File Persistence** | **PASS** | Datasets are written to `.tmp` files before being atomically swapped with `os.replace`. |
| **Bounded Retries** | **PASS** | Dispatch API rate limits (HTTP 429) and server errors (HTTP 500) are retried with exponential backoff (pages 3 and 5 recovered on attempt 1/3). |
| **Validation Firewall** | **PASS** | Deliberate schema defects (`--chaos missing_column`) and freshness violations (`--chaos stale_data`) halted execution with return code 2 and wrote zero output files. |
| **Audit Logging** | **PASS** | Dual logging to terminal and dated files (`logs/pipeline_YYYY-MM-DD.log`) with row counts and stage timings. |

---

## 2. Data Quality & Semantic Validation

| Data Dimension | Status | Current Finding & Risk |
|---|---|---|
| **Schema Completeness** | **PASS** | All 9 core columns (`order_id`, `created_at`, `promised_eta`, etc.) are consistently present. |
| **Delivery Completion Timestamps** | **WARN** | **37 delivered orders lack completion timestamps** (`actual_delivery_at` is null). They cannot be measured for delay. |
| **Duplicate Orders** | **WARN** | 3 duplicate order IDs exist in the source database (6 rows). The pipeline cleans them by keeping the first occurrence, but upstream ingestion should enforce uniqueness. |
| **Freshness SLA** | **PASS** | Orders are within the 60-day operational freshness window. |
| **KPI Definition Ownership** | **FAIL** | **There is no agreed definition of "late."** VP Operations considers any delay > 0 min as late (56.4%), whereas Support considers only delays > 10 min as late (23.3%). |
| **Driver Arrival Tracking** | **FAIL** | **The system does not record when drivers arrive at restaurants.** We only have GPS pings and pickup taps. We cannot separate restaurant cooking delays from driver parking/wait times. |

---

## 3. Why We Recommend Waiting on the AI Model

1. **Missing Explanatory Variables (The Kitchen Black Box)**:
   - Kitchen preparation duration correlates 0.83 with delivery delay. However, without an explicit `driver_arrived_at_restaurant` timestamp, the model cannot distinguish between food taking 30 minutes to cook vs. food being ready in 10 minutes while a driver waits 20 minutes outside.
   - Feeding incomplete timing data into an algorithm will produce noisy, untrustworthy predictions.

2. **Unresolved Target Variable**:
   - Supervised machine learning requires a clear target label (what constitutes a late delivery?). Until leadership formally signs off on whether a 2-minute delay is a failure, any model optimization will optimize for the wrong outcome.

3. **Data Logging Defects**:
   - Delivered orders with missing timestamps (37 orders) represent system dropouts that must be resolved before model training.

---

## 4. Required Next Steps Before AI Investment

1. **Instrument Restaurant Arrival**: Deploy an automated geofence event in the driver mobile app when the driver arrives within 50 meters of the restaurant.
2. **Instrument Food Ready Timestamp**: Provide restaurant kitchens with a single-tap tablet button to mark orders physically packed and ready for pickup.
3. **Formal KPI Signoff**: Require the VP of Operations, Head of Support, and Data Lead to sign off on a canonical Late Delivery Rate definition.
4. **Fix Timestamp Nulls**: Audit the mobile app sync service to ensure 100% of delivered orders record `actual_delivery_at`.
