# HW4: Cleaning the Wildcat Capital Data
MIS3060 Business Intelligence with AI | Villanova University

Audit, clean and validate the eight Wildcat Capital tables (5 dimensions, 3 facts), producing a clean copy of every table plus a full audit trail. Raw files are never modified.

## Folder structure

```
hw04/
├── README.md                      this file
├── HW04_Data_Cleaning.md          assignment instructions
├── decision_log.md                Part B - one entry per issue, written before the cleaning code
├── *.csv                          the 8 RAW tables, as downloaded (e.g. "dim_client (1).csv")
├── scripts/
│   ├── 01_profile.py   (+ .md)    Part A - generic profiler + 4 groups of DQ checks
│   ├── 02_clean.py     (+ .md)    Part C - cleaning program
│   └── 03_validate.py  (+ .md)    Part D - RI function, rules, reconciliations, IQR, scorecard
├── data/
│   ├── clean/                     8 clean tables (same names and columns, + 0/1 flag columns)
│   │   └── README_clean.md        relationships, BI column types, flags, known limitations
│   └── audit/
│       ├── cleaning_log.csv       table, issue, action, rows affected, note (24 entries)
│       ├── value_changes.csv      every changed cell: table, key, column, old, new (198,462 rows)
│       ├── quarantine_dim_client_duplicates.csv            25 rows
│       └── quarantine_fact_transactions_orphan_client.csv  200 rows
└── reports/
    ├── profile_raw.csv            Part A - one row per column (75)
    ├── dq_summary_raw.csv         Part A - 344 checks: severity ERROR/WARN/INFO + status FAIL/PASS (20 failed)
    ├── data_quality_scorecard.csv Part D - one row per table per stage (raw / clean)
    ├── validation_details.csv     Part D - every check behind the scorecard
    └── cleaning_report.md         Part E - report for the portfolio committee
```

Each `.md` file in `scripts/` is an identical, readable copy of the `.py` script next to it.

## How to run

Requires Python 3 and pandas (`pip install pandas`). Run from the `hw04` folder, in order:

```powershell
python scripts/01_profile.py     # audit raw data   -> reports/profile_raw.csv, dq_summary_raw.csv
python scripts/02_clean.py       # clean            -> data/clean/, data/audit/
python scripts/03_validate.py    # validate raw + clean -> reports/data_quality_scorecard.csv
```

- The scripts find the raw files automatically in `hw04/`, `hw04/Wildcat Capital/` or `hw04/data/raw/`, and accept browser-download names such as `dim_client (1).csv`. To point at another folder: `--data <folder>` (01, 02) or `--raw <folder>` (03).
- Every file is read as text (`dtype=str, keep_default_na=False`) and converted on purpose.
- `02_clean.py` stops with an `AssertionError` if any fix does not do what it claims; no clean files are written in that case.

## Results at a glance

| | Raw | Clean |
|---|---:|---:|
| `dim_client` rows | 2,525 | 2,500 (+25 quarantined) |
| `fact_transactions` rows | 298,772 | 298,572 (+200 quarantined) |
| Transactions % referential match | 81.95% | 100% |
| Transactions % type validity | 91.73% | 100% |
| Clients % key uniqueness | 98.02% | 100% |

All 13 relationships (10 ID-based + 3 to `dim_date`) match 100% after cleaning; raw rows = clean rows + quarantined rows for every table. Details: `reports/cleaning_report.md`.

**Scorecard definitions**
- *% completeness:* non-blank cells, where a blank that is legitimate structure (security fields on cash-flow transactions, expense ratio on stocks, sector on ETFs) counts as complete. Flag columns are excluded.
- *% key uniqueness:* rows whose ID is unique **and** whose business key is unique (e.g. one row per client per month in snapshots). An ID-only check would score raw `dim_client` 100% despite its 25 duplicate clients.
- *% type validity:* non-blank cells that parse as the column's expected type.
- *% rule pass:* passed rule evaluations / rule evaluations for that table (41 rules on both stages, plus 4 rules on the flag columns that exist only in the clean stage). It includes one rule for a known limitation (decision L08: market holidays marked as trading days), which is why `dim_date` scores 99.90% in both stages.
- *% referential match:* non-null foreign-key values found in the parent table, pooled over the table's relationships (blank for tables without foreign keys).
- *% reconciliation pass:* (extra column) rows passing the cross-column / cross-table reconciliations R1-R10, pooled per table.

`03_validate.py` writes the scorecard only after a gate passes: on the clean stage, 0 orphans on all 13 relationships, 0 failing rules and reconciliations (except the documented L08 rule), and clean >= raw on every metric.

## Process

Claude Desktop drafted each script; I ran and debugged it in VS Code; Claude Code reviewed it before each commit.

## Claude Code review findings

<!-- Fill in from your own Claude Code reviews: one row per thing it flagged. -->

### `01_profile.py` (14 findings)

| # | Sev. | What Claude Code flagged | What I did about it |
|---|---|---|---|
| 1 | Medium | The holiday check could not catch the L08 defect: 0 non-trading weekdays printed as a harmless INFO line | **Fixed.** Added a WARN that tests the fixed-date exchange holidays (Jan 1, Jul 4, Dec 25) on weekdays; it now fails on 9 of 9. The INFO line shows non-trading weekdays per year. Decision log L08 cites the new WARN. |
| 2 | Medium | `return_ytd` range `(-1, 5)` reported extreme returns as an ERROR (311 rows), duplicating the D09 WARN | **Fixed.** Range is now `>= -100%` with no upper limit (a loss can't exceed 100%; gains have no natural cap). Extreme returns are reported once, as WARN, using D09's thresholds. |
| 3 | Medium | Conclusions were hard-coded text ("blank risk_profile rows all carry one benchmark", "blanks line up exactly", "the value is right", "not a defect") | **Fixed.** Each conclusion is now computed. The D05 line says "candidate fill" only if the blank rows use exactly one benchmark that exactly one profile uses; L03 and D06 claim a match only when the counts show it; the inactive-client line no longer pre-judges. |
| 4 | Medium | A passed check looked the same as one that never ran; unparseable values dropped out silently; no assertions | **Fixed.** Every check is saved with `status` PASS / FAIL / INFO (344 checks, 290 PASS), so decision-log Part 3 traces to the file. Unparseable inputs to the fee and alpha identities are now their own ERROR (300 rows for alpha = the D06 rows). The script asserts that every column the rules use exists. **Not done:** asserting raw row counts. The profiler is generic and must run on any extract; counts are proven in `02_clean.py` (raw = clean + quarantined). |
| 5 | Low | Docstring said the profiler never reads the config, but it reads `types` | **Fixed** the comment. |
| 6 | Low | Redundant condition: mixed shapes never reported for numbers | **Fixed** (simplified to dates only). Shapes are deliberately not used for numbers: `99` vs `999` differs in digit count, not format. Numeric format problems are caught by the `n.0` and `$ , %` checks. |
| 7 | Low | `bad_signed` counted every signed mismatch, not "only reconciles when flipped" | **Fixed** (`& ~bad`). Still 836, now for the right reason. |
| 8 | Low | "Risk profile maps to >1 benchmark" summed benchmarks, not profiles | **Fixed.** Counts profiles; result 0 of 5. |
| 9 | Low | Integer-as-float was WARN in group 1 and ERROR in group 3 | **Fixed.** Both ERROR, matching D01. |
| 10 | Low | Some comparisons use raw text without strip/normalise | **Left as is.** The same script's whitespace and case-variant checks pass on every column (0 rows), so normalising would not change any result; `03_validate.py` re-checks the clean data. |
| 11 | Low | Grain wording in the log ("client + month") differs from the code (exact date) | **Fixed the log wording.** Every monthly row is dated the 1st (also a PASS check), so the two are equivalent. |
| 12 | Low | L01 compared by day, producing 930 / 858 WARNs the log calls false alarms | **Left as is, on purpose.** Part A is the raw audit; the follow-up (decision log L01) and the month-level check R8 in `03_validate.py` show the rows are legitimate. Keeping the WARN shows how the false alarm was found and resolved. |
| 13 | Low | Hard-coded dates, list and tolerances; floor = column minimum; no floor check on `fact_fees.aum_basis` | **Mostly fixed.** Date and year bounds now come from `dim_date`; Buy/Sell/Dividend is one constant; tolerances are named constants with a comment on each value; added the floor check to `fact_fees.aum_basis` (386 rows, matching D08). **Kept** "floor = repeated column minimum" so the check stays generic; it reports the value (1000.0). |
| 14 | Low | Edge cases: blank date counted as out of range, gap check hid bad dates, `(10)` sorted before `(9)`, `FINDINGS` grew on a second run, missing strip | **Fixed all five.** |

Claude Code also confirmed (no change needed): the near-duplicate check catches all 25 D03 copies; Dividend rows reconcile to shares x price; counts 836 (D07), 386 (D08) and 1,305 / 522 trading days (L08) match the decision log.

### `02_clean.py` (14 findings)

| # | Sev. | What Claude Code flagged | What I did about it |
|---|---|---|---|
| 1 | Medium | D04 check could not catch a wrong state mapping: "before" totals used the same `STATE_MAP` | **Fixed.** Asserts every target code is already used by other rows (a typo like `PA -> PN` now stops the script - tested), and the expected per-state totals are counted from the raw values before mapping. |
| 2 | Medium | D02 checks could not fail; quarantined count never checked | **Fixed.** Before quarantining, asserts the orphan IDs are clean integers (no `45.0` format problem), all above the highest client ID (2702-3192 vs 2525), with valid advisors; asserts exactly 200 rows. |
| 3 | Medium | Final RI check skipped blank keys on every relationship | **Fixed.** A blank key now fails the script unless it is `security_id` on a Deposit / Withdrawal / Advisory Fee row (decision L02). |
| 4 | Medium | Some files were written before the last checks ran | **Fixed.** All checks (each step, final checks, new pre-write checks) run first; nothing is written until every assertion passes. Tested: with a planted bug, no files are written. |
| 5 | Medium | Expected counts from the decision log were never asserted | **Fixed.** Added an `EXPECTED` table (D01 197,175 ... D09 2,639) and each step asserts its count; final checks assert 2,500 / 298,572 clean and 25 / 200 quarantined. Tested: changing D07's expected count stops the script. |
| 6 | Low | Quarantine file names and reason text differ from the log | **Fixed the log** to match the script's more descriptive names (`quarantine_dim_client_duplicates.csv`, `quarantine_fact_transactions_orphan_client.csv`) and reason text. |
| 7 | Low | Leave-as-is rows in `cleaning_log.csv` showed 0 or hand-typed counts | **Fixed.** L01-L12 are now computed from the raw tables and match the log (930 / 858, 101,597, 281 / 219, 6, 6, 4, 1,827, 176, 5, 7,350); L01 and L03 are split into two rows each (24 log entries). |
| 8 | Low | `Decimal.normalize()` can write `1E+1` | **Fixed** with `format(..., "f")`. Output unchanged on this data. |
| 9 | Low | A failed `.map()` would be written as the text `"nan"` | **Fixed.** `record_changes` asserts no missing values. |
| 10 | Low | D05's reverse mapping `{"3": "Balanced"}` was typed by hand | **Fixed.** Derived from `RISK_TO_BENCHMARK` (benchmarks owned by exactly one profile). |
| 11 | Low | Some checks pass by construction; log vs value_changes compared only in total | **Partly fixed.** `value_changes.csv` is now reconciled to `cleaning_log.csv` step by step (by table and column). **Kept** the "flagging changed a value" asserts as a cheap guard against a future edit to those steps. |
| 12 | Low | Blank checks used exact `""` | **Fixed.** All blank tests strip spaces first. |
| 13 | Low | `README_clean.md` claims advisor agreement that this script never checked; alpha not in final checks | **Fixed.** Final checks now assert advisor agreement on all three facts, the alpha identity and shares x price (all 100%). |
| 14 | Low | Repeated code: `(10)` sorted before `(9)`, globals grow on a second run, list typed 3 times | **Fixed all three** (numeric sort, lists cleared at start, one `SECURITY_TXN_TYPES` constant). |

After the fixes the clean tables, quarantine files and `value_changes.csv` are byte-for-byte identical to before; only `cleaning_log.csv` changed (leave-as-is counts). Claude Code also confirmed (no change needed): the step order matches the log, D01 / D03 / D06 / D07 / D08 reconciliations are sound, and D03 runs before D04 so the `Florida` duplicate pair still matches.

### `03_validate.py` (17 findings)

| # | Sev. | What Claude Code flagged | What I did about it |
|---|---|---|---|
| 1 | High | Only RI and key uniqueness stopped the script; failing rules or reconciliations would still pass | **Fixed.** New gate: the clean stage must have 0 failing rules and reconciliations (except the documented L08 rule), 100% completeness / key uniqueness / type validity, and clean >= raw on every metric. Tested: one wrong flag value in a copy of the clean data stops the script. |
| 2 | Medium | Rounding could hide 1-5 orphans in the pooled RI percentage | **Fixed.** The gate asserts the unrounded orphan count = 0 for each of the 13 relationships. |
| 3 | Medium | Assertions ran after the reports were written | **Fixed.** Reports are written only after the gate passes (tested: no files written on failure). |
| 4 | Medium | The flag columns added by cleaning were never checked | **Fixed.** 4 new clean-stage rules: each flag is 0/1 and equals its defining condition (`aum_floor_flag` = AUM of exactly 1,000 in snapshots and fees; `extreme_return_flag` = > +100% or < -50%; `risk_profile_imputed` = 1 only on Balanced). All pass. |
| 5 | Medium | Clean R6 was circular: the 75 imputed clients pass the rule they were filled from | **Fixed.** Imputed clients are excluded from R6 (125,605 rows tested in both stages) and reported in the note. |
| 6 | Medium | Reconciliations were not in the scorecard | **Fixed.** Added `pct_reconciliation_pass` (raw: snapshots 99.942%, transactions 99.895%; clean: 100%). |
| 7 | Medium | The "flagged does not mean wrong" sentence was hard-coded; overlap never computed | **Fixed.** The script now counts flagged values that also fail a rule or reconciliation (raw: 26 transactions, 37 snapshots, 16 clients; clean: 0 of 32,074) and builds the sentence from that count. |
| 8 | Low | L01 only partly checked (no fees, no transactions) | **Fixed.** Added R9 (no fee before the client_since month) and R10 (no transaction before client_since); both 100%. |
| 9 | Low | Limits differ from `01_profile.py` (`years_experience`, R4 tolerance) | **Fixed** `years_experience` to [0, 60] in both. **Kept** R4 at 1e-4 (vs 2e-6 in the profiler) because the 300 returns converted from `%` text only have 4 decimals; explained in a comment. |
| 10 | Low | Rule lists copied by hand across scripts | **Partly fixed.** Within this script the risk-profile rule, trade-type list and D09 thresholds are now single constants. **Not shared across scripts:** each script is meant to run on its own; the gate would fail if they disagreed on the data. |
| 11 | Low | L08 limitation invisible (`dim_date` 100%) | **Fixed.** Added the rule "fixed-date market holiday is not a trading day": 9 of 9 fail in both stages, so `dim_date` rule pass is 99.90%. It is marked as a known limitation so it does not stop the run. Committee report updated to match. |
| 12 | Low | R8 treated a blank `client_since` as present | **Fixed.** Blank values are excluded. |
| 13 | Low | Non-null count rebuilt from a rounded rate | **Fixed.** `check_referential_integrity` now also returns `non_null_keys`. |
| 14 | Low | R2 merge could fan out | **Fixed.** Asserts the snapshot grain is unique and the merge keeps one row per fee. |
| 15 | Low | `fact_transactions` had no business key | **Fixed.** Business key = every column except `txn_id`; still 100% unique. |
| 16 | Low | Text "n/a" in a numeric column; IQR printout showed the fence; non-numeric values counted as passing | **Fixed all three.** Blank instead of "n/a"; printout shows flagged counts; non-numeric values are reported as "not tested". |
| 17 | Low | `(10)` before `(9)` sort; global `DETAILS` grows | **Fixed both.** |

Claude Code also confirmed (no change needed): the RI function compares keys as stored and is reusable as written; completeness excuses structural blanks only where expected; the raw-to-clean changes are as expected.

## Commits

One or more commits per part, each saying what changed, e.g.
`HW4 Part C: clean 8 tables - 25 dup clients + 200 orphan txns quarantined, 198,462 cells changed, 100% RI`.
