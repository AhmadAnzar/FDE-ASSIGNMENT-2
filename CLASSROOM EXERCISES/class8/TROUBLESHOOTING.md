# Pipeline Runbook & Troubleshooting Guide

This guide is for engineers running or debugging the FlashEats daily order pipeline.

---

## 1. Exit Codes & Meaning

| Exit Code | Meaning | What happened | What to do |
|---|---|---|---|
| **0** | **SUCCESS** | All stages completed. Output saved to `data/processed/run_date=YYYY-MM-DD/`. | No action needed. Output is ready for reporting. |
| **2** | **VALIDATION GATE HALT** | A critical data quality rule was broken. **Zero processed output was written.** | Inspect `logs/pipeline_YYYY-MM-DD.log` to see the exact contract violation. Fix upstream source. |
| **1** | **SYSTEM / RUNTIME ERROR** | Unhandled exception (e.g. database file missing, network down). | Check stack trace in log file. Ensure dependencies and files exist. |

---

## 2. Common Scenarios & Fixes

### Scenario A: Pipeline exits with Code 2: `missing required columns`
- **Error message in log**: `VALIDATION FAILED: orders: missing required columns: ['promised_eta']`
- **Cause**: Upstream engineering changed the schema or dropped a column.
- **Why the pipeline stopped**: Proceeding without `promised_eta` would compute wrong delay metrics and publish invalid KPIs.
- **Fix**: Verify database schema with the orders engineering team. Do not bypass the validation gate.

### Scenario B: Pipeline exits with Code 2: `Data is too stale`
- **Error message in log**: `VALIDATION FAILED: Data is too stale: latest order is X days old`
- **Cause**: The data ingestion job for the SQLite database stopped running, or an incorrect `--run-date` was passed.
- **Fix**: Check that the ingestion pipeline populated yesterday's orders. If running a historical backfill, adjust `MAX_DATA_AGE_DAYS` in your environment or `.env`.

### Scenario C: Mock Dispatch API Connection Refused (Port 8000)
- **Error message**: `Failed to establish a new connection: [WinError 10061]`
- **Cause**: Port 8000 is occupied or blocked by another process.
- **Fix**: The pipeline attempts to start `api/mock_dispatch_api.py` automatically. If port 8000 is held by an old process, terminate it:
  ```bash
  # Check if port 8000 is listening
  curl http://127.0.0.1:8000/health
  ```
  Or change `DISPATCH_API_URL` in `.env` to another port.

---

## 3. How to Inspect Logs

Every pipeline execution logs to both the terminal and a daily log file:

```text
CLASSROOM EXERCISES/class8/logs/pipeline_YYYY-MM-DD.log
```

Key log markers to look for:
- `[WARNING] Page X: HTTP 500 / 429`: Transient API retry occurred (expected occasionally).
- `[WARNING] VALIDATION WARNING`: Non-fatal warning (e.g. delivered orders without completion timestamp).
- `[ERROR] VALIDATION FAILED`: The exact contract that halted the pipeline.
