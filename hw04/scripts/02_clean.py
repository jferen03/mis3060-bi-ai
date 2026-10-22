"""
HW4 Part C - Cleaning program for the Wildcat Capital tables
MIS3060 Business Intelligence with AI | Villanova University

Implements decision_log.md, one decision at a time, in the order the log defends:
    D01 convert   fact_transactions.security_id  '45.0' -> '45'
    D03 quarantine dim_client duplicate copies (before D05 so copies are not imputed)
    D04 standardize dim_client.state full names -> USPS codes
    D05 fill      dim_client.risk_profile from the benchmark rule + risk_profile_imputed flag
    D02 quarantine fact_transactions rows with orphan client_id
    D07 convert   fact_transactions.shares negative Buy -> absolute value
    D06 convert   fact_portfolio_snapshot.return_ytd '9.28%' -> 0.0928 (before D09)
    D08 flag      aum_floor_flag on snapshots and fees
    D09 flag      extreme_return_flag on snapshots
Every L-entry in the log (leave as is) is recorded in the cleaning log too.

Rules
- Raw files are read as text (dtype=str, keep_default_na=False) and never modified.
- After each step: print rows affected + before/after check, then assert the after-state.
  A failed assert stops the script. All checks (each step, final checks, pre-write checks)
  run before any file is written, so no clean or audit file is written from a bad fix.
- Every changed cell -> data/audit/value_changes.csv
- Every removed row  -> data/audit/quarantine_<set>.csv, and raw = clean + quarantined is proven.

How to run (from the hw04 folder):
    python scripts/02_clean.py
Optional: python scripts/02_clean.py --data "path/to/raw/folder"
"""

import argparse
import glob
import os
import re
import sys
from decimal import Decimal

import pandas as pd

HW_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLEAN_DIR = os.path.join(HW_DIR, "data", "clean")
AUDIT_DIR = os.path.join(HW_DIR, "data", "audit")

TABLES = ["dim_advisor", "dim_benchmark", "dim_client", "dim_date", "dim_security",
          "fact_fees", "fact_portfolio_snapshot", "fact_transactions"]
PK = {"dim_advisor": "advisor_id", "dim_benchmark": "benchmark_id", "dim_client": "client_id",
      "dim_date": "date_id", "dim_security": "security_id", "fact_fees": "fee_id",
      "fact_portfolio_snapshot": "snapshot_id", "fact_transactions": "txn_id"}

# ID-based relationships (fact table, fk, dim table, pk) - all must be 100% after cleaning
ID_RELATIONSHIPS = [
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
]
DATE_RELATIONSHIPS = [
    ("fact_fees", "fee_date", "dim_date", "date"),
    ("fact_portfolio_snapshot", "snapshot_date", "dim_date", "date"),
    ("fact_transactions", "txn_date", "dim_date", "date"),
]

STATE_MAP = {"Pennsylvania": "PA", "Florida": "FL", "New York": "NY", "New Jersey": "NJ",
             "California": "CA", "Illinois": "IL", "Texas": "TX"}
RISK_TO_BENCHMARK = {"Aggressive": "1", "Moderately Aggressive": "1", "Balanced": "3",
                     "Conservative": "8", "Moderately Conservative": "8"}
EXTREME_HIGH, EXTREME_LOW = 1.0, -0.5   # YTD return bounds for extreme_return_flag
AUM_FLOOR = "1000.0"
SECURITY_TXN_TYPES = ["Buy", "Sell", "Dividend"]

# Row counts the decision log commits to. Each step asserts its count, so a fix that touches
# more or fewer rows than the log claims stops the script (review finding 02-#5).
EXPECTED = {"D01": 197175, "D03": 25, "D04": 77, "D05": 75, "D02": 200, "D07": 835, "D06": 300,
            "D08 fact_portfolio_snapshot": 420, "D08 fact_fees": 386, "D09": 2639}
# which (table, column) each value-changing step writes - used to reconcile value_changes.csv per step
STEP_COLUMN = {"D01": ("fact_transactions", "security_id"), "D04": ("dim_client", "state"),
               "D05": ("dim_client", "risk_profile"), "D07": ("fact_transactions", "shares"),
               "D06": ("fact_portfolio_snapshot", "return_ytd")}

# --------------------------------------------------------------------------
# Audit-trail helpers
# --------------------------------------------------------------------------
CLEAN_LOG, VALUE_CHANGES, QUARANTINE = [], [], {}


def expect(step, n):
    assert n == EXPECTED[step], f"{step}: touched {n} rows, decision log says {EXPECTED[step]}"


def is_blank(s):
    return s.astype(str).str.strip() == ""


def log(table, decision_id, issue, action, rows, note=""):
    CLEAN_LOG.append({"step": len(CLEAN_LOG) + 1, "decision_id": decision_id, "table": table,
                      "issue": issue, "action": action, "rows_affected": int(rows), "note": note})


def record_changes(table, df, mask, column, new_values):
    """Write new values into df[column] for mask and log every changed cell."""
    key = PK[table]
    old = df.loc[mask, column]
    new = pd.Series(new_values, index=old.index)
    assert new.notna().all(), f"{table}.{column}: a mapping produced a missing value"
    new = new.astype(str)
    changed = old != new
    VALUE_CHANGES.append(pd.DataFrame({
        "table": table, "key_column": key, "key": df.loc[old.index[changed], key].values,
        "column": column, "old_value": old[changed].values, "new_value": new[changed].values}))
    df.loc[old.index, column] = new
    return int(changed.sum())


def quarantine(name, table, df, mask, reason, extra=None):
    """Move rows to a quarantine set. Returns the remaining (clean) frame."""
    q = df.loc[mask].copy()
    q.insert(0, "quarantine_reason", reason if isinstance(reason, str) else reason[mask].values)
    q.insert(0, "source_table", table)
    if extra is not None:
        for col, vals in extra.items():
            q[col] = vals
    QUARANTINE[name] = (table, q)
    return df.loc[~mask].copy()


def header(title):
    print("\n" + "=" * 78 + f"\n{title}\n" + "=" * 78)


def num(s):
    return pd.to_numeric(s, errors="coerce")


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------
def find_file(data_dir, table):
    exact = os.path.join(data_dir, table + ".csv")
    if os.path.exists(exact):
        return exact
    hits = glob.glob(os.path.join(data_dir, glob.escape(table) + " (*).csv"))
    hits = sorted(hits, key=lambda h: int(re.search(r"\((\d+)\)\.csv$", h).group(1)))   # (10) after (9)
    return hits[-1] if hits else None


def locate_data(arg):
    if arg:
        return arg
    for cand in [os.path.join(HW_DIR, "Wildcat Capital"), os.path.join(HW_DIR, "data", "raw"), HW_DIR]:
        if find_file(cand, "dim_client"):
            return cand
    sys.exit("Raw data folder not found - pass --data <folder>")


# --------------------------------------------------------------------------
# Cleaning steps - each one: before, change, after, assert
# --------------------------------------------------------------------------
def d01_security_id(t):
    header("D01  fact_transactions.security_id  '45.0' -> '45'")
    tx = t["fact_transactions"]
    sid = tx["security_id"]
    nonblank = ~is_blank(sid)
    float_like = sid.str.fullmatch(r"\d+\.0")
    dim_ids = set(t["dim_security"]["security_id"])
    before_match = sid[nonblank].isin(dim_ids).mean()
    print(f"  before: {nonblank.sum():,} non-blank ids, {float_like.sum():,} look like 'n.0', "
          f"text match to dim_security = {before_match:.2%}")
    # safety: every non-blank value must be an integer in disguise, nothing with real decimals
    assert (float_like == nonblank).all(), "some security_id values are not of the form n.0"

    n = record_changes("fact_transactions", tx, float_like, "security_id",
                       sid[float_like].str.replace(r"\.0$", "", regex=True))
    after = tx["security_id"]
    after_match = after[after != ""].isin(dim_ids).mean()
    print(f"  after : {n:,} values changed, text match to dim_security = {after_match:.2%}, "
          f"blanks unchanged = {(after == '').sum():,}")
    assert n == float_like.sum()
    assert after[after != ""].str.fullmatch(r"\d+").all()
    assert after_match == 1.0, "security_id still has orphans after normalising"
    expect("D01", n)
    assert (after == "").sum() == (~nonblank).sum(), "blank count changed"
    log("fact_transactions", "D01", "security_id stored as float text ('45.0')",
        "convert: strip trailing .0", n, f"RI match {before_match:.2%} -> {after_match:.2%}")


def d03_duplicate_clients(t):
    header("D03  dim_client duplicate copies -> quarantine")
    cl = t["dim_client"]
    match_cols = [c for c in cl.columns if c not in ("client_id", "last_name")]
    tmp = cl.assign(_id=cl["client_id"].astype(int)).sort_values("_id")
    grp = tmp.groupby(match_cols, sort=False)["client_id"]
    sizes = grp.transform("size")
    original = grp.transform("first")                 # lowest id in the group is the original
    is_copy = (sizes > 1) & (tmp["client_id"] != original)
    copies = tmp.loc[is_copy, ["client_id"]].assign(duplicate_of=original[is_copy])
    print(f"  before: {len(cl):,} clients, {int((sizes > 1).sum())} rows in {copies.shape[0]} duplicate groups")

    # verify, do not assume: copies must have no facts and only differ by a last-name typo
    fact_ids = set(t["fact_fees"]["client_id"]) | set(t["fact_portfolio_snapshot"]["client_id"]) | \
               set(t["fact_transactions"]["client_id"])
    assert not copies["client_id"].isin(fact_ids).any(), "a duplicate copy has fact rows - remap needed"
    assert copies["duplicate_of"].isin(fact_ids).all(), "an original has no fact rows"
    assert (sizes <= 2).all(), "a client appears more than twice"
    ln = cl.set_index("client_id")["last_name"]
    for c, o in zip(copies["client_id"], copies["duplicate_of"]):
        a, b = ln[o], ln[c]
        assert a[:-1] == b or b[:-1] == a, f"client {c} vs {o}: names differ by more than one letter"

    mask = cl["client_id"].isin(copies["client_id"])
    dup_of = cl.loc[mask, "client_id"].map(dict(zip(copies["client_id"], copies["duplicate_of"])))
    reason = "duplicate of client_id " + dup_of
    t["dim_client"] = quarantine("dim_client_duplicates", "dim_client", cl, mask, reason,
                                 {"duplicate_of": dup_of.values,
                                  "original_last_name": dup_of.map(ln).values})
    after = t["dim_client"]
    print(f"  after : {len(after):,} clients, {mask.sum()} quarantined, "
          f"remaining near-duplicates = {after.duplicated(match_cols).sum()}")
    assert len(after) + mask.sum() == len(cl)
    assert after.duplicated(match_cols).sum() == 0
    assert after["client_id"].isin(fact_ids).all(), "a remaining client has no facts"
    expect("D03", int(mask.sum()))
    log("dim_client", "D03", "duplicate client rows (same attributes, typo'd last name)",
        "quarantine copy (higher id)", mask.sum(),
        "verified: copies have 0 fact rows, originals all have facts -> no FK remap needed")


def d04_state(t):
    header("D04  dim_client.state full names -> USPS codes")
    cl = t["dim_client"]
    full = cl["state"].isin(STATE_MAP)
    # independent check of the mapping: every target code must already be used by other rows
    # (catches a typo such as 'Pennsylvania' -> 'PN', which would still be 2 capital letters)
    existing_codes = set(cl.loc[~full, "state"])
    assert set(STATE_MAP.values()) <= existing_codes, \
        f"STATE_MAP targets not used anywhere else: {set(STATE_MAP.values()) - existing_codes}"
    # expected totals counted BEFORE mapping: code rows + full-name rows, by the code each name maps to
    code_counts = cl.loc[~full, "state"].value_counts()
    name_counts = cl.loc[full, "state"].value_counts().rename(index=STATE_MAP).groupby(level=0).sum()
    before_counts = code_counts.add(name_counts, fill_value=0).astype(int)
    print(f"  before: {full.sum()} full names: {cl.loc[full, 'state'].value_counts().to_dict()}")
    assert (cl.loc[~full, "state"].str.fullmatch(r"[A-Z]{2}")).all(), "unmapped non-code state found"
    n = record_changes("dim_client", cl, full, "state", cl.loc[full, "state"].map(STATE_MAP))
    after_counts = cl["state"].value_counts()
    print(f"  after : {n} changed; distinct states {cl['state'].nunique()}; "
          f"PA count {after_counts.get('PA', 0)}")
    assert cl["state"].str.fullmatch(r"[A-Z]{2}").all()
    assert after_counts.sort_index().equals(before_counts.sort_index()), "per-state totals do not add up"
    assert set(after_counts.index) == existing_codes, "mapping created a new state code"
    expect("D04", n)
    log("dim_client", "D04", "state stored as full name", "standardize to USPS code", n,
        "per-state count = old code count + old full-name count")


def d05_risk_profile(t):
    header("D05  dim_client.risk_profile blank -> fill from benchmark rule + flag")
    cl, sn = t["dim_client"], t["fact_portfolio_snapshot"]
    blank = is_blank(cl["risk_profile"])
    print(f"  before: {blank.sum()} blank risk_profile")

    # reconcile: confirm the rule risk_profile -> benchmark on clients that HAVE a profile
    m = sn.merge(cl[["client_id", "risk_profile"]], on="client_id")
    known = m[~is_blank(m["risk_profile"])]
    rule_holds = (known["benchmark_id"] == known["risk_profile"].map(RISK_TO_BENCHMARK)).mean()
    print(f"  rule check on {len(known):,} snapshots of known profiles: {rule_holds:.2%} follow the rule")
    assert rule_holds == 1.0, "risk_profile -> benchmark rule does not hold; fill would be a guess"
    # benchmarks that belong to exactly ONE profile can be read back to that profile
    owners = pd.Series(RISK_TO_BENCHMARK).groupby(lambda rp: RISK_TO_BENCHMARK[rp]).apply(lambda s: list(s.index))
    inverse = {bm_id: rps[0] for bm_id, rps in owners.items() if len(rps) == 1}
    print(f"  benchmarks that identify a single profile: {inverse}")
    bm = m[is_blank(m["risk_profile"])].groupby("client_id")["benchmark_id"].agg(lambda s: set(s))
    single = bm[bm.map(len) == 1].map(lambda s: next(iter(s)))
    fillable = single[single.isin(inverse)].map(inverse)
    print(f"  blank clients with snapshots: {len(bm)}, all on one benchmark: {len(single)}, "
          f"benchmark uniquely identifies profile: {len(fillable)}")

    mask = blank & cl["client_id"].isin(fillable.index)
    cl["risk_profile_imputed"] = 0
    n = record_changes("dim_client", cl, mask, "risk_profile", cl.loc[mask, "client_id"].map(fillable))
    cl.loc[mask, "risk_profile_imputed"] = 1
    left = is_blank(cl["risk_profile"]).sum()
    print(f"  after : {n} filled with 'Balanced', still blank = {left}, flagged = {cl['risk_profile_imputed'].sum()}")
    assert n == blank.sum(), "not every blank profile could be verified - review before filling"
    assert left == 0 and cl["risk_profile_imputed"].sum() == n
    expect("D05", n)
    log("dim_client", "D05", "risk_profile blank", "fill 'Balanced' + risk_profile_imputed=1", n,
        "all snapshots of these clients use benchmark 3, which only Balanced uses (rule holds 100%)")


def d02_orphan_transactions(t):
    header("D02  fact_transactions orphan client_id -> quarantine")
    tx = t["fact_transactions"]
    valid = set(t["dim_client"]["client_id"])
    orphan = ~tx["client_id"].isin(valid)
    amt = num(tx.loc[orphan, "amount"]).sum()
    # verify these are genuinely missing clients, not a format problem making valid ids look orphaned
    oid = tx.loc[orphan, "client_id"]
    assert oid.str.fullmatch(r"\d+").all(), "orphan client_id has a format problem (e.g. '45.0') - fix, don't quarantine"
    assert (oid.astype(int) > max(int(c) for c in valid)).all(), "an orphan id falls inside the client id range"
    assert tx.loc[orphan, "advisor_id"].isin(set(t["dim_advisor"]["advisor_id"])).all()
    print(f"  verified: orphan ids are clean integers {oid.astype(int).min()}-{oid.astype(int).max()}, "
          f"all above the highest client id, advisors valid")
    print(f"  before: {len(tx):,} rows, {orphan.sum()} orphan rows, "
          f"{tx.loc[orphan, 'client_id'].nunique()} distinct ids, amount ${amt:,.2f}")
    t["fact_transactions"] = quarantine("fact_transactions_orphan_client", "fact_transactions",
                                        tx, orphan, "client_id not in dim_client")
    after = t["fact_transactions"]
    print(f"  after : {len(after):,} rows, orphan rows = {(~after['client_id'].isin(valid)).sum()}")
    assert after["client_id"].isin(valid).all()
    assert len(after) + orphan.sum() == len(tx)
    expect("D02", int(orphan.sum()))
    log("fact_transactions", "D02", "client_id not in dim_client", "quarantine", orphan.sum(),
        f"{tx.loc[orphan, 'client_id'].nunique()} distinct ids, total amount ${amt:,.2f}")


def d07_negative_shares(t):
    header("D07  fact_transactions.shares negative -> absolute value")
    tx = t["fact_transactions"]
    sh, pr, am = num(tx["shares"]), num(tx["price"]), num(tx["amount"])
    neg = sh < 0
    print(f"  before: {neg.sum()} negative, by type {tx.loc[neg, 'txn_type'].value_counts().to_dict()}")
    # reconcile: the stored amount must match |shares| x price, and NOT shares x price
    ok_abs = ((sh.abs() * pr - am).abs() <= 0.05)[neg]
    ok_signed = ((sh * pr - am).abs() <= 0.05)[neg]
    print(f"  reconcile: |shares| x price = amount for {ok_abs.sum()} / {neg.sum()}; "
          f"signed for {ok_signed.sum()}")
    assert ok_abs.all() and not ok_signed.any(), "amount does not confirm a sign error"
    assert (tx.loc[neg, "txn_type"] == "Buy").all()

    n = record_changes("fact_transactions", tx, neg, "shares", tx.loc[neg, "shares"].str.lstrip("-"))
    sh2 = num(tx["shares"])
    sec = tx["txn_type"].isin(SECURITY_TXN_TYPES)
    recon = ((sh2 * num(tx["price"]) - num(tx["amount"])).abs() <= 0.05)[sec].mean()
    print(f"  after : {n} changed, negative remaining = {(sh2 < 0).sum()}, "
          f"shares x price = amount on {recon:.2%} of security rows")
    assert (sh2 < 0).sum() == 0 and recon == 1.0
    expect("D07", n)
    log("fact_transactions", "D07", "negative shares on Buy", "convert: absolute value", n,
        "amount reconciles to |shares| x price for 100% of changed rows")


def d06_percent_returns(t):
    header("D06  fact_portfolio_snapshot.return_ytd '9.28%' -> 0.0928")
    sn = t["fact_portfolio_snapshot"]
    pct = sn["return_ytd"].str.endswith("%")
    print(f"  before: {pct.sum()} percent-text values, e.g. {sn.loc[pct, 'return_ytd'].head(3).tolist()}")
    # format(..., "f") never produces scientific notation ('1000%' -> '10', not '1E+1')
    new = sn.loc[pct, "return_ytd"].map(lambda v: format((Decimal(v.strip().rstrip("%")) / 100).normalize(), "f"))
    # reconcile against the alpha identity BEFORE writing
    check = (num(new) - num(sn.loc[pct, "benchmark_return_ytd"]) - num(sn.loc[pct, "active_alpha_ytd"])).abs()
    print(f"  reconcile: value/100 = benchmark + alpha (<=0.0001) for {(check <= 1e-4).sum()} / {pct.sum()}")
    assert (check <= 1e-4).all(), "a converted return does not reconcile with benchmark + alpha"

    n = record_changes("fact_portfolio_snapshot", sn, pct, "return_ytd", new)
    r = num(sn["return_ytd"])
    alpha_ok = ((r - num(sn["benchmark_return_ytd"]) - num(sn["active_alpha_ytd"])).abs() <= 1e-4).mean()
    print(f"  after : {n} converted, non-numeric remaining = {r.isna().sum()}, "
          f"alpha identity holds on {alpha_ok:.2%} of rows")
    assert r.notna().all() and alpha_ok == 1.0
    expect("D06", n)
    log("fact_portfolio_snapshot", "D06", "return_ytd stored as percent text", "convert: strip %, /100", n,
        "100% reconcile to benchmark_return_ytd + active_alpha_ytd")


def d08_aum_floor(t):
    header("D08  aum exactly 1,000.00 -> aum_floor_flag (value kept)")
    sn, fe = t["fact_portfolio_snapshot"], t["fact_fees"]
    # reconcile: fees and snapshots must agree on the same client-month before flagging both
    j = fe.merge(sn[["client_id", "snapshot_date", "aum"]], left_on=["client_id", "fee_date"],
                 right_on=["client_id", "snapshot_date"], how="left")
    agree = (j["aum_basis"] == j["aum"]).mean()
    print(f"  reconcile: fee aum_basis = snapshot aum for {agree:.2%} of fees")
    assert agree == 1.0
    for name, df, col in [("fact_portfolio_snapshot", sn, "aum"), ("fact_fees", fe, "aum_basis")]:
        before_vals = df[col].copy()
        df["aum_floor_flag"] = (df[col] == AUM_FLOOR).astype(int)
        k = df["aum_floor_flag"].sum()
        print(f"  {name}: flagged {k}; minimum {col} = {num(df[col]).min()}")
        assert df[col].equals(before_vals), "flagging changed a value"
        assert k == (num(df[col]) == 1000).sum()
        expect(f"D08 {name}", int(k))
        log(name, "D08", f"{col} sitting at 1,000.00 floor", "flag aum_floor_flag=1 (value kept)", k,
            "no other source for true AUM; fee and snapshot agree 100%")
    # a flagged fee should sit on a flagged snapshot
    fl = fe.merge(sn[["client_id", "snapshot_date", "aum_floor_flag"]], left_on=["client_id", "fee_date"],
                  right_on=["client_id", "snapshot_date"], suffixes=("", "_snap"))
    assert (fl["aum_floor_flag"] == fl["aum_floor_flag_snap"]).all()


def d09_extreme_returns(t):
    header(f"D09  return_ytd > {EXTREME_HIGH:+.0%} or < {EXTREME_LOW:+.0%} -> extreme_return_flag")
    sn = t["fact_portfolio_snapshot"]
    r = num(sn["return_ytd"])
    assert r.notna().all(), "D06 must run before D09"
    before_vals = sn["return_ytd"].copy()
    hi, lo = r > EXTREME_HIGH, r < EXTREME_LOW
    sn["extreme_return_flag"] = (hi | lo).astype(int)
    k = sn["extreme_return_flag"].sum()
    clients = sn.loc[hi | lo, "client_id"].nunique()
    print(f"  flagged {k:,} rows ({hi.sum()} high, {lo.sum()} low) across {clients} clients; "
          f"benchmark min {num(sn['benchmark_return_ytd']).min():.1%}")
    assert sn["return_ytd"].equals(before_vals)
    expect("D09", int(k))
    log("fact_portfolio_snapshot", "D09", "implausible YTD return", "flag extreme_return_flag=1 (value kept)", k,
        f"{hi.sum()} > +100%, {lo.sum()} < -50%, {clients} clients; alpha identity still holds")


def log_leave_as_is(raw):
    """Record the leave-as-is decisions (L01-L12) with counts computed from the RAW tables,
    so they match the decision log's evidence (review finding 02-#7)."""
    tx, sec, cl = raw["fact_transactions"], raw["dim_security"], raw["dim_client"]
    sn, fe, adv, dd = raw["fact_portfolio_snapshot"], raw["fact_fees"], raw["dim_advisor"], raw["dim_date"]
    since = cl.set_index("client_id")["client_since"]
    early_sn = int((sn["snapshot_date"] < sn["client_id"].map(since)).sum())
    early_fe = int((fe["fee_date"] < fe["client_id"].map(since)).sum())
    early_tx = int((tx["txn_date"] < tx["client_id"].map(since)).sum())
    cash = ~tx["txn_type"].isin(SECURITY_TXN_TYPES)
    etf = sec["is_etf"] == "True"
    d = pd.to_datetime(dd["date"])
    hol = d.dt.strftime("%m-%d").isin(["01-01", "07-04", "12-25"]) & (d.dt.dayofweek < 5) & (dd["is_trading_day"] == "1")
    names = adv["first_name"].duplicated(keep=False) | adv["last_name"].duplicated(keep=False)
    unused_bm = int((~raw["dim_benchmark"]["benchmark_id"].isin(set(sn["benchmark_id"]))).sum())
    no_fee = len(set(zip(sn["client_id"], sn["snapshot_date"])) - set(zip(fe["client_id"], fe["fee_date"])))
    per_client = sn.groupby("client_id").size()
    items = [
        ("fact_portfolio_snapshot", "L01", "snapshot dated before client_since", early_sn,
         f"the snapshot for the joining month is stamped the 1st; {early_tx} transactions precede client_since"),
        ("fact_fees", "L01", "fee dated before client_since", early_fe, "same month-grain effect as snapshots"),
        ("fact_transactions", "L02", "blank security_id/shares/price", int(cash.sum()),
         "structural: exactly the Deposit / Withdrawal / Advisory Fee rows (raw count)"),
        ("dim_security", "L03", "blank expense_ratio_bps on non-ETFs", int((~etf & is_blank(sec["expense_ratio_bps"])).sum()),
         "single stocks have no expense ratio"),
        ("dim_security", "L03", "blank sector on ETFs", int((etf & is_blank(sec["sector"])).sum()),
         "multi-sector funds have no single sector"),
        ("dim_advisor", "L04", "certifications = 'None'", int((adv["certifications"] == "None").sum()),
         "real value (no certification), kept as text"),
        ("dim_security", "L05", "duplicate security names", int(sec["name"].duplicated(keep=False).sum()),
         "different tickers/asset classes - distinct securities"),
        ("dim_advisor", "L06", "shared first or last names", int(names.sum()), "different people"),
        ("dim_client", "L07", "zip_code with leading zero", int(cl["zip_code"].str.startswith("0").sum()), "kept as text"),
        ("dim_date", "L08", "is_trading_day ignores market holidays", len(dd),
         f"whole column affected; {int(hol.sum())} fixed-date holidays marked trading; needs external calendar"),
        ("dim_client", "L09", "inactive clients with history", int((cl["is_active"] == "False").sum()), "real history"),
        ("dim_benchmark", "L10", "benchmarks unused by snapshots", unused_bm, "dimension members may be unused"),
        ("fact_fees", "L11", "snapshot client-months with no fee row", no_fee,
         "cannot recompute a fee that was never charged"),
        ("fact_portfolio_snapshot", "L12", "clients with < 60 snapshots", int((per_client < 60).sum()),
         "joined after Jan-2020"),
    ]
    for table, did, issue, rows, note in items:
        log(table, did, issue, "leave as is", rows, note)


# --------------------------------------------------------------------------
# Final validation
# --------------------------------------------------------------------------
def final_checks(raw_counts, t):
    header("FINAL CHECKS")
    q_counts = {}
    for _, (table, q) in QUARANTINE.items():
        q_counts[table] = q_counts.get(table, 0) + len(q)
    print(f"  {'table':<26}{'raw':>10}{'clean':>10}{'quarantined':>13}  ok")
    for tb in TABLES:
        raw, clean, qn = raw_counts[tb], len(t[tb]), q_counts.get(tb, 0)
        ok = raw == clean + qn
        print(f"  {tb:<26}{raw:>10,}{clean:>10,}{qn:>13,}  {'yes' if ok else 'NO'}")
        assert ok, f"{tb}: raw != clean + quarantined"

    tx = t["fact_transactions"]
    cash = ~tx["txn_type"].isin(SECURITY_TXN_TYPES)
    for ft, fk, dt, dk in ID_RELATIONSHIPS + DATE_RELATIONSHIPS:
        v = t[ft][fk]
        blank = is_blank(v)
        # a blank key is only legitimate for security_id on cash-flow rows (decision log L02)
        allowed_blank = (cash & blank) if (ft, fk) == ("fact_transactions", "security_id") else pd.Series(False, index=v.index)
        assert not (blank & ~allowed_blank).any(), f"{ft}.{fk}: {int((blank & ~allowed_blank).sum())} unexpected blank keys"
        rate = v[~blank].isin(set(t[dt][dk])).mean()
        print(f"  RI {ft}.{fk} -> {dt}.{dk}: {rate:.2%}  (blank keys: {int(blank.sum()):,}, all structural)")
        assert rate == 1.0

    for tb in TABLES:
        assert t[tb][PK[tb]].is_unique, f"{tb} PK not unique"

    fe, sn, cl = t["fact_fees"], t["fact_portfolio_snapshot"], t["dim_client"]
    fee_ok = ((num(fe["aum_basis"]) * num(fe["bps_charged"]) / 120000 - num(fe["amount"])).abs() <= 0.02).mean()
    alpha_ok = ((num(sn["return_ytd"]) - num(sn["benchmark_return_ytd"]) - num(sn["active_alpha_ytd"])).abs() <= 1e-4).mean()
    sec = tx["txn_type"].isin(SECURITY_TXN_TYPES)
    trade_ok = ((num(tx["shares"]) * num(tx["price"]) - num(tx["amount"])).abs() <= 0.05)[sec].mean()
    adv = cl.set_index("client_id")["advisor_id"]
    adv_ok = {f: (t[f]["advisor_id"] == t[f]["client_id"].map(adv)).mean()
              for f in ["fact_fees", "fact_portfolio_snapshot", "fact_transactions"]}
    print(f"  fee amount = aum_basis x bps / 10000 / 12: {fee_ok:.2%}")
    print(f"  active_alpha_ytd = return_ytd - benchmark_return_ytd: {alpha_ok:.2%}")
    print(f"  amount = shares x price (security txns): {trade_ok:.2%}")
    print(f"  fact advisor_id = dim_client.advisor_id: " + ", ".join(f"{k} {v:.2%}" for k, v in adv_ok.items()))
    assert fee_ok == 1.0 and alpha_ok == 1.0 and trade_ok == 1.0 and all(v == 1.0 for v in adv_ok.values())

    # expected row counts from the decision log
    assert len(t["dim_client"]) == 2500 and len(tx) == 298572, "clean row counts differ from the decision log"
    assert q_counts == {"dim_client": 25, "fact_transactions": 200}, f"quarantine counts differ: {q_counts}"


def pre_write_checks(t, raw_cols, vc):
    """Everything that must hold before a single file is written (review finding 02-#4)."""
    header("PRE-WRITE CHECKS")
    flag_cols = {"risk_profile_imputed", "aum_floor_flag", "extreme_return_flag"}
    for tb in TABLES:
        cols = list(t[tb].columns)
        assert cols[:len(raw_cols[tb])] == raw_cols[tb], f"{tb}: original columns changed"
        assert set(cols[len(raw_cols[tb]):]) <= flag_cols, f"{tb}: unexpected new column"
        for fc in set(cols) & flag_cols:
            assert t[tb][fc].isin([0, 1]).all(), f"{tb}.{fc} is not 0/1"
    # value_changes must agree with cleaning_log step by step, not just in total
    per_col = vc.groupby(["table", "column"]).size()
    for row in CLEAN_LOG:
        if row["decision_id"] in STEP_COLUMN:
            key = STEP_COLUMN[row["decision_id"]]
            got = int(per_col.get(key, 0))
            print(f"  {row['decision_id']}: cleaning_log {row['rows_affected']:,} = value_changes {got:,}")
            assert got == row["rows_affected"], f"{row['decision_id']}: log and value_changes disagree"
    assert set(per_col.index) == set(STEP_COLUMN.values()), "value_changes has cells from an unlogged step"


# --------------------------------------------------------------------------
def write_readme(t, raw_counts):
    sn, fe, cl = t["fact_portfolio_snapshot"], t["fact_fees"], t["dim_client"]
    tx = t["fact_transactions"]
    vc = pd.concat(VALUE_CHANGES, ignore_index=True)
    n_shares = int(((vc["table"] == "fact_transactions") & (vc["column"] == "shares")).sum())
    n_imp = int(cl["risk_profile_imputed"].sum())
    bm_min = num(sn["benchmark_return_ytd"]).min()
    cash_share = (tx["security_id"] == "").mean()
    no_fee = len(set(zip(sn["client_id"], sn["snapshot_date"])) - set(zip(fe["client_id"], fe["fee_date"])))
    qtx = len(QUARANTINE["fact_transactions_orphan_client"][1])
    qamt = num(QUARANTINE["fact_transactions_orphan_client"][1]["amount"]).sum()
    text = f"""# Wildcat Capital - clean tables

Produced by `scripts/02_clean.py` from the eight raw extracts. Raw files were not modified.
Decisions are documented in `../../decision_log.md`; every changed cell is in `../audit/value_changes.csv`.

## Files and row counts

| File | Raw rows | Clean rows | Quarantined |
|---|---:|---:|---:|
""" + "\n".join(
        f"| `{tb}.csv` | {raw_counts[tb]:,} | {len(t[tb]):,} | {raw_counts[tb] - len(t[tb]):,} |" for tb in TABLES) + f"""

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
| `fact_transactions.security_id` | `dim_security.security_id` | blank on Deposit / Withdrawal / Advisory Fee ({cash_share:.0%}) - structural |
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
| `dim_client` | `risk_profile_imputed` | risk_profile was blank and filled with `Balanced` from the benchmark rule (all snapshots on benchmark 3) | {cl['risk_profile_imputed'].sum()} |
| `fact_portfolio_snapshot` | `aum_floor_flag` | `aum` is exactly 1,000.00, the column minimum - likely a system floor, not a market value | {sn['aum_floor_flag'].sum()} |
| `fact_fees` | `aum_floor_flag` | `aum_basis` is exactly 1,000.00 (same client-months as above) | {fe['aum_floor_flag'].sum()} |
| `fact_portfolio_snapshot` | `extreme_return_flag` | `return_ytd` > +100% or < -50% (benchmarks never fell below {bm_min:.1%}) | {sn['extreme_return_flag'].sum():,} |

Suggested use: exclude `extreme_return_flag = 1` from average-return and alpha measures (or use medians);
exclude `aum_floor_flag = 1` from AUM trend analysis.

## Known limitations (not fixed, with reason)

1. **{qtx} transactions quarantined for unknown clients** (`../audit/quarantine_fact_transactions_orphan_client.csv`, total amount ${qamt:,.2f}).
   Their client IDs do not exist in `dim_client`; attributing them would be invented data. Firm-level transaction totals are understated by this amount.
2. **Imputed risk profiles.** {n_imp} clients carry `Balanced` because that is how their accounts are benchmarked. If benchmark 3 was a system
   default for missing profiles, this describes the benchmark, not the client's stated risk tolerance. Use `risk_profile_imputed` to exclude them.
3. **AUM floor and extreme returns are flagged, not corrected.** There is no other source for the true AUM; the returns are internally consistent
   (alpha identity holds) but implausible.
4. **`dim_date.is_trading_day` marks every weekday as a trading day,** including market holidays (e.g. 2020-01-01). Fixing it needs an external
   exchange calendar, which is outside the provided data. Trading-day counts are overstated by roughly 9-10 days a year.
5. **{no_fee:,} client-months have a snapshot but no fee row.** Possibly fee waivers or billing gaps; a fee cannot be recomputed without inventing a rate and fee type.
6. **Monthly rows dated before `client_since`.** Snapshots and fees for the joining month are stamped the 1st, so they precede a mid-month
   `client_since`. This is a grain difference, not an error: compare at month level.
7. **`fact_transactions.shares` sign.** {n_shares} negative Buy quantities were made positive because the amount reconciles only to |shares| x price.
   If any were meant as reversals, they are now counted as purchases (all are listed in `value_changes.csv`).
"""
    with open(os.path.join(CLEAN_DIR, "README_clean.md"), "w", encoding="utf-8") as f:
        f.write(text)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=None)
    args = ap.parse_args()
    data_dir = locate_data(args.data)
    CLEAN_LOG.clear(); VALUE_CHANGES.clear(); QUARANTINE.clear()   # safe if main() runs twice

    print(f"Reading raw files (as text) from: {data_dir}")
    t, raw_counts, raw_cols = {}, {}, {}
    for tb in TABLES:
        path = find_file(data_dir, tb)
        if path is None:
            sys.exit(f"missing {tb}.csv")
        t[tb] = pd.read_csv(path, dtype=str, keep_default_na=False)
        raw_counts[tb], raw_cols[tb] = len(t[tb]), list(t[tb].columns)
        print(f"  {tb:<26}{len(t[tb]):>9,} rows  <- {os.path.basename(path)}")

    raw = {tb: df.copy() for tb, df in t.items()}     # untouched copy for leave-as-is counts

    d01_security_id(t)
    d03_duplicate_clients(t)
    d04_state(t)
    d05_risk_profile(t)
    d02_orphan_transactions(t)
    d07_negative_shares(t)
    d06_percent_returns(t)
    d08_aum_floor(t)
    d09_extreme_returns(t)
    log_leave_as_is(raw)
    final_checks(raw_counts, t)
    vc = pd.concat(VALUE_CHANGES, ignore_index=True)
    pre_write_checks(t, raw_cols, vc)

    # only now - with every assertion passed - is anything written
    header("WRITING OUTPUTS")
    os.makedirs(CLEAN_DIR, exist_ok=True)
    os.makedirs(AUDIT_DIR, exist_ok=True)
    for tb in TABLES:
        t[tb].to_csv(os.path.join(CLEAN_DIR, f"{tb}.csv"), index=False)
        added = list(t[tb].columns)[len(raw_cols[tb]):]
        print(f"  data/clean/{tb}.csv  ({len(t[tb]):,} rows, added: {added or 'none'})")
    pd.DataFrame(CLEAN_LOG).to_csv(os.path.join(AUDIT_DIR, "cleaning_log.csv"), index=False)
    vc.to_csv(os.path.join(AUDIT_DIR, "value_changes.csv"), index=False)
    for name, (_, q) in QUARANTINE.items():
        q.to_csv(os.path.join(AUDIT_DIR, f"quarantine_{name}.csv"), index=False)
    write_readme(t, raw_counts)
    print(f"  data/audit/cleaning_log.csv ({len(CLEAN_LOG)} entries)")
    print(f"  data/audit/value_changes.csv ({len(vc):,} changed cells)")
    for name, (_, q) in QUARANTINE.items():
        print(f"  data/audit/quarantine_{name}.csv ({len(q)} rows)")
    print("  data/clean/README_clean.md")
    print("\nDone - all assertions passed.")


if __name__ == "__main__":
    main()
