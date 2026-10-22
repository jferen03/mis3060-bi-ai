# scripts/01_profile.py

HW4 Part A - Audit. Identical copy of `scripts/01_profile.py`.

Run from the `hw04` folder:

```powershell
python scripts/01_profile.py
```

Outputs: `reports/profile_raw.csv` and `reports/dq_summary_raw.csv`

```python
"""
HW4 Part A - Audit of the Wildcat Capital raw tables
MIS3060 Business Intelligence with AI | Villanova University

What this script does
---------------------
1. PROFILE (generic): every column of every table gets the same statistics,
   with no table-specific code: blank / null-token counts, distinct count,
   dominant value shapes, inferred type and the share of values that fail to
   parse as that type, whitespace problems, mixed formats and numeric min/max.
   -> reports/profile_raw.csv

2. DQ CHECKS in four groups, driven by the TABLES / RELATIONSHIPS config below
   (rules are data, the checking functions are reusable):
     1 Column level           type, allowed values, ranges, key uniqueness
     2 Single-table rules     duplicates, near-duplicates, row contradictions
     3 Referential integrity  every FK points to an existing PK
     4 Cross-table rules      facts vs dimensions, facts vs each other
   Each finding is tagged ERROR / WARN / INFO.
   -> reports/dq_summary_raw.csv

Rule for this assignment: every file is read as TEXT
(dtype=str, keep_default_na=False) and converted on purpose.

How to run (from the hw04 folder):
    python scripts/01_profile.py
Optional: python scripts/01_profile.py --data "path/to/raw/folder"
"""

import argparse
import glob
import os
import re
import sys

import pandas as pd

# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------
HW_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # .../hw04
REPORT_DIR = os.path.join(HW_DIR, "reports")

NULL_TOKENS = {"", "none", "null", "nan", "n/a", "na", "nat", "-", "?"}
TRUE_FALSE = {"true", "false", "0", "1", "yes", "no", "t", "f", "y", "n"}

# --------------------------------------------------------------------------
# Rule configuration (data, not code). The DQ checks read all of it; the profiler
# reads only "types" (to measure parse failures against the expected type, and
# infers the type itself for any column not listed).
# type: int | float | date | bool | text
# --------------------------------------------------------------------------
TABLES = {
    "dim_advisor": {
        "pk": "advisor_id",
        "types": {"advisor_id": "int", "years_experience": "int", "aum_target_mm": "float"},
        "allowed": {"region": ["Northeast", "Mid-Atlantic", "Southeast", "Midwest", "West", "Southwest"]},
        "ranges": {"years_experience": (0, 50), "aum_target_mm": (0, 10000)},
        "required": ["advisor_id", "first_name", "last_name", "region"],
        "near_dup_cols": ["first_name", "last_name"],
    },
    "dim_benchmark": {
        "pk": "benchmark_id",
        "types": {"benchmark_id": "int"},
        "required": ["benchmark_id", "name", "asset_class", "ticker_proxy"],
        "unique": ["name", "ticker_proxy"],
    },
    "dim_client": {
        "pk": "client_id",
        "types": {"client_id": "int", "age": "int", "initial_aum": "float",
                  "client_since": "date", "advisor_id": "int", "is_active": "bool",
                  "zip_code": "text"},
        "allowed": {
            "risk_profile": ["Conservative", "Moderately Conservative", "Balanced",
                             "Moderately Aggressive", "Aggressive"],
            "client_tier": ["Retail", "HNW", "UHNW"],
            "primary_account_type": ["Taxable", "IRA", "Roth IRA", "Trust", "529"],
            "is_active": ["True", "False"],
            "state": ["AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI",
                      "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN",
                      "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH",
                      "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA",
                      "WV", "WI", "WY"],
        },
        "ranges": {"age": (18, 110), "initial_aum": (0, None),
                   "client_since": ("1990-01-01", "2024-12-31")},
        "patterns": {"zip_code": r"^\d{5}$"},
        "required": ["client_id", "first_name", "last_name", "risk_profile", "client_tier",
                     "primary_account_type", "advisor_id"],
        # same person entered twice: every attribute equal except id and (typo'd) name
        "near_dup_cols": ["age", "city", "state", "zip_code", "client_tier",
                          "primary_account_type", "initial_aum", "client_since", "advisor_id"],
    },
    "dim_date": {
        "pk": "date_id",
        "types": {"date_id": "int", "date": "date", "year": "int", "quarter": "int",
                  "month": "int", "week_of_year": "int", "is_month_end": "bool",
                  "is_quarter_end": "bool", "is_year_end": "bool", "is_trading_day": "bool"},
        "ranges": {"quarter": (1, 4), "month": (1, 12), "week_of_year": (1, 53),
                   "date": ("2020-01-01", "2024-12-31")},
        "unique": ["date"],
        "required": ["date_id", "date"],
    },
    "dim_security": {
        "pk": "security_id",
        "types": {"security_id": "int", "benchmark_id": "int", "is_etf": "bool",
                  "expense_ratio_bps": "float"},
        "allowed": {"asset_class": ["Equity", "Fixed Income", "Alternative", "Cash Equivalent"],
                    "is_etf": ["True", "False"]},
        "ranges": {"expense_ratio_bps": (0, 300)},
        "unique": ["ticker"],
        "required": ["security_id", "ticker", "name", "asset_class", "benchmark_id", "is_etf"],
        "near_dup_cols": ["name"],
    },
    "fact_fees": {
        "pk": "fee_id",
        "types": {"fee_id": "int", "client_id": "int", "advisor_id": "int", "fee_date": "date",
                  "aum_basis": "float", "bps_charged": "float", "amount": "float"},
        "allowed": {"fee_type": ["Management", "Advisory", "Custodial", "Performance"]},
        "ranges": {"aum_basis": (0, None), "bps_charged": (0, 300), "amount": (0, None)},
        "required": ["fee_id", "client_id", "advisor_id", "fee_date", "fee_type", "amount"],
        "grain": ["client_id", "fee_date", "fee_type"],
    },
    "fact_portfolio_snapshot": {
        "pk": "snapshot_id",
        "types": {"snapshot_id": "int", "client_id": "int", "advisor_id": "int",
                  "benchmark_id": "int", "snapshot_date": "date", "year": "int", "month": "int",
                  "aum": "float", "return_ytd": "float", "benchmark_return_ytd": "float",
                  "active_alpha_ytd": "float", "cash_pct": "float"},
        "allowed": {"account_type": ["Taxable", "IRA", "Roth IRA", "Trust", "529"]},
        "ranges": {"aum": (0, None), "return_ytd": (-1, None), "benchmark_return_ytd": (-1, None),
                   "cash_pct": (0, 1), "month": (1, 12), "year": (2020, 2024)},
        "required": ["snapshot_id", "client_id", "advisor_id", "benchmark_id", "snapshot_date", "aum"],
        "grain": ["client_id", "snapshot_date"],
    },
    "fact_transactions": {
        "pk": "txn_id",
        "types": {"txn_id": "int", "client_id": "int", "advisor_id": "int", "security_id": "int",
                  "txn_date": "date", "shares": "float", "price": "float", "amount": "float"},
        "allowed": {"txn_type": ["Buy", "Sell", "Dividend", "Deposit", "Withdrawal", "Advisory Fee"]},
        "ranges": {"price": (0, None), "amount": (0, None), "shares": (0, None)},
        "required": ["txn_id", "client_id", "advisor_id", "txn_date", "txn_type", "amount"],
    },
}

# (fact table, fact column, dim table, dim column)
RELATIONSHIPS = [
    ("dim_client", "advisor_id", "dim_advisor", "advisor_id"),
    ("dim_security", "benchmark_id", "dim_benchmark", "benchmark_id"),
    ("fact_fees", "client_id", "dim_client", "client_id"),
    ("fact_fees", "advisor_id", "dim_advisor", "advisor_id"),
    ("fact_portfolio_snapshot", "client_id", "dim_client", "client_id"),
    ("fact_portfolio_snapshot", "advisor_id", "dim_advisor", "advisor_id"),
    ("fact_portfolio_snapshot", "benchmark_id", "dim_benchmark", "benchmark_id"),
    ("fact_transactions", "client_id", "dim_client", "client_id"),
    ("fact_transactions", "advisor_id", "dim_advisor", "advisor_id"),
    ("fact_transactions", "security_id", "dim_security", "security_id"),
    # date relationships
    ("fact_fees", "fee_date", "dim_date", "date"),
    ("fact_portfolio_snapshot", "snapshot_date", "dim_date", "date"),
    ("fact_transactions", "txn_date", "dim_date", "date"),
]

# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------
def find_file(data_dir, table):
    """Find table.csv, tolerating browser-download suffixes like 'table (2).csv'."""
    exact = os.path.join(data_dir, table + ".csv")
    if os.path.exists(exact):
        return exact
    hits = glob.glob(os.path.join(data_dir, glob.escape(table) + " (*).csv"))
    # sort by the number in "(n)" so "(10)" comes after "(9)"
    hits = sorted(hits, key=lambda h: int(re.search(r"\((\d+)\)\.csv$", h).group(1)))
    if len(hits) > 1:
        print(f"  WARNING: several files match {table}; using {os.path.basename(hits[-1])}")
    return hits[-1] if hits else None


def load_tables(data_dir):
    tables = {}
    for t in TABLES:
        path = find_file(data_dir, t)
        if path is None:
            sys.exit(f"Could not find {t}.csv in {data_dir}")
        tables[t] = pd.read_csv(path, dtype=str, keep_default_na=False)
        print(f"  loaded {t:<26} {len(tables[t]):>8,} rows x {tables[t].shape[1]:>2} cols"
              f"  <- {os.path.basename(path)}")
    return tables


# --------------------------------------------------------------------------
# Generic helpers
# --------------------------------------------------------------------------
INT_RE = re.compile(r"^[+-]?\d+$")
INT_AS_FLOAT_RE = re.compile(r"^[+-]?\d+\.0+$")
FLOAT_RE = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$")
ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def shape(v):
    """Value 'shape': digits -> 9, letter runs -> A. '2020-01-05' -> '9999-99-99'."""
    return re.sub(r"[A-Za-z]+", "A", re.sub(r"\d", "9", v))


def is_null(s):
    return s.str.strip().str.lower().isin(NULL_TOKENS)


def parse_ok(s, typ):
    """Boolean Series: does each (non-null) value parse as typ?"""
    s = s.str.strip()
    if typ == "int":
        return s.str.match(INT_RE)
    if typ == "float":
        return s.str.match(FLOAT_RE)
    if typ == "date":
        return s.str.match(ISO_DATE_RE) & pd.to_datetime(s, format="%Y-%m-%d", errors="coerce").notna()
    if typ == "bool":
        return s.str.lower().isin(TRUE_FALSE)
    return pd.Series(True, index=s.index)


def infer_type(s):
    """Pick the narrowest type that parses >= 95% of non-null values."""
    vals = s[~is_null(s)]
    if vals.empty:
        return "text"
    if vals.str.strip().str.lower().isin(TRUE_FALSE).mean() >= 0.95 and vals.nunique() <= 2:
        return "bool"
    for typ in ("int", "float", "date"):
        if parse_ok(vals, typ).mean() >= 0.95:
            # leading-zero codes (zip codes, account numbers) are text, not numbers
            if typ == "int" and vals.str.strip().str.match(r"^0\d").any():
                return "text"
            return typ
    # IDs stored as '45.0' are integers in disguise
    if (vals.str.match(INT_RE) | vals.str.match(INT_AS_FLOAT_RE)).mean() >= 0.95:
        return "int"
    return "text"


def to_num(s):
    return pd.to_numeric(s.str.strip(), errors="coerce")


def norm_id(s):
    """'45.0' -> '45', ' 45 ' -> '45' so keys compare as the same text."""
    return s.str.strip().str.replace(r"\.0+$", "", regex=True)


# --------------------------------------------------------------------------
# 1. Generic profile
# --------------------------------------------------------------------------
def profile_table(name, df, expected_types=None):
    expected_types = expected_types or {}
    rows = []
    n = len(df)
    for col in df.columns:
        s = df[col]
        null_mask = is_null(s)
        blank = int((s.str.strip() == "").sum())
        null_tokens = int(null_mask.sum()) - blank
        vals = s[~null_mask]
        inferred = infer_type(s)
        expected = expected_types.get(col, inferred)
        fail = int((~parse_ok(vals, expected)).sum()) if len(vals) else 0

        shapes = vals.map(shape).value_counts()
        top_shapes = "; ".join(f"{k} ({v / max(len(vals), 1):.0%})" for k, v in shapes.head(3).items())
        n_shapes_1pct = int((shapes / max(len(vals), 1) >= 0.01).sum())

        lead_trail = int((s != s.str.strip()).sum())
        dbl_space = int(s.str.contains(r"\s{2,}", regex=True).sum())
        # same value spelled differently (case / spacing) e.g. 'Equity' vs 'equity '
        canon = vals.str.strip().str.lower().str.replace(r"\s+", " ", regex=True)
        case_variants = int(vals.nunique() - canon.nunique())
        int_as_float = int(vals.str.match(INT_AS_FLOAT_RE).sum()) if expected == "int" else 0

        mixed = []
        # shapes only signal mixed formats for dates; numbers differ in digit count naturally
        if expected == "date" and n_shapes_1pct > 1:
            mixed.append(f"{n_shapes_1pct} date shapes")
        if int_as_float:
            mixed.append(f"{int_as_float} ints stored as 'n.0'")
        if case_variants:
            mixed.append(f"{case_variants} case/space variants")
        if expected in ("int", "float") and vals.str.contains(r"[$,%]", regex=True).any():
            mixed.append("contains $ , or %")

        num_min = num_max = num_mean = ""
        if expected in ("int", "float"):
            nums = to_num(vals.str.replace(r"[$,%]", "", regex=True))
            if nums.notna().any():
                num_min, num_max, num_mean = nums.min(), nums.max(), round(nums.mean(), 4)
        elif expected == "date":
            d = vals[parse_ok(vals, "date")].str.strip()
            if len(d):
                num_min, num_max = d.min(), d.max()

        lens = vals.str.len()
        if expected == "text" and len(lens) and lens.max() > 0:
            # e.g. state 'PA' (len 2) mixed with 'Pennsylvania' (len 12)
            common = lens.mode().iloc[0]
            off = int((lens != common).sum())
            if lens.nunique() > 1 and off / len(lens) < 0.10 and lens.nunique() <= 20:
                mixed.append(f"{off} values differ from the usual length {common}")

        top_vals = "; ".join(f"{k} ({v})" for k, v in s.value_counts().head(5).items())
        rows.append({
            "table": name, "column": col, "rows": n,
            "blank_count": blank, "null_token_count": null_tokens,
            "null_pct": round(null_mask.mean() * 100, 2),
            "distinct_count": int(s.nunique()),
            "distinct_pct": round(s.nunique() / max(n, 1) * 100, 2),
            "inferred_type": inferred, "expected_type": expected,
            "parse_fail_count": fail,
            "parse_fail_pct": round(fail / max(len(vals), 1) * 100, 2),
            "top_shapes": top_shapes, "n_shapes_ge_1pct": n_shapes_1pct,
            "leading_trailing_ws": lead_trail, "double_space": dbl_space,
            "case_space_variants": case_variants, "int_stored_as_float": int_as_float,
            "mixed_formats": "; ".join(mixed),
            "min": num_min, "max": num_max, "mean": num_mean,
            "text_len_min": int(lens.min()) if len(lens) else "",
            "text_len_max": int(lens.max()) if len(lens) else "",
            "top_values": top_vals,
        })
    return rows


# --------------------------------------------------------------------------
# DQ findings collector
# --------------------------------------------------------------------------
FINDINGS = []

# Tolerances for recomputed values (half a unit of the stored precision, rounded up):
TOL_CENTS = 0.02         # money stored to 2 decimals (fees); allows rounding of a product
TOL_TRADE = 0.05         # trade amount = shares (4 dp) x price (2 dp): rounding error up to ~$0.05
TOL_RETURN_EXACT = 2e-6  # returns stored to 6 dp: a - b - c can be off by 1.5e-6 from rounding
TOL_RETURN_PCT = 1e-4    # '9.28%' has only 2 dp of a percent = 4 dp of a decimal
SECURITY_TXN_TYPES = ["Buy", "Sell", "Dividend"]


def add(group, table, column, check, severity, affected, total, detail, examples=None):
    """Record every check, passed or not. status=PASS means 0 rows affected, so a check
    that ran and passed is visible and different from a check that never ran."""
    if severity == "INFO":
        status = "INFO"
    else:
        status = "FAIL" if affected else "PASS"
    FINDINGS.append({
        "check_group": group, "table": table, "column": column, "check": check,
        "severity": severity, "status": status, "rows_affected": int(affected), "total_rows": int(total),
        "pct_affected": round(affected / max(total, 1) * 100, 3),
        "detail": detail,
        "examples": "" if examples is None else "; ".join(str(x) for x in list(examples)[:5]),
    })


def examples_of(df, mask, cols):
    cols = list(dict.fromkeys(cols))          # drop repeated column names
    sub = df.loc[mask, cols].head(5).astype(str)
    return [" | ".join(row) for row in sub.itertuples(index=False, name=None)]


# --------------------------------------------------------------------------
# Group 1 - column level
# --------------------------------------------------------------------------
def column_checks(name, df, spec):
    n = len(df)
    g = "1 Column level"
    pk = spec.get("pk")

    # primary key
    if pk:
        k = norm_id(df[pk])
        nulls = is_null(df[pk]).sum()
        add(g, name, pk, "PK null", "ERROR", nulls, n, "primary key is blank")
        dups = k.duplicated(keep=False) & ~is_null(df[pk])
        add(g, name, pk, "PK not unique", "ERROR", dups.sum(), n,
            f"{k[dups].nunique()} key values repeat", k[dups].unique()[:5])
    for col in spec.get("unique", []):
        dups = df[col].duplicated(keep=False) & ~is_null(df[col])
        add(g, name, col, "alternate key not unique", "WARN", dups.sum(), n,
            f"{df.loc[dups, col].nunique()} values repeat", df.loc[dups, col].unique()[:5])

    # required columns
    for col in spec.get("required", []):
        m = is_null(df[col])
        add(g, name, col, "required value missing", "ERROR" if col.endswith("_id") else "WARN",
            m.sum(), n, "blank or null token in a required column",
            examples_of(df, m, [pk, col]) if pk else None)

    # types
    for col, typ in spec.get("types", {}).items():
        vals = df[col]
        nn = ~is_null(vals)
        bad = nn & ~parse_ok(vals, typ)
        if typ == "int":
            as_float = nn & vals.str.strip().str.match(INT_AS_FLOAT_RE)
            add(g, name, col, "integer stored as float text", "ERROR", as_float.sum(), n,
                "values like '45.0' - will not match integer keys as text and import as decimal",
                vals[as_float].unique()[:5])
            bad = bad & ~as_float
        add(g, name, col, f"type invalid ({typ})", "ERROR", bad.sum(), n,
            f"value does not parse as {typ}", vals[bad].unique()[:5])
        if typ == "text" and vals.str.match(r"^\d+$").mean() > 0.5:
            lz = vals.str.match(r"^0\d")
            add(g, name, col, "leading-zero code", "INFO", lz.sum(), n,
                "numeric-looking code with leading zeros: must stay text (default read_csv drops them)",
                vals[lz].unique()[:5])

    # whitespace (all columns)
    for col in df.columns:
        m = df[col] != df[col].str.strip()
        add(g, name, col, "leading/trailing whitespace", "WARN", m.sum(), n,
            "breaks equality joins and group-bys", df.loc[m, col].map(repr).unique()[:5])

    # allowed values (exact, then case-insensitive to separate typos from casing)
    for col, allowed in spec.get("allowed", {}).items():
        v = df[col]
        nn = ~is_null(v)
        bad = nn & ~v.isin(allowed)
        if bad.any():
            lower_ok = v.str.strip().str.lower().isin([a.lower() for a in allowed])
            casing = bad & lower_ok
            add(g, name, col, "allowed values - case/space variant", "WARN", casing.sum(), n,
                "value is valid apart from case or spacing", v[casing].unique()[:5])
            add(g, name, col, "allowed values - not in list", "ERROR", (bad & ~lower_ok).sum(), n,
                f"allowed: {allowed[:8]}", v[bad & ~lower_ok].unique()[:5])
        # domain summary is always useful
        add(g, name, col, "domain observed", "INFO", 0, n,
            "; ".join(f"{k}={c}" for k, c in v.value_counts().head(10).items()))

    # ranges
    for col, (lo, hi) in spec.get("ranges", {}).items():
        typ = spec.get("types", {}).get(col, "float")
        v = df[col]
        if typ == "date":
            x = pd.to_datetime(v, format="%Y-%m-%d", errors="coerce")
            lo_, hi_ = pd.Timestamp(lo) if lo else None, pd.Timestamp(hi) if hi else None
        else:
            x = to_num(v)
            lo_, hi_ = lo, hi
        bad = pd.Series(False, index=df.index)
        if lo_ is not None:
            bad |= x < lo_
        if hi_ is not None:
            bad |= x > hi_
        add(g, name, col, f"out of range [{lo}, {hi}]", "ERROR", bad.sum(), n,
            f"observed min {x.min()} max {x.max()}", examples_of(df, bad, [spec['pk'], col]))

    # patterns
    for col, pat in spec.get("patterns", {}).items():
        v = df[col]
        bad = ~is_null(v) & ~v.str.strip().str.match(pat)
        add(g, name, col, f"pattern {pat}", "ERROR", bad.sum(), n,
            "value does not match expected format", v[bad].unique()[:5])

    # null tokens that read_csv would silently turn into NaN
    for col in df.columns:
        tok = df[col].str.strip().str.lower().isin(NULL_TOKENS - {""})
        if tok.any():
            add(g, name, col, "null-like token stored as text", "INFO", tok.sum(), n,
                "word such as 'None'/'NULL' - default read_csv turns it into NaN; "
                "decide if it means missing or is a real value",
                df.loc[tok, col].unique()[:5])


# --------------------------------------------------------------------------
# Group 2 - single-table rules
# --------------------------------------------------------------------------
def single_table_checks(name, df, spec):
    n = len(df)
    g = "2 Single-table"
    pk = spec.get("pk")
    non_pk = [c for c in df.columns if c != pk]

    # exact duplicate rows (ignoring surrogate key)
    canon = df[non_pk].apply(lambda c: c.str.strip().str.lower())
    d = canon.duplicated(keep=False)
    add(g, name, "(all non-key)", "exact duplicate rows", "ERROR", d.sum(), n,
        "rows identical in every column except the surrogate key", examples_of(df, d, [pk]))

    # grain duplicates (one row expected per grain)
    if "grain" in spec:
        gd = df.duplicated(spec["grain"], keep=False)
        add(g, name, "+".join(spec["grain"]), "grain duplicate", "ERROR", gd.sum(), n,
            f"more than one row per {spec['grain']}", examples_of(df, gd, [pk] + spec["grain"]))

    # near-duplicates
    if "near_dup_cols" in spec:
        cols = spec["near_dup_cols"]
        key = df[cols].apply(lambda c: c.str.strip().str.lower())
        nd = key.duplicated(keep=False) & ~d
        groups = key[nd].astype(str).agg("|".join, axis=1).nunique()
        add(g, name, "+".join(cols), "near-duplicate rows", "WARN", nd.sum(), n,
            f"{groups} groups of rows that match on {cols} but have different keys"
            " - possible same entity entered twice",
            examples_of(df, nd, df.columns[:4].tolist()))


def row_contradictions(t):
    """Values that contradict other columns of the same row."""
    g = "2 Single-table"

    # dim_date: derived attributes must agree with the date itself
    dd = t["dim_date"]
    d = pd.to_datetime(dd["date"], format="%Y-%m-%d", errors="coerce")
    checks = {
        "year": d.dt.year.astype("Int64").astype(str),
        "month": d.dt.month.astype("Int64").astype(str),
        "quarter": d.dt.quarter.astype("Int64").astype(str),
        "month_name": d.dt.month_name(),
        "day_of_week": d.dt.day_name(),
        "is_month_end": d.dt.is_month_end.astype(int).astype(str),
        "is_quarter_end": d.dt.is_quarter_end.astype(int).astype(str),
        "is_year_end": d.dt.is_year_end.astype(int).astype(str),
    }
    for col, expect in checks.items():
        bad = norm_id(dd[col]) != expect
        add(g, "dim_date", col, "derived attribute disagrees with date", "ERROR", bad.sum(), len(dd),
            "recomputed from the date column", examples_of(dd, bad, ["date", col]))
    weekend = d.dt.dayofweek >= 5
    bad = weekend & (dd["is_trading_day"] == "1")
    add(g, "dim_date", "is_trading_day", "weekend marked as trading day", "ERROR", bad.sum(), len(dd),
        "Saturday/Sunday flagged 1", examples_of(dd, bad, ["date", "day_of_week"]))
    hol = (~weekend) & (dd["is_trading_day"].str.strip() == "0")
    per_year = hol.groupby(d.dt.year).sum()
    add(g, "dim_date", "is_trading_day", "weekday marked non-trading (market holidays)", "INFO", hol.sum(), len(dd),
        f"per year: {per_year.to_dict()} - US exchanges close about 9-10 weekdays a year")
    # fixed-date exchange holidays that fall on a weekday must not be trading days
    fixed = d.dt.strftime("%m-%d").isin(["01-01", "07-04", "12-25"]) & ~weekend
    bad = fixed & (dd["is_trading_day"].str.strip() == "1")
    add(g, "dim_date", "is_trading_day", "fixed-date market holiday marked as trading day", "WARN",
        bad.sum(), int(fixed.sum()),
        f"New Year's Day / July 4 / Christmas on a weekday flagged 1; years with < 5 non-trading weekdays: "
        f"{int((per_year < 5).sum())} of {len(per_year)}", examples_of(dd, bad, ["date", "day_of_week"]))
    add(g, "dim_date", "date", "unparseable calendar date", "ERROR", int(d.isna().sum()), len(dd), "")
    gaps = d.dropna().sort_values().diff().dt.days.iloc[1:]
    add(g, "dim_date", "date", "calendar gap", "ERROR", int((gaps != 1).sum()), len(dd),
        "calendar table should have one row per day with no gaps")

    # dim_security: ETF attributes must be consistent
    s = t["dim_security"]
    etf = s["is_etf"].str.strip().str.lower().isin(["true", "1"])
    has_er = ~is_null(s["expense_ratio_bps"])
    has_sector = ~is_null(s["sector"])
    add(g, "dim_security", "expense_ratio_bps", "ETF without expense ratio", "ERROR",
        (etf & ~has_er).sum(), len(s), "every ETF should carry an expense ratio")
    add(g, "dim_security", "expense_ratio_bps", "non-ETF with expense ratio", "WARN",
        (~etf & has_er).sum(), len(s), "single stocks have no expense ratio")
    add(g, "dim_security", "expense_ratio_bps / sector", "blank is structural (not a defect)", "INFO",
        int((~etf & ~has_er).sum() + (etf & ~has_sector).sum()), len(s),
        f"non-ETFs w/o expense ratio: {(~etf & ~has_er).sum()}; ETFs w/o sector: {(etf & ~has_sector).sum()}"
        + (" - blanks line up exactly with is_etf, so they are legitimate structure"
           if (etf & ~has_er).sum() == 0 and (~etf & has_er).sum() == 0 and (~etf & ~has_sector).sum() == 0
           else " - blanks do NOT line up exactly with is_etf: see the ETF/stock findings above"))
    add(g, "dim_security", "sector", "stock without sector", "WARN", (~etf & ~has_sector).sum(), len(s),
        "single stocks should have a GICS sector")

    # fact_fees: amount = aum_basis * bps / 10000 / 12 (monthly fee)
    f = t["fact_fees"]
    calc = to_num(f["aum_basis"]) * to_num(f["bps_charged"]) / 10000 / 12
    diff = (calc - to_num(f["amount"])).abs()
    bad = diff > TOL_CENTS
    add(g, "fact_fees", "amount", "fee identity not checkable (unparseable inputs)", "ERROR", int(diff.isna().sum()),
        len(f), "rows where aum_basis, bps_charged or amount is not a number are reported here, not skipped")
    add(g, "fact_fees", "amount", "amount != aum_basis x bps / 10000 / 12", "ERROR", bad.sum(), len(f),
        f"max abs difference {diff.max():.4f}", examples_of(f, bad, ["fee_id", "aum_basis", "bps_charged", "amount"]))

    # fact_portfolio_snapshot: year/month vs date; alpha = return - benchmark
    p = t["fact_portfolio_snapshot"]
    pdte = pd.to_datetime(p["snapshot_date"], format="%Y-%m-%d", errors="coerce")
    bad = (norm_id(p["year"]) != pdte.dt.year.astype("Int64").astype(str)) | \
          (norm_id(p["month"]) != pdte.dt.month.astype("Int64").astype(str))
    add(g, "fact_portfolio_snapshot", "year / month", "year/month disagree with snapshot_date", "ERROR",
        bad.sum(), len(p), "", examples_of(p, bad, ["snapshot_id", "snapshot_date", "year", "month"]))
    add(g, "fact_portfolio_snapshot", "snapshot_date", "snapshot not on 1st of month", "WARN",
        (pdte.dt.day != 1).sum(), len(p), "monthly snapshots are dated the 1st")
    alpha = to_num(p["return_ytd"]) - to_num(p["benchmark_return_ytd"]) - to_num(p["active_alpha_ytd"])
    bad = alpha.abs() > TOL_RETURN_EXACT
    add(g, "fact_portfolio_snapshot", "active_alpha_ytd", "alpha identity not checkable (unparseable inputs)",
        "ERROR", int(alpha.isna().sum()), len(p), "see the percent-formatted text finding below")
    add(g, "fact_portfolio_snapshot", "active_alpha_ytd", "alpha != return_ytd - benchmark_return_ytd",
        "ERROR", bad.sum(), len(p), f"max abs difference {alpha.abs().max():.2e} (parseable rows)",
        examples_of(p, bad, ["snapshot_id", "return_ytd", "benchmark_return_ytd", "active_alpha_ytd"]))
    # percent-formatted text ('9.28%'): does value/100 reconcile with bench + alpha?
    pct = p["return_ytd"].str.strip().str.endswith("%")
    pct_val = to_num(p["return_ytd"].str.replace("%", "", regex=False)) / 100
    recon = (pct_val - to_num(p["benchmark_return_ytd"]) - to_num(p["active_alpha_ytd"])).abs() <= TOL_RETURN_PCT
    n_ok = int((pct & recon).sum())
    add(g, "fact_portfolio_snapshot", "return_ytd", "percent-formatted text ('n%')", "ERROR", pct.sum(), len(p),
        f"{n_ok} of {pct.sum()} reconcile to benchmark + alpha after stripping % and /100"
        + (" - so the value is right, only the format is wrong" if n_ok == pct.sum()
           else f" - {pct.sum() - n_ok} do NOT reconcile, so the value itself may be wrong"),
        examples_of(p, pct, ["snapshot_id", "return_ytd", "benchmark_return_ytd", "active_alpha_ytd"]))
    r = to_num(p["return_ytd"])
    big = r > 1
    add(g, "fact_portfolio_snapshot", "return_ytd", "implausible YTD gain (> +100%)", "WARN", big.sum(), len(p),
        f"{p.loc[big, 'client_id'].nunique()} clients; max {r.max():.2f}. Check whether these accounts have a"
        " tiny AUM base (see aum floor finding)",
        examples_of(p, big, ["snapshot_id", "client_id", "snapshot_date", "aum", "return_ytd"]))
    bad = r < -0.5
    add(g, "fact_portfolio_snapshot", "return_ytd", "implausible YTD loss (< -50%)", "WARN", bad.sum(), len(p),
        f"{p.loc[bad, 'client_id'].nunique()} clients; benchmarks never fell below "
        f"{to_num(p['benchmark_return_ytd']).min():.1%}",
        examples_of(p, bad, ["snapshot_id", "client_id", "snapshot_date", "aum", "return_ytd"]))
    # a floor = the column minimum repeated many times (a real market value rarely repeats to the cent)
    for tname, col, keycols in [("fact_portfolio_snapshot", "aum", ["snapshot_id", "client_id", "snapshot_date"]),
                                ("fact_fees", "aum_basis", ["fee_id", "client_id", "fee_date"])]:
        df = t[tname]
        a = to_num(df[col])
        floor = a == a.min()
        sev = "WARN" if floor.sum() >= 10 else "INFO"
        add(g, tname, col, f"{col} sitting at a floor value", sev, floor.sum(), len(df),
            f"{floor.sum()} rows exactly {a.min()} - looks like a system floor/placeholder, not a market value",
            examples_of(df, floor, keycols + [col]))

    # fact_transactions: trade fields present only for security transactions; amount = shares x price
    x = t["fact_transactions"]
    typ = x["txn_type"].str.strip()
    sec_types = typ.isin(SECURITY_TXN_TYPES)
    has_sec = ~is_null(x["security_id"])
    has_sp = ~is_null(x["shares"]) & ~is_null(x["price"])
    add(g, "fact_transactions", "security_id", "security trade missing security/shares/price", "ERROR",
        (sec_types & ~(has_sec & has_sp)).sum(), len(x), "Buy/Sell/Dividend need security, shares and price")
    add(g, "fact_transactions", "security_id", "cash flow carries security/shares/price", "WARN",
        (~sec_types & (has_sec | has_sp)).sum(), len(x), "Deposit/Withdrawal/Advisory Fee should not")
    add(g, "fact_transactions", "security_id / shares / price", "blank is structural (not a defect)", "INFO",
        (~sec_types & ~has_sec).sum(), len(x),
        "Deposit / Withdrawal / Advisory Fee rows have no security - legitimate, keep as blank")
    sh, pr, am = to_num(x["shares"]), to_num(x["price"]), to_num(x["amount"])
    neg = sh < 0
    add(g, "fact_transactions", "shares", "negative shares", "ERROR", neg.sum(), len(x),
        "by txn_type: " + str(typ[neg].value_counts().to_dict()) +
        " - direction is carried by txn_type, amount is positive",
        examples_of(x, neg, ["txn_id", "txn_type", "shares", "price", "amount"]))
    diff = (sh.abs() * pr - am).abs()
    bad = sec_types & (diff > TOL_TRADE)
    add(g, "fact_transactions", "amount", "amount != |shares| x price", "ERROR", bad.sum(), len(x),
        f"max abs difference {diff[sec_types].max():.2f}",
        examples_of(x, bad, ["txn_id", "txn_type", "shares", "price", "amount"]))
    bad_signed = sec_types & ((sh * pr - am).abs() > TOL_TRADE) & ~bad   # fails signed, passes with |shares|
    add(g, "fact_transactions", "amount", "amount != shares x price (signed)", "INFO", bad_signed.sum(), len(x),
        "rows where the stored amount only reconciles if the shares sign is flipped "
        "- evidence that the negative sign, not the amount, is the error")


# --------------------------------------------------------------------------
# Group 3 - referential integrity
# --------------------------------------------------------------------------
def ri_checks(t):
    g = "3 Referential integrity"
    for ft, fk, dt, dk in RELATIONSHIPS:
        f, d = t[ft], t[dt]
        fv, dv = norm_id(f[fk]), set(norm_id(d[dk]))
        nullk = is_null(f[fk])
        orphan = ~nullk & ~fv.isin(dv)
        nonnull = (~nullk).sum()
        match = 1 - orphan.sum() / max(nonnull, 1)
        detail = (f"{ft}.{fk} -> {dt}.{dk}: match rate {match:.2%}, "
                  f"{fv[orphan].nunique()} distinct orphan keys, null-key rate {nullk.mean():.2%}")
        add(g, ft, fk, f"orphan FK -> {dt}", "ERROR", orphan.sum(), len(f), detail,
            sorted(fv[orphan].unique(), key=lambda v: (len(v), v))[:5])
        raw_float = ~nullk & f[fk].str.strip().str.match(INT_AS_FLOAT_RE)
        if raw_float.any():
            add(g, ft, fk, f"FK format differs from {dt}.{dk}", "ERROR", raw_float.sum(), len(f),
                "FK stored as '45.0' while PK is '45' - a text join matches 0% until normalised",
                f[fk][raw_float].unique()[:5])
        if nullk.any():
            add(g, ft, fk, f"null FK -> {dt}", "INFO", nullk.sum(), len(f),
                "null keys (check whether they are structural)")
        # unused dimension members
        unused = ~norm_id(d[dk]).isin(set(fv))
        if dt != "dim_date":
            add(g, dt, dk, f"dimension member never used by {ft}", "INFO", unused.sum(), len(d),
                f"{unused.sum()} of {len(d)} {dt} keys never appear in {ft}.{fk}",
                d.loc[unused, dk].head(5).tolist())


# --------------------------------------------------------------------------
# Group 4 - cross-table business rules
# --------------------------------------------------------------------------
def cross_table_checks(t):
    g = "4 Cross-table"
    cl = t["dim_client"].copy()
    cl["client_id"] = norm_id(cl["client_id"])
    cl_cols = cl[["client_id", "advisor_id", "primary_account_type", "risk_profile",
                  "client_since", "is_active"]].rename(columns=lambda c: c if c == "client_id" else "c_" + c)

    facts = {
        "fact_fees": "fee_date",
        "fact_portfolio_snapshot": "snapshot_date",
        "fact_transactions": "txn_date",
    }
    for ft, dcol in facts.items():
        f = t[ft].copy()
        f["client_id"] = norm_id(f["client_id"])
        m = f.merge(cl_cols, on="client_id", how="inner")
        pkc = TABLES[ft]["pk"]
        # advisor on fact = advisor on client
        bad = norm_id(m["advisor_id"]) != norm_id(m["c_advisor_id"])
        add(g, ft, "advisor_id", "advisor differs from dim_client.advisor_id", "WARN", bad.sum(), len(f),
            "could be a legitimate advisor change; investigate", examples_of(m, bad, [pkc, "client_id", "advisor_id", "c_advisor_id"]))
        # activity before relationship started
        early = m[dcol] < m["c_client_since"]
        add(g, ft, dcol, "activity before client_since", "WARN", early.sum(), len(f),
            f"{m.loc[early, 'client_id'].nunique()} clients have {ft} rows dated before they became clients",
            examples_of(m, early, [pkc, "client_id", dcol, "c_client_since"]))
        # inactive clients
        inact = m["c_is_active"].str.lower() == "false"
        last = m.loc[inact].groupby("client_id")[dcol].max()
        add(g, ft, "client_id", "rows for inactive clients", "INFO", inact.sum(), len(f),
            f"{inact.sum()} rows / {m.loc[inact, 'client_id'].nunique()} inactive clients "
            f"(latest activity {last.max() if len(last) else 'n/a'}) - history from before they left is expected; "
            "decide whether activity after leaving is plausible")

    # snapshot account_type vs client primary_account_type
    p = t["fact_portfolio_snapshot"].copy()
    p["client_id"] = norm_id(p["client_id"])
    m = p.merge(cl_cols, on="client_id", how="inner")
    bad = m["account_type"] != m["c_primary_account_type"]
    add(g, "fact_portfolio_snapshot", "account_type", "account_type differs from client's primary_account_type",
        "WARN", bad.sum(), len(p), "", examples_of(m, bad, ["snapshot_id", "client_id", "account_type", "c_primary_account_type"]))

    # benchmark assignment follows risk profile -> each profile should map to ONE benchmark
    xt = pd.crosstab(m["c_risk_profile"].replace("", "(blank)"), m["benchmark_id"])
    multi = (xt > 0).sum(axis=1)
    mapping = {rp: ",".join(xt.columns[xt.loc[rp] > 0]) for rp in xt.index}
    blank_bm = mapping.get("(blank)", "")
    used_by_known = {b for rp, bs in mapping.items() if rp != "(blank)" for b in bs.split(",")}
    owners = [rp for rp, bs in mapping.items() if rp != "(blank)" and blank_bm in bs.split(",")]
    if "(blank)" not in mapping:
        verdict = "no blank risk_profile rows"
    elif "," in blank_bm:
        verdict = f"blank risk_profile rows use {blank_bm.count(',') + 1} benchmarks - profile cannot be recovered"
    elif len(owners) == 1:
        verdict = f"blank risk_profile rows all use benchmark {blank_bm}, used only by {owners[0]} - candidate fill"
    else:
        verdict = f"blank risk_profile rows all use benchmark {blank_bm}, shared by {owners or 'no'} profile(s) - not recoverable"
    add(g, "fact_portfolio_snapshot", "benchmark_id", "risk_profile -> benchmark mapping", "INFO", 0, len(p),
        "observed mapping: " + "; ".join(f"{k}->{v}" for k, v in mapping.items()) + " - " + verdict)
    known = multi.drop("(blank)", errors="ignore")
    add(g, "fact_portfolio_snapshot", "benchmark_id", "risk profile maps to >1 benchmark", "WARN",
        int((known > 1).sum()), len(known),
        "count = risk profiles (not rows) whose snapshots use more than one benchmark")

    # fee aum_basis = snapshot aum for the same client-month
    f = t["fact_fees"].copy()
    j = f.merge(t["fact_portfolio_snapshot"][["client_id", "snapshot_date", "aum"]],
                left_on=["client_id", "fee_date"], right_on=["client_id", "snapshot_date"], how="left")
    nosnap = j["aum"].isna()
    add(g, "fact_fees", "aum_basis", "fee with no snapshot for that client-month", "WARN", nosnap.sum(), len(f), "")
    diff = (to_num(j["aum_basis"]) - pd.to_numeric(j["aum"], errors="coerce")).abs()
    bad = ~nosnap & (diff > 0.01)
    add(g, "fact_fees", "aum_basis", "aum_basis != snapshot aum (same client-month)", "ERROR", bad.sum(), len(f),
        f"matched {(~nosnap).sum():,} fees to snapshots",
        examples_of(j, bad, ["fee_id", "client_id", "fee_date", "aum_basis", "aum"]))

    # every snapshot month should have fees and vice versa (coverage)
    sk = set(zip(p["client_id"], t["fact_portfolio_snapshot"]["snapshot_date"]))
    fk = set(zip(norm_id(f["client_id"]), f["fee_date"]))
    add(g, "fact_portfolio_snapshot", "client_id+snapshot_date", "snapshot month with no fee row", "INFO",
        len(sk - fk), len(sk), "client-months with a snapshot but no fee (could be fee waivers)")

    # dim_client members with no activity at all
    active_ids = set(norm_id(t["fact_portfolio_snapshot"]["client_id"])) | \
                 set(norm_id(t["fact_transactions"]["client_id"])) | set(norm_id(f["client_id"]))
    none = ~cl["client_id"].isin(active_ids)
    add(g, "dim_client", "client_id", "client with no fact rows in any table", "WARN", none.sum(), len(cl),
        "compare with near-duplicate clients: these may be the duplicate copies",
        cl.loc[none, "client_id"].head(5).tolist())

    # security asset_class vs benchmark asset class
    s = t["dim_security"].merge(t["dim_benchmark"][["benchmark_id", "asset_class"]].rename(
        columns={"asset_class": "bm_asset_class"}), on="benchmark_id", how="left")
    xt = pd.crosstab(s["asset_class"], s["bm_asset_class"])
    add(g, "dim_security", "benchmark_id", "security asset_class vs benchmark asset_class", "INFO", 0, len(s),
        "; ".join(f"{a}->{','.join(xt.columns[xt.loc[a] > 0])}" for a in xt.index))

    # fact dates inside the calendar range
    dd = t["dim_date"]["date"]
    for ft, dcol in facts.items():
        v = t[ft][dcol].str.strip()
        out = ~is_null(v) & ((v < dd.min()) | (v > dd.max()))
        add(g, ft, dcol, "date outside dim_date range", "ERROR", out.sum(), len(t[ft]),
            f"calendar covers {dd.min()} to {dd.max()}")


# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=None, help="folder that holds the raw CSV files")
    args = ap.parse_args()

    data_dir = args.data
    if data_dir is None:
        for cand in [os.path.join(HW_DIR, "Wildcat Capital"), os.path.join(HW_DIR, "data", "raw"), HW_DIR]:
            if find_file(cand, "dim_client"):
                data_dir = cand
                break
    if data_dir is None:
        sys.exit("Raw data folder not found - pass --data <folder>")
    os.makedirs(REPORT_DIR, exist_ok=True)

    print(f"Reading raw files from: {data_dir}")
    t = load_tables(data_dir)
    FINDINGS.clear()                       # safe if main() is called twice
    # every column the rules refer to must exist, or a check would silently test nothing
    for name, spec in TABLES.items():
        needed = {spec["pk"]} | set(spec.get("types", {})) | set(spec.get("allowed", {})) | \
                 set(spec.get("ranges", {})) | set(spec.get("required", [])) | set(spec.get("near_dup_cols", []))
        missing = needed - set(t[name].columns)
        assert not missing, f"{name}: expected columns missing {sorted(missing)}"
    # fact-date and client_since bounds come from the calendar, not from hard-coded years
    cal = t["dim_date"]["date"].str.strip()
    TABLES["dim_client"]["ranges"]["client_since"] = ("1990-01-01", cal.max())
    TABLES["dim_date"]["ranges"]["date"] = (cal.min(), cal.max())
    TABLES["fact_portfolio_snapshot"]["ranges"]["year"] = (int(cal.min()[:4]), int(cal.max()[:4]))

    print("\nProfiling columns ...")
    prof = []
    for name, df in t.items():
        prof += profile_table(name, df, TABLES[name].get("types"))
    prof = pd.DataFrame(prof)
    prof.to_csv(os.path.join(REPORT_DIR, "profile_raw.csv"), index=False)
    print(f"  {len(prof)} columns profiled -> reports/profile_raw.csv")

    print("\nRunning DQ checks ...")
    for name, df in t.items():
        column_checks(name, df, TABLES[name])
        single_table_checks(name, df, TABLES[name])
    row_contradictions(t)
    ri_checks(t)
    cross_table_checks(t)

    dq = pd.DataFrame(FINDINGS)
    sev_order = {"ERROR": 0, "WARN": 1, "INFO": 2}
    dq = dq.sort_values(["check_group", "severity", "table", "column"],
                        key=lambda c: c.map(sev_order) if c.name == "severity" else c).reset_index(drop=True)
    dq.insert(0, "finding_id", [f"F{i + 1:03d}" for i in range(len(dq))])
    dq.to_csv(os.path.join(REPORT_DIR, "dq_summary_raw.csv"), index=False)
    n_fail = (dq["status"] == "FAIL").sum()
    print(f"  {len(dq)} checks recorded ({n_fail} failed, {(dq['status'] == 'PASS').sum()} passed, "
          f"{(dq['status'] == 'INFO').sum()} INFO) -> reports/dq_summary_raw.csv\n")

    print(pd.crosstab(dq["check_group"], [dq["status"], dq["severity"]]).to_string())
    print("\nFailed ERROR and WARN checks:")
    show = dq[dq["status"] == "FAIL"]
    for _, r in show.iterrows():
        print(f"  [{r.severity:<5}] {r.table}.{r.column}: {r.check} - {r.rows_affected:,} rows ({r.pct_affected}%)")


if __name__ == "__main__":
    main()
```
