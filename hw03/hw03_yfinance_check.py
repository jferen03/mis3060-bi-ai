"""
HW03 - Cross-check the most recent quarter against yfinance.

Gets the most recent quarterly revenue and net income for a ticker from
yfinance and prints them next to the values extracted from the 8-K text
(earnings_history.csv), as a Markdown table ready to paste.

Usage:
    pip install yfinance
    python hw03_yfinance_check.py          # defaults to MSFT
    python hw03_yfinance_check.py AAPL
"""

import csv
import sys
from pathlib import Path

import yfinance as yf

TICKER = sys.argv[1].upper() if len(sys.argv) > 1 else "MSFT"
EARNINGS_CSV = Path(__file__).parent / "earnings_history.csv"


def get_yfinance_quarter(ticker):
    """Return (period_end, revenue, net_income) for the most recent quarter."""
    stmt = yf.Ticker(ticker).quarterly_income_stmt
    if stmt is None or stmt.empty:
        raise SystemExit(f"yfinance returned no quarterly income statement for {ticker}")
    latest = stmt.columns[0]  # columns are quarter-end dates, newest first
    revenue = stmt.loc["Total Revenue", latest] if "Total Revenue" in stmt.index else None
    net_income = stmt.loc["Net Income", latest] if "Net Income" in stmt.index else None
    return latest.date(), revenue, net_income


def get_csv_quarter(ticker):
    """Return the most recent earnings_history.csv row for the ticker."""
    with open(EARNINGS_CSV, newline="", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r["ticker"] == ticker]
    if not rows:
        raise SystemExit(f"No rows for {ticker} in {EARNINGS_CSV.name}")
    return max(rows, key=lambda r: r["filing_date"])


def to_dollars(value):
    """'90.0 billion' / '29789 million' / '850' -> float dollars (None if NOT_FOUND)."""
    parts = value.split()
    if not parts or parts[0] == "NOT_FOUND":
        return None
    number = float(parts[0])
    unit = parts[1].lower() if len(parts) > 1 else ""
    return number * {"billion": 1e9, "million": 1e6}.get(unit, 1)


def fmt(dollars):
    return "N/A" if dollars is None else f"${dollars / 1e9:,.1f} billion"


def match(a, b, tolerance=0.01):
    """Match if within 1% (the 8-K value is rounded to one decimal)."""
    if a is None or b is None:
        return "Can't compare"
    return "Yes" if abs(a - b) <= tolerance * abs(b) else "No"


def main():
    period_end, yf_rev, yf_ni = get_yfinance_quarter(TICKER)
    row = get_csv_quarter(TICKER)
    csv_rev, csv_ni = to_dollars(row["revenue_reported"]), to_dollars(row["net_income"])

    print(f"{TICKER}: yfinance quarter ended {period_end}; "
          f"8-K filed {row['filing_date']} ({row['period']})\n")
    print("| Metric | From 8-K text extraction | From yfinance | Match? |")
    print("|---|---|---|---|")
    print(f"| Revenue | {fmt(csv_rev)} | {fmt(yf_rev)} | {match(csv_rev, yf_rev)} |")
    print(f"| Net Income | {fmt(csv_ni)} | {fmt(yf_ni)} | {match(csv_ni, yf_ni)} |")


if __name__ == "__main__":
    main()
