import re
import sqlite3
from dateutil import parser as date_parser

DB_PATH = "resources/sunshine_records.db"

KNOWN_DOC_DATES = {
    "RFQ_Data_Center_Development_Support_Services.pdf": ("2026-10-14", "RFQ No. 2026-01: Data Center Development Support Services"),
    "Data_Center_Services_RFQ_Questions.pdf": ("2026-11-03", "RFQ No. 2026-01: Q&A Responses"),
    "Data_Center_Services_RFQ_Addendum_1.pdf": ("2026-11-03", "RFQ No. 2026-01: Addendum 1"),
}


def clean_field(text: str, max_len: int = 160) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text[:max_len]


from datetime import datetime
TZINFOS = {"CST": -21600, "CDT": -18000, "EST": -18000, "EDT": -14400, "MST": -25200, "MDT": -21600, "PST": -28800, "PDT": -25200}

def parse_date_safe(raw: str):
    cleaned = re.sub(r"\s+", " ", raw).strip()
    cleaned = re.sub(r"\s*\([A-Z]{2,5}\)\s*$", "", cleaned)
    if not re.search(r"\b202[0-7]\b|\b\d{1,2}[/-]\d{1,2}[/-]2[0-7]\b", cleaned):
        return None
    try:
        dt = date_parser.parse(cleaned, fuzzy=True, tzinfos=TZINFOS).replace(tzinfo=None)
        if 2020 <= dt.year <= 2027 and dt <= datetime.now():
            return dt
    except Exception:
        pass
    return None


def extract_filename_date(filename: str):
    patterns = [
        (r"(202\d)-(\d{2})-(\d{2})", lambda m: f"{m.group(1)}-{m.group(2)}-{m.group(3)}"),
        (r"(202\d)(\d{2})(\d{2})", lambda m: f"{m.group(1)}-{m.group(2)}-{m.group(3)}"),
        (r"(\d{1,2})\.(\d{1,2})\.(202\d)", lambda m: f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"),
        (r"(\d{1,2})\.(\d{1,2})\.(2\d)(?!\d)", lambda m: f"20{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"),
        (r"(\d{1,2})-(\d{1,2})-(2\d)(?!\d)", lambda m: f"20{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"),
        (r"(?<!\d)(\d{2})(\d{2})(202\d)(?!\d)", lambda m: f"{m.group(3)}-{m.group(1)}-{m.group(2)}"),
        (r"(?<!\d)(\d{2})(\d{2})(26)(?!\d)", lambda m: f"20{m.group(3)}-{m.group(1)}-{m.group(2)}"),
    ]
    for pat, fmt in patterns:
        m = re.search(pat, filename)
        if m:
            iso = fmt(m)
            try:
                dt = date_parser.parse(iso)
                if 2020 <= dt.year <= 2027:
                    return dt.strftime("%Y-%m-%d")
            except Exception:
                continue
    return None


def extract_emails_from_page(filename: str, page_number: int, content: str):
    lines = content.splitlines()
    entries = []

    for i, line in enumerate(lines):
        m = re.match(r"^\s*(Sent|Date)\s*:\s*(.+)$", line, flags=re.IGNORECASE)
        if not m:
            continue

        raw_date = m.group(2).strip()
        dt = parse_date_safe(raw_date)
        if not dt:
            continue

        start = max(0, i - 4)
        end = min(len(lines), i + 7)
        window = lines[start:end]

        sender = ""
        recipients = ""
        subject = ""

        for wline in window:
            if not sender:
                fm = re.match(r"^\s*From\s*:\s*(.+)$", wline, flags=re.IGNORECASE)
                if fm:
                    sender = clean_field(fm.group(1), 120)
            if not recipients:
                tm = re.match(r"^\s*To\s*:\s*(.+)$", wline, flags=re.IGNORECASE)
                if tm:
                    recipients = clean_field(tm.group(1), 150)
            if not subject:
                sm = re.match(r"^\s*Subject\s*:\s*(.+)$", wline, flags=re.IGNORECASE)
                if sm:
                    subject = clean_field(sm.group(1), 180)

        body_lines = [l.strip() for l in lines[min(len(lines), i + 3):min(len(lines), i + 10)] if l.strip()]
        snippet = clean_field(" ".join(body_lines), 220)

        entries.append({
            "event_date": dt.strftime("%Y-%m-%d %H:%M"),
            "date_display": dt.strftime("%Y-%m-%d %I:%M %p"),
            "event_type": "Email",
            "sender": sender or "(Unknown / Redacted)",
            "recipients": recipients,
            "subject": subject or "(No Subject)",
            "filename": filename,
            "page_number": page_number,
            "snippet": snippet,
        })

    return entries


def build():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DROP TABLE IF EXISTS timeline")
    conn.execute("""
        CREATE TABLE timeline (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_date TEXT,
            date_display TEXT,
            event_type TEXT,
            sender TEXT,
            recipients TEXT,
            subject TEXT,
            filename TEXT,
            page_number INTEGER,
            snippet TEXT
        )
    """)

    rows = conn.execute(
        "SELECT filename, page_number, content FROM documents ORDER BY filename, page_number"
    ).fetchall()

    raw_emails = []
    for fname, pnum, content in rows:
        if content:
            raw_emails.extend(extract_emails_from_page(fname, pnum, content))

    seen = set()
    unique_events = []
    for ev in raw_emails:
        key = (
            ev["event_date"],
            re.sub(r"\W+", "", ev["sender"].lower())[:35],
            re.sub(r"^(re|fwd|fw):\s*", "", ev["subject"].lower()).strip()[:45],
        )
        if key not in seen:
            seen.add(key)
            unique_events.append(ev)

    all_files = [r[0] for r in conn.execute("SELECT DISTINCT filename FROM documents ORDER BY filename").fetchall()]
    bulk_markers = ("responsive_records", "batch_", "i5_group", "doenges_request")

    doc_count = 0
    for fname in all_files:
        if any(m in fname.lower() for m in bulk_markers):
            continue

        if fname in KNOWN_DOC_DATES:
            iso_date, title = KNOWN_DOC_DATES[fname]
        else:
            iso_date = extract_filename_date(fname)
            title = fname.replace("_", " ").replace(".pdf", "")

        if iso_date:
            unique_events.append({
                "event_date": f"{iso_date} 00:00",
                "date_display": iso_date,
                "event_type": "Document",
                "sender": "City of Festus / Official Filing",
                "recipients": "Public Record",
                "subject": title,
                "filename": fname,
                "page_number": 1,
                "snippet": f"Standalone document: {fname}",
            })
            doc_count += 1

    unique_events.sort(key=lambda x: x["event_date"])

    conn.executemany("""
        INSERT INTO timeline
            (event_date, date_display, event_type, sender, recipients, subject, filename, page_number, snippet)
        VALUES
            (:event_date, :date_display, :event_type, :sender, :recipients, :subject, :filename, :page_number, :snippet)
    """, unique_events)
    conn.commit()

    print(f"Raw email headers parsed: {len(raw_emails)}")
    print(f"Unique emails after thread deduplication: {len(unique_events) - doc_count}")
    print(f"Standalone documents added: {doc_count}")
    print(f"Total timeline entries: {len(unique_events)}")
    if unique_events:
        print(f"Date range: {unique_events[0]['event_date']}  -->  {unique_events[-1]['event_date']}")
        print("\nSample entries:")
        for sample in unique_events[:5]:
            print(f"  [{sample['date_display']}] ({sample['event_type']}) {sample['sender']} | {sample['subject']} -> {sample['filename']} p.{sample['page_number']}")

    conn.close()


if __name__ == "__main__":
    build()
