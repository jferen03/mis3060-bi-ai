# HW03 Specifications — SEC EDGAR 8-K Pipelines

These are instructions for building two Python scripts. Implement exactly what is described here. When something is unclear, choose the simplest approach that meets the stated requirements, and leave a code comment explaining the choice.

---

## Shared Requirements (apply to both scripts)

### Companies

Both scripts process the same five companies. Define them once at the top of each script as a list of dictionaries with `company`, `ticker`, and `cik`:

| company | ticker | cik |
|---|---|---|
| _TODO_ | _TODO_ | _TODO_ |
| _TODO_ | _TODO_ | _TODO_ |
| _TODO_ | _TODO_ | _TODO_ |
| _TODO_ | _TODO_ | _TODO_ |
| _TODO_ | _TODO_ | _TODO_ |

- Store the CIK as a string. When building the submissions URL, zero-pad it to 10 digits (for example, `320193` becomes `0000320193`).
- When building Archive URLs (filing index and documents), use the CIK **without** leading zeros.

### HTTP requests

- Every HTTP request to any `sec.gov` domain must send this header:
  `User-Agent: MIS3060 Villanova youremail@villanova.edu`
  Define it once as a constant (`HEADERS`) and pass it on every call. Do not make any request without it.
- SEC allows at most 10 requests per second. Wait at least 0.2 seconds (`time.sleep(0.2)`) after every request.
- Use a 30-second timeout on every request. Call `raise_for_status()` so HTTP errors are not silently ignored.
- If a single filing fails to download or parse, print a short warning naming the ticker and accession number, and **continue with the next filing**. One bad filing must not stop the script.

### Reading the submissions API

The response from `https://data.sec.gov/submissions/CIK{cik}.json` holds recent filings in `filings.recent`. That object contains **parallel arrays** where index `i` in each array describes the same filing. Use these arrays:

- `form`: keep only entries equal to exactly `"8-K"` (exclude `"8-K/A"` amendments)
- `filingDate`: in `YYYY-MM-DD` format
- `accessionNumber`: in `0000000000-00-000000` format
- `primaryDocument`: filename of the main 8-K document
- `items`: a comma-separated string such as `"2.02,9.01"`. Split it on commas, strip whitespace, and check whether the target item code is one of the resulting values. Use an exact match on the split values, not a substring search.

Sort matching filings by `filingDate`, newest first.

### Building filing URLs

- Accession number without dashes: `accessionNumber.replace("-", "")`
- Filing folder: `https://www.sec.gov/Archives/edgar/data/{cik_no_zeros}/{accession_no_dashes}/`
- Filing index page: `{filing folder}{accessionNumber}-index.htm` (this part keeps the dashes)
- Primary document: `{filing folder}{primaryDocument}`

### Converting HTML to plain text

- Parse with BeautifulSoup (`html.parser`). Remove `<script>` and `<style>` tags.
- Use `get_text(separator=" ")` so words from neighboring cells or tags don't run together.
- Replace non-breaking spaces (`\xa0`) with regular spaces, then collapse every run of whitespace into a single space.
- Do all regex extraction on this cleaned text.

### Files and paths

- Resolve every output path relative to the script's own folder (`Path(__file__).parent`), so the script behaves the same no matter which directory it is run from.
- Write CSVs with UTF-8 encoding and a header row. Write the header even if there are no data rows.
- Libraries: `requests`, `beautifulsoup4`, and the standard library (`re`, `csv`, `time`, `datetime`, `pathlib`). `pandas` may be used for writing the CSV but is not required.
- Organize the code into small functions (for example `get_submissions`, `filter_filings`, `fetch_text`, `extract_fields`, `save_csv`) and call them from a `main()` function guarded by `if __name__ == "__main__":`.

### Missing values

If a field cannot be extracted (the regex finds no match), store the literal string `"NOT_FOUND"`. **Never leave a cell blank.** A blank cell suggests the data was never looked for, while `NOT_FOUND` records that the script looked and found nothing.

---

## Specification A — Earnings Pipeline (Item 2.02)

**Script:** `hw03/hw03_earnings.py`
**Output:** `hw03/earnings_history.csv`

### Steps

1. **Header.** Use the shared `HEADERS` constant with `User-Agent: MIS3060 Villanova youremail@villanova.edu` on every request.

2. **Find earnings filings.** For each of the five companies, request `https://data.sec.gov/submissions/CIK{cik}.json` and keep 8-K filings whose `items` list includes `"2.02"` (Results of Operations and Financial Condition).

3. **Select four.** Keep the **four most recent** matching filings per company (sorted by `filingDate`, newest first). These represent the last four quarterly earnings releases. If a company has fewer than four, process however many exist and print a note saying so.

4. **Find and download the press release.**
   - Download the filing index page (`{accessionNumber}-index.htm`).
   - In its document table, find the row whose **Type** column is `EX-99.1`. If no row has that type, use the first row whose type starts with `EX-99`. Take the link to that document, which must be an `.htm` or `.html` file.
   - If no EX-99 `.htm` exhibit exists, fall back to the primary document and print a warning.
   - Download the exhibit and convert it to plain text using the shared HTML-to-text steps.

5. **Extract four fields** from the plain text using regular expressions. Search case-insensitively. When several matches are found, use the **first** one, because the headline figures usually appear near the top of the release.

   - **`period`**: the fiscal period being reported. Match phrases such as `fourth quarter fiscal 2024`, `fourth quarter of fiscal year 2024`, `Q4 FY24`, `third quarter 2025`, or `quarter ended June 30, 2025`. Store the matched phrase as it appears in the text.
   - **`revenue_reported`**: quarterly revenue. Look for a dollar amount near the words `revenue`, `revenues`, `total revenue`, `net revenue`, or `net sales` (for example, `revenue of $94.9 billion` or `net sales were $35.1 billion`). Store the number **with its unit** in the form `94.9 billion` or `850.2 million`. Do not store the `$` sign or commas. If there is no unit word next to the number, store the number alone.
   - **`eps_diluted`**: diluted earnings per share. Match patterns such as `diluted earnings per share of $1.64`, `$1.64 per diluted share`, or `diluted EPS of $1.64`. Store only the number (for example `1.64`). Store a loss as a negative number (for example, `$(0.12)` or `loss of $0.12 per diluted share` becomes `-0.12`).
   - **`net_income`**: match `net income of $X billion/million` or `net income was $X billion/million`. Store it the same way as revenue (for example, `23.6 billion`). Store a net loss as a negative number.

   Any field with no match is stored as `"NOT_FOUND"`.

6. **Print progress.** After each filing is processed, print one line in exactly this format:
   ```
   [Ticker] | [Period] | Revenue: $X | EPS: $X | Net Income: $X
   ```
   Example: `AAPL | fourth quarter fiscal 2024 | Revenue: $94.9 billion | EPS: $1.64 | Net Income: $14.7 billion`
   If a value is `NOT_FOUND`, print `NOT_FOUND` in its place without the `$` sign.

7. **Save the CSV.** After all companies are processed, write every row to `hw03/earnings_history.csv` with these columns, in this order:
   `company`, `ticker`, `cik`, `filing_date`, `period`, `revenue_reported`, `eps_diluted`, `net_income`
   - `cik` is the CIK as defined in the company list.
   - `filing_date` is the filing's `filingDate` (`YYYY-MM-DD`).
   - The CSV should contain up to 20 rows (5 companies × 4 filings).

8. **Missing data.** Any field that cannot be extracted is stored as `"NOT_FOUND"`, never blank.

9. **Summary.** At the end, print the total number of rows written and the number of `NOT_FOUND` values in each field column.

---

## Specification B — Executive Events Pipeline (Item 5.02)

**Script:** `hw03/hw03_executives.py`
**Output:** `hw03/executive_events.csv`

### Steps

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
