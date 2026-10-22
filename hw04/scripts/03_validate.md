# scripts/03_validate.py

HW4 Part D - Referential integrity and validation. Identical copy of `scripts/03_validate.py`.

Run from the `hw04` folder (after `02_clean.py`):

```powershell
python scripts/03_validate.py
```

Outputs: `reports/data_quality_scorecard.csv` and `reports/validation_details.csv`

```python
"""
HW4 Part D - Referential integrity and validation, raw vs clean
MIS3060 Business Intelligence with AI | Villanova University

Contents
  1. check_referential_integrity()  - ONE reusable RI function (keep for Assignment 5)
     applied to all 13 relationships (10 ID-based + 3 to dim_date)
  2. Rule-based checks for every column with a natural business bound
     (ranges, allowed code lists, sign rules, conditional presence)
  3. Cross-table reconciliations (recomputed vs stored values, facts vs facts, facts vs dims)
  4. IQR outlier flags on numeric columns with no natural upper bound
  5. Scorecard: one row per table per stage (raw / clean)
       % completeness, % key uniqueness, % type validity, % rule pass, % referential match

Every check runs on BOTH the raw files and data/clean/.
Outputs
  reports/data_quality_scorecard.csv   one row per table per stage
  reports/validation_details.csv       every RI / rule / reconciliation / IQR result behind the scorecard

How to run (from the hw04 folder, after 02_clean.py):
    python scripts/03_validate.py
Optional: python scripts/03_validate.py --raw "path/to/raw/folder"
"""

import argparse
import glob
import os
import sys

import pandas as pd

HW_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLEAN_DIR = os.path.join(HW_DIR, "data", "clean")
REPORT_DIR = os.path.join(HW_DIR, "reports")

TABLES = ["dim_advisor", "dim_benchmark", "dim_client", "dim_date", "dim_security",
          "fact_fees", "fact_portfolio_snapshot", "fact_transactions"]
PK = {"dim_advisor": "advisor_id", "dim_benchmark": "benchmark_id", "dim_client": "client_id",
      "dim_date": "date_id", "dim_security": "security_id", "fact_fees": "fee_id",
      "fact_portfolio_snapshot": "snapshot_id", "fact_transactions": "txn_id"}

# (fact table, fact key, dimension table, dimension key)
RELATIONSHIPS = [
    # 10 ID-based
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
    # 3 date joins
    ("fact_fees", "fee_date", "dim_date", "date"),
    ("fact_portfolio_snapshot", "snapshot_date", "dim_date", "date"),
    ("fact_transactions", "txn_date", "dim_date", "date"),
]

# expected type of each column (anything not listed is text)
TYPES = {
    "dim_advisor": {"advisor_id": "int", "years_experience": "int", "aum_target_mm": "float"},
    "dim_benchmark": {"benchmark_id": "int"},
    "dim_client": {"client_id": "int", "age": "int", "initial_aum": "float", "client_since": "date",
                   "advisor_id": "int", "is_active": "bool"},
    "dim_date": {"date_id": "int", "date": "date", "year": "int", "quarter": "int", "month": "int",
                 "week_of_year": "int", "is_month_end": "bool", "is_quarter_end": "bool",
                 "is_year_end": "bool", "is_trading_day": "bool"},
    "dim_security": {"security_id": "int", "benchmark_id": "int", "is_etf": "bool",
                     "expense_ratio_bps": "float"},
    "fact_fees": {"fee_id": "int", "client_id": "int", "advisor_id": "int", "fee_date": "date",
                  "aum_basis": "float", "bps_charged": "float", "amount": "float"},
    "fact_portfolio_snapshot": {"snapshot_id": "int", "client_id": "int", "advisor_id": "int",
                                "benchmark_id": "int", "snapshot_date": "date", "year": "int",
                                "month": "int", "aum": "float", "return_ytd": "float",
                                "benchmark_return_ytd": "float", "active_alpha_ytd": "float",
                                "cash_pct": "float"},
    "fact_transactions": {"txn_id": "int", "client_id": "int", "advisor_id": "int",
                          "security_id": "int", "txn_date": "date", "shares": "float",
                          "price": "float", "amount": "float"},
}
# blanks that are legitimate structure (decision log L02, L03) are not counted as incomplete
STRUCTURAL_BLANKS = {
    "fact_transactions": {"security_id": "cash", "shares": "cash", "price": "cash"},
    "dim_security": {"expense_ratio_bps": "stock", "sector": "etf"},
}
# business (natural) keys: a surrogate PK can be unique while the same entity appears twice
NATURAL_KEYS = {
    "dim_advisor": ["first_name", "last_name"],
    "dim_benchmark": ["ticker_proxy"],
    "dim_client": ["first_name", "age", "city", "state", "zip_code", "client_tier", "primary_account_type",
                   "initial_aum", "client_since", "advisor_id"],   # last_name excluded: duplicates differ by a typo
    "dim_date": ["date"],
    "dim_security": ["ticker"],
    "fact_fees": ["client_id", "fee_date", "fee_type"],
    "fact_portfolio_snapshot": ["client_id", "snapshot_date"],
}
FLAG_COLUMNS = {"risk_profile_imputed", "aum_floor_flag", "extreme_return_flag"}
US_STATES = set("AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE "
                "NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY".split())

DETAILS = []


# ==========================================================================
# 1. Reusable referential-integrity function  (keep for Assignment 5)
# ==========================================================================
def check_referential_integrity(fact_df, fact_key, dim_df, dim_key):
    """
    Check that every value of fact_df[fact_key] exists in dim_df[dim_key].

    Keys are compared exactly as stored (after trimming spaces), so a format
    mismatch such as '45.0' vs '45' counts as an orphan - that is what a BI
    relationship would do. Null keys (blank / NaN) are excluded from the match
    rate and reported separately, because some nulls are legitimate.

    Returns a dict:
        match_rate           share of non-null fact keys found in the dimension (0-1)
        orphan_rows          number of fact rows whose non-null key is not in the dimension
        distinct_orphan_keys number of different orphan key values
        null_key_rate        share of fact rows with a null key (0-1)
        orphan_keys          sorted list of up to 20 example orphan keys
        orphan_df            the orphan rows themselves (DataFrame)
    """
    def clean_key(s):
        s = s.astype(str).str.strip()
        return s.mask(s.str.lower().isin(["", "nan", "none", "null"]))

    fk = clean_key(fact_df[fact_key])
    dk = set(clean_key(dim_df[dim_key]).dropna())
    null = fk.isna()
    orphan = ~null & ~fk.isin(dk)
    non_null = int((~null).sum())
    orphan_keys = sorted(fk[orphan].unique(), key=lambda v: (len(v), v))
    return {
        "match_rate": (non_null - int(orphan.sum())) / non_null if non_null else 1.0,
        "orphan_rows": int(orphan.sum()),
        "distinct_orphan_keys": len(orphan_keys),
        "null_key_rate": float(null.mean()) if len(fk) else 0.0,
        "orphan_keys": orphan_keys[:20],
        "orphan_df": fact_df.loc[orphan],
    }


# ==========================================================================
# helpers
# ==========================================================================
def num(s):
    return pd.to_numeric(s, errors="coerce")


def blank(s):
    return s.astype(str).str.strip() == ""


def parses(s, typ):
    s = s.astype(str).str.strip()
    if typ == "int":
        return s.str.fullmatch(r"[+-]?\d+")
    if typ == "float":
        return s.str.fullmatch(r"[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?")
    if typ == "date":
        return s.str.fullmatch(r"\d{4}-\d{2}-\d{2}") & pd.to_datetime(s, format="%Y-%m-%d", errors="coerce").notna()
    if typ == "bool":
        return s.isin(["True", "False", "0", "1"])
    return pd.Series(True, index=s.index)


def detail(stage, kind, table, check, passed, total, note=""):
    DETAILS.append({"stage": stage, "check_type": kind, "table": table, "check": check,
                    "rows_checked": int(total), "rows_passed": int(passed),
                    "rows_failed": int(total - passed),
                    "pass_pct": round(passed / total * 100, 3) if total else 100.0, "note": note})


def find_file(folder, table):
    exact = os.path.join(folder, table + ".csv")
    if os.path.exists(exact):
        return exact
    hits = sorted(glob.glob(os.path.join(folder, glob.escape(table) + " (*).csv")))
    return hits[-1] if hits else None


def load(folder):
    out = {}
    for tb in TABLES:
        p = find_file(folder, tb)
        if p is None:
            sys.exit(f"missing {tb}.csv in {folder}")
        out[tb] = pd.read_csv(p, dtype=str, keep_default_na=False)
    return out


# ==========================================================================
# 2. Rule-based checks (natural business bounds)
#    each rule: (table, name, applies_to(df) -> mask, passes(df, t) -> mask)
# ==========================================================================
def between(col, lo=None, hi=None, strict_lo=False):
    def f(df, t):
        x = num(df[col])
        ok = x.notna()
        if lo is not None:
            ok &= (x > lo) if strict_lo else (x >= lo)
        if hi is not None:
            ok &= x <= hi
        return ok
    return f


def in_list(col, allowed):
    return lambda df, t: df[col].isin(allowed)


def nonblank(col):
    return lambda df: ~blank(df[col])


def is_sec_txn(df):
    return df["txn_type"].isin(["Buy", "Sell", "Dividend"])


RULES = [
    # dim_advisor
    ("dim_advisor", "years_experience in [0, 60]", nonblank("years_experience"), between("years_experience", 0, 60)),
    ("dim_advisor", "aum_target_mm > 0", nonblank("aum_target_mm"), between("aum_target_mm", 0, strict_lo=True)),
    ("dim_advisor", "region in allowed list", None,
     in_list("region", ["Northeast", "Mid-Atlantic", "Southeast", "Midwest", "West", "Southwest"])),
    ("dim_advisor", "certifications from CFA/CFP/CIMA or 'None'", None,
     lambda df, t: df["certifications"].str.split(", ").map(lambda xs: set(xs) <= {"CFA", "CFP", "CIMA", "None"})),
    # dim_benchmark
    ("dim_benchmark", "name / ticker_proxy present", None,
     lambda df, t: ~blank(df["name"]) & ~blank(df["ticker_proxy"])),
    # dim_client
    ("dim_client", "age in [18, 110]", None, between("age", 18, 110)),
    ("dim_client", "initial_aum > 0", None, between("initial_aum", 0, strict_lo=True)),
    ("dim_client", "client_since <= 2024-12-31", None,
     lambda df, t: pd.to_datetime(df["client_since"], errors="coerce") <= pd.Timestamp("2024-12-31")),
    ("dim_client", "state is a USPS code", None, lambda df, t: df["state"].isin(US_STATES)),
    ("dim_client", "zip_code is 5 digits", None, lambda df, t: df["zip_code"].str.fullmatch(r"\d{5}")),
    ("dim_client", "risk_profile in allowed list", None,
     in_list("risk_profile", ["Conservative", "Moderately Conservative", "Balanced",
                              "Moderately Aggressive", "Aggressive"])),
    ("dim_client", "client_tier in allowed list", None, in_list("client_tier", ["Retail", "HNW", "UHNW"])),
    ("dim_client", "primary_account_type in allowed list", None,
     in_list("primary_account_type", ["Taxable", "IRA", "Roth IRA", "Trust", "529"])),
    ("dim_client", "is_active is True/False", None, in_list("is_active", ["True", "False"])),
    # dim_date
    ("dim_date", "quarter in [1, 4]", None, between("quarter", 1, 4)),
    ("dim_date", "month in [1, 12]", None, between("month", 1, 12)),
    ("dim_date", "week_of_year in [1, 53]", None, between("week_of_year", 1, 53)),
    ("dim_date", "is_* flags are 0/1", None,
     lambda df, t: df[["is_month_end", "is_quarter_end", "is_year_end", "is_trading_day"]].isin(["0", "1"]).all(axis=1)),
    ("dim_date", "weekend is never a trading day", None,
     lambda df, t: ~(df["day_of_week"].isin(["Saturday", "Sunday"]) & (df["is_trading_day"] == "1"))),
    # dim_security
    ("dim_security", "asset_class in allowed list", None,
     in_list("asset_class", ["Equity", "Fixed Income", "Alternative", "Cash Equivalent"])),
    ("dim_security", "expense_ratio_bps in [0, 300]", nonblank("expense_ratio_bps"), between("expense_ratio_bps", 0, 300)),
    ("dim_security", "ETF has expense ratio; stock has none", None,
     lambda df, t: (df["is_etf"] == "True") == ~blank(df["expense_ratio_bps"])),
    ("dim_security", "ticker is 1-5 capital letters", None, lambda df, t: df["ticker"].str.fullmatch(r"[A-Z]{1,5}")),
    # fact_fees
    ("fact_fees", "fee_type in allowed list", None,
     in_list("fee_type", ["Management", "Advisory", "Custodial", "Performance"])),
    ("fact_fees", "aum_basis > 0", None, between("aum_basis", 0, strict_lo=True)),
    ("fact_fees", "bps_charged in (0, 300]", None, between("bps_charged", 0, 300, strict_lo=True)),
    ("fact_fees", "amount >= 0", None, between("amount", 0)),
    ("fact_fees", "fee_date is 1st of month", None, lambda df, t: df["fee_date"].str.endswith("-01")),
    # fact_portfolio_snapshot
    ("fact_portfolio_snapshot", "aum > 0", None, between("aum", 0, strict_lo=True)),
    ("fact_portfolio_snapshot", "cash_pct in [0, 1]", None, between("cash_pct", 0, 1)),
    ("fact_portfolio_snapshot", "return_ytd numeric and >= -100%", None, between("return_ytd", -1)),
    ("fact_portfolio_snapshot", "benchmark_return_ytd >= -100%", None, between("benchmark_return_ytd", -1)),
    ("fact_portfolio_snapshot", "month in [1, 12], year in [2020, 2024]", None,
     lambda df, t: between("month", 1, 12)(df, t) & between("year", 2020, 2024)(df, t)),
    ("fact_portfolio_snapshot", "account_type in allowed list", None,
     in_list("account_type", ["Taxable", "IRA", "Roth IRA", "Trust", "529"])),
    ("fact_portfolio_snapshot", "snapshot_date is 1st of month", None, lambda df, t: df["snapshot_date"].str.endswith("-01")),
    # fact_transactions
    ("fact_transactions", "txn_type in allowed list", None,
     in_list("txn_type", ["Buy", "Sell", "Dividend", "Deposit", "Withdrawal", "Advisory Fee"])),
    ("fact_transactions", "amount > 0 (sign carried by txn_type)", None, between("amount", 0, strict_lo=True)),
    ("fact_transactions", "shares > 0 on security transactions", is_sec_txn, between("shares", 0, strict_lo=True)),
    ("fact_transactions", "price > 0 on security transactions", is_sec_txn, between("price", 0, strict_lo=True)),
    ("fact_transactions", "security fields present iff Buy/Sell/Dividend", None,
     lambda df, t: is_sec_txn(df) == (~blank(df["security_id"]) & ~blank(df["shares"]) & ~blank(df["price"]))),
]


def run_rules(stage, t):
    """Returns {table: (passed, checked)} pooled over that table's rules."""
    pooled = {}
    for table, name, applies, rule in RULES:
        df = t[table]
        scope = applies(df) if applies else pd.Series(True, index=df.index)
        ok = rule(df, t).fillna(False).astype(bool)
        passed, checked = int((ok & scope).sum()), int(scope.sum())
        detail(stage, "rule", table, name, passed, checked)
        p, c = pooled.get(table, (0, 0))
        pooled[table] = (p + passed, c + checked)
    return pooled


# ==========================================================================
# 3. Cross-table reconciliations
# ==========================================================================
def reconciliations(stage, t):
    fe, sn, tx, cl = t["fact_fees"], t["fact_portfolio_snapshot"], t["fact_transactions"], t["dim_client"]

    # R1 recomputed fee amount vs stored amount
    calc = num(fe["aum_basis"]) * num(fe["bps_charged"]) / 10000 / 12
    ok = (calc - num(fe["amount"])).abs() <= 0.02
    detail(stage, "reconciliation", "fact_fees", "R1 amount = aum_basis x bps / 10000 / 12", ok.sum(), len(fe))

    # R2 fee aum_basis vs snapshot aum, same client-month (two tables describe the same fact)
    j = fe.merge(sn[["client_id", "snapshot_date", "aum"]], left_on=["client_id", "fee_date"],
                 right_on=["client_id", "snapshot_date"], how="left")
    ok = (num(j["aum_basis"]) - num(j["aum"])).abs() <= 0.01
    detail(stage, "reconciliation", "fact_fees", "R2 aum_basis = fact_portfolio_snapshot.aum (same client-month)",
           ok.sum(), len(j), f"{j['aum'].isna().sum()} fees without a matching snapshot")

    # R3 transaction amount vs shares x price
    sec = tx["txn_type"].isin(["Buy", "Sell", "Dividend"])
    ok = (num(tx["shares"]) * num(tx["price"]) - num(tx["amount"])).abs() <= 0.05
    detail(stage, "reconciliation", "fact_transactions", "R3 amount = shares x price (security txns)",
           (ok & sec).sum(), sec.sum())

    # R4 alpha identity within the snapshot
    ok = (num(sn["return_ytd"]) - num(sn["benchmark_return_ytd"]) - num(sn["active_alpha_ytd"])).abs() <= 1e-4
    detail(stage, "reconciliation", "fact_portfolio_snapshot",
           "R4 active_alpha_ytd = return_ytd - benchmark_return_ytd", ok.sum(), len(sn))

    # R5 advisor on every fact = advisor on dim_client
    adv = cl.set_index("client_id")["advisor_id"]
    for name, df in [("fact_fees", fe), ("fact_portfolio_snapshot", sn), ("fact_transactions", tx)]:
        exp = df["client_id"].map(adv)
        has = exp.notna()
        detail(stage, "reconciliation", name, "R5 advisor_id = dim_client.advisor_id",
               (df["advisor_id"] == exp)[has].sum(), has.sum(), f"{(~has).sum()} rows with no client to compare")

    # R6 snapshot benchmark follows the client's risk profile
    rule = {"Aggressive": "1", "Moderately Aggressive": "1", "Balanced": "3",
            "Conservative": "8", "Moderately Conservative": "8"}
    exp = sn["client_id"].map(cl.set_index("client_id")["risk_profile"].map(rule))
    has = exp.notna()
    detail(stage, "reconciliation", "fact_portfolio_snapshot", "R6 benchmark_id follows dim_client.risk_profile",
           (sn["benchmark_id"] == exp)[has].sum(), has.sum(),
           f"{(~has).sum()} snapshot rows whose client has no usable risk_profile")

    # R7 snapshot account_type = client primary_account_type
    exp = sn["client_id"].map(cl.set_index("client_id")["primary_account_type"])
    has = exp.notna()
    detail(stage, "reconciliation", "fact_portfolio_snapshot", "R7 account_type = dim_client.primary_account_type",
           (sn["account_type"] == exp)[has].sum(), has.sum())

    # R8 first monthly snapshot = month the client joined (or Jan-2020) - checked at month grain (log L01)
    first = sn.groupby("client_id")["snapshot_date"].min()
    since = cl.set_index("client_id")["client_since"].reindex(first.index)
    exp = (since.str[:7] + "-01").where(since >= "2020-01-01", "2020-01-01")
    has = since.notna()
    detail(stage, "reconciliation", "dim_client", "R8 first snapshot month = client_since month",
           (first == exp)[has].sum(), has.sum())


# ==========================================================================
# 4. IQR outliers on columns with no natural upper bound
# ==========================================================================
IQR_COLUMNS = [("fact_transactions", "amount"), ("fact_fees", "amount"),
               ("fact_portfolio_snapshot", "aum"), ("dim_client", "initial_aum")]
IQR_SENTENCE = ("Flagged does not mean wrong: these columns are right-skewed by design (UHNW clients hold "
                "far more than Retail clients), so an IQR fence marks the large-but-real accounts as outliers; "
                "a flag is a prompt to look, and a value is only wrong if it fails a rule or a reconciliation.")


def iqr_flags(stage, t):
    out = {}
    for table, col in IQR_COLUMNS:
        x = num(t[table][col])
        q1, q3 = x.quantile(0.25), x.quantile(0.75)
        lo, hi = q1 - 1.5 * (q3 - q1), q3 + 1.5 * (q3 - q1)
        flag = ((x < lo) | (x > hi)).astype(int)
        out[(table, col)] = flag
        # how many flagged rows ALSO fail a rule or reconciliation? (evidence flagged != wrong)
        note = f"Q1={q1:,.2f} Q3={q3:,.2f} fence=[{lo:,.2f}, {hi:,.2f}]"
        if table == "dim_client":
            tiers = t[table].loc[flag == 1, "client_tier"].value_counts().to_dict()
            note += f"; flagged by tier {tiers}"
        detail(stage, "iqr_outlier", table, f"IQR 1.5x fence on {col}", int((flag == 0).sum()), len(flag),
               note + f"; {flag.sum():,} rows flagged ({flag.mean():.1%})")
    return out


# ==========================================================================
# 5. Scorecard
# ==========================================================================
def completeness(table, df):
    cols = [c for c in df.columns if c not in FLAG_COLUMNS]
    cells = filled = 0
    struct = STRUCTURAL_BLANKS.get(table, {})
    for c in cols:
        b = blank(df[c])
        if c in struct:
            kind = struct[c]
            if kind == "cash":
                expected_blank = ~df["txn_type"].isin(["Buy", "Sell", "Dividend"])
            elif kind == "stock":
                expected_blank = df["is_etf"] != "True"
            else:  # etf
                expected_blank = df["is_etf"] == "True"
            b = b & ~expected_blank          # a blank where blank is expected is not missing
        cells += len(df)
        filled += int((~b).sum())
    return filled / cells


def type_validity(table, df):
    ok = total = 0
    for c in df.columns:
        if c in FLAG_COLUMNS:
            continue
        nb = ~blank(df[c])
        typ = TYPES[table].get(c, "text")
        ok += int((parses(df[c], typ) & nb).sum())
        total += int(nb.sum())
    return ok / total if total else 1.0


def key_uniqueness(table, df):
    """Share of rows whose surrogate PK is unique AND whose business key is unique."""
    ok = ~df[PK[table]].duplicated(keep=False)
    if table in NATURAL_KEYS:
        nk = df[NATURAL_KEYS[table]].apply(lambda c: c.str.strip().str.lower())
        ok &= ~nk.duplicated(keep=False)
    return ok.mean()


def run_stage(stage, t):
    print(f"\n{'=' * 78}\nSTAGE: {stage.upper()}\n{'=' * 78}")

    # RI
    ri_pool = {}
    print(f"  {'relationship':<64}{'match':>8}{'orphans':>9}{'keys':>6}{'null':>7}")
    for ft, fk, dt, dk in RELATIONSHIPS:
        r = check_referential_integrity(t[ft], fk, t[dt], dk)
        nn = round(len(t[ft]) * (1 - r["null_key_rate"]))
        detail(stage, "referential_integrity", ft, f"{ft}.{fk} -> {dt}.{dk}", nn - r["orphan_rows"], nn,
               f"distinct orphan keys {r['distinct_orphan_keys']}; null-key rate {r['null_key_rate']:.2%}; "
               f"examples {r['orphan_keys'][:5]}")
        print(f"  {ft + '.' + fk + ' -> ' + dt + '.' + dk:<64}{r['match_rate']:>8.2%}"
              f"{r['orphan_rows']:>9,}{r['distinct_orphan_keys']:>6}{r['null_key_rate']:>7.1%}")
        p, c = ri_pool.get(ft, (0, 0))
        ri_pool[ft] = (p + nn - r["orphan_rows"], c + nn)

    rule_pool = run_rules(stage, t)
    reconciliations(stage, t)
    iqr_flags(stage, t)

    rows = []
    for tb in TABLES:
        df = t[tb]
        rp, rc = rule_pool.get(tb, (0, 0))
        rip, ric = ri_pool.get(tb, (0, 0))
        rows.append({
            "table": tb, "stage": stage, "rows": len(df),
            "pct_completeness": round(completeness(tb, df) * 100, 3),
            "pct_key_uniqueness": round(key_uniqueness(tb, df) * 100, 3),
            "pct_type_validity": round(type_validity(tb, df) * 100, 3),
            "pct_rule_pass": round(rp / rc * 100, 3) if rc else "",
            "pct_referential_match": round(rip / ric * 100, 3) if ric else "n/a (no foreign keys)",
            "rules_checked": len([r for r in RULES if r[0] == tb]),
            "relationships_checked": len([r for r in RELATIONSHIPS if r[0] == tb]),
        })
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default=None, help="folder with the raw CSVs")
    args = ap.parse_args()
    raw_dir = args.raw
    if raw_dir is None:
        for cand in [os.path.join(HW_DIR, "Wildcat Capital"), os.path.join(HW_DIR, "data", "raw"), HW_DIR]:
            if find_file(cand, "dim_client"):
                raw_dir = cand
                break
    if raw_dir is None or not os.path.isdir(CLEAN_DIR):
        sys.exit("Need the raw folder (--raw) and data/clean/ (run 02_clean.py first)")
    os.makedirs(REPORT_DIR, exist_ok=True)

    scorecard = run_stage("raw", load(raw_dir)) + run_stage("clean", load(CLEAN_DIR))
    sc = pd.DataFrame(scorecard).sort_values(["table", "stage"], key=lambda c: c.map(
        {"raw": 0, "clean": 1}) if c.name == "stage" else c).reset_index(drop=True)
    sc.to_csv(os.path.join(REPORT_DIR, "data_quality_scorecard.csv"), index=False)
    det = pd.DataFrame(DETAILS)
    det.to_csv(os.path.join(REPORT_DIR, "validation_details.csv"), index=False)

    print(f"\n{'=' * 78}\nSCORECARD (reports/data_quality_scorecard.csv)\n{'=' * 78}")
    show = sc[["table", "stage", "rows", "pct_completeness", "pct_key_uniqueness", "pct_type_validity",
               "pct_rule_pass", "pct_referential_match"]]
    print(show.to_string(index=False))

    print("\nFailing checks, raw -> clean:")
    piv = det.pivot_table(index=["check_type", "table", "check"], columns="stage", values="rows_failed",
                          aggfunc="sum").fillna(0).astype(int)
    piv = piv[(piv.get("raw", 0) > 0) | (piv.get("clean", 0) > 0)]
    piv = piv[[c for c in ["raw", "clean"] if c in piv.columns]]
    print(piv.drop(index="iqr_outlier", errors="ignore").to_string())

    print("\nIQR outlier flags (rows flagged, raw -> clean):")
    for _, r in det[(det.check_type == "iqr_outlier")].iterrows():
        print(f"  [{r.stage:<5}] {r.table}.{r.check.split(' on ')[-1]}: {r.rows_failed:,} flagged  ({r.note.split('; ')[1] if 'tier' in r.note else r.note.split('; ')[0]})")
    print("\n" + IQR_SENTENCE)

    # the clean stage must be at least as good as raw on every metric, and RI must be perfect
    clean = sc[sc.stage == "clean"].set_index("table")
    for tb, r in clean.iterrows():
        if isinstance(r.pct_referential_match, float):
            assert r.pct_referential_match == 100.0, f"{tb}: clean RI below 100%"
        assert r.pct_key_uniqueness == 100.0, f"{tb}: clean PK not unique"
    print("\nSaved reports/data_quality_scorecard.csv and reports/validation_details.csv")


if __name__ == "__main__":
    main()
```
