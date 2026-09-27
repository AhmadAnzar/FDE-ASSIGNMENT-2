# FlashEats — Class 6 Data Validation Pack

## Today's objective

Class 5 focused on retrieving data from multiple systems.

Class 6 asks a different question:

> Can this data safely support a business decision?

The classroom case centers on the leadership claim:

> "Late Delivery Rate is 56%."

Students use the existing FlashEats sources to validate whether that metric is safe to publish.

## Start here

### Student notebook
`FlashEats_Class6_Student.ipynb`

### Instructor / shareable solution notebook
`FlashEats_Class6_Challenge_and_Solution.ipynb`

## Updated files for Class 6

- `database/flasheats.db`
- `data/restaurant_status.csv`
- `data/support_tickets.csv`
- `data/client_metric_definitions.json`

The rest of the original FlashEats structure is unchanged.

## Class 6 challenge flow

1. Can we defend the "56% late" claim?
2. Stakeholders disagree on what "late" means.
3. Validate categories without cleaning by instinct.
4. Validate cross-source integrity.
5. Treat freshness as an SLA question.
6. Build the final PASS / WARN / FAIL / UNKNOWN validation gate.

## FDE framing

The goal is not to produce a perfectly clean dataframe.

The goal is to determine:

> Is this data fit to support this decision, what remains unresolved, and who must own the unresolved business rules?
