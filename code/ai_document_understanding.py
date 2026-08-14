from pathlib import Path
from typing import Literal
import base64
import os
import time

import pandas as pd
import pymupdf
import requests

from openai import OpenAI
from pydantic import BaseModel, Field

import storage_manager

from dotenv import load_dotenv

load_dotenv()


# ============================================================
# PATHS
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent

LATEST_TRIAGE_FILE = (
    BASE_DIR
    / "outputfiles"
    / "latest"
    / "pdf_triage_results.csv"
)

AI_CONTEXT_CACHE = (
    BASE_DIR
    / "outputfiles"
    / "cache"
    / "pdf_ai_document_context.csv"
)


# ============================================================
# SETTINGS
# ============================================================

MODEL = os.getenv(
    "MARIS_AI_MODEL",
    "gpt-5.6",
)

REQUEST_TIMEOUT = 30

MAX_TEXT_CHARACTERS = 14000

VISION_TEXT_THRESHOLD = 300


# ============================================================
# STRUCTURED AI OUTPUT
# ============================================================

DocumentPurpose = Literal[
    "INFORM",
    "PROMOTE_EVENT",
    "COLLECT_INFORMATION",
    "PROVIDE_DIRECTIONS",
    "REFERENCE",
    "OFFICIAL_RECORD",
    "FORMAL_PUBLICATION",
    "INSTRUCT",
    "UNKNOWN",
]


InteractionType = Literal[
    "READ_ONLY",
    "DATA_ENTRY",
    "SIGNATURE_WORKFLOW",
    "STAFF_WORKFLOW",
    "SPATIAL_NAVIGATION",
    "REFERENCE",
    "MIXED",
    "UNKNOWN",
]


EvidenceLevel = Literal[
    "LOW",
    "MEDIUM",
    "HIGH",
    "UNKNOWN",
]


ConfidenceLevel = Literal[
    "LOW",
    "MEDIUM",
    "HIGH",
]


class AIDocumentContext(BaseModel):

    document_type: str = Field(
        description=(
            "Specific semantic document type such as "
            "Academic CV, Eligibility Form, Event Flyer, "
            "Annual Report, Academic Catalog, Program Guide, "
            "Meeting Minutes, Campus Map, Policy, Brochure, etc."
        )
    )

    document_purpose: DocumentPurpose

    interaction_type: InteractionType

    requires_signature: bool

    requires_staff_action: bool

    is_official_record: bool

    is_formal_publication: bool

    download_print_value: EvidenceLevel

    fixed_layout_value: EvidenceLevel

    web_content_suitability: EvidenceLevel

    pdf_necessity: EvidenceLevel

    confidence: ConfidenceLevel

    evidence_summary: str = Field(
        description=(
            "Short factual explanation of what in the document "
            "supports the classification. Do not recommend remediation."
        )
    )


# ============================================================
# SYSTEM PROMPT
# ============================================================

SYSTEM_PROMPT = """
You are the document-understanding component of Maris,
a PDF accessibility remediation planning system.

Your task is ONLY to understand what a document is,
what it is used for, and whether the PDF format appears
to have meaningful functional value.

Do NOT determine WCAG compliance.
Do NOT determine PDF/UA compliance.
Do NOT recommend remediation.

Distinguish carefully between document type and document purpose.

DOCUMENT PURPOSE values:

INFORM
PROMOTE_EVENT
COLLECT_INFORMATION
PROVIDE_DIRECTIONS
REFERENCE
OFFICIAL_RECORD
FORMAL_PUBLICATION
INSTRUCT
UNKNOWN

PDF NECESSITY values:

HIGH:
Strong evidence that stable layout, download, printing,
signatures, archival value, official record status, or fixed
publication format matters.

MEDIUM:
PDF has plausible useful value, but may not be essential.

LOW:
The content could naturally function as ordinary web content
without meaningful loss of function.

UNKNOWN:
Insufficient evidence.

Important examples:

An academic CV is REFERENCE content and often has
download/print value.

A form with applicant fields is COLLECT_INFORMATION.
If it contains signatures, attestations, staff review,
or eligibility decisions, identify those workflow signals.

A catalog, annual report, or strategic plan is generally a
FORMAL_PUBLICATION.

A flyer or event poster is PROMOTE_EVENT.

A map is PROVIDE_DIRECTIONS and SPATIAL_NAVIGATION.

Use UNKNOWN instead of inventing facts.

Base your answer only on the supplied evidence.
"""


# ============================================================
# CLIENT
# ============================================================

def create_client():

    api_key = os.getenv(
        "OPENAI_API_KEY"
    )

    if not api_key:

        raise RuntimeError(
            "\nOPENAI_API_KEY is not set.\n\n"
            "Set it in this terminal first:\n\n"
            'export OPENAI_API_KEY="YOUR_KEY_HERE"\n'
        )

    return OpenAI(
        api_key=api_key
    )


# ============================================================
# PDF DOWNLOAD
# ============================================================

def download_pdf(url):

    headers = {
        "User-Agent": (
            "Mozilla/5.0 "
            "Maris-PDF-Accessibility-Research/1.0"
        )
    }

    response = requests.get(
        url,
        headers=headers,
        timeout=REQUEST_TIMEOUT,
        allow_redirects=True,
    )

    response.raise_for_status()

    content_type = (
        response.headers
        .get(
            "Content-Type",
            "",
        )
        .lower()
    )

    data = response.content

    if (
        "pdf" not in content_type
        and not data.startswith(
            b"%PDF"
        )
    ):

        raise ValueError(
            "URL did not return a valid PDF."
        )

    return data


# ============================================================
# REPRESENTATIVE PAGES
# ============================================================

def representative_page_indexes(
    page_count
):

    if page_count <= 0:
        return []

    candidates = [
        0,
        1,
        2,
        page_count // 2,
        page_count - 2,
        page_count - 1,
    ]

    indexes = []

    for index in candidates:

        if (
            0 <= index < page_count
            and index not in indexes
        ):
            indexes.append(
                index
            )

    return indexes


# ============================================================
# TEXT EXTRACTION
# ============================================================

def extract_document_text(
    pdf_bytes
):

    document = pymupdf.open(
        stream=pdf_bytes,
        filetype="pdf",
    )

    page_count = len(
        document
    )

    indexes = (
        representative_page_indexes(
            page_count
        )
    )

    sections = []

    total_characters = 0

    for page_index in indexes:

        page = document[
            page_index
        ]

        text = (
            page
            .get_text(
                "text"
            )
            .strip()
        )

        if not text:
            continue

        text = text[
            :5000
        ]

        remaining = (
            MAX_TEXT_CHARACTERS
            - total_characters
        )

        if remaining <= 0:
            break

        text = text[
            :remaining
        ]

        sections.append(
            (
                f"\n--- PAGE "
                f"{page_index + 1} "
                f"OF {page_count} ---\n"
                f"{text}"
            )
        )

        total_characters += len(
            text
        )

    full_text = "\n".join(
        sections
    )

    document.close()

    return (
        full_text,
        page_count,
        total_characters,
    )


# ============================================================
# VISION FALLBACK
# ============================================================

def render_first_page_base64(
    pdf_bytes
):

    document = pymupdf.open(
        stream=pdf_bytes,
        filetype="pdf",
    )

    if len(document) == 0:

        document.close()

        return None

    page = document[0]

    matrix = pymupdf.Matrix(
        1.4,
        1.4,
    )

    pixmap = page.get_pixmap(
        matrix=matrix,
        alpha=False,
    )

    image_bytes = (
        pixmap.tobytes(
            "jpeg"
        )
    )

    document.close()

    encoded = (
        base64
        .b64encode(
            image_bytes
        )
        .decode(
            "utf-8"
        )
    )

    return encoded


# ============================================================
# EXISTING METADATA
# ============================================================

def build_existing_metadata(
    row
):

    fields = {
        "filename":
            row.get(
                "filename",
                "",
            ),

        "title":
            row.get(
                "title",
                "",
            ),

        "source_page":
            row.get(
                "source_page",
                "",
            ),

        "rule_document_type":
            row.get(
                "document_type",
                "",
            ),

        "rule_document_purpose":
            row.get(
                "document_purpose",
                "",
            ),

        "rule_pdf_necessity":
            row.get(
                "pdf_necessity",
                "",
            ),

        "page_count":
            row.get(
                "page_count",
                "",
            ),

        "form_field_count":
            row.get(
                "form_field_count",
                "",
            ),

        "image_count":
            row.get(
                "image_count",
                "",
            ),

        "likely_scanned":
            row.get(
                "likely_scanned",
                "",
            ),

        "likely_complex_layout":
            row.get(
                "likely_complex_layout",
                "",
            ),

        "source_application_hint":
            row.get(
                "source_application_hint",
                "",
            ),
    }

    lines = []

    for key, value in fields.items():

        if (
            value is None
            or str(
                value
            ).strip()
            == ""
        ):
            continue

        lines.append(
            f"{key}: {value}"
        )

    return "\n".join(
        lines
    )


# ============================================================
# USER PROMPT
# ============================================================

def build_user_text(
    row,
    extracted_text,
    page_count,
    extracted_character_count,
):

    metadata = (
        build_existing_metadata(
            row
        )
    )

    return f"""
Analyze this PDF only for semantic document understanding.

EXISTING MACHINE METADATA
These are hints, not ground truth.

{metadata}

ACTUAL PDF PAGE COUNT
{page_count}

EXTRACTED TEXT CHARACTERS
{extracted_character_count}

REPRESENTATIVE CONTENT
{extracted_text if extracted_text else "[No reliable text extracted]"}

Return structured document context.
Do not recommend remediation.
"""


# ============================================================
# AI CLASSIFICATION
# ============================================================

def classify_with_ai(
    client,
    row,
    pdf_bytes,
):

    (
        extracted_text,
        page_count,
        extracted_character_count,
    ) = extract_document_text(
        pdf_bytes
    )

    user_text = build_user_text(
        row,
        extracted_text,
        page_count,
        extracted_character_count,
    )

    content = [
        {
            "type":
                "input_text",

            "text":
                user_text,
        }
    ]

    used_vision = False

    if (
        extracted_character_count
        < VISION_TEXT_THRESHOLD
    ):

        first_page_image = (
            render_first_page_base64(
                pdf_bytes
            )
        )

        if first_page_image:

            content.append(
                {
                    "type":
                        "input_image",

                    "image_url": (
                        "data:image/jpeg;base64,"
                        + first_page_image
                    ),
                }
            )

            used_vision = True

    response = (
        client.responses.parse(
            model=MODEL,

            input=[
                {
                    "role":
                        "system",

                    "content":
                        SYSTEM_PROMPT,
                },

                {
                    "role":
                        "user",

                    "content":
                        content,
                },
            ],

            text_format=
                AIDocumentContext,
        )
    )

    result = (
        response.output_parsed
    )

    if result is None:

        raise RuntimeError(
            "Model did not return "
            "structured document context."
        )

    return (
        result,
        extracted_character_count,
        used_vision,
    )


# ============================================================
# SUCCESS RECORD
# ============================================================

def success_record(
    row,
    context,
    extracted_characters,
    used_vision,
):

    return {
        "pdf_url":
            row.get(
                "pdf_url",
                "",
            ),

        "filename":
            row.get(
                "filename",
                "",
            ),

        "ai_status":
            "SUCCESS",

        "ai_document_type":
            context.document_type,

        "ai_document_purpose":
            context.document_purpose,

        "ai_interaction_type":
            context.interaction_type,

        "ai_requires_signature":
            context.requires_signature,

        "ai_requires_staff_action":
            context.requires_staff_action,

        "ai_is_official_record":
            context.is_official_record,

        "ai_is_formal_publication":
            context.is_formal_publication,

        "ai_download_print_value":
            context.download_print_value,

        "ai_fixed_layout_value":
            context.fixed_layout_value,

        "ai_web_content_suitability":
            context.web_content_suitability,

        "ai_pdf_necessity":
            context.pdf_necessity,

        "ai_confidence":
            context.confidence,

        "ai_evidence_summary":
            context.evidence_summary,

        "ai_used_vision":
            used_vision,

        "ai_extracted_characters":
            extracted_characters,

        "ai_error":
            "",
    }


# ============================================================
# ERROR RECORD
# ============================================================

def error_record(
    row,
    error_message
):

    return {
        "pdf_url":
            row.get(
                "pdf_url",
                "",
            ),

        "filename":
            row.get(
                "filename",
                "",
            ),

        "ai_status":
            "ERROR",

        "ai_document_type":
            "",

        "ai_document_purpose":
            "",

        "ai_interaction_type":
            "",

        "ai_requires_signature":
            "",

        "ai_requires_staff_action":
            "",

        "ai_is_official_record":
            "",

        "ai_is_formal_publication":
            "",

        "ai_download_print_value":
            "",

        "ai_fixed_layout_value":
            "",

        "ai_web_content_suitability":
            "",

        "ai_pdf_necessity":
            "",

        "ai_confidence":
            "",

        "ai_evidence_summary":
            "",

        "ai_used_vision":
            False,

        "ai_extracted_characters":
            0,

        "ai_error":
            str(
                error_message
            ),
    }


# ============================================================
# LOAD CURRENT RUN
# ============================================================

def load_latest_triage():

    if not LATEST_TRIAGE_FILE.exists():

        raise FileNotFoundError(
            "\nNo latest Maris scan was found.\n\n"
            "Run a scan through the Maris web interface first.\n\n"
            f"Expected:\n{LATEST_TRIAGE_FILE}"
        )

    df = pd.read_csv(
        LATEST_TRIAGE_FILE
    )

    if df.empty:

        raise RuntimeError(
            "The latest Maris scan contains no triaged PDFs."
        )

    if (
        "pdf_url"
        not in df.columns
    ):

        raise ValueError(
            "Latest triage file does not contain pdf_url."
        )

    return df


# ============================================================
# CONFIRM PAID CALLS
# ============================================================

def confirm_paid_calls(
    count
):

    if count <= 0:
        return True

    print()
    print(
        "----------------------------------------"
    )
    print(
        "PAID OPENAI CALL CONFIRMATION"
    )
    print(
        "----------------------------------------"
    )
    print()
    print(
        f"{count} new PDF(s) require AI document understanding."
    )
    print(
        f"Estimated OpenAI API calls: {count}"
    )
    print()
    print(
        "Cached PDFs will NOT be charged again."
    )
    print()

    answer = input(
        "Continue with paid API calls? [y/N]: "
    )

    return (
        answer
        .strip()
        .lower()
        in {
            "y",
            "yes",
        }
    )


# ============================================================
# RUN
# ============================================================

def run(confirm_cost=True):

    storage_manager.ensure_storage()

    current_df = (
        load_latest_triage()
    )

    cache_df = (
        storage_manager
        .load_ai_context_cache()
    )

    cached_matches = (
        storage_manager
        .get_cached_matches(
            current_df,
            cache_df,
            key="pdf_url",
        )
    )

    uncached_df = (
        storage_manager
        .find_uncached_rows(
            current_df,
            cache_df,
            key="pdf_url",
        )
    )

    total_current = len(
        current_df
    )

    cached_count = len(
        cached_matches
    )

    new_count = len(
        uncached_df
    )

    print()
    print(
        "========================================"
    )
    print(
        "MARIS AI DOCUMENT UNDERSTANDING"
    )
    print(
        "========================================"
    )
    print(
        f"Model: {MODEL}"
    )
    print()
    print(
        f"Documents in current run: {total_current}"
    )
    print(
        f"Already cached: {cached_count}"
    )
    print(
        f"New documents requiring AI: {new_count}"
    )
    print(
        f"Estimated OpenAI calls: {new_count}"
    )
    print()

    # --------------------------------------------------------
    # NOTHING NEW
    # --------------------------------------------------------

    if new_count == 0:

        print(
            "No paid API calls are needed."
        )

        print()
        print(
            "All current PDFs already have cached "
            "AI document understanding."
        )

        print()
        print(
            f"Cache:\n{AI_CONTEXT_CACHE}"
        )

        print(
            "========================================"
        )

        return cached_matches

    # --------------------------------------------------------
    # USER CONFIRMATION
    # --------------------------------------------------------

    if confirm_cost:

     if not confirm_paid_calls(
        new_count
    ):

        print()
        print(
            "Cancelled. No OpenAI API calls were made."
        )

        return pd.DataFrame()

    client = create_client()

    records = []

    total_new = len(
        uncached_df
    )

    print()
    print(
        "Processing new PDFs only:"
    )
    print()

    for _, row in (
        uncached_df.iterrows()
    ):

        position = (
            len(records)
            + 1
        )

        filename = str(
            row.get(
                "filename",
                "Untitled PDF",
            )
        )

        pdf_url = str(
            row.get(
                "pdf_url",
                "",
            )
        )

        print(
            f"[{position}/{total_new}] "
            f"{filename}"
        )

        if not pdf_url:

            error = (
                "Missing PDF URL."
            )

            print(
                f"    ERROR: {error}"
            )

            records.append(
                error_record(
                    row,
                    error,
                )
            )

            continue

        try:

            pdf_bytes = (
                download_pdf(
                    pdf_url
                )
            )

            (
                context,
                extracted_characters,
                used_vision,
            ) = classify_with_ai(
                client,
                row,
                pdf_bytes,
            )

            record = (
                success_record(
                    row,
                    context,
                    extracted_characters,
                    used_vision,
                )
            )

            records.append(
                record
            )

            print(
                "    "
                f"{context.document_type}"
                " | "
                f"{context.document_purpose}"
                " | PDF need: "
                f"{context.pdf_necessity}"
                " | "
                f"{context.confidence}"
            )

            if used_vision:

                print(
                    "    Vision fallback used"
                )

        except Exception as error:

            print(
                f"    ERROR: {error}"
            )

            records.append(
                error_record(
                    row,
                    error,
                )
            )

        time.sleep(
            0.2
        )

    # --------------------------------------------------------
    # SAVE NEW RESULTS INTO PERMANENT CACHE
    # --------------------------------------------------------

    new_results = (
        pd.DataFrame(
            records
        )
    )

    full_cache = (
        storage_manager
        .save_ai_context_results(
            new_results
        )
    )

    # --------------------------------------------------------
    # CURRENT RUN MATCHES
    # --------------------------------------------------------

    current_matches = (
        storage_manager
        .get_cached_matches(
            current_df,
            full_cache,
            key="pdf_url",
        )
    )

    successful_new = (
        new_results[
            new_results[
                "ai_status"
            ]
            == "SUCCESS"
        ]
        if (
            not new_results.empty
            and "ai_status"
            in new_results.columns
        )
        else pd.DataFrame()
    )

    failed_new = (
        new_results[
            new_results[
                "ai_status"
            ]
            == "ERROR"
        ]
        if (
            not new_results.empty
            and "ai_status"
            in new_results.columns
        )
        else pd.DataFrame()
    )

    print()
    print(
        "========================================"
    )
    print(
        "AI DOCUMENT UNDERSTANDING COMPLETE"
    )
    print(
        "========================================"
    )

    print(
        f"New successful results: "
        f"{len(successful_new)}"
    )

    print(
        f"New errors: "
        f"{len(failed_new)}"
    )

    print(
        f"Total cached AI documents: "
        f"{len(full_cache)}"
    )

    print(
        f"Current run AI matches: "
        f"{len(current_matches)}"
    )

    print()
    print(
        f"Permanent cache:\n"
        f"{AI_CONTEXT_CACHE}"
    )

    print(
        "========================================"
    )

    return current_matches


# ============================================================
# CLI
# ============================================================

if __name__ == "__main__":

    run()