# Validation Rules & Data Quality Audit

## 1. Five Core Validation Rules

The pipeline enforces five domain-specific business validation rules on the raw trip dataset. Each rule evaluates a physical or operational necessity for a completed metered taxi trip.

| # | Rule Column | Rule Logic | Failure Condition | Business Rationale | June 2026 Failures |
|---|---|---|---|---|---|
| **1** | `valid_pickup_date` | `tpep_pickup_datetime >= start` and `< end` | Pickup date outside target month | Restricts dataset strictly to trips originating in the target month; eliminates boundary / misdated vendor records | **17** |
| **2** | `valid_timestamp_order` | `tpep_dropoff_datetime > tpep_pickup_datetime` | Duration $\le 0$ minutes | Drop-off must strictly occur after pickup. Negative or zero trip duration is physically impossible for completed trips | **49,807** |
| **3** | `valid_distance` | `trip_distance > 0` | Distance $\le 0$ miles | A completed passenger trip must traverse positive physical distance | **128,106** |
| **4** | `valid_pickup_zone` | `PULocationID.isin(valid_zone_ids)` | ID not in official TLC zone table | Required for spatial attribution, zone joining, and Zone Delay Index calculations | **0** |
| **5** | `valid_dropoff_zone` | `DOLocationID.isin(valid_zone_ids)` | ID not in official TLC zone table | Required for complete trip integrity and spatial validity | **0** |

---

## 2. Combined Validation Gate & Auditability

- **Overall Valid Flag**:
  $$\text{is\_valid} = \text{rule}_1 \land \text{rule}_2 \land \text{rule}_3 \land \text{rule}_4 \land \text{rule}_5$$
- **No Silent Dropping**:
  Each rule is computed as an auditable boolean column. Records failing any rule are retained in the intermediate dataset with `is_valid = False` to permit complete failure profiling and auditability.
- **June 2026 Summary**:
  - **Raw Rows Processed**: 3,837,248
  - **Core Validation Failures (any rule)**: 176,773 (4.61%)
  - **Core Valid Rows**: 3,660,475 (95.39% Core Valid Trip Rate)

---

## 3. Secondary Analytical Filter: Total Amount

- **Filter Condition**: `total_amount > 0` applied to validated trips.
- **Rationale**: Records with `total_amount <= 0` (12,932 records in June 2026) represent credit adjustments, vendor cancellations, or meter dispute refunds rather than completed economic passenger trips.
- **Treatment of Filtered Rows**: Filtered rows are logged in [`quality_audit.csv`](file:///outputs/quality_audit.csv) and excluded from final KPI aggregation.
- **Final Analytical Dataset**: 3,647,543 rows (95.06% retention from raw).

---

## 4. Handling of Missing Zone Metadata

- TLC LocationIDs `264` and `265` correspond to `"Unknown"` / `"N/A"`.
- When joined against the zone lookup table:
  - Unknown Pickup Zones: **3,654** trips
  - Unknown Drop-off Zones: **3,389** trips
- **Treatment**: Missing zone names are explicitly filled with `"Unknown"` (`fillna('Unknown')`) and retained in the analytical dataset for system totals, but excluded from borough/zone specific delay rankings.
