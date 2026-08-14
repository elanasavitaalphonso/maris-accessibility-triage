import csv
import os
import tempfile
import statistics
from pathlib import Path
from urllib.parse import urlparse

import requests
import fitz
import pikepdf


# --------------------------------------------------
# DEFAULTS (used only when running this file directly)
# --------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent

DEFAULT_INPUT_FILE = BASE_DIR / "outputfiles" / "pdf_inventory.csv"
DEFAULT_OUTPUT_FILE = BASE_DIR / "outputfiles" / "pdf_analysis.csv"

USER_AGENT = "PDF-Accessibility-Triage-Research/1.0"
MAX_FILE_SIZE_MB = 50


# --------------------------------------------------
# OUTPUT COLUMNS
# --------------------------------------------------

FIELDS = [
    "institution", "filename", "pdf_url", "source_page",
    "file_size_mb", "page_count",
    "title", "author", "subject", "creation_date", "creator", "producer",
    "text_characters", "image_count", "link_count",
    "internal_link_count", "external_link_count", "form_field_count",
    "has_text", "likely_scanned", "has_tags", "document_language", "has_bookmarks",
    "font_family_count", "min_font_size", "max_font_size", "avg_font_size",
    "heading_like_count", "table_like_count",
    "text_per_page", "images_per_page",
    "metadata_score", "source_application_hint",
    "likely_complex_layout",
    "analysis_status",
]


# --------------------------------------------------
# CSV HELPERS
# --------------------------------------------------

def _initialize_output(output_file):
    output_file = Path(output_file)
    if output_file.exists():
        output_file.unlink()

    with open(output_file, "w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS)
        writer.writeheader()


def _save_result(record, output_file):
    with open(output_file, "a", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS)
        writer.writerow(record)


# --------------------------------------------------
# DOWNLOAD PDF
# --------------------------------------------------

def download_pdf(url):
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    response.raise_for_status()

    file_size = len(response.content)
    size_mb = file_size / (1024 * 1024)

    if size_mb > MAX_FILE_SIZE_MB:
        raise Exception(f"PDF too large: {size_mb:.2f} MB")

    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    temp_file.write(response.content)
    temp_file.close()

    return temp_file.name, size_mb


# --------------------------------------------------
# TAGS / LANGUAGE
# --------------------------------------------------

def inspect_pdf_structure(pdf_path):
    has_tags = False
    language = ""

    try:
        with pikepdf.open(pdf_path) as pdf:
            root = pdf.Root

            if "/MarkInfo" in root:
                mark_info = root["/MarkInfo"]
                if "/Marked" in mark_info:
                    has_tags = bool(mark_info["/Marked"])

            if "/Lang" in root:
                language = str(root["/Lang"])

    except Exception:
        pass

    return has_tags, language


# --------------------------------------------------
# SOURCE APPLICATION HINT
# --------------------------------------------------

def detect_source_application(creator, producer, title):
    combined = f"{creator} {producer} {title}".lower()

    applications = {
        "Microsoft Word": ["microsoft word", ".docx", ".doc"],
        "Adobe InDesign": ["indesign", ".indd"],
        "Microsoft PowerPoint": ["powerpoint", ".pptx", ".ppt"],
        "Adobe Acrobat": ["acrobat"],
        "LaTeX": ["latex", "tex"],
    }

    for app, keywords in applications.items():
        if any(keyword in combined for keyword in keywords):
            return app

    return "Unknown"


# --------------------------------------------------
# METADATA SCORE
# --------------------------------------------------

def calculate_metadata_score(title, author, subject, language):
    fields = [title, author, subject, language]
    populated = sum(1 for field in fields if str(field).strip())
    return round(populated / len(fields), 2)


# --------------------------------------------------
# ANALYZE PDF
# --------------------------------------------------

def analyze_pdf(pdf_path):

    document = fitz.open(pdf_path)
    metadata = document.metadata or {}
    page_count = len(document)

    text_characters = 0
    image_count = 0
    link_count = 0
    internal_link_count = 0
    external_link_count = 0
    form_field_count = 0

    font_families = set()
    font_sizes = []

    heading_like_count = 0
    table_like_count = 0

    for page in document:

        text = page.get_text("text")
        text_characters += len(text.strip())

        images = page.get_images(full=True)
        image_count += len(images)

        links = page.get_links()
        link_count += len(links)

        for link in links:
            uri = link.get("uri")
            page_target = link.get("page")

            if uri:
                parsed = urlparse(uri)
                if parsed.scheme in ("http", "https"):
                    external_link_count += 1
            elif page_target is not None and page_target >= 0:
                internal_link_count += 1

        widgets = page.widgets()
        if widgets:
            form_field_count += sum(1 for _ in widgets)

        text_dict = page.get_text("dict")

        for block in text_dict.get("blocks", []):
            if "lines" not in block:
                continue

            for line in block["lines"]:
                for span in line.get("spans", []):
                    font_name = span.get("font", "")
                    font_size = span.get("size")
                    span_text = span.get("text", "").strip()

                    if font_name:
                        font_families.add(font_name)

                    if font_size:
                        font_sizes.append(float(font_size))

                    # Simple heading-like heuristic
                    if font_size and font_size >= 16 and 2 <= len(span_text) <= 120:
                        heading_like_count += 1

        # table-like detection
        try:
            tables = page.find_tables()
            if tables:
                table_like_count += len(tables.tables)
        except Exception:
            pass

    has_text = text_characters > 50
    likely_scanned = text_characters < (page_count * 50) and image_count > 0

    toc = document.get_toc()
    has_bookmarks = len(toc) > 0

    document.close()

    has_tags, document_language = inspect_pdf_structure(pdf_path)

    if font_sizes:
        min_font_size = round(min(font_sizes), 2)
        max_font_size = round(max(font_sizes), 2)
        avg_font_size = round(statistics.mean(font_sizes), 2)
    else:
        min_font_size = 0
        max_font_size = 0
        avg_font_size = 0

    if page_count > 0:
        text_per_page = round(text_characters / page_count, 2)
        images_per_page = round(image_count / page_count, 2)
    else:
        text_per_page = 0
        images_per_page = 0

    title = metadata.get("title", "")
    author = metadata.get("author", "")
    subject = metadata.get("subject", "")
    creator = metadata.get("creator", "")
    producer = metadata.get("producer", "")

    source_application_hint = detect_source_application(creator, producer, title)
    metadata_score = calculate_metadata_score(title, author, subject, document_language)

    complexity_signals = 0
    if image_count >= 10:
        complexity_signals += 1
    if table_like_count >= 2:
        complexity_signals += 1
    if form_field_count >= 10:
        complexity_signals += 1
    if page_count >= 30:
        complexity_signals += 1
    if len(font_families) >= 6:
        complexity_signals += 1

    likely_complex_layout = complexity_signals >= 2

    return {
        "page_count": page_count,
        "title": title,
        "author": author,
        "subject": subject,
        "creation_date": metadata.get("creationDate", ""),
        "creator": creator,
        "producer": producer,
        "text_characters": text_characters,
        "image_count": image_count,
        "link_count": link_count,
        "internal_link_count": internal_link_count,
        "external_link_count": external_link_count,
        "form_field_count": form_field_count,
        "has_text": has_text,
        "likely_scanned": likely_scanned,
        "has_tags": has_tags,
        "document_language": document_language,
        "has_bookmarks": has_bookmarks,
        "font_family_count": len(font_families),
        "min_font_size": min_font_size,
        "max_font_size": max_font_size,
        "avg_font_size": avg_font_size,
        "heading_like_count": heading_like_count,
        "table_like_count": table_like_count,
        "text_per_page": text_per_page,
        "images_per_page": images_per_page,
        "metadata_score": metadata_score,
        "source_application_hint": source_application_hint,
        "likely_complex_layout": likely_complex_layout,
    }


# --------------------------------------------------
# RUN (callable)
# --------------------------------------------------

def run(input_file=DEFAULT_INPUT_FILE, output_file=DEFAULT_OUTPUT_FILE, on_progress=None):
    """
    Analyze every PUBLIC_PDF row from `input_file` (the crawler's inventory
    CSV) and write per-document accessibility features to `output_file`.

    on_progress(current, total, filename) is called before each document,
    so a caller (e.g. Streamlit) can show live progress.

    Returns a dict with summary counts.
    """

    input_file = Path(input_file)
    output_file = Path(output_file)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    _initialize_output(output_file)

    with open(input_file, "r", encoding="utf-8") as file:
        rows = list(csv.DictReader(file))

    public_pdfs = [row for row in rows if row["status"] == "PUBLIC_PDF"]

    success_count = 0
    error_count = 0

    for number, row in enumerate(public_pdfs, start=1):

        if on_progress:
            on_progress(number, len(public_pdfs), row.get("filename", ""))

        temp_path = None

        try:
            temp_path, file_size_mb = download_pdf(row["final_url"])
            analysis = analyze_pdf(temp_path)

            record = {
                "institution": row["institution"],
                "filename": row["filename"],
                "pdf_url": row["final_url"],
                "source_page": row["source_page"],
                "file_size_mb": round(file_size_mb, 2),
                **analysis,
                "analysis_status": "SUCCESS",
            }

            _save_result(record, output_file)
            success_count += 1

        except Exception as error:

            record = {field: "" for field in FIELDS}
            record["institution"] = row["institution"]
            record["filename"] = row["filename"]
            record["pdf_url"] = row["final_url"]
            record["source_page"] = row["source_page"]
            record["analysis_status"] = f"ERROR: {error}"

            _save_result(record, output_file)
            error_count += 1

        finally:
            if temp_path and os.path.exists(temp_path):
                os.remove(temp_path)

    return {
        "analyzed": success_count,
        "errors": error_count,
        "output_file": str(output_file),
    }


# --------------------------------------------------
# STANDALONE CLI USE
# --------------------------------------------------

if __name__ == "__main__":

    def _print_progress(current, total, filename):
        print(f"[{current}/{total}] Analyzing: {filename}")

    stats = run(
        DEFAULT_INPUT_FILE,
        DEFAULT_OUTPUT_FILE,
        on_progress=_print_progress,
    )

    print()
    print("==============================")
    print("PDF ANALYSIS COMPLETE")
    print("==============================")
    print(f"Analyzed: {stats['analyzed']}   Errors: {stats['errors']}")
    print(f"Saved to: {stats['output_file']}")
