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
│       ├── cleaning_log.csv       table, issue, action, rows affected, note (22 entries)
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
- *% rule pass:* passed rule evaluations / rule evaluations for that table (40 rules in total).
- *% referential match:* non-null foreign-key values found in the parent table, pooled over the table's relationships ("n/a" for tables without foreign keys).

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

### `02_clean.py`

| # | Sev. | What Claude Code flagged | What I did about it |
|---|---|---|---|
| | | | |

### `03_validate.py`

| # | Sev. | What Claude Code flagged | What I did about it |
|---|---|---|---|
| | | | |

## Commits

One or more commits per part, each saying what changed, e.g.
`HW4 Part C: clean 8 tables - 25 dup clients + 200 orphan txns quarantined, 198,462 cells changed, 100% RI`.
