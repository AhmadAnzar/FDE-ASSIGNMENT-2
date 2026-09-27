# FlashEats Classroom Investigation

## Client escalation
> “Late deliveries are increasing and customers say our ETA is unreliable. Figure out what is happening before we invest in a new AI delay-prediction system.”

## Sources
- SQLite: `database/flasheats.db` → `orders`, `customers`, `drivers`, `restaurants`
- CSV: `data/support_tickets.csv`, `restaurants.csv`, `restaurant_status.csv`
- Nested JSON: `data/driver_events.json`
- Mock Dispatch API: `/dispatch/orders?page=1&page_size=50` and `/dispatch/orders/<order_id>`

Run API:
```bash
pip install -r api/requirements.txt
python api/mock_dispatch_api.py
```

## Mission
1. Define late delivery and size the problem.
2. Investigate plausible causes using multiple sources.
3. Check retrieval completeness and reliability.
4. State what the current data cannot prove.
5. Prepare one FDE recommendation slide.

## Rules
- No ML model in the first 90 minutes.
- Preserve raw API responses.
- State exclusions and assumptions.
- If teams get different numbers, investigate why.
