from __future__ import annotations

import html
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen

BASE = "https://www.admie.gr"
LISTING = f"{BASE}/file-type/realtimescadasystemload"

# The ADMIE page filters by publication date, while the filename contains the data date.
# We therefore search a little into January 2026 so that late-Dec 2025 data
# (which may be uploaded the following day) are not accidentally excluded.
SEARCH_SINCE = "01/01/2025"
SEARCH_UNTIL = "01/03/2026"

TARGET_START = datetime.strptime("20250101", "%Y%m%d").date()
TARGET_END = datetime.strptime("20251231", "%Y%m%d").date()

OUTPUT_DIR = Path("admie_system_load_2025")
OUTPUT_DIR.mkdir(exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; EnergyPortfolioDataCollector/1.0)"
}

FILE_RE = re.compile(
    r'href=["\']([^"\']*?(\d{8})_RealTimeSCADASystemLoad_\d+\.xls)["\']',
    re.IGNORECASE,
)


def fetch_text(url: str, retries: int = 3) -> str:
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            req = Request(url, headers=HEADERS)
            with urlopen(req, timeout=30) as response:
                return response.read().decode("utf-8", errors="ignore")
        except Exception as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(2 * attempt)
    raise RuntimeError(f"Could not fetch {url}\n{last_error}")


def download_file(url: str, destination: Path, retries: int = 3) -> None:
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            req = Request(url, headers=HEADERS)
            with urlopen(req, timeout=60) as response:
                data = response.read()
            destination.write_bytes(data)
            return
        except Exception as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(2 * attempt)
    raise RuntimeError(f"Could not download {url}\n{last_error}")


def expected_dates(start, end):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


files_by_date = {}
previous_signature = None

print("Searching ADMIE listing pages...")

for page in range(0, 80):
    params = {
        "since": SEARCH_SINCE,
        "until": SEARCH_UNTIL,
        "op": "Υποβολή",
        "page": page,
    }
    url = f"{LISTING}?{urlencode(params)}"
    page_html = fetch_text(url)

    matches = FILE_RE.findall(page_html)
    current_page = []

    for href, yyyymmdd in matches:
        try:
            data_date = datetime.strptime(yyyymmdd, "%Y%m%d").date()
        except ValueError:
            continue

        if TARGET_START <= data_date <= TARGET_END:
            full_url = urljoin(BASE, html.unescape(href))
            current_page.append((data_date, full_url))
            files_by_date.setdefault(data_date, full_url)

    signature = tuple(sorted(url for _, url in current_page))
    if page > 0 and signature and signature == previous_signature:
        break
    previous_signature = signature

    if page > 0 and not matches:
        break

    print(f"  page {page + 1}: {len(current_page)} target-2025 file(s)")
    time.sleep(0.25)

expected = set(expected_dates(TARGET_START, TARGET_END))
found = set(files_by_date)
missing = sorted(expected - found)

print()
print(f"Found unique 2025 data files: {len(found)} / {len(expected)}")

if missing:
    print("Missing data date(s):")
    for d in missing:
        print("  -", d.isoformat())
else:
    print("No missing dates detected.")

print()
print(f"Downloading to: {OUTPUT_DIR.resolve()}")

failed = []

for i, data_date in enumerate(sorted(files_by_date), start=1):
    url = files_by_date[data_date]
    filename = url.split("/")[-1].split("?")[0]
    destination = OUTPUT_DIR / filename

    if destination.exists() and destination.stat().st_size > 0:
        print(f"[{i:03d}/{len(files_by_date)}] already exists: {filename}")
        continue

    try:
        download_file(url, destination)
        print(f"[{i:03d}/{len(files_by_date)}] downloaded: {filename}")
    except Exception as exc:
        failed.append((data_date, url, str(exc)))
        print(f"[{i:03d}/{len(files_by_date)}] FAILED: {filename}")

    time.sleep(0.20)

print()
print("Finished.")
print(f"Downloaded/available files: {len(list(OUTPUT_DIR.glob('*.xls')))}")

if failed:
    print("\nFailed downloads:")
    for data_date, url, error in failed:
        print(f"  {data_date.isoformat()} -> {url}")
        print(f"    {error}")

if missing:
    print("\nImportant: the listing did not expose every expected 2025 data date.")
    print("Keep the missing-date list; we can retrieve/check those dates separately.")
