# Wildcat Capital - clean tables

Produced by `scripts/02_clean.py` from the eight raw extracts. Raw files were not modified.
Decisions are documented in `../../decision_log.md`; every changed cell is in `../audit/value_changes.csv`.

## Files and row counts

| File | Raw rows | Clean rows | Quarantined |
|---|---:|---:|---:|
| `dim_advisor.csv` | 25 | 25 | 0 |
| `dim_benchmark.csv` | 8 | 8 | 0 |
| `dim_client.csv` | 2,525 | 2,500 | 25 |
| `dim_date.csv` | 1,827 | 1,827 | 0 |
| `dim_security.csv` | 500 | 500 | 0 |
| `fact_fees.csv` | 122,197 | 122,197 | 0 |
| `fact_portfolio_snapshot.csv` | 129,547 | 129,547 | 0 |
| `fact_transactions.csv` | 298,772 | 298,572 | 200 |

## Relationships (star schema)

All facts are many-to-one onto the dimensions. Every ID relationship matches 100% after cleaning.

| From (many) | To (one) | Note |
|---|---|---|
| `fact_fees.client_id` | `dim_client.client_id` | |
| `fact_fees.advisor_id` | `dim_advisor.advisor_id` | |
| `fact_fees.fee_date` | `dim_date.date` | monthly, always the 1st |
| `fact_portfolio_snapshot.client_id` | `dim_client.client_id` | |
| `fact_portfolio_snapshot.advisor_id` | `dim_advisor.advisor_id` | |
| `fact_portfolio_snapshot.benchmark_id` | `dim_benchmark.benchmark_id` | |
| `fact_portfolio_snapshot.snapshot_date` | `dim_date.date` | monthly, always the 1st |
| `fact_transactions.client_id` | `dim_client.client_id` | |
| `fact_transactions.advisor_id` | `dim_advisor.advisor_id` | |
| `fact_transactions.security_id` | `dim_security.security_id` | blank on Deposit / Withdrawal / Advisory Fee (34%) - structural |
| `fact_transactions.txn_date` | `dim_date.date` | daily |
| `dim_client.advisor_id` | `dim_advisor.advisor_id` | snowflake: client -> advisor |
| `dim_security.benchmark_id` | `dim_benchmark.benchmark_id` | snowflake: security -> benchmark |

Join facts to `dim_date` on the **`date`** column (YYYY-MM-DD), not on `date_id`; the facts do not carry `date_id`.
`advisor_id` appears both on the facts and on `dim_client`; they agree 100%, so use one path in the model to avoid ambiguity.
Fees and snapshots share the grain client x month; `fact_fees.aum_basis` equals the snapshot `aum` for the same client-month in 100% of rows.

## Column types for the BI tool

| Type | Columns |
|---|---|
| Whole number | every `*_id` column; `dim_client.age`; `dim_advisor.years_experience`; `dim_date.year/quarter/month/week_of_year`; `fact_portfolio_snapshot.year/month` |
| Decimal | `aum`, `aum_basis`, `initial_aum`, `amount`, `price`, `shares`, `bps_charged`, `expense_ratio_bps`, `aum_target_mm` |
| Decimal, format as % | `return_ytd`, `benchmark_return_ytd`, `active_alpha_ytd`, `cash_pct` (stored as decimals: 0.0928 = 9.28%) |
| Date | `dim_date.date`, `client_since`, `fee_date`, `snapshot_date`, `txn_date` |
| True/False | `dim_client.is_active`, `dim_security.is_etf` (text `True`/`False`); `dim_date.is_*` (0/1) |
| **Text** (must not be numeric) | `dim_client.zip_code` (leading zeros, e.g. `03897`); `primary_account_type` / `account_type` (contain `529`); `dim_advisor.certifications` |
| 0/1 flags | all columns listed below |

Read the CSVs with null handling off (`keep_default_na=False` in pandas): `dim_advisor.certifications` contains the
real value `None` (= no certifications), which pandas would otherwise turn into a missing value.

## Flag columns added

| Table | Column | 1 means | Rows = 1 |
|---|---|---|---:|
| `dim_client` | `risk_profile_imputed` | risk_profile was blank and filled with `Balanced` from the benchmark rule (all snapshots on benchmark 3) | 75 |
| `fact_portfolio_snapshot` | `aum_floor_flag` | `aum` is exactly 1,000.00, the column minimum - likely a system floor, not a market value | 420 |
| `fact_fees` | `aum_floor_flag` | `aum_basis` is exactly 1,000.00 (same client-months as above) | 386 |
| `fact_portfolio_snapshot` | `extreme_return_flag` | `return_ytd` > +100% or < -50% (benchmarks never fell below -24.0%) | 2,639 |

Suggested use: exclude `extreme_return_flag = 1` from average-return and alpha measures (or use medians);
exclude `aum_floor_flag = 1` from AUM trend analysis.

## Known limitations (not fixed, with reason)

1. **200 transactions quarantined for unknown clients** (`../audit/quarantine_fact_transactions_orphan_client.csv`, total amount $10,888,495.37).
   Their client IDs do not exist in `dim_client`; attributing them would be invented data. Firm-level transaction totals are understated by this amount.
2. **Imputed risk profiles.** 75 clients carry `Balanced` because that is how their accounts are benchmarked. If benchmark 3 was a system
   default for missing profiles, this describes the benchmark, not the client's stated risk tolerance. Use `risk_profile_imputed` to exclude them.
3. **AUM floor and extreme returns are flagged, not corrected.** There is no other source for the true AUM; the returns are internally consistent
   (alpha identity holds) but implausible.
4. **`dim_date.is_trading_day` marks every weekday as a trading day,** including market holidays (e.g. 2020-01-01). Fixing it needs an external
   exchange calendar, which is outside the provided data. Trading-day counts are overstated by roughly 9-10 days a year.
5. **7,350 client-months have a snapshot but no fee row.** Possibly fee waivers or billing gaps; a fee cannot be recomputed without inventing a rate and fee type.
6. **Monthly rows dated before `client_since`.** Snapshots and fees for the joining month are stamped the 1st, so they precede a mid-month
   `client_since`. This is a grain difference, not an error: compare at month level.
7. **`fact_transactions.shares` sign.** 835 negative Buy quantities were made positive because the amount reconciles only to |shares| x price.
   If any were meant as reversals, they are now counted as purchases (all are listed in `value_changes.csv`).
