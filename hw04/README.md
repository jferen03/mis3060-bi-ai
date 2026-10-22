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
    ├── dq_summary_raw.csv         Part A - findings tagged ERROR / WARN / INFO (52)
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

| Script | What Claude Code flagged | What I did about it |
|---|---|---|
| `01_profile.py` | | |
| `02_clean.py` | | |
| `03_validate.py` | | |

## Commits

One or more commits per part, each saying what changed, e.g.
`HW4 Part C: clean 8 tables - 25 dup clients + 200 orphan txns quarantined, 198,462 cells changed, 100% RI`.
