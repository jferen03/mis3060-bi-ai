Assignment: HW 3
Student: Jack Ference
Date: 9/29/2026

## Prompts I sent to Claude Cowork

### 1. Specification A: Earnings pipeline (Item 2.02)

hw03/hw03_earnings.py Output: hw03/earnings_history.csv

Steps
Header. Use the shared HEADERS constant with User-Agent: MIS3060 Villanova youremail@villanova.edu on every request.

Find earnings filings. For each of the five companies, request https://data.sec.gov/submissions/CIK{cik}.json and keep 8-K filings whose items list includes "2.02" (Results of Operations and Financial Condition).

Select four. Keep the four most recent matching filings per company (sorted by filingDate, newest first). These represent the last four quarterly earnings releases. If a company has fewer than four, process however many exist and print a note saying so.

Find and download the press release.

Download the filing index page ({accessionNumber}-index.htm).
In its document table, find the row whose Type column is EX-99.1. If no row has that type, use the first row whose type starts with EX-99. Take the link to that document, which must be an .htm or .html file.
If no EX-99 .htm exhibit exists, fall back to the primary document and print a warning.
Download the exhibit and convert it to plain text using the shared HTML-to-text steps.
Extract four fields from the plain text using regular expressions. Search case-insensitively. When several matches are found, use the first one, because the headline figures usually appear near the top of the release.

period: the fiscal period being reported. Match phrases such as fourth quarter fiscal 2024, fourth quarter of fiscal year 2024, Q4 FY24, third quarter 2025, or quarter ended June 30, 2025. Store the matched phrase as it appears in the text.
revenue_reported: quarterly revenue. Look for a dollar amount near the words revenue, revenues, total revenue, net revenue, or net sales (for example, revenue of $94.9 billion or net sales were $35.1 billion). Store the number with its unit in the form 94.9 billion or 850.2 million. Do not store the $ sign or commas. If there is no unit word next to the number, store the number alone.
eps_diluted: diluted earnings per share. Match patterns such as diluted earnings per share of $1.64, $1.64 per diluted share, or diluted EPS of $1.64. Store only the number (for example 1.64). Store a loss as a negative number (for example, $(0.12) or loss of $0.12 per diluted share becomes -0.12).
net_income: match net income of $X billion/million or net income was $X billion/million. Store it the same way as revenue (for example, 23.6 billion). Store a net loss as a negative number.
Any field with no match is stored as "NOT_FOUND".

Print progress. After each filing is processed, print one line in exactly this format:

[Ticker] | [Period] | Revenue: $X | EPS: $X | Net Income: $X

Example: AAPL | fourth quarter fiscal 2024 | Revenue: $94.9 billion | EPS: $1.64 | Net Income: $14.7 billion If a value is NOT_FOUND, print NOT_FOUND in its place without the $ sign.

Save the CSV. After all companies are processed, write every row to hw03/earnings_history.csv with these columns, in this order: company, ticker, cik, filing_date, period, revenue_reported, eps_diluted, net_income

cik is the CIK as defined in the company list.
filing_date is the filing's filingDate (YYYY-MM-DD).
The CSV should contain up to 20 rows (5 companies × 4 filings).
Missing data. Any field that cannot be extracted is stored as "NOT_FOUND", never blank.

Summary. At the end, print the total number of rows written and the number of NOT_FOUND values in each field column.



This one produced `hw03_earnings.py`, which wrote `earnings_history.csv` (20 rows, 4 per company).

### 2. Specification B: Executive events pipeline (Item 5.02)

1. **Header.** Use the same `HEADERS` constant with `User-Agent: MIS3060 Villanova youremail@villanova.edu` on every request.

2. **Find executive-change filings.** For each of the five companies, request the submissions API and keep 8-K filings where **both** of these are true:
   - The `items` list includes `"5.02"` (Departure of Directors or Certain Officers; Election of Directors; Appointment of Certain Officers).
   - `filingDate` falls within the past 12 months, meaning on or after today's date minus 365 days, computed with `datetime.date.today()` when the script runs. Do not hard-code a date.

3. **Download and extract.** For each matching filing:
   - Download the **primary document** (the full 8-K, not an exhibit) and convert it to plain text using the shared steps.
   - **Isolate the Item 5.02 section.** Start at the text `Item 5.02` and stop at the next `Item X.XX` heading or at `SIGNATURE`, whichever comes first. If the section cannot be isolated, use the full text and print a warning.
   - Split the section into sentences, and identify each executive event from the sentences:
     - **Departure keywords:** `resign`, `resignation`, `retire`, `retirement`, `step down`, `depart`, `departure`, `terminate`, `will not stand for re-election`, `leave the company`
     - **Appointment keywords:** `appoint`, `appointed`, `elect`, `elected`, `named`, `promoted`, `hired`, `will succeed`, `join`
   - For each event, extract:
     - **`event_type`**: `"departure"`, `"appointment"`, or `"both"`. Use `"both"` only when **one person** both leaves a role and takes a new one in the same event, such as a transition from President to CEO or from CEO to Executive Chair.
     - **`person_name`**: the person's full name, meaning two to four capitalized words. The name is often preceded by `Mr.`, `Ms.`, `Mrs.`, or `Dr.`, or is followed by a comma and a title. Store the name without the honorific.
     - **`title`**: the role involved, such as `Chief Financial Officer`, `Chief Executive Officer`, `President`, `Director`, `member of the Board of Directors`, or `Executive Vice President ...`. Store the title phrase as written.
     - **`effective_date`**: a date near the words `effective`, `effective as of`, or `effective on`. Accept formats such as `January 15, 2026`, `Jan. 15, 2026`, and `1/15/2026`, and normalize the result to `YYYY-MM-DD`. If the text says the change is effective `immediately` or `upon filing`, use the `filing_date`.
     - Any field with no match is stored as `"NOT_FOUND"`.

4. **One row per event.** If a filing reports several events (for example, one departure and one appointment, or two director elections), create a **separate row for each event**. Remove duplicate events within a single filing, meaning the same person with the same event type. If the 5.02 section contains no departure or appointment (for example, a filing that only covers compensation), still write one row for that filing with `event_type` set to `"NOT_FOUND"`, so the filing is not silently dropped.

5. **Print progress.** Print each event as it is extracted, in exactly this format:
   ```
   [Ticker] | [Date] | [Event Type] | [Name] | [Title]
   ```
   `[Date]` is the `filing_date`.
   Example: `MSFT | 2026-03-02 | appointment | Jane A. Smith | Chief Financial Officer`

6. **No filings found.** If a company has no Item 5.02 filings in the past 12 months, print exactly:
   ```
   [Ticker]: No executive events in past 12 months
   ```
   This is a valid result, not an error. Do not print a warning or raise an exception, and do not add a row for that company to the CSV.

7. **Save the CSV.** Write every event to `hw03/executive_events.csv` with these columns, in this order:
   `company`, `ticker`, `cik`, `filing_date`, `event_type`, `person_name`, `title`, `effective_date`
   Write the header row even if no company had any events.

8. **Summary.** At the end, print the total number of events written, the number of events per company (including companies with zero), and the number of `NOT_FOUND` values in each field column.

This one produced `hw03_executives.py`, which wrote `executive_events.csv` (32 rows).

### 3. Timeline prompt

> Write a Python script that reads `hw03/earnings_history.csv` and `hw03/executive_events.csv`. Do the following:
> 1. For each executive event in the events table, calculate the number of days between the executive event's `filing_date` and the nearest earnings filing date for the same company in the earnings table. Call this `days_to_nearest_earnings`.
> 2. Add a column `event_timing` that categorizes each executive event as: `'before earnings'` if the event came before the nearest earnings filing, `'after earnings'` if it came after, or `'same week'` if within 7 days of an earnings filing.
> 3. Save the combined table to `hw03/corporate_events_timeline.csv` with all columns from both source tables plus `days_to_nearest_earnings` and `event_timing`.
> 4. Print a summary: for each company, list any executive events and whether they occurred before or after the nearest earnings announcement.
> 5. Print a final count: how many events occurred before vs. after an earnings announcement across all five companies.

This gave me `hw03_timeline.py` and `corporate_events_timeline.csv` (32 rows). After looking at the output, I followed up with: *"can you fix the name matching in hw03_executives.py"*

## Which extractions needed another round

The earnings side worked on the first try. All five companies came back with a period, revenue, EPS and net income, and there were zero `NOT_FOUND` values.

The executive events side was a different story. Once I looked at the CSV, a lot of the "names" obviously weren't people, so I had Claude go back and fix the name matching. In the end, every company's results changed:

- **NVIDIA:** one of the names was "Worldwide Field," which is actually part of a job title (Executive Vice President, Worldwide Field Operations). Suzanne Nora Johnson also showed up twice, once as just "Nora Johnson." After the fix, the real name (Ajay K. Puri) shows up and Johnson is only listed once.
- **Walmart:** it picked up "Covenant Not" and "Non-Competition Agreements" as people, which was pretty funny. Those are gone now, but Walmart still has a few people listed more than once in the same filing.
- **Microsoft:** every row said `both` with no name. It turned out the script was reading the Item 5.02 heading itself ("Departure of Directors... Appointment of Certain Officers") as if it described an event. Now the compensation-only filings correctly show `NOT_FOUND`, but the script still can't pull Microsoft names.
- **JPMorgan and Apple:** the script was splitting sentences after every "Mr." or "Ms.," so names were getting cut in half. Fixing that picked up Todd A. Combs and Doug Petno at JPMorgan, and got rid of a fake "Tim Cook, senior vice president" row at Apple.

## Something the script did that I wouldn't have thought to ask for

The fixed script only counts something as a name if the filing also refers to that person as "Mr." or "Ms." plus their last name somewhere else. I never would have thought to spell that out, but it makes sense: 8-Ks introduce someone by full name and then call them "Mr. Smith" for the rest of the filing. For the most part it worked, because every fake name disappeared. I'm not fully sure it's right, though. Apple's April 2026 CEO filing used to have three people (Tim Cook, John Ternus and Art Levinson) and now it only has John Ternus. So it might be throwing out some real people too, and I'd want to check that filing myself before trusting it completely.
