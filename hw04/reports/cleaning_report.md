# Wildcat Capital: Data Cleaning Report
**To:** Portfolio Committee  |  **Re:** Quality of the 2020–2024 data warehouse extract  |  **Prepared for:** HW4, MIS3060

## Executive summary

We audited all eight tables in the extract (five dimensions, three facts; 555,401 rows in total) before they are used for reporting. The data is usable: no table needed to be rebuilt, and fees, AUM and returns reconcile with each other almost everywhere. We did find nine problems, and three of them would have produced wrong numbers in committee reports:

- **Two-thirds of transactions could not be linked to a security.** All 197,175 security IDs on trades were stored as `45.0` instead of `45`, so a join matched **0%**. After a format fix it matches **100%**.
- **25 clients were in the client list twice**, inflating the client count from 2,500 to 2,525.
- **200 transactions ($10.89M) belong to client IDs that do not exist.** These were set aside, not deleted.

After cleaning, every one of the 13 table relationships matches 100%, and every business rule and reconciliation we tested passes on the clean data, except one documented limitation: 9 market holidays in the calendar are marked as trading days (Limitation 4). Four flag columns were added so analysts can exclude suspicious AUM and return figures that we could not correct without inventing data.

## Cleaning summary

| # | Table / column | Problem found | Action | Rows |
|---|---|---|---|---:|
| D01 | Transactions: security_id | ID stored as `45.0`; 0% join to securities | Converted to `45` | 197,175 |
| D02 | Transactions: client_id | Client ID not in client list (IDs 2702–3192) | Quarantined | 200 |
| D03 | Client list | Same client entered twice; last name typo (`Lopez` / `Lope`) | Quarantined the copy | 25 |
| D04 | Client: state | Full name (`Pennsylvania`) instead of code (`PA`) | Standardized | 77 |
| D05 | Client: risk_profile | Blank | Filled `Balanced` + flagged | 75 |
| D06 | Snapshot: return_ytd | Stored as text `9.28%` | Converted to 0.0928 | 300 |
| D07 | Transactions: shares | Negative quantity on Buy trades | Made positive | 835 |
| D08 | Snapshot AUM / fee AUM basis | Exactly $1,000.00 (system floor) | Flagged, value kept | 420 / 386 |
| D09 | Snapshot: return_ytd | Above +100% (977) or below −50% (1,662) | Flagged, value kept | 2,639 |

Twelve further items looked odd but are legitimate and were left unchanged (e.g., blank security fields on deposits and withdrawals, the advisor certification value `None`, and the ZIP codes with leading zeros). Every changed cell (198,462) is logged in `data/audit/value_changes.csv`.

**Scorecard: the three tables that changed.** Cleaning did not change the other five. Four of them score 100% on every measure; the calendar scores 99.90% on rules in both stages because of the holiday limitation (Limitation 4).

| Table | Measure | Raw | Clean |
|---|---|---:|---:|
| Transactions | % referential match | 81.95% | 100% |
| Transactions | % type validity | 91.73% | 100% |
| Transactions | rows | 298,772 | 298,572 (+200 quarantined) |
| Clients | % key uniqueness | 98.02% | 100% |
| Clients | % rule pass | 99.32% | 100% |
| Clients | % completeness | 99.79% | 100% |
| Clients | rows | 2,525 | 2,500 (+25 quarantined) |
| Snapshots | % type validity | 99.98% | 100% |
| Snapshots | % rule pass | 99.97% | 100% |

For every table, raw rows = clean rows + quarantined rows.

## Key judgment calls

**1. Removing the 25 duplicate clients (D03).** *Justification:* each pair matches on all 12 other attributes, including starting AUM to the cent, and differs only by a one-letter typo in the surname. We checked the other tables before acting: none of the 25 copies has a single fee, snapshot or transaction, while every original does. Removing them changes no financial figure and corrects the client count. *Risk:* if a pair were two real people, one client would be missing. Given an identical AUM to the cent, we consider this very unlikely; both rows are kept in the quarantine file.

**2. Filling 75 blank risk profiles with "Balanced" (D05).** *Justification:* every client's benchmark follows their risk profile, and that rule held in 100% of 125,605 snapshots for clients with a known profile. All snapshots of the 75 blank-profile clients use benchmark 3, which only Balanced clients use. The fill is therefore based on how the firm manages these accounts, not on a default. *Risk:* if benchmark 3 is simply what the system assigns when the profile is missing, "Balanced" describes the benchmark, not the client's stated risk tolerance. That is a suitability question for compliance. The `risk_profile_imputed` flag lets any report exclude these clients.

**3. Flipping the sign on 835 negative Buy quantities (D07).** *Justification:* for all 835 rows, the stored dollar amount equals the positive share count × price; with the negative sign, 0 rows reconcile. The table records direction in the transaction type, not in the sign. *Risk:* if any of these were cancelled or reversed trades, they are now counted as purchases. All 835 are listed in the change log for review.

**4. Flagging, not fixing, extreme returns and the $1,000 AUM floor (D08, D09).** *Justification:* there is no second source for the true AUM, and the extreme returns are internally consistent (return − benchmark = alpha holds), so changing them would mean inventing numbers. Benchmarks never fell below −24.0%, yet 2,639 snapshots show returns above +100% or below −50%; these would dominate any average return or alpha ranking. *Risk:* the cut-offs are a judgment call, and some flagged rows may be real; that is why the values are kept.

## Limitations

1. **$10.89M of transactions (200 rows, 0.07% of transaction value) are excluded** because their clients are missing from the client list. If those clients exist, firm-level activity is understated by that amount.
2. **Imputed risk profiles** (75 clients) rely on the benchmark rule described above.
3. **AUM and return outliers are flagged, not corrected.** Reports should exclude `extreme_return_flag = 1` from averages or use medians.
4. **The calendar marks every weekday as a trading day**, including market holidays: all 9 New Year's Days, Independence Days and Christmases that fall on a weekday in 2020–2024 (e.g., 1 January 2020) are flagged as trading days. Fixing it needs an exchange holiday calendar, which is outside the data provided.
5. **7,350 client-months have a portfolio snapshot but no fee charge.** These may be fee waivers; a missing fee cannot be recreated without inventing a rate.
6. **Statistical outliers are not errors.** An IQR test flags 251 client starting balances, all of them UHNW clients, as expected for a firm with very large accounts.

---
*AI-assisted report — reviewed for factual accuracy on 10/21/2026 by Jack Ference*
