import csv
import logging
import os
import time
from collections import deque
from pathlib import Path
from urllib.parse import urldefrag, urljoin, urlparse
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

# Browser-compatible, but still clearly identifies this prototype.
USER_AGENT = (
    "Mozilla/5.0 (compatible; MarisAccessibilityCrawler/1.0; "
    "+https://github.com/elanasavitaalphonso/maris-accessibility-triage)"
)

REQUEST_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": (
        "text/html,application/xhtml+xml,application/pdf;q=0.9,"
        "*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
}

PAGE_TIMEOUT = (10, 20)
PDF_TIMEOUT = (10, 30)
ROBOTS_TIMEOUT = (5, 10)

logger = logging.getLogger(__name__)


class CrawlAccessError(RuntimeError):
    """Raised when Maris cannot access the website well enough to scan it."""


# --------------------------------------------------
# URL HELPERS
# --------------------------------------------------

def normalize_url(url):
    """Remove URL fragments and surrounding whitespace."""
    url, _ = urldefrag(url)
    return url.strip()


def base_domain_of(url):
    return urlparse(url).netloc.lower()


def is_same_site(url, root_domain):
    """Allow only the scanned domain and its subdomains."""
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()
    root_hostname = root_domain.split(":", 1)[0].lower()
    root_bare = (
        root_hostname[4:]
        if root_hostname.startswith("www.")
        else root_hostname
    )

    return (
        parsed.scheme in ("http", "https")
        and (
            hostname == root_hostname
            or hostname == root_bare
            or hostname.endswith("." + root_bare)
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
        "authentication",
    ]

    return any(pattern in lower_url for pattern in blocked_patterns)


def looks_like_pdf(url):
    """Determine whether the URL path appears to reference a PDF."""
    return urlparse(url).path.lower().endswith(".pdf")


def _origin(url):
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _request_error_text(error):
    """Return a short request failure message suitable for logs and the UI."""
    response = getattr(error, "response", None)
    if response is not None:
        return f"HTTP {response.status_code} {response.reason}"
    return str(error) or error.__class__.__name__


# --------------------------------------------------
# ROBOTS.TXT
# --------------------------------------------------

def _robots_for(url, session, robots_cache):
    """Return a cached RobotFileParser, or None if robots.txt is unavailable."""
    origin = _origin(url)

    if origin in robots_cache:
        return robots_cache[origin]

    robots_url = origin + "/robots.txt"

    try:
        response = session.get(
            robots_url,
            timeout=ROBOTS_TIMEOUT,
            allow_redirects=True,
        )

        if response.status_code == 200:
            parser = RobotFileParser()
            parser.set_url(robots_url)
            parser.parse(response.text.splitlines())
            robots_cache[origin] = parser
            logger.info("Loaded robots.txt: %s", robots_url)
            return parser

        # A missing robots.txt means no published crawl rules. Other failures
        # are logged, but are not treated as permission to bypass a known rule.
        if response.status_code == 404:
            logger.info("No robots.txt found: %s", robots_url)
        else:
            logger.warning(
                "Could not read robots.txt %s (HTTP %s)",
                robots_url,
                response.status_code,
            )

    except requests.RequestException as error:
        logger.warning(
            "Could not read robots.txt %s: %s",
            robots_url,
            _request_error_text(error),
        )

    robots_cache[origin] = None
    return None


# --------------------------------------------------
# PDF VALIDATION
# --------------------------------------------------

def validate_pdf(pdf_url, session=None):
    """Validate a discovered PDF without downloading the entire document."""
    request_session = session or requests.Session()

    if session is None:
        request_session.headers.update(REQUEST_HEADERS)

    response = None

    try:
        response = request_session.get(
            pdf_url,
            timeout=PDF_TIMEOUT,
            allow_redirects=True,
            stream=True,
        )

        final_url = response.url
        content_type = response.headers.get("Content-Type", "").lower()
        final_lower = final_url.lower()

        auth_patterns = [
            "login",
            "libproxy",
            "sso",
            "signin",
            "authentication",
        ]

        if any(pattern in final_lower for pattern in auth_patterns):
            return "AUTH_REQUIRED", content_type, final_url

        if response.status_code in (401, 403):
            return "FORBIDDEN", content_type, final_url

        if response.status_code == 404:
            return "BROKEN_LINK", content_type, final_url

        if response.status_code == 429:
            return "RATE_LIMITED", content_type, final_url

        if response.status_code == 200 and "application/pdf" in content_type:
            return "PUBLIC_PDF", content_type, final_url

        if "text/html" in content_type:
            return "HTML_NOT_PDF", content_type, final_url

        return f"OTHER_{response.status_code}", content_type, final_url

    except requests.RequestException as error:
        logger.warning(
            "PDF validation failed for %s: %s",
            pdf_url,
            _request_error_text(error),
        )
        return "REQUEST_ERROR", "", pdf_url

    finally:
        if response is not None:
            response.close()
        if session is None:
            request_session.close()


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
    "content_type",
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
    Crawl ``start_url`` for public pages and PDF links.

    ``on_progress(pages_visited, pdfs_found)`` is called after each page
    attempt. ``should_stop()`` is checked before page requests, while links are
    processed, and before the polite delay.

    A reachable crawl with no discovered PDFs returns normally with
    ``pdfs_found == 0``. If the starting website cannot be accessed, or its
    robots.txt explicitly disallows Maris, ``CrawlAccessError`` is raised so
    the server reports a failed scan instead of a misleading zero-PDF result.
    """
    output_file = Path(output_file)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    start_url = normalize_url(start_url)
    if not urlparse(start_url).scheme:
        start_url = "https://" + start_url

    parsed_start = urlparse(start_url)
    if parsed_start.scheme not in ("http", "https") or not parsed_start.netloc:
        raise ValueError("Please enter a valid public http or https website URL.")

    root_domain = base_domain_of(start_url)
    institution_name = institution_name or root_domain

    visited_pages = set()
    queued_pages = {start_url}
    pages_to_visit = deque([start_url])
    seen_pdf_urls = set()

    successful_pages = 0
    failed_pages = 0
    robots_blocked_pages = 0
    crawl_errors = []
    stopped_early = False
    robots_cache = {}

    session = requests.Session()
    session.headers.update(REQUEST_HEADERS)

    _write_header(output_file)
    logger.info(
        "Starting Maris crawl: url=%s max_pages=%s",
        start_url,
        max_pages,
    )

    try:
        while pages_to_visit and len(visited_pages) < max_pages:
            if should_stop and should_stop():
                stopped_early = True
                logger.info("Crawl stopped by user after %s pages", len(visited_pages))
                break

            current_url = normalize_url(pages_to_visit.popleft())

            if current_url in visited_pages or should_skip_page(current_url):
                continue

            robots = _robots_for(current_url, session, robots_cache)
            if robots is not None and not robots.can_fetch(USER_AGENT, current_url):
                robots_blocked_pages += 1
                visited_pages.add(current_url)
                message = f"robots.txt does not allow Maris to crawl {current_url}"
                logger.warning(message)

                if on_progress:
                    on_progress(len(visited_pages), len(seen_pdf_urls))

                if current_url == start_url and successful_pages == 0:
                    raise CrawlAccessError(
                        "This website's robots.txt does not allow Maris to scan "
                        "the starting page. The restriction was respected."
                    )
                continue

            response = None

            try:
                response = session.get(
                    current_url,
                    timeout=PAGE_TIMEOUT,
                    allow_redirects=True,
                )
                response.raise_for_status()

                final_url = normalize_url(response.url)
                if not is_same_site(final_url, root_domain):
                    raise CrawlAccessError(
                        "The starting website redirected Maris to a different "
                        f"domain: {urlparse(final_url).netloc}"
                    )

            except CrawlAccessError:
                raise

            except requests.RequestException as error:
                failed_pages += 1
                visited_pages.add(current_url)
                error_text = _request_error_text(error)
                crawl_errors.append(f"{current_url}: {error_text}")
                logger.warning("Page request failed for %s: %s", current_url, error_text)

                if on_progress:
                    on_progress(len(visited_pages), len(seen_pdf_urls))

                if current_url == start_url and successful_pages == 0:
                    raise CrawlAccessError(
                        "Maris could not access the starting website. "
                        f"Request failed: {error_text}. The site may be blocking "
                        "hosted crawlers, rate-limiting requests, or temporarily unavailable."
                    ) from error
                continue

            try:
                visited_pages.add(current_url)
                successful_pages += 1
                content_type = response.headers.get("Content-Type", "").lower()

                if "text/html" in content_type:
                    soup = BeautifulSoup(response.text, "html.parser")

                    for link in soup.find_all("a", href=True):
                        if should_stop and should_stop():
                            stopped_early = True
                            break

                        href = link.get("href", "").strip()
                        if not href:
                            continue

                        full_url = normalize_url(urljoin(response.url, href))

                        if looks_like_pdf(full_url):
                            if full_url in seen_pdf_urls:
                                continue

                            seen_pdf_urls.add(full_url)
                            status, pdf_content_type, final_url = validate_pdf(
                                full_url,
                                session=session,
                            )
                            filename = os.path.basename(urlparse(final_url).path)

                            _append_row(
                                output_file,
                                {
                                    "institution": institution_name,
                                    "pdf_url": full_url,
                                    "final_url": final_url,
                                    "source_page": current_url,
                                    "filename": filename,
                                    "status": status,
                                    "content_type": pdf_content_type,
                                },
                            )

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

            finally:
                response.close()

            if stopped_early:
                logger.info("Crawl stopped by user while processing %s", current_url)
                break

            if delay_seconds > 0:
                # Keep stop-scan responsive instead of sleeping for one long block.
                delay_remaining = delay_seconds
                while delay_remaining > 0:
                    if should_stop and should_stop():
                        stopped_early = True
                        break
                    sleep_time = min(0.1, delay_remaining)
                    time.sleep(sleep_time)
                    delay_remaining -= sleep_time

                if stopped_early:
                    logger.info("Crawl stopped by user during request delay")
                    break

        if successful_pages == 0 and not stopped_early:
            if robots_blocked_pages:
                raise CrawlAccessError(
                    "Maris could not scan any pages because robots.txt blocked access."
                )
            if failed_pages:
                raise CrawlAccessError(
                    "Maris could not access any pages on this website. "
                    f"The last request error was: {crawl_errors[-1]}"
                )

        logger.info(
            "Maris crawl finished: pages=%s successful=%s failed=%s "
            "robots_blocked=%s pdfs=%s stopped=%s",
            len(visited_pages),
            successful_pages,
            failed_pages,
            robots_blocked_pages,
            len(seen_pdf_urls),
            stopped_early,
        )

        return {
            "institution_name": institution_name,
            "root_domain": root_domain,
            "pages_visited": len(visited_pages),
            "pdfs_found": len(seen_pdf_urls),
            "output_file": str(output_file),
            "successful_pages": successful_pages,
            "failed_pages": failed_pages,
            "robots_blocked_pages": robots_blocked_pages,
            "crawl_errors": crawl_errors[:20],
            "stopped_early": stopped_early,
        }

    except CrawlAccessError:
        logger.exception("Maris could not access website: %s", start_url)
        raise

    finally:
        session.close()


# --------------------------------------------------
# STANDALONE CLI USE
# --------------------------------------------------

if __name__ == "__main__":

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    def _print_progress(pages, pdfs):
        print(f"Pages visited: {pages}  |  PDFs found: {pdfs}", end="\r")

    try:
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
        print(f"Successful pages: {stats['successful_pages']}")
        print(f"Failed pages: {stats['failed_pages']}")
        print(f"PDF links found: {stats['pdfs_found']}")
        print(f"Results saved to: {stats['output_file']}")
        print("==============================")

    except CrawlAccessError as error:
        print()
        print(f"CRAWL FAILED: {error}")
