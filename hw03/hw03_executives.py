"""
HW03 - Specification B: Executive Events Pipeline (SEC EDGAR 8-K, Item 5.02)

For each company, finds 8-K filings from the past 12 months that report
Item 5.02 (Departure of Directors or Certain Officers; Election of Directors;
Appointment of Certain Officers), downloads the full 8-K, isolates the
Item 5.02 section, and extracts one row per executive event: event type,
person name, title, and effective date. Results are printed as they are
processed and saved to executive_events.csv next to this script.
"""

import csv
import datetime
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

TARGET_ITEM = "5.02"
LOOKBACK_DAYS = 365
REQUEST_DELAY = 0.2   # seconds; SEC allows at most 10 requests/second
TIMEOUT = 30          # seconds
NOT_FOUND = "NOT_FOUND"

SCRIPT_DIR = Path(__file__).parent
OUTPUT_CSV = SCRIPT_DIR / "executive_events.csv"
CSV_COLUMNS = [
    "company", "ticker", "cik", "filing_date", "event_type",
    "person_name", "title", "effective_date",
]
FIELD_COLUMNS = ["event_type", "person_name", "title", "effective_date"]


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


def filter_filings(submissions, item_code, since_date):
    """Return 8-K filings with item_code filed on or after since_date, newest first."""
    recent = submissions.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    accessions = recent.get("accessionNumber", [])
    primary_docs = recent.get("primaryDocument", [])
    items_list = recent.get("items", [])
    since = since_date.isoformat()  # YYYY-MM-DD strings compare correctly

    matches = []
    for i, form in enumerate(forms):
        if form != "8-K":  # exact match excludes 8-K/A amendments
            continue
        if dates[i] < since:
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

def primary_document_url(cik, filing):
    cik_no_zeros = str(int(cik))
    accession_no_dashes = filing["accession"].replace("-", "")
    return (f"https://www.sec.gov/Archives/edgar/data/"
            f"{cik_no_zeros}/{accession_no_dashes}/{filing['primary_document']}")


def html_to_text(html):
    """Strip HTML to a single line of clean plain text."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    text = soup.get_text(separator=" ")
    text = text.replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def fetch_text(cik, filing):
    return html_to_text(sec_get(primary_document_url(cik, filing)).text)


def isolate_item_502(text):
    """Return the Item 5.02 section, or None if it cannot be isolated.

    The cover page of an 8-K also mentions "5.02" (and the body can refer to
    "Item 5.02(c)"), so the section start is the heading that is followed by
    the item's title words. The section ends at the next "Item X.XX" heading
    or at "SIGNATURE".
    """
    heading = re.search(
        r"Item\s*5\.02\s*[.:\-–—]?\s*(?=Departure|Resignation|Election|Appointment)",
        text, re.IGNORECASE)
    if heading:
        start = heading.end()
    else:
        # Fallback: the last "Item 5.02" that is not a reference like "Item 5.02(c)".
        refs = list(re.finditer(r"Item\s*5\.02(?!\s*\()", text, re.IGNORECASE))
        if not refs:
            return None
        start = refs[-1].end()

    rest = text[start:]
    end = re.search(r"Item\s*\d\.\d\d(?!\s*\()|SIGNATURE", rest, re.IGNORECASE)
    section = rest[:end.start()] if end else rest
    # Drop the item's own title ("Departure of Directors or Certain Officers;
    # Election of Directors; ..."). Its words "Departure" and "Appointment"
    # would otherwise make every filing look like it has both kinds of event.
    section = ITEM_502_TITLE_RE.sub("", section.strip(), count=1)
    return section.strip() or None


# One piece of the Item 5.02 title. The lazy match stops at the first
# Officers/Directors/Arrangements that is followed by ";", "." or a new
# capitalized word, so "Departure of Directors or Certain Officers" is taken
# whole and the first sentence of the body is never swallowed.
_TITLE_PIECE = (r"(?:Departure|Resignation|Election|Appointment|Compensatory)[^.;]*?"
                r"(?:Officers?|Directors?|Arrangements?)(?:[.;]|\s+(?=(?-i:[A-Z]))|$)")
ITEM_502_TITLE_RE = re.compile(rf"^(?:\s*(?:and\s+)?{_TITLE_PIECE})+", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Event extraction
# ---------------------------------------------------------------------------

DEPARTURE_RE = re.compile(
    r"\b(?:resign(?:s|ed|ation)?|retire(?:s|d|ment)?|retiring|step(?:s|ping)?\s+down|"
    r"stepped\s+down|depart(?:s|ed|ure)?|terminat(?:e|es|ed|ion)|"
    r"will\s+not\s+stand\s+for\s+re-?election|leav(?:e|ing)\s+the\s+company)\b",
    re.IGNORECASE)

# "elect" uses word boundaries so it does not fire on "re-election" or "Election".
# "will become" / "to become" is added because filings often phrase an
# appointment that way ("will become Apple's general counsel on March 1").
APPOINTMENT_RE = re.compile(
    r"\b(?:appoint(?:s|ed|ment)?|elect(?:s|ed)?|named|promot(?:ed|ion)|hired|"
    r"will\s+succeed|join(?:s|ed|ing)?|(?:will|to)\s+become)\b",
    re.IGNORECASE)

# One person moving from one role to another ("transition from CEO to Executive Chair").
TRANSITION_RE = re.compile(r"\btransition(?:s|ing)?\s+from\b[^.]*?\bto\b", re.IGNORECASE)

# Name immediately after these words is the person leaving
# ("Mr. Borders succeeds Chris Kondo", "a transition of duties from Kate Adams").
DEPARTING_NAME_BEFORE_RE = re.compile(
    r"(?:\bsucceed(?:s|ing)?|\breplac(?:es|ing|e)|\btransition\b[^.]{0,40}\bfrom)\s+$",
    re.IGNORECASE)

# Background sentences that mention keywords but do not describe an event.
BOILERPLATE_RE = re.compile(
    r"arrangements?\s+or\s+understandings?|family\s+relationships?|Item\s+404|"
    r"related\s+person|material\s+interest|compensat|salary|bonus|equity\s+award|"
    r"restricted\s+stock|indemnif|offer\s+letter|press\s+release|Exhibit\s+99",
    re.IGNORECASE)

# Committee names ("Compensation Committee", "Audit and Finance Committee")
# are removed before the boilerplate check. Otherwise "elected Jane Doe to the
# Board and appointed her to the Compensation Committee" is thrown away as a
# compensation sentence and the person is never found.
COMMITTEE_RE = re.compile(r"\b[A-Z][\w,&]*(?:\s+(?:and|&|of|[A-Z][\w,&]*))*\s+Committee\b")


def is_boilerplate(sentence):
    return bool(BOILERPLATE_RE.search(COMMITTEE_RE.sub("Committee", sentence)))


# Biographical "joined the Company in 2010" is not a new appointment.
BIO_JOIN_RE = re.compile(r"\bjoin(?:ed|s)?\b[^.]{0,40}?\bin\s+\d{4}", re.IGNORECASE)

TITLE_RE = re.compile(
    r"\b(?i:(?:(?:executive|senior|corporate|group)\s+)*(?:vice\s+)?"
    r"(?:chief\s+[a-z]+(?:\s+[a-z]+)?\s+officer|president|general\s+counsel|"
    r"principal\s+(?:accounting|financial|executive)\s+officer|"
    r"chair(?:man|woman)?(?:\s+of\s+the\s+board)?|lead\s+independent\s+director|"
    r"member\s+of\s+the\s+board(?:\s+of\s+directors)?|director|controller|treasurer|"
    r"(?:corporate\s+)?secretary|head\s+of\s+[a-z]+(?:\s+[a-z]+)?))\b"
    # Optional capitalized tail: "President and Chief Executive Officer",
    # "Senior Vice President of Hardware Engineering"
    r"(?:,?\s+(?:of|and|for)\s+(?:the\s+)?[A-Z][\w&’']*"
    r"(?:\s+(?:[A-Z][\w&’']*|&))*)?")

NAME_WORD = r"[A-Z][a-zA-Z’'\-]*[a-z]"
FULL_NAME_RE = re.compile(rf"\b{NAME_WORD}(?:\s+(?:[A-Z]\.|{NAME_WORD})){{1,3}}\b")
HONORIFIC_NAME_RE = re.compile(rf"\b(?:Mr|Ms|Mrs|Dr)\.?\s+({NAME_WORD})")
# Up to two words after an honorific, for multi-word surnames ("Ms. Nora Johnson").
HONORIFIC_SURNAME_RE = re.compile(rf"\b(?:Mr|Ms|Mrs|Dr)\.?\s+({NAME_WORD}(?:\s+{NAME_WORD})?)")

# Capitalized words that are never part of a person's name.
NOT_NAME_WORDS = {
    "on", "the", "in", "as", "at", "by", "for", "of", "and", "upon", "following", "prior",
    "effective", "board", "directors", "director", "company", "chief", "executive", "officer",
    "officers", "financial", "operating", "technology", "senior", "vice", "president",
    "general", "counsel", "principal", "accounting", "chair", "chairman", "chairwoman", "lead",
    "independent", "transition", "date", "committee", "item", "form", "exchange", "act",
    "securities", "annual", "meeting", "shareholders", "stockholders", "global", "hardware",
    "engineering", "human", "resources", "legal", "operations", "certain", "departure",
    "appointment", "election", "compensatory", "arrangements", "nominating", "governance",
    "compensation", "audit", "plan", "agreement", "letter", "press", "release", "exhibit",
    "report", "current", "apple", "microsoft", "nvidia", "walmart", "jpmorgan", "chase",
    "inc", "corporation", "corp", "co", "llc", "bank", "international", "united", "states",
    "commercial", "consumer", "community", "asset", "wealth", "management", "investment",
    "retail", "club", "mr", "ms", "mrs", "dr",
    # Contract and business-unit words that showed up as fake names
    # ("Covenant Not to Compete", "Non-Competition Agreements",
    # "Worldwide Field Operations").
    "agreements", "covenant", "covenants", "not", "non-competition", "non-solicitation",
    "confidentiality", "worldwide", "field", "sales", "marketing", "services", "group",
    "north", "america", "americas", "strategy", "people", "business", "policy",
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december",
    "monday", "tuesday", "wednesday", "thursday", "friday",
}

MONTH = (r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|"
         r"Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?")
DATE = rf"(?:{MONTH}\s+\d{{1,2}},?\s+\d{{4}}|\d{{1,2}}/\d{{1,2}}/\d{{4}})"
DATE_RE = re.compile(DATE)
EFFECTIVE_DATE_RE = re.compile(rf"\beffective(?:\s+as\s+of|\s+on)?\s+({DATE})", re.IGNORECASE)
IMMEDIATE_RE = re.compile(r"\beffective\s+immediately\b|\bupon\s+(?:the\s+)?filing\b",
                          re.IGNORECASE)
MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def normalize_date(raw):
    """'January 15, 2026' / 'Jan. 15, 2026' / '1/15/2026' -> '2026-01-15'."""
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", raw)
    if m:
        month, day, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
    else:
        m = re.match(r"([A-Za-z]+)\.?\s+(\d{1,2}),?\s+(\d{4})", raw)
        if not m:
            return NOT_FOUND
        month = MONTHS.get(m.group(1)[:3].lower())
        day, year = int(m.group(2)), int(m.group(3))
    try:
        return datetime.date(year, month, day).isoformat()
    except (TypeError, ValueError):
        return NOT_FOUND


def split_sentences(text):
    """Split on sentence-ending punctuation, but not after Mr./Ms./Dr./Inc./Co. or initials."""
    # Each lookbehind includes the period itself. (Checking only the letters
    # before the period never matched, so every "Mr." and middle initial
    # ended a sentence and cut names in half.)
    parts = re.split(
        r"(?<!\bMr\.)(?<!\bMs\.)(?<!\bDr\.)(?<!\bMrs\.)(?<!\bInc\.)(?<!\bCo\.)(?<!\bJr\.)"
        r"(?<!\bSr\.)(?<!\bNo\.)(?<!\b[A-Z]\.)(?<=[.!?])\s+(?=[A-Z“\"(])",
        text)
    return [p.strip() for p in parts if p.strip()]


def clean_name_candidate(candidate):
    """Split a capitalized run at non-name words; return a 2-4 word name or None."""
    pieces, current = [], []
    for word in candidate.split():
        base = re.sub(r"[’']s$", "", word)
        if base.rstrip(".").lower() in NOT_NAME_WORDS:
            if current:
                pieces.append(current)
            current = []
        else:
            current.append(base)
    if current:
        pieces.append(current)
    for piece in pieces:
        if 2 <= len(piece) <= 4 and not re.fullmatch(r"[A-Z]\.", piece[-1]):
            return " ".join(piece)
    return None


def honorific_surnames(section):
    """Words that appear right after Mr./Ms./Mrs./Dr. anywhere in the section.

    8-Ks introduce a person by full name and then refer to them as
    "Mr. Surname" / "Ms. Surname". A capitalized phrase whose last word is
    never used that way ("Worldwide Field", "Covenant Not") is almost
    certainly not a person.
    """
    words = set()
    for m in HONORIFIC_SURNAME_RE.finditer(section):
        for word in m.group(1).split():
            words.add(re.sub(r"[’']s$", "", word))
    return words


def is_person(name, confirmed_surnames):
    """Accept a name if its surname is confirmed by an honorific in the section.

    If the section never uses an honorific at all, there is nothing to check
    against, so fall back to the NOT_NAME_WORDS filter alone (the simplest
    rule that still finds names in filings written that way).
    """
    return not confirmed_surnames or name.split()[-1] in confirmed_surnames


def canonical_name(name, known_names):
    """Map a shorter form to the longest known name that ends with it.

    "Ms. Nora Johnson" is matched as "Nora Johnson", but it is the same person
    as "Suzanne Nora Johnson", so both resolve to the full name and the
    duplicate-event check catches it.
    """
    longer = [k for k in known_names
              if len(k.split()) > len(name.split()) and k.endswith(" " + name)]
    return max(longer, key=len) if longer else name


def find_people(sentence, surname_map, confirmed_surnames=frozenset(), known_names=()):
    """Return [(full_name, start, end)] for every person mentioned in a sentence."""
    people = []
    for m in FULL_NAME_RE.finditer(sentence):
        name = clean_name_candidate(m.group(0))
        if name and is_person(name, confirmed_surnames):
            start = sentence.find(name.split()[0], m.start())
            name = canonical_name(name, known_names)
            people.append((name, start, m.end()))
            surname_map.setdefault(name.split()[-1], name)
    for m in HONORIFIC_NAME_RE.finditer(sentence):
        surname = re.sub(r"[’']s$", "", m.group(1))
        if any(start <= m.start(1) < end for _, start, end in people):
            continue
        full = surname_map.get(surname)
        if full:
            people.append((full, m.start(), m.end()))
    people.sort(key=lambda p: p[1])
    return people


def classify(segment, text_before_name):
    """Return 'departure', 'appointment', 'both', or None for one person's text."""
    if DEPARTING_NAME_BEFORE_RE.search(text_before_name):
        return "departure"
    if TRANSITION_RE.search(segment):
        return "both"
    check = BIO_JOIN_RE.sub(" ", segment)
    departed = bool(DEPARTURE_RE.search(check))
    check = re.sub(r"re-?election", " ", check, flags=re.IGNORECASE)
    appointed = bool(APPOINTMENT_RE.search(check))
    if departed and appointed:
        return "both"
    if departed:
        return "departure"
    if appointed:
        return "appointment"
    return None


def clean_title(title):
    return re.sub(r"(?:,?\s+(?:and|of|for|the))+$", "", title.strip(" ,"))


def find_title(after, before, event_type):
    """Title for one person: prefer 'as <title>' after the name, then any title nearby."""
    titles_after = []
    for m in re.finditer(r"\bas\s+(?:the\s+|its\s+|our\s+|[A-Z][\w&]*[’']s\s+)?", after):
        t = TITLE_RE.match(after, m.end())
        if t:
            titles_after.append(clean_title(t.group(0)))
    if not titles_after:
        titles_after = [clean_title(t.group(0)) for t in TITLE_RE.finditer(after)]
    # A transition names two roles: "Chief Executive Officer to Executive Chair".
    if event_type == "both" and len(titles_after) >= 2:
        return f"{titles_after[0]} to {titles_after[1]}"
    if titles_after:
        return titles_after[0]
    titles_before = [clean_title(t.group(0)) for t in TITLE_RE.finditer(before)]
    return titles_before[-1] if titles_before else NOT_FOUND


def find_effective_date(segment, sentence, section, filing_date):
    """Effective date for one event, from the most specific text to the least."""
    m = EFFECTIVE_DATE_RE.search(segment)
    if m:
        return normalize_date(m.group(1))
    if IMMEDIATE_RE.search(segment) or IMMEDIATE_RE.search(sentence):
        return filing_date
    for text in (segment, sentence):
        for d in DATE_RE.finditer(text):
            # Skip announcement dates at the start of a sentence: "On April 20, 2026, ..."
            if re.search(r"(?:^|\s)On\s+$", text[:d.start()]):
                continue
            return normalize_date(d.group(0))
    m = EFFECTIVE_DATE_RE.search(section)
    if m:
        return normalize_date(m.group(1))
    return NOT_FOUND


def extract_events(section, filing_date):
    """Return a list of event dicts from an Item 5.02 section (one per person/event)."""
    events, seen = [], set()
    confirmed = honorific_surnames(section)
    # First pass: learn full names so "Mr. Ternus" can be resolved to "John Ternus".
    known_names = set()
    for m in FULL_NAME_RE.finditer(section):
        name = clean_name_candidate(m.group(0))
        if name and is_person(name, confirmed):
            known_names.add(name)
    surname_map = {}
    # Longest names first, so "Johnson" maps to "Suzanne Nora Johnson".
    for name in sorted(known_names, key=len, reverse=True):
        surname_map.setdefault(name.split()[-1], name)

    for sentence in split_sentences(section):
        if is_boilerplate(sentence):
            continue
        if not (DEPARTURE_RE.search(sentence) or APPOINTMENT_RE.search(sentence)
                or TRANSITION_RE.search(sentence) or re.search(r"\bsucceed", sentence)):
            continue
        people = find_people(sentence, surname_map, confirmed, known_names)
        for i, (name, start, end) in enumerate(people):
            next_start = people[i + 1][1] if i + 1 < len(people) else len(sentence)
            before = sentence[:start]
            after = sentence[end:next_start]
            # The first person in a sentence also owns the text before them
            # ("the Board appointed John Ternus"); later people only own the
            # text after their name.
            segment = (before + " " + after) if i == 0 else after
            event_type = classify(segment, before)
            if not event_type or (name, event_type) in seen:
                continue
            seen.add((name, event_type))
            events.append({
                "event_type": event_type,
                "person_name": name,
                "title": find_title(after, before, event_type),
                "effective_date": find_effective_date(segment, sentence, section, filing_date),
            })

    if not events:
        # Keep the filing in the output even when no person could be matched.
        departed = bool(DEPARTURE_RE.search(section))
        appointed = bool(APPOINTMENT_RE.search(section))
        event_type = ("both" if departed and appointed else "departure" if departed
                      else "appointment" if appointed else NOT_FOUND)
        title = TITLE_RE.search(section)
        events.append({
            "event_type": event_type,
            "person_name": NOT_FOUND,
            "title": clean_title(title.group(0)) if title and event_type != NOT_FOUND else NOT_FOUND,
            "effective_date": find_effective_date("", "", section, filing_date)
                              if event_type != NOT_FOUND else NOT_FOUND,
        })
    return events


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def print_event(row):
    print(f"{row['ticker']} | {row['filing_date']} | {row['event_type']} | "
          f"{row['person_name']} | {row['title']}")


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
    print(f"Saved {len(rows)} events to {OUTPUT_CSV}")
    print("Events per company:")
    for company in COMPANIES:
        count = sum(1 for r in rows if r["ticker"] == company["ticker"])
        print(f"  {company['ticker']}: {count}")
    print("NOT_FOUND counts by field:")
    for col in FIELD_COLUMNS:
        count = sum(1 for r in rows if r[col] == NOT_FOUND)
        print(f"  {col}: {count}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def process_company(company, since_date):
    ticker, cik = company["ticker"], company["cik"]
    rows = []

    try:
        filings = filter_filings(get_submissions(cik), TARGET_ITEM, since_date)
    except Exception as e:
        print(f"WARNING: {ticker}: could not load submissions ({e}); skipping company")
        return rows

    if not filings:
        # Valid result, not an error.
        print(f"{ticker}: No executive events in past 12 months")
        return rows

    for filing in filings:
        try:
            text = fetch_text(cik, filing)
            section = isolate_item_502(text)
            if section is None:
                print(f"  WARNING: {ticker} {filing['accession']}: could not isolate "
                      f"Item 5.02 section; using full text")
                section = text
            events = extract_events(section, filing["filing_date"])
        except Exception as e:
            # One bad filing must not stop the script.
            print(f"  WARNING: {ticker} {filing['accession']}: {e}")
            continue

        for event in events:
            row = {
                "company": company["company"],
                "ticker": ticker,
                "cik": cik,
                "filing_date": filing["filing_date"],
                **event,
            }
            print_event(row)
            rows.append(row)

    return rows


def main():
    since_date = datetime.date.today() - datetime.timedelta(days=LOOKBACK_DAYS)
    print(f"Item {TARGET_ITEM} 8-K filings on or after {since_date.isoformat()}\n")

    all_rows = []
    for company in COMPANIES:
        all_rows.extend(process_company(company, since_date))

    save_csv(all_rows, OUTPUT_CSV)
    print_summary(all_rows)


if __name__ == "__main__":
    main()
