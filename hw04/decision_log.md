# HW4 Decision Log - Wildcat Capital

**Purpose:** this log is written *before* the cleaning code. Each entry is an instruction to Claude Desktop for `scripts/02_clean.py`.
Evidence comes from `reports/dq_summary_raw.csv` (Part A; every check is listed there with `status` FAIL / PASS / INFO) plus follow-up queries on the raw files. Every number below was produced by a script, not estimated.

**Ground rules for the cleaning script**
- Read every raw file with `dtype=str, keep_default_na=False`. Never modify the raw files.
- One transformation at a time; after each one print rows affected and a before/after check, then `assert` the after-state.
- Log every changed cell to `data/audit/value_changes.csv`. Removed rows go to `data/audit/quarantine_<table>.csv`. Prove `raw = clean + quarantined` for every table.
- Flag columns are 0/1 integers and are only *added*, never replace an original column.

---

## Summary

| ID | Table / column | Issue | Decision | Rows |
|---|---|---|---|---:|
| D01 | fact_transactions.security_id | Integer key stored as `"45.0"` | convert | 197,175 |
| D02 | fact_transactions.client_id | Orphan client IDs | quarantine | 200 |
| D03 | dim_client (whole row) | Duplicate clients with typo'd last name | quarantine | 25 |
| D04 | dim_client.state | Full state names instead of USPS codes | standardize | 78 raw (77 after D03) |
| D05 | dim_client.risk_profile | Blank risk profile | fill + flag | 75 (+1 in D03) |
| D06 | fact_portfolio_snapshot.return_ytd | Text percentages like `"9.28%"` | convert | 300 |
| D07 | fact_transactions.shares | Negative shares on Buy rows | convert (sign) | 836 raw (835 after D02) |
| D08 | fact_portfolio_snapshot.aum, fact_fees.aum_basis | AUM stuck at exactly 1,000.00 | flag | 420 / 386 |
| D09 | fact_portfolio_snapshot.return_ytd | Extreme YTD returns | flag | 2,639 |
| L01 | fact_portfolio_snapshot.snapshot_date, fact_fees.fee_date | Dated before client_since | leave as is | 930 / 858 |
| L02 | fact_transactions.security_id / shares / price | Blank on cash-flow rows | leave as is | 101,597 |
| L03 | dim_security.expense_ratio_bps / sector | Blank by design | leave as is | 281 / 219 |
| L04 | dim_advisor.certifications | The word `None` | leave as is | 6 |
| L05 | dim_security.name | Same name, different securities | leave as is | 6 |
| L06 | dim_advisor first/last name | Shared names | leave as is | 4 |
| L07 | dim_client.zip_code | Leading zeros | leave as is (keep as text) | all |
| L08 | dim_date.is_trading_day | Market holidays marked as trading days | leave as is (limitation) | 1,827 |
| L09 | dim_client.is_active | Inactive clients with history | leave as is | 176 clients |
| L10 | dim_benchmark | Benchmarks not used by every fact | leave as is | 5 of 8 |
| L11 | fact_fees vs fact_portfolio_snapshot | Snapshot months with no fee row | leave as is | 7,350 |
| L12 | fact_portfolio_snapshot | Clients with fewer than 60 snapshots | leave as is | - |

**Expected row counts after cleaning**

| Table | Raw | Clean | Quarantined |
|---|---:|---:|---:|
| dim_client | 2,525 | 2,500 | 25 |
| fact_transactions | 298,772 | 298,572 | 200 |
| all other 6 tables | unchanged | unchanged | 0 |

---

## Part 1 - Defects to fix

### D01 - fact_transactions.security_id stored as float text

| Field | Entry |
|---|---|
| **Table / column** | `fact_transactions.security_id` |
| **Evidence** | **All 197,175 non-blank values** (66% of rows) look like `"45.0"`, while `dim_security.security_id` is `"45"`. A text join matches 0%. After stripping `.0`, 100% of them match `dim_security` (0 orphans). Example: txn 1 has `45.0`. |
| **Dimension violated** | Validity, Referential Integrity |
| **Decision** | **convert** - strip the trailing `.0` so the value is the integer text `"45"`. Leave the 101,597 blanks blank (see L02). |
| **Justification** | The ID is a whole number that was exported through a float column. Nothing about the security changes, only its format, and without the fix two-thirds of transactions cannot be linked to a security. |
| **Risk** | If a value had a real fractional part (`45.5`) it would be silently truncated. Mitigation: `assert` that every non-blank value matches `^\d+\.0$` before converting, and assert 100% RI match after. |

### D02 - fact_transactions.client_id points to clients that do not exist

| Field | Entry |
|---|---|
| **Table / column** | `fact_transactions.client_id` |
| **Evidence** | 200 rows, 200 distinct client IDs (2702-3192); `dim_client` only goes to 2525. Mix: 58 Buy, 38 Dividend, 35 Sell, 25 Deposit, 24 Advisory Fee, 20 Withdrawal. Total amount $10,888,495.37. Their `advisor_id`s are all valid. RI match rate for this relationship is 99.93%. |
| **Dimension violated** | Referential Integrity |
| **Decision** | **quarantine** to `data/audit/quarantine_fact_transactions.csv`, all original columns plus `quarantine_reason = "orphan client_id"`. |
| **Justification** | A transaction with no client cannot be attributed in any client, tier or risk-profile report. Inventing a client (or re-mapping to a similar ID) would be fabricating data. The rows are kept outside the clean table so they can be restored if the missing clients are found. |
| **Risk** | If `dim_client` is simply missing these clients, firm-level totals are understated by $10.9M of transaction value. That figure is stated in the report so the committee knows the size of the gap. |

### D03 - dim_client duplicate clients

| Field | Entry |
|---|---|
| **Table / column** | `dim_client` (whole row) |
| **Evidence** | 25 pairs of rows identical in all 12 non-name attributes (age, city, state, zip, tier, account type, initial_aum to the cent, client_since, advisor_id...) and the same first name. Only `last_name` differs: 23 copies drop the last letter (`Lopez` / `Lope`, `Kelly` / `Kell`), 2 add an `n` (`Lee` / `Leen`, `Pace` / `Pacen`). **Cross-table check:** the copy is always the higher ID (2501-2525) and **none of the 25 copies has a single row** in fees, snapshots or transactions; every original does. |
| **Dimension violated** | Uniqueness, Accuracy |
| **Decision** | **quarantine** the 25 copy rows (IDs 2501-2525) to `quarantine_dim_client.csv` with `quarantine_reason = "duplicate of client_id <original>"`. Keep the original. |
| **Justification** | Two people sharing every attribute including AUM to the cent is not plausible; the truncated surnames point to a data-entry or migration duplicate. Because the copies have no facts, removing them changes no transaction, fee or snapshot, and client counts become correct (2,500 = the number of clients that appear in the facts). |
| **Risk** | If a pair were genuinely two people, one real client would be dropped. Mitigation: `assert` that the quarantined IDs have 0 fact rows in every fact table before removing them. |

### D04 - dim_client.state full names

| Field | Entry |
|---|---|
| **Table / column** | `dim_client.state` |
| **Evidence** | 78 rows use the full name: Pennsylvania 25, Florida 15, New York 14, New Jersey 13, California 5, Illinois 4, Texas 2. The other 2,447 rows use 2-letter codes, including all 7 of these states. |
| **Dimension violated** | Validity, Consistency |
| **Decision** | **standardize** to USPS codes with an explicit 7-entry map (`Pennsylvania -> PA`, ...). One of the 78 (a `Florida`) belongs to duplicate client 2517, which D03 quarantines first, so 77 values are changed. |
| **Justification** | One state should be one value; otherwise a map or slicer shows "PA" and "Pennsylvania" as two places and splits the client counts. The mapping is a fixed fact, not a guess. |
| **Risk** | Very low. Mitigation: assert every state is exactly 2 letters after the change, and that the count per state equals the old code count + the old full-name count. |

### D05 - dim_client.risk_profile blank

| Field | Entry |
|---|---|
| **Table / column** | `dim_client.risk_profile` |
| **Evidence** | 76 blank (3.0%). One of them (client 2510) is a D03 duplicate copy and is quarantined, leaving 75. **Cross-table check:** in `fact_portfolio_snapshot` the benchmark follows the risk profile exactly: Aggressive / Moderately Aggressive -> 1, Balanced -> 3, Conservative / Moderately Conservative -> 8, with no exceptions. All 3,942 snapshot rows of the 75 blank-profile clients use benchmark **3**, which no profile other than Balanced uses. |
| **Dimension violated** | Completeness |
| **Decision** | **fill** with `Balanced` and add flag `risk_profile_imputed = 1` (0 for everyone else). |
| **Justification** | The firm's own benchmark assignment tells us how these accounts are being managed, so the fill is evidence-based, not a default. Without it, 75 clients drop out of every risk-profile breakdown. The flag lets anyone exclude the imputed rows. |
| **Risk** | Benchmark 3 could also be the system's fallback when the profile is missing, in which case "Balanced" describes how the account is benchmarked, not the client's actual risk tolerance. That is a suitability question compliance would need to confirm; it is listed as a limitation. |

### D06 - fact_portfolio_snapshot.return_ytd stored as percent text

| Field | Entry |
|---|---|
| **Table / column** | `fact_portfolio_snapshot.return_ytd` |
| **Evidence** | 300 rows (279 clients) hold text such as `"9.28%"` (snapshot 42); every other row is a decimal (`0.0928`). **Cross-column check:** `active_alpha_ytd = return_ytd - benchmark_return_ytd` holds for every normal row. For the 300 percent rows, `value / 100` reconciles within 0.0001 in **300 of 300**; the raw number (9.28) reconciles in 0 of 300. |
| **Dimension violated** | Validity, Consistency |
| **Decision** | **convert**: strip `%`, divide by 100. |
| **Justification** | The reconciliation proves these are the right returns in the wrong format. Left as is, they import as text (or as 9.28 = 928%) and break every average return. |
| **Risk** | Low, because each converted value is checked against benchmark + alpha. Mitigation: assert the alpha identity holds for 100% of rows after the conversion. |

### D07 - fact_transactions.shares negative on Buy rows

| Field | Entry |
|---|---|
| **Table / column** | `fact_transactions.shares` |
| **Evidence** | 836 rows with negative shares, **all `Buy`** (e.g. txn 272: shares -261.9719, price 441.71, amount 115,715.61). No Sell or Dividend row is negative. **Cross-column check:** `|shares| x price = amount` (within $0.05) for 836 of 836; with the negative sign, 0 of 836 reconcile. All amounts in the table are positive; direction is carried by `txn_type`. |
| **Dimension violated** | Validity, Consistency |
| **Decision** | **convert** to the absolute value. One of the 836 (txn 298603) belongs to an orphan client and is quarantined by D02 first, so 835 values are changed. |
| **Justification** | Amount and price both say this was a normal purchase, and the table's convention is positive quantities with the type giving direction. A negative Buy would make position and share-count totals wrong. |
| **Risk** | If a negative Buy meant a cancelled or reversed trade, flipping the sign turns a reversal into a purchase. Against that: the amount is positive and the row reconciles as a purchase. Mitigation: log all 836 changes in `value_changes.csv` and assert none remain negative. |

### D08 - AUM stuck at exactly 1,000.00

| Field | Entry |
|---|---|
| **Table / column** | `fact_portfolio_snapshot.aum`; `fact_fees.aum_basis` |
| **Evidence** | 420 snapshot rows and 386 fee rows are exactly `1000.0`, the minimum of each column. Accounts fall to the value and then climb back, e.g. client 29: 43,384 (Dec-2020) -> 16,705 -> **1,000.00 -> 1,000.00** -> 1,013 ... -> 12,453 (Aug-2021). `fact_fees.aum_basis` equals the snapshot AUM for the same client-month in 100% of rows, so the two tables agree with each other. |
| **Dimension violated** | Accuracy / Plausibility |
| **Decision** | **flag**: add `aum_floor_flag = 1` to both tables where the value is exactly 1000.0. Do not change the value. |
| **Justification** | An exact round number at the minimum looks like a system floor or placeholder, not a market value. There is no other source for the true AUM, so changing it would be inventing data. The flag lets the committee exclude these months from AUM and fee analysis. |
| **Risk** | If 1,000 is a real (if unlucky) balance, the flag is only a caution and nothing is lost. If it is a placeholder, AUM totals are slightly understated, but these rows are a negligible share of firm AUM. |

### D09 - extreme YTD returns

| Field | Entry |
|---|---|
| **Table / column** | `fact_portfolio_snapshot.return_ytd` (after D06) |
| **Evidence** | After D06: 977 rows above +100% (max 94.67 = +9,467%) and 1,662 below -50%, i.e. 2,639 rows across 252 clients. (Part A showed 976 / 1,658 because the 300 percent-text rows could not be read yet.) Benchmarks never fell below -24.0% in the same period. 37% of these 252 clients also hit the D08 floor; returns measured from a tiny base explode (client 81: AUM 1,141 -> 9,925, return_ytd 8.06). The alpha identity still holds for all of them, so they are internally consistent. |
| **Dimension violated** | Accuracy / Plausibility |
| **Decision** | **flag**: `extreme_return_flag = 1` where `return_ytd > 1.0` or `< -0.5`. Keep the value. |
| **Justification** | These are arithmetically consistent but not believable for real portfolios, and they would dominate any average return or alpha ranking. A flag lets reports exclude them or use medians without deleting history. |
| **Risk** | Thresholds are a judgment call; some flagged rows may be real (a concentrated position that crashed). Flagging, not deleting, keeps that option open. |

---

## Part 2 - Looks odd, but is legitimate structure (leave as is)

### L01 - snapshots and fees dated before client_since

| Field | Entry |
|---|---|
| **Table / column** | `fact_portfolio_snapshot.snapshot_date` (930 rows), `fact_fees.fee_date` (858 rows) vs `dim_client.client_since` |
| **Evidence** | Part A flagged these as WARN. Follow-up: each one is the snapshot or fee for **the month the client joined**: client 2 joined 2020-11-18, first snapshot 2020-11-01. For **100% of 2,500 clients**, first snapshot = the 1st of the `client_since` month (or 2020-01-01 if they joined earlier). Transactions are daily and **0** are dated before `client_since`. |
| **Dimension violated** | None (monthly grain vs daily date) |
| **Decision** | **leave as is**. Compare at month grain in `03_validate.py`. |
| **Justification** | Monthly facts are stamped on the 1st, so the first month always appears "early" against a mid-month start date. This is a grain difference, not an error. |
| **Risk** | None if the date rule is checked by month. If someone later checks at day grain, the false alarm returns, so it is documented in `README_clean.md`. |

### L02 - blank security / shares / price on cash-flow transactions

| Field | Entry |
|---|---|
| **Table / column** | `fact_transactions.security_id`, `shares`, `price` |
| **Evidence** | 101,597 blanks (34%) = exactly the Deposit (35,981) + Withdrawal (29,850) + Advisory Fee (35,766) rows. Every Buy / Sell / Dividend has all three. |
| **Dimension violated** | None |
| **Decision** | **leave as is** (blank, not 0). |
| **Justification** | A deposit has no security. Filling with 0 would create a fake security 0 and fake zero-price trades. |
| **Risk** | The RI null-key rate for security_id is 34%; reported as structural, not a failure. |

### L03 - dim_security blank expense ratio and sector

| Field | Entry |
|---|---|
| **Table / column** | `dim_security.expense_ratio_bps` (281 blank), `sector` (219 blank) |
| **Evidence** | The 281 blank expense ratios are exactly the 281 non-ETFs; the 219 blank sectors are exactly the 219 ETFs. No ETF lacks an expense ratio, no stock lacks a sector. |
| **Dimension violated** | None |
| **Decision** | **leave as is**. |
| **Justification** | Single stocks have no expense ratio; multi-sector funds have no single sector. |
| **Risk** | A BI average of expense ratio must be read as "ETF average", which is the correct meaning. |

### L04 - dim_advisor.certifications = "None"

| Field | Entry |
|---|---|
| **Table / column** | `dim_advisor.certifications` |
| **Evidence** | 6 of 25 advisors have the text `None`. Default `read_csv` turns it into NaN, making it look missing. |
| **Dimension violated** | None (real value) |
| **Decision** | **leave as is**; write it back as the text `None` and note in `README_clean.md`. |
| **Justification** | "No certifications" is a real, known answer, different from "unknown". |
| **Risk** | A tool reading with default null handling would count these advisors as missing data. Documented. |

### L05 - dim_security duplicate names

| Field | Entry |
|---|---|
| **Table / column** | `dim_security.name` |
| **Evidence** | 3 names appear twice (`Davis PLC Fund`, `Jones Inc Fund`, `Graham Group Inc.`), but each pair has different tickers, asset classes or sectors and benchmarks (e.g. RONV = Fixed Income, YMS = Alternative). |
| **Dimension violated** | None |
| **Decision** | **leave as is**. |
| **Justification** | Fund families reuse names across products; ticker is the real identifier and is 100% unique. |
| **Risk** | None. |

### L06 - dim_advisor shared names

| Field | Entry |
|---|---|
| **Table / column** | `dim_advisor.first_name`, `last_name` |
| **Evidence** | Two "Johnson"s and two "Christopher"s, but no full name repeats, and region / experience / certifications differ. |
| **Dimension violated** | None |
| **Decision** | **leave as is**. |
| **Justification** | Different people. |
| **Risk** | None. |

### L07 - dim_client.zip_code leading zeros

| Field | Entry |
|---|---|
| **Table / column** | `dim_client.zip_code` |
| **Evidence** | All 2,525 values are 5 characters; many start with 0 (e.g. `03897`). |
| **Dimension violated** | None in the raw file (it would be Validity if read as a number) |
| **Decision** | **leave as is**; keep it as text and set the column to Text in Power BI. |
| **Justification** | ZIP is a code, not a quantity. |
| **Risk** | Any numeric read turns `03897` into `3897`. Documented in `README_clean.md`. |

### L08 - dim_date.is_trading_day ignores market holidays

| Field | Entry |
|---|---|
| **Table / column** | `dim_date.is_trading_day` |
| **Evidence** | Part A WARN: 9 of 9 fixed-date exchange holidays that fall on a weekday (New Year's Day, July 4, Christmas) are flagged as trading days. 1,305 trading days = every weekday; 0 weekdays are marked non-trading in any year, so e.g. 2020-01-01 is flagged 1. All other date attributes (year, quarter, month, names, month/quarter/year end) recompute exactly from `date`. |
| **Dimension violated** | Accuracy |
| **Decision** | **leave as is**; record as a known limitation. |
| **Justification** | Fixing it needs an external exchange holiday calendar, which is outside the eight files we may use. |
| **Risk** | Trading-day counts are overstated by roughly 9-10 days a year. |

### L09 - inactive clients with history

| Field | Entry |
|---|---|
| **Table / column** | `dim_client.is_active` |
| **Evidence** | 176 inactive clients still have fees, snapshots and transactions. |
| **Dimension violated** | None |
| **Decision** | **leave as is**. |
| **Justification** | Former clients had real history; deleting it would distort past AUM and revenue. |
| **Risk** | None; reports on current clients should filter on `is_active`. |

### L10 - dimension members not used by every fact

| Field | Entry |
|---|---|
| **Table / column** | `dim_benchmark.benchmark_id` |
| **Evidence** | Snapshots use only benchmarks 1, 3 and 8; securities use 1, 2, 3, 4, 5 and 7. All 8 are used somewhere except 6 (MSCI Emerging Markets). |
| **Dimension violated** | None |
| **Decision** | **leave as is**. |
| **Justification** | A dimension can hold members with no facts. |
| **Risk** | None. |

### L11 - snapshot months with no fee row

| Field | Entry |
|---|---|
| **Table / column** | `fact_fees` vs `fact_portfolio_snapshot` |
| **Evidence** | 7,350 client-months (2,261 clients, 1-12 months each) have a snapshot but no fee. That equals the row difference 129,547 - 122,197. Every fee row has a matching snapshot. |
| **Dimension violated** | Completeness (possible) |
| **Decision** | **leave as is**. |
| **Justification** | Could be fee waivers or billing gaps; there is nothing to recompute a missing fee from without inventing a rate and fee type. |
| **Risk** | If fees were dropped by the extract, revenue is understated. Listed as a limitation. |

### L12 - clients with fewer than 60 snapshots

| Field | Entry |
|---|---|
| **Table / column** | `fact_portfolio_snapshot` |
| **Evidence** | Snapshots per client range from 5 to 60 (median 60). Fewer snapshots line up with a later `client_since` (see L01). |
| **Dimension violated** | None |
| **Decision** | **leave as is**. |
| **Justification** | Clients who joined after Jan-2020 have shorter histories. |
| **Risk** | None. |

---

## Part 3 - Checked and passed (no action)

Each row below is a `status = PASS` check in `reports/dq_summary_raw.csv` (or a reconciliation in `reports/validation_details.csv`).

| Check | Result |
|---|---|
| Primary keys unique and non-blank (all 8 tables) | Pass |
| Leading/trailing whitespace, case variants in categories | None found |
| `fact_fees.amount = aum_basis x bps_charged / 10000 / 12` | 0 mismatches |
| `active_alpha_ytd = return_ytd - benchmark_return_ytd` | 0 mismatches (excluding the 300 D06 rows, which pass after conversion) |
| `fact_fees.aum_basis` = snapshot `aum` for the same client-month | 0 mismatches |
| Fact `advisor_id` = the client's advisor in `dim_client` | 0 mismatches in all 3 facts |
| Snapshot `account_type` = client `primary_account_type` | 0 mismatches |
| Snapshot `year` / `month` agree with `snapshot_date` | 0 mismatches |
| All fact dates exist in `dim_date` | 100% |
| Grain duplicates (client + snapshot_date in snapshots, client + fee_date + fee_type in fees; every monthly row is dated the 1st, so this is the same as client + month) | 0 |

---

## Order of operations for `02_clean.py`

1. **D01** normalize `security_id` first, so every later RI check compares like with like.
2. **D03** quarantine duplicate clients **before D05**, so the duplicate copy (2510) is not imputed.
3. **D04** standardize state.
4. **D05** fill `risk_profile` + flag (needs snapshots, which are not changed by anything before it).
5. **D02** quarantine orphan transactions (after D03, so the client list is final).
6. **D07** fix share signs.
7. **D06** convert percent returns **before D09**, otherwise "9.28" would be flagged as a +928% return.
8. **D08** and **D09** add flags last, on final values.
9. Final assertions: raw = clean + quarantined per table; 100% RI on every ID relationship; alpha and fee identities hold for 100% of rows.
