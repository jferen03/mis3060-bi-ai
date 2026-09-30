# HW03 Validation

Checks of the three output CSVs against `specifications.md`, run on the files generated on 2026-09-29. The structural checks below read the CSVs directly. Sections 5a–5c compare a sample of extracted values against outside sources (company press releases and yfinance), and 5d is the final checklist.

## Summary

| File | Rows | Structure | Data quality |
|---|---|---|---|
| `earnings_history.csv` | 20 (5 companies × 4) | Pass | Pass, one formatting note |
| `executive_events.csv` | 32 | Pass | Several known extraction problems |
| `corporate_events_timeline.csv` | 32 | Pass | Pass (inherits the events-file problems) |

## earnings_history.csv (Specification A)

| Check | Result |
|---|---|
| Columns and order: `company, ticker, cik, filing_date, period, revenue_reported, eps_diluted, net_income` | Pass |
| Up to 20 rows, four most recent per company | Pass: 4 each for AAPL, MSFT, NVDA, JPM, WMT |
| No blank cells | Pass: 0 blanks |
| `filing_date` in `YYYY-MM-DD` | Pass |
| No duplicate filings per company | Pass |
| `revenue_reported` / `net_income` stored as a number plus unit, with no `$` or commas | Pass |
| `eps_diluted` stored as a plain number | Pass |
| `NOT_FOUND` counts | period 0, revenue 0, EPS 0, net income 0 |

**Note:** net income is stored in different units depending on the company. AAPL, NVDA and WMT come out in millions (for example `29789 million`, `59688 million`), while MSFT and JPM come out in billions (for example `35.8 billion`). This follows the spec, which says to store the number with its unit as written, but the values can't be compared across companies without converting them first.

## executive_events.csv (Specification B)

| Check | Result |
|---|---|
| Columns and order: `company, ticker, cik, filing_date, event_type, person_name, title, effective_date` | Pass |
| No blank cells | Pass: 0 blanks |
| `filing_date` and `effective_date` in `YYYY-MM-DD` (or `NOT_FOUND`) | Pass |
| All filings within the past 12 months | Pass: oldest is 2025-09-30 (window starts 2025-09-29) |
| `event_type` is one of `departure`, `appointment`, `both`, `NOT_FOUND` | Pass: 16 appointment, 11 departure, 2 both, 3 NOT_FOUND |
| No exact duplicates (same person and event type in one filing) | Pass |
| Events per company | WMT 13, NVDA 6, JPM 5, AAPL 4, MSFT 4 |
| `NOT_FOUND` counts | event_type 3, person_name 6, title 13, effective_date 7 |

### Known problems

1. **Same person listed more than once in one filing.** The spec only removes duplicates with the same person *and* event type, so these got through. A person moving from one role to another should be a single `both` row.
   - WMT 2025-10-22: Dwayne Milum appears 3 times (appointment, both, departure).
   - WMT 2025-11-14: John R. Furner appears as both an appointment and a departure.
   - WMT 2026-01-16: David Guggina and Latriece Watkins each appear as an appointment and a departure.
2. **Impossible effective date.** WMT 2026-01-16, David Guggina departure: `2020-01-18`. This date most likely comes from his biography, not the event.
3. **Missing names.** None of MSFT's rows has a name. Three MSFT filings (2025-09-30, 2025-12-08, 2026-06-05) have `event_type = NOT_FOUND`, which the spec expects for filings that only cover compensation. Other rows with no name: NVDA 2026-03-06 (President and CEO) and JPM 2026-01-22 (Corporate Secretary).
4. **Missing titles.** 13 of 32 rows have `title = NOT_FOUND`. These are mostly the extra departure rows from problem 1 and the JPM 2026-06-25 leadership changes.

## corporate_events_timeline.csv

| Check | Result |
|---|---|
| All 15 expected columns: the 8 event columns, `earnings_filing_date`, the 4 earnings fields, `days_to_nearest_earnings`, `event_timing` | Pass |
| One row per executive event (32 in, 32 out) | Pass |
| No blank cells | Pass |
| `earnings_filing_date` really is the closest earnings filing for that company (recalculated independently) | Pass: 0 mismatches |
| `days_to_nearest_earnings` equals the gap between the two dates | Pass: 0 mismatches |
| `event_timing` follows the rules (within 7 days = `same week`, otherwise `before earnings`/`after earnings`) | Pass: 0 mismatches |
| Timing distribution | 20 before earnings, 9 after earnings, 3 same week |

Because the timeline copies every row of `executive_events.csv`, the Walmart duplicates in problem 1 inflate its event counts. Counting each 8-K filing once gives 19 filings: 11 before earnings, 7 after, 1 same week.

## 5a. Official source check: earnings

Official figures come from Microsoft's FY26 Q4 earnings press release on its [Investor Relations website](https://www.microsoft.com/en-us/investor/earnings/fy-2026-q4/press-release-webcast).

| Check | Official Source | Your CSV | Match? |
|---|---|---|---|
| MSFT Q4 FY2026 (quarter ended June 30, 2026) Revenue | $90.0 billion | 90.0 billion | Yes |
| MSFT Q4 FY2026 (quarter ended June 30, 2026) EPS Diluted | $4.81 (GAAP) | 4.81 | Yes |

Microsoft also reported non-GAAP diluted EPS of $4.74, which excludes a $0.07 impact from its OpenAI investments. The CSV correctly captured the GAAP figure.

## 5b. Official source check: executive event

Official information comes from Walmart's November 14, 2025 press release on its [corporate newsroom](https://corporate.walmart.com/content/corporate/en_us/news/2025/11/14/walmart-announces-john-furner-as-president-and-chief-executive-o0.html).

| Check | Official Source | Your CSV | Match? |
|---|---|---|---|
| WMT executive event: Person Name | John Furner | John R. Furner | Yes |
| WMT executive event: Event Type | Appointment as President and CEO of Walmart Inc., succeeding Doug McMillon | appointment | Yes |
| WMT executive event: Title | President and Chief Executive Officer | president | Partial |
| WMT executive event: Announcement / Filing Date | November 14, 2025 | 2025-11-14 | Yes |
| WMT executive event: Effective Date | February 1, 2026 | 2026-02-01 | Yes |

The CSV captured only "president" instead of the full title, "President and Chief Executive Officer." It also has a second row for John R. Furner in the same filing, listing him as a departure. That row reflects him leaving his previous role as President and CEO of Walmart U.S., so the event should be recorded once, as `both`.

## 5c. Cross-validation with yfinance

Prompt: *"Write Python using yfinance to get the most recent quarterly revenue and net income for MSFT."* The resulting script is `hw03_yfinance_check.py`.

| Metric | From 8-K text extraction | From yfinance | Match? |
|---|---|---|---|
| Revenue | $90.0 billion | $90.0 billion ($90,007 million) | Yes |
| Net Income | $35.8 billion | $35.8 billion ($35,766 million) | Yes |

Both values match for Microsoft's most recent quarter (fiscal Q4 2026, ended June 30, 2026). The 8-K extraction rounds to one decimal in billions, while yfinance reports exact dollar amounts, so a small rounding difference is expected and doesn't count as a mismatch. Both sources use GAAP net income. Microsoft's non-GAAP net income ($35,286 million, which excludes a $480 million gain on its OpenAI investment) would not have matched, so a gap of about that size would point to a metric definition difference rather than an extraction error.

## 5d. Final checks

| Check | Expected | Actual | Pass/Fail |
|---|---|---|---|
| earnings_history.csv row count | Up to 20 (5 companies × 4 quarters) | 20 (4 each for AAPL, MSFT, NVDA, JPM, WMT) | Pass |
| executive_events.csv row count | At least 0 (document actual) | 32 (WMT 13, NVDA 6, JPM 5, AAPL 4, MSFT 4) | Pass |
| corporate_events_timeline.csv created | Yes | Yes (32 rows, 15 columns) | Pass |
| Rows with all three fields "NOT_FOUND" | 0 (investigate if > 0) | 0 (no NOT_FOUND values for revenue, EPS or net income) | Pass |

In `executive_events.csv`, three Microsoft filings (2025-09-30, 2025-12-08, 2026-06-05) have `NOT_FOUND` for name, title and effective date. These appear to be compensation-only filings, which the spec says to record this way.
