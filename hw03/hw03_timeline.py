"""
HW03 - Corporate Events Timeline

Joins the two HW03 outputs:
  - earnings_history.csv   (Item 2.02 earnings filings, from hw03_earnings.py)
  - executive_events.csv   (Item 5.02 executive events, from hw03_executives.py)

For every executive event, finds the nearest earnings filing for the same
company, measures the gap in days, classifies the timing, and saves the
combined table to corporate_events_timeline.csv next to this script.

Run hw03_earnings.py and hw03_executives.py first so both input CSVs exist.
"""

import csv
from datetime import date
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).parent
EARNINGS_CSV = SCRIPT_DIR / "earnings_history.csv"
EVENTS_CSV = SCRIPT_DIR / "executive_events.csv"
OUTPUT_CSV = SCRIPT_DIR / "corporate_events_timeline.csv"

NOT_FOUND = "NOT_FOUND"
SAME_WEEK_DAYS = 7

# Both source tables share company, ticker, cik and filing_date. To keep
# "all columns from both tables" without two columns named filing_date, the
# event's own date stays `filing_date` and the matched earnings filing's date
# is renamed `earnings_filing_date`. The shared company/ticker/cik columns
# appear once (they are identical for a matched pair).
EVENT_COLUMNS = [
    "company", "ticker", "cik", "filing_date", "event_type",
    "person_name", "title", "effective_date",
]
EARNINGS_FIELD_COLUMNS = ["period", "revenue_reported", "eps_diluted", "net_income"]
OUTPUT_COLUMNS = (
    EVENT_COLUMNS
    + ["earnings_filing_date"]
    + EARNINGS_FIELD_COLUMNS
    + ["days_to_nearest_earnings", "event_timing"]
)


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------

def load_csv(path):
    """Read a CSV into a list of dicts. Every value stays a string, so CIKs
    keep their leading zeros."""
    if not path.exists():
        raise SystemExit(
            f"ERROR: {path.name} not found in {path.parent}. "
            "Run the pipeline that creates it first."
        )
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def parse_date(text):
    """Parse YYYY-MM-DD; return None if the value is missing or malformed."""
    try:
        return date.fromisoformat(text.strip())
    except (AttributeError, ValueError):
        return None


def group_earnings_by_ticker(earnings_rows):
    """Map ticker -> list of (filing date, row), sorted oldest first.

    Companies are matched on ticker rather than CIK, because the ticker is
    the same in both files while CIK formatting (zero-padded or not) could
    differ between scripts.
    """
    grouped = {}
    for row in earnings_rows:
        d = parse_date(row.get("filing_date"))
        if d is None:
            print(f"WARNING: {row.get('ticker')}: skipping earnings row with "
                  f"bad filing_date {row.get('filing_date')!r}")
            continue
        grouped.setdefault(row["ticker"], []).append((d, row))
    for ticker in grouped:
        grouped[ticker].sort(key=lambda pair: pair[0])
    return grouped


# ---------------------------------------------------------------------------
# Match and classify
# ---------------------------------------------------------------------------

def find_nearest_earnings(event_date, earnings_list):
    """Return (earnings_date, earnings_row) closest to event_date.

    Ties (an event exactly halfway between two earnings filings) go to the
    earlier earnings filing, because min() keeps the first of equal values
    and the list is sorted oldest first.
    """
    return min(earnings_list, key=lambda pair: abs((event_date - pair[0]).days))


def classify_timing(signed_days):
    """signed_days = event date minus earnings date.

    'same week' takes priority: any event within 7 days (either side, or the
    same day) of an earnings filing is 'same week'. Otherwise a negative gap
    means the event came first ('before earnings'), a positive gap means it
    came after ('after earnings').
    """
    if abs(signed_days) <= SAME_WEEK_DAYS:
        return "same week"
    return "before earnings" if signed_days < 0 else "after earnings"


def build_timeline(events, earnings_by_ticker):
    """Combine each event with its nearest earnings filing."""
    timeline = []
    for event in events:
        row = {col: event.get(col, NOT_FOUND) for col in EVENT_COLUMNS}
        event_date = parse_date(event.get("filing_date"))
        earnings_list = earnings_by_ticker.get(event.get("ticker"), [])

        if event_date is None or not earnings_list:
            # No way to compare: record NOT_FOUND rather than dropping the event.
            reason = "bad filing_date" if event_date is None else "no earnings filings"
            print(f"WARNING: {event.get('ticker')} | {event.get('filing_date')} | "
                  f"{event.get('person_name')}: {reason}; timing set to NOT_FOUND")
            row["earnings_filing_date"] = NOT_FOUND
            for col in EARNINGS_FIELD_COLUMNS:
                row[col] = NOT_FOUND
            row["days_to_nearest_earnings"] = NOT_FOUND
            row["event_timing"] = NOT_FOUND
        else:
            earn_date, earn_row = find_nearest_earnings(event_date, earnings_list)
            signed_days = (event_date - earn_date).days
            row["earnings_filing_date"] = earn_row["filing_date"]
            for col in EARNINGS_FIELD_COLUMNS:
                row[col] = earn_row.get(col) or NOT_FOUND
            # "Number of days between" is stored as a non-negative count;
            # the direction is captured by event_timing.
            row["days_to_nearest_earnings"] = abs(signed_days)
            row["event_timing"] = classify_timing(signed_days)
            row["_signed_days"] = signed_days  # used for printing only, not saved
        timeline.append(row)

    # Sort chronologically within each company, keeping the company order
    # of the events file.
    company_order = {}
    for row in timeline:
        company_order.setdefault(row["ticker"], len(company_order))
    timeline.sort(key=lambda r: (company_order[r["ticker"]], r["filing_date"]))
    return timeline


# ---------------------------------------------------------------------------
# Save and report
# ---------------------------------------------------------------------------

def save_csv(rows, path):
    """Write the timeline with a header row (even if there are no rows)."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"Saved {len(rows)} rows to {path}\n")


def direction_text(row):
    """Describe where an event falls relative to its nearest earnings filing."""
    if row["event_timing"] == NOT_FOUND:
        return "timing NOT_FOUND (no earnings filing to compare)"
    signed = row["_signed_days"]
    days = abs(signed)
    unit = "day" if days == 1 else "days"
    if signed == 0:
        side = "on the same day as"
    elif signed < 0:
        side = f"{days} {unit} before"
    else:
        side = f"{days} {unit} after"
    label = row["event_timing"].upper()
    return f"{label}: {side} earnings filed {row['earnings_filing_date']}"


def print_company_summary(timeline, events_tickers, earnings_by_ticker):
    """Step 4: per-company list of events and their timing."""
    print("=" * 70)
    print("EXECUTIVE EVENTS vs. NEAREST EARNINGS FILING, BY COMPANY")
    print("=" * 70)

    # Show every company that appears in either file, so a company with
    # earnings but no executive events is still listed.
    tickers = list(dict.fromkeys(list(events_tickers) + list(earnings_by_ticker)))
    for ticker in tickers:
        rows = [r for r in timeline if r["ticker"] == ticker]
        name = rows[0]["company"] if rows else (
            earnings_by_ticker[ticker][0][1]["company"] if ticker in earnings_by_ticker else ticker
        )
        print(f"\n{name} ({ticker}) - {len(rows)} executive event(s)")
        if not rows:
            print("  No executive events in past 12 months")
            continue
        for r in rows:
            who = r["person_name"] if r["person_name"] != NOT_FOUND else "(name NOT_FOUND)"
            role = r["title"] if r["title"] != NOT_FOUND else "(title NOT_FOUND)"
            print(f"  {r['filing_date']} | {r['event_type']:<11} | {who} | {role}")
            print(f"      -> {direction_text(r)}")


def print_final_counts(timeline):
    """Step 5: before vs. after counts across all companies.

    'same week' events are counted in their own bucket (they are the third
    category defined in step 2), and are also broken down by which side of
    the earnings date they fell on, so every event is accounted for.
    """
    before = sum(r["event_timing"] == "before earnings" for r in timeline)
    after = sum(r["event_timing"] == "after earnings" for r in timeline)
    same_week = [r for r in timeline if r["event_timing"] == "same week"]
    sw_before = sum(r["_signed_days"] < 0 for r in same_week)
    sw_after = sum(r["_signed_days"] > 0 for r in same_week)
    sw_same_day = sum(r["_signed_days"] == 0 for r in same_week)
    missing = sum(r["event_timing"] == NOT_FOUND for r in timeline)
    companies = len({r["ticker"] for r in timeline})

    print("\n" + "=" * 70)
    print(f"FINAL COUNT - {len(timeline)} executive events across {companies} companies")
    print("=" * 70)
    print(f"  Before earnings: {before}")
    print(f"  After earnings:  {after}")
    print(f"  Same week (within {SAME_WEEK_DAYS} days): {len(same_week)} "
          f"({sw_before} before, {sw_after} after, {sw_same_day} same day)")
    if missing:
        print(f"  Timing NOT_FOUND: {missing}")
    print(f"\n  Including same-week events by direction: "
          f"{before + sw_before} before vs. {after + sw_after} after"
          + (f" ({sw_same_day} on the same day)" if sw_same_day else ""))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    earnings = load_csv(EARNINGS_CSV)
    events = load_csv(EVENTS_CSV)
    print(f"Loaded {len(earnings)} earnings filings and {len(events)} executive events\n")

    earnings_by_ticker = group_earnings_by_ticker(earnings)
    timeline = build_timeline(events, earnings_by_ticker)
    save_csv(timeline, OUTPUT_CSV)

    events_tickers = dict.fromkeys(e["ticker"] for e in events)
    print_company_summary(timeline, events_tickers, earnings_by_ticker)
    print_final_counts(timeline)


if __name__ == "__main__":
    main()
