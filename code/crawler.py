import csv
import os
import time
from collections import deque
from pathlib import Path
from urllib.parse import urljoin, urlparse, urldefrag
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup


# --------------------------------------------------
# DEFAULTS (used only when running this file directly)
# --------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent

DEFAULT_START_URL = "https://www.upstate.edu/"
DEFAULT_OUTPUT_FILE = BASE_DIR / "outputfiles" / "pdf_inventory.csv"

DEFAULT_MAX_PAGES = 400
DEFAULT_DELAY_SECONDS = 0.3

USER_AGENT = "PDF-Accessibility-Triage-Research/1.0"


# --------------------------------------------------
# URL HELPERS
# --------------------------------------------------

def normalize_url(url):
    """Remove #fragments and unnecessary trailing fragments."""
    url, _ = urldefrag(url)
    return url.strip()


def base_domain_of(url):
    hostname = urlparse(url).netloc.lower()
    return hostname


def is_same_site(url, root_domain):
    """Allow only the scanned domain and its subdomains."""
    parsed = urlparse(url)

    root_bare = root_domain[4:] if root_domain.startswith("www.") else root_domain

    return (
        parsed.scheme in ("http", "https")
        and (
            parsed.netloc.lower() == root_domain
            or parsed.netloc.lower() == root_bare
            or parsed.netloc.lower().endswith("." + root_bare)
        )
    )


def should_skip_page(url):
    """Skip obvious login, search, calendar, and internal areas."""

    lower_url = url.lower()

    blocked_patterns = [
        "/search/",
        "/calendar",
        "/login",
        "/logout",
        "/intra/",
        "/ipage/",
        "libproxy",
        "sso",
        "signin",
        "authentication"
    ]

    return any(pattern in lower_url for pattern in blocked_patterns)


def looks_like_pdf(url):
    """Determine whether the URL path appears to reference a PDF."""
    path = urlparse(url).path.lower()
    return path.endswith(".pdf")


# --------------------------------------------------
# PDF VALIDATION
# --------------------------------------------------

def validate_pdf(pdf_url):

    try:
        response = requests.get(
            pdf_url,
            headers={"User-Agent": USER_AGENT},
            timeout=20,
            allow_redirects=True,
            stream=True
        )

        final_url = response.url
        content_type = response.headers.get("Content-Type", "").lower()
        final_lower = final_url.lower()

        auth_patterns = ["login", "libproxy", "sso", "signin", "authentication"]

        if any(pattern in final_lower for pattern in auth_patterns):
            response.close()
            return "AUTH_REQUIRED", content_type, final_url

        if response.status_code == 403:
            response.close()
            return "FORBIDDEN", content_type, final_url

        if response.status_code == 404:
            response.close()
            return "BROKEN_LINK", content_type, final_url

        if response.status_code == 200 and "application/pdf" in content_type:
            response.close()
            return "PUBLIC_PDF", content_type, final_url

        if "text/html" in content_type:
            response.close()
            return "HTML_NOT_PDF", content_type, final_url

        status = f"OTHER_{response.status_code}"
        response.close()
        return status, content_type, final_url

    except requests.RequestException:
        return "REQUEST_ERROR", "", pdf_url


# --------------------------------------------------
# CSV
# --------------------------------------------------

CSV_FIELDS = [
    "institution",
    "pdf_url",
    "final_url",
    "source_page",
    "filename",
    "status",
    "content_type"
]


def _write_header(output_file):
    with open(output_file, "w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=CSV_FIELDS)
        writer.writeheader()


def _append_row(output_file, record):
    with open(output_file, "a", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=CSV_FIELDS)
        writer.writerow(record)


# --------------------------------------------------
# CRAWLER (callable)
# --------------------------------------------------

def run(
    start_url,
    output_file=DEFAULT_OUTPUT_FILE,
    institution_name=None,
    max_pages=DEFAULT_MAX_PAGES,
    delay_seconds=DEFAULT_DELAY_SECONDS,
    on_progress=None,
    should_stop=None,
):
    """
    Crawl `start_url` for public pages and PDF links.

    on_progress(pages_visited, pdfs_found) is called after every page,
    so a caller (e.g. Streamlit) can show live progress.

    should_stop() is checked at the top of every loop iteration. If it
    returns True, the crawl stops early and returns whatever was found
    so far — the output CSV already has every PDF discovered up to that
    point, since rows are appended as they're found rather than buffered.

    Returns a dict with summary counts.
    """

    output_file = Path(output_file)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    start_url = normalize_url(start_url)
    if not urlparse(start_url).scheme:
        start_url = "https://" + start_url

    root_domain = base_domain_of(start_url)
    institution_name = institution_name or root_domain

    # --- per-run state (never module-level, so repeated calls don't leak) ---
    visited_pages = set()
    queued_pages = {start_url}
    pages_to_visit = deque([start_url])
    seen_pdf_urls = set()

    # --- robots.txt ---
    robots = RobotFileParser()
    robots_available = False

    try:
        robots_url = f"{urlparse(start_url).scheme}://{root_domain}/robots.txt"
        robots_response = requests.get(
            robots_url, headers={"User-Agent": USER_AGENT}, timeout=10
        )
        if robots_response.status_code == 200:
            robots.parse(robots_response.text.splitlines())
            robots_available = True
    except requests.RequestException:
        pass

    _write_header(output_file)

    while pages_to_visit and len(visited_pages) < max_pages:

        if should_stop and should_stop():
            break

        current_url = normalize_url(pages_to_visit.popleft())

        if current_url in visited_pages:
            continue

        if should_skip_page(current_url):
            continue

        if robots_available and not robots.can_fetch(USER_AGENT, current_url):
            continue

        try:
            response = requests.get(
                current_url,
                headers={"User-Agent": USER_AGENT},
                timeout=15,
                allow_redirects=True,
            )
            response.raise_for_status()
        except requests.RequestException:
            visited_pages.add(current_url)
            if on_progress:
                on_progress(len(visited_pages), len(seen_pdf_urls))
            continue

        visited_pages.add(current_url)

        content_type = response.headers.get("Content-Type", "").lower()

        if "text/html" in content_type:
            soup = BeautifulSoup(response.text, "html.parser")

            for link in soup.find_all("a", href=True):
                href = link.get("href", "").strip()
                if not href:
                    continue

                full_url = normalize_url(urljoin(current_url, href))

                if looks_like_pdf(full_url):
                    if full_url in seen_pdf_urls:
                        continue
                    seen_pdf_urls.add(full_url)

                    status, pdf_content_type, final_url = validate_pdf(full_url)
                    filename = os.path.basename(urlparse(final_url).path)

                    record = {
                        "institution": institution_name,
                        "pdf_url": full_url,
                        "final_url": final_url,
                        "source_page": current_url,
                        "filename": filename,
                        "status": status,
                        "content_type": pdf_content_type,
                    }

                    _append_row(output_file, record)

                elif (
                    is_same_site(full_url, root_domain)
                    and not should_skip_page(full_url)
                    and full_url not in visited_pages
                    and full_url not in queued_pages
                ):
                    pages_to_visit.append(full_url)
                    queued_pages.add(full_url)

        if on_progress:
            on_progress(len(visited_pages), len(seen_pdf_urls))

        time.sleep(delay_seconds)

    return {
        "institution_name": institution_name,
        "root_domain": root_domain,
        "pages_visited": len(visited_pages),
        "pdfs_found": len(seen_pdf_urls),
        "output_file": str(output_file),
    }


# --------------------------------------------------
# STANDALONE CLI USE
# --------------------------------------------------

if __name__ == "__main__":

    def _print_progress(pages, pdfs):
        print(f"Pages visited: {pages}  |  PDFs found: {pdfs}", end="\r")

    stats = run(
        DEFAULT_START_URL,
        DEFAULT_OUTPUT_FILE,
        max_pages=DEFAULT_MAX_PAGES,
        on_progress=_print_progress,
    )

    print()
    print("==============================")
    print("CRAWL COMPLETE")
    print("==============================")
    print(f"Pages visited: {stats['pages_visited']}")
    print(f"PDF links found: {stats['pdfs_found']}")
    print(f"Results saved to: {stats['output_file']}")
    print("==============================")
