"""
HW03 - Specification A: Earnings Pipeline (SEC EDGAR 8-K, Item 2.02)

For each company, finds the four most recent 8-K filings that report Item 2.02
(Results of Operations), downloads the earnings press release exhibit
(EX-99.1), and extracts the reporting period, revenue, diluted EPS, and
net income. Results are printed as they are processed and saved to
earnings_history.csv next to this script.
"""

import csv
import re
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# CIK is stored as a string; it is zero-padded for the submissions API
# and stripped of leading zeros for Archive URLs.
COMPANIES = [
    {"company": "Apple Inc.", "ticker": "AAPL", "cik": "0000320193"},
    {"company": "Microsoft Corporation", "ticker": "MSFT", "cik": "0000789019"},
    {"company": "NVIDIA Corporation", "ticker": "NVDA", "cik": "0001045810"},
    {"company": "JPMorgan Chase & Co.", "ticker": "JPM", "cik": "0000019617"},
    {"company": "Walmart Inc.", "ticker": "WMT", "cik": "0000104169"},
]

# Sent on EVERY request. sec_get() is the only function that calls
# requests.get(), so no request can go out without this header.
HEADERS = {"User-Agent": "MIS3060 Villanova jferen03@villanova.edu"}

TARGET_ITEM = "2.02"
FILINGS_PER_COMPANY = 4
REQUEST_DELAY = 0.2   # seconds; SEC allows at most 10 requests/second
TIMEOUT = 30          # seconds
NOT_FOUND = "NOT_FOUND"

SCRIPT_DIR = Path(__file__).parent
OUTPUT_CSV = SCRIPT_DIR / "earnings_history.csv"
CSV_COLUMNS = [
    "company", "ticker", "cik", "filing_date", "period",
    "revenue_reported", "eps_diluted", "net_income",
]
FIELD_COLUMNS = ["period", "revenue_reported", "eps_diluted", "net_income"]


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def sec_get(url):
    """GET a sec.gov URL with the required User-Agent, a timeout, and throttling.

    This is the ONLY place in the script that calls requests.get().
    """
    response = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    time.sleep(REQUEST_DELAY)
    response.raise_for_status()
    return response


# ---------------------------------------------------------------------------
# Submissions API
# ---------------------------------------------------------------------------

def get_submissions(cik):
    """Return the submissions JSON for a company (CIK zero-padded to 10 digits)."""
    url = f"https://data.sec.gov/submissions/CIK{str(cik).zfill(10)}.json"
    return sec_get(url).json()


def filter_filings(submissions, item_code):
    """Return 8-K filings whose items list contains item_code, newest first."""
    recent = submissions.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    accessions = recent.get("accessionNumber", [])
    primary_docs = recent.get("primaryDocument", [])
    items_list = recent.get("items", [])

    matches = []
    for i, form in enumerate(forms):
        if form != "8-K":  # exact match excludes 8-K/A amendments
            continue
        items = [code.strip() for code in (items_list[i] or "").split(",")]
        if item_code in items:  # exact match on split values, not substring
            matches.append({
                "filing_date": dates[i],
                "accession": accessions[i],
                "primary_document": primary_docs[i],
            })

    matches.sort(key=lambda f: f["filing_date"], reverse=True)
    return matches


# ---------------------------------------------------------------------------
# Filing documents
# ---------------------------------------------------------------------------

def filing_folder_url(cik, accession):
    cik_no_zeros = str(int(cik))
    return (f"https://www.sec.gov/Archives/edgar/data/"
            f"{cik_no_zeros}/{accession.replace('-', '')}/")


def find_exhibit_url(index_html):
    """Find the EX-99.1 (or first EX-99*) .htm document in a filing index page.

    Returns the absolute URL, or None if no suitable exhibit exists.
    """
    soup = BeautifulSoup(index_html, "html.parser")
    candidates = []  # (type, url)

    for row in soup.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 4:
            continue
        doc_type = cells[3].get_text(strip=True).upper()
        link = row.find("a", href=True)
        if not link:
            continue
        href = link["href"]
        # Inline XBRL viewer links look like /ix?doc=/Archives/...; keep the real path.
        if href.startswith("/ix?doc="):
            href = href[len("/ix?doc="):]
        if not href.lower().endswith((".htm", ".html")):
            continue
        if href.startswith("/"):
            href = "https://www.sec.gov" + href
        candidates.append((doc_type, href))

    for doc_type, url in candidates:
        if doc_type == "EX-99.1":
            return url
    for doc_type, url in candidates:
        if doc_type.startswith("EX-99"):
            return url
    return None


def html_to_text(html):
    """Strip HTML to a single line of clean plain text."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    text = soup.get_text(separator=" ")
    text = text.replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def fetch_press_release_text(ticker, cik, filing):
    """Download the earnings press release for a filing and return plain text.

    Falls back to the primary 8-K document (with a warning) if no EX-99
    exhibit can be found. Any download error propagates to the caller,
    which prints a warning and moves on.
    """
    folder = filing_folder_url(cik, filing["accession"])
    index_url = f"{folder}{filing['accession']}-index.htm"
    exhibit_url = find_exhibit_url(sec_get(index_url).text)

    if exhibit_url is None:
        print(f"  WARNING: {ticker} {filing['accession']}: no EX-99 .htm exhibit "
              f"found; falling back to primary document")
        exhibit_url = folder + filing["primary_document"]

    return html_to_text(sec_get(exhibit_url).text)


# ---------------------------------------------------------------------------
# Field extraction
# ---------------------------------------------------------------------------

AMOUNT = r"([\d,]+(?:\.\d+)?)"
UNIT = r"(billion|million|thousand)?"


def first_match(patterns, text):
    """Return the earliest match (by position in the text) across all patterns."""
    found = [m for p in patterns for m in [re.search(p, text, re.IGNORECASE)] if m]
    return min(found, key=lambda m: m.start()) if found else None


def format_amount(number, unit, negative=False):
    """'94,930.5', 'Billion' -> '94930.5 billion'. No $ sign, no commas."""
    value = number.replace(",", "")
    if negative:
        value = "-" + value
    return f"{value} {unit.lower()}" if unit else value


def extract_period(text):
    patterns = [
        # fourth quarter fiscal 2024 / fourth quarter of fiscal year 2024 / third quarter 2025
        r"\b(?:first|second|third|fourth)\s+(?:fiscal\s+)?quarter\s+(?:of\s+)?"
        r"(?:fiscal\s+)?(?:year\s+)?(?:\d{4}|'\d{2})\b",
        # fiscal 2025 fourth quarter
        r"\bfiscal\s+(?:year\s+)?\d{4}\s+(?:first|second|third|fourth)\s+quarter\b",
        # Q4 FY24 / Q4 2025 / Q4 fiscal 2025
        r"\bQ[1-4]\s*(?:FY|fiscal\s+)?\s*'?\d{2,4}\b",
        # quarter ended June 30, 2025 / three months ended June 30, 2025
        r"\b(?:quarter|three\s+months)\s+ended\s+[A-Za-z]+\.?\s+\d{1,2},\s+\d{4}",
    ]
    m = first_match(patterns, text)
    return m.group(0) if m else NOT_FOUND


def extract_revenue(text):
    rev_words = r"(?:total\s+|net\s+)?(?:revenues?|net\s+sales)"
    patterns = [
        # revenue of $94.9 billion / net sales were $35.1 billion
        rf"\b{rev_words}\b[^$.]{{0,60}}?\$\s?{AMOUNT}\s*{UNIT}",
        # $94.9 billion in revenue
        rf"\$\s?{AMOUNT}\s*(billion|million)\s+(?:in\s+|of\s+)?{rev_words}\b",
    ]
    m = first_match(patterns, text)
    return format_amount(m.group(1), m.group(2)) if m else NOT_FOUND


def extract_eps(text):
    patterns = [
        # diluted earnings per share of $1.64 / diluted net income per share was $(0.12)
        r"\bdiluted\s+(?:earnings|net\s+income|net\s+\(?loss\)?|income|\(?loss\)?)"
        r"(?:\s+\(loss\))?\s+per\s+(?:common\s+)?share\b[^$]{0,40}?\$\s?(\()?(\d+\.\d+)",
        # net income (loss) per diluted share of $(0.12)
        r"\bnet\s+(?:income|\(?loss\)?)(?:\s+\(loss\))?\s+per\s+diluted\s+share\b"
        r"[^$]{0,40}?\$\s?(\()?(\d+\.\d+)",
        # diluted EPS of $1.64
        r"\bdiluted\s+EPS\b[^$]{0,40}?\$\s?(\()?(\d+\.\d+)",
        # $1.64 per diluted share / loss of $0.12 per diluted share
        r"\$\s?(\()?(\d+\.\d+)\)?\s+per\s+diluted\s+share",
    ]
    m = first_match(patterns, text)
    if not m:
        # Fallback: JPMorgan reports only "NET INCOME OF $21.2 BILLION ($7.70 PER SHARE)";
        # that headline per-share figure is its diluted EPS.
        m = re.search(r"\(\s?\$\s?()(\d+\.\d+)\s+per\s+share\)", text, re.IGNORECASE)
    if not m:
        return NOT_FOUND
    # Negative if shown in parentheses, or described as a "loss of $X".
    preceding = text[max(0, m.start() - 15):m.end()]
    negative = bool(m.group(1)) or bool(
        re.search(r"\bloss\s+of\s+\$|\bnet\s+loss\s+per\b", preceding, re.IGNORECASE))
    return ("-" if negative else "") + m.group(2)


def extract_net_income(text):
    patterns = [
        # net income of $23.6 billion / net income was $14.7 billion / net loss of $(1.2) million
        rf"\bnet\s+(income|loss)\b[^$.]{{0,40}}?\b(?:of|was|were|totaled|totaling)\s+"
        # A unit word is required here, so per-share phrases such as
        # "net loss of $0.12 on equity investments" (Walmart) are not mistaken
        # for net income.
        rf"(?:approximately\s+)?\$\s?(\()?{AMOUNT}\)?\s*(billion|million)",
    ]
    m = first_match(patterns, text)
    if m:
        negative = m.group(1).lower() == "loss" or bool(m.group(2))
        return format_amount(m.group(3), m.group(4), negative)

    # Fallback: many releases (Apple, NVIDIA, Walmart) state net income only in
    # the financial statement tables, e.g. "Net income $ 29,789" or
    # "Consolidated net income attributable to Walmart $ 6,366".
    table_patterns = [
        rf"\bnet\s+income\s+attributable\s+to\s+(?!non)[^$]{{0,40}}?\$\s?(\()?{AMOUNT}",
        rf"\bnet\s+(?:income|loss)\s+\$\s?(\()?{AMOUNT}",
    ]
    for pattern in table_patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            unit = table_unit_before(text, m.start())
            return format_amount(m.group(2), unit, negative=bool(m.group(1)))
    return NOT_FOUND


def table_unit_before(text, position):
    """Find the unit of a table figure from the nearest '(In millions...' header above it.

    Table amounts carry no unit word, so the unit comes from the table header.
    A header in parentheses is preferred, because some headers mention a second
    unit later on (Apple: "(In millions, except ... shares ... in thousands)").
    Returns 'million', 'thousand', 'billion', or None if no header is found.
    """
    window = text[max(0, position - 6000):position]
    for pattern in (r"\(\s*\$?\s*in\s+(millions|thousands|billions)\b",
                    r"\bin\s+(millions|thousands|billions)\b"):
        found = re.findall(pattern, window, re.IGNORECASE)
        if found:
            return found[-1].lower().rstrip("s")
    return None


def extract_fields(text):
    return {
        "period": extract_period(text),
        "revenue_reported": extract_revenue(text),
        "eps_diluted": extract_eps(text),
        "net_income": extract_net_income(text),
    }


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def dollar(value):
    """Prefix $ for printing, except for NOT_FOUND."""
    return value if value == NOT_FOUND else f"${value}"


def print_row(row):
    print(f"{row['ticker']} | {row['period']} | "
          f"Revenue: {dollar(row['revenue_reported'])} | "
          f"EPS: {dollar(row['eps_diluted'])} | "
          f"Net Income: {dollar(row['net_income'])}")


def save_csv(rows, path):
    """Write rows with a header (even if empty). Never writes a blank cell."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({
                col: (NOT_FOUND if row.get(col) in (None, "") else row[col])
                for col in CSV_COLUMNS
            })


def print_summary(rows):
    print("\n" + "=" * 60)
    print(f"Saved {len(rows)} rows to {OUTPUT_CSV}")
    print("NOT_FOUND counts by field:")
    for col in FIELD_COLUMNS:
        count = sum(1 for r in rows if r[col] == NOT_FOUND)
        print(f"  {col}: {count}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def process_company(company):
    ticker, cik = company["ticker"], company["cik"]
    rows = []

    try:
        filings = filter_filings(get_submissions(cik), TARGET_ITEM)
    except Exception as e:
        print(f"WARNING: {ticker}: could not load submissions ({e}); skipping company")
        return rows

    selected = filings[:FILINGS_PER_COMPANY]
    if len(selected) < FILINGS_PER_COMPANY:
        print(f"NOTE: {ticker} has only {len(selected)} Item {TARGET_ITEM} 8-K filing(s)")

    for filing in selected:
        row = {
            "company": company["company"],
            "ticker": ticker,
            "cik": cik,
            "filing_date": filing["filing_date"],
            **{col: NOT_FOUND for col in FIELD_COLUMNS},
        }
        try:
            text = fetch_press_release_text(ticker, cik, filing)
            row.update(extract_fields(text))
        except Exception as e:
            # One bad filing must not stop the script. The row is still kept,
            # with NOT_FOUND fields, so the filing is not silently dropped.
            print(f"  WARNING: {ticker} {filing['accession']}: {e}")
        print_row(row)
        rows.append(row)

    return rows


def main():
    all_rows = []
    for company in COMPANIES:
        all_rows.extend(process_company(company))

    save_csv(all_rows, OUTPUT_CSV)
    print_summary(all_rows)


if __name__ == "__main__":
    main()
