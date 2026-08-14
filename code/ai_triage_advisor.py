from pathlib import Path
from typing import Literal
import os
import time
import json

import pandas as pd

from openai import OpenAI
from pydantic import BaseModel, Field

from rag_knowledge_base import retrieve
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

RAG_TRIAGE_CACHE = (
    BASE_DIR
    / "outputfiles"
    / "cache"
    / "pdf_rag_triage_advice.csv"
)


# ============================================================
# SETTINGS
# ============================================================

MODEL = os.getenv(
    "MARIS_TRIAGE_MODEL",
    "gpt-5.6-terra",
)

RAG_TOP_K = int(
    os.getenv(
        "MARIS_RAG_TOP_K",
        "5",
    )
)


# ============================================================
# ALLOWED ACTIONS
# ============================================================

RecommendedAction = Literal[
    "Convert to HTML",
    "Convert to Web Form",
    "Fix Source & Re-export",
    "Remediate PDF",
    "Specialist Review",
    "Keep / Review",
    "External Owner Review",
]

Priority = Literal[
    "Low",
    "Medium",
    "High",
]

Confidence = Literal[
    "Low",
    "Medium",
    "High",
]


# ============================================================
# STRUCTURED OUTPUT
# ============================================================

class RAGTriageDecision(BaseModel):

    recommended_action: RecommendedAction

    priority: Priority

    confidence: Confidence

    decision_reason: str = Field(
        description=(
            "Concise explanation connecting document purpose, "
            "workflow, PDF value, accessibility evidence, and "
            "retrieved guidance to the chosen remediation pathway."
        )
    )

    accessibility_concern: str = Field(
        description=(
            "Most important accessibility concern supported by "
            "the supplied evidence. Do not invent failures."
        )
    )

    guidance_basis: str = Field(
        description=(
            "Short explanation of how the retrieved guidance "
            "supports or constrains the recommendation."
        )
    )

    alternative_action: RecommendedAction

    alternative_reason: str

    human_review_required: bool

    human_review_reason: str


# ============================================================
# SYSTEM PROMPT
# ============================================================

SYSTEM_PROMPT = """
You are the standards-grounded remediation advisor inside Maris,
a PDF accessibility remediation planning system.

You are given:

1. deterministic PDF analyzer evidence,
2. an existing rule-based Maris recommendation,
3. semantic AI document understanding,
4. retrieved accessibility guidance.

Your job is to recommend ONE remediation pathway.

You may ONLY choose:

- Convert to HTML
- Convert to Web Form
- Fix Source & Re-export
- Remediate PDF
- Specialist Review
- Keep / Review
- External Owner Review

The retrieved guidance is evidence, not permission to invent
requirements.

Distinguish between authoritative guidance and Maris decision
rules.

Do not present a Maris rule as though it were a WCAG or
Section 508 requirement.

Use Convert to HTML when content is primarily informational
and web delivery is a natural fit, unless there is meaningful
fixed, archival, print, publication, or record value.

Use Convert to Web Form when the primary purpose is collecting
or submitting information and the workflow can reasonably be
implemented online.

Use caution when forms contain signatures, attestations,
staff-only sections, approval steps, eligibility decisions,
or other official workflow requirements.

Use Fix Source & Re-export when the PDF should remain, an
editable source is likely available, and accessibility problems
are better corrected in that source.

Use Remediate PDF when the PDF should remain and direct PDF
repair is more appropriate than source-level repair.

Use Specialist Review when automated evidence is insufficient
or the document contains maps, scanned content, complex forms,
complex tables, unusual reading order, conflicting evidence,
or other cases requiring human judgment.

Use Keep / Review when there is legitimate reason to retain
the PDF but no strong remediation pathway can be justified
from current evidence.

Use External Owner Review when the document appears externally
owned or hosted.

Never invent:

- WCAG failures
- screen reader failures
- keyboard failures
- reading order failures
- contrast failures
- missing alt text
- table failures

unless explicitly supplied.

Documents in the same apparent family should normally receive
consistent remediation logic unless document-specific evidence
justifies a difference.

Return a remediation recommendation with traceable reasoning,
not a legal compliance determination.
"""


# ============================================================
# HELPERS
# ============================================================

def value(row, column, default=""):

    result = row.get(
        column,
        default,
    )

    if pd.isna(result):
        return default

    return result


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
# LOAD CURRENT RUN
# ============================================================

def load_latest_triage():

    if not LATEST_TRIAGE_FILE.exists():

        raise FileNotFoundError(
            "\nNo latest Maris triage file was found.\n\n"
            "Run Maris through the web interface first.\n\n"
            f"Expected:\n{LATEST_TRIAGE_FILE}"
        )

    df = pd.read_csv(
        LATEST_TRIAGE_FILE
    )

    if df.empty:

        raise RuntimeError(
            "The latest Maris scan contains no triaged PDFs."
        )

    return df


# ============================================================
# LOAD AI DOCUMENT CONTEXT FOR CURRENT RUN
# ============================================================

def load_current_ai_context(current_df):

    cache_df = (
        storage_manager
        .load_ai_context_cache()
    )

    if cache_df.empty:

        raise RuntimeError(
            "AI document-understanding cache is empty.\n"
            "Run ai_document_understanding.py first."
        )

    matches = (
        storage_manager
        .get_cached_matches(
            current_df,
            cache_df,
            key="pdf_url",
        )
    )

    if matches.empty:

        raise RuntimeError(
            "None of the PDFs in the latest scan have cached "
            "AI document understanding.\n"
            "Run ai_document_understanding.py first."
        )

    return matches


# ============================================================
# RAG TRIAGE CACHE
# ============================================================

def load_rag_cache():

    if not RAG_TRIAGE_CACHE.exists():
        return pd.DataFrame()

    try:

        return pd.read_csv(
            RAG_TRIAGE_CACHE
        )

    except Exception:

        return pd.DataFrame()


def save_rag_cache(new_df):

    storage_manager.ensure_storage()

    if new_df is None or new_df.empty:

        return load_rag_cache()

    existing = load_rag_cache()

    if existing.empty:

        combined = (
            new_df
            .drop_duplicates(
                subset=["pdf_url"],
                keep="last",
            )
            .copy()
        )

    else:

        combined = pd.concat(
            [
                existing,
                new_df,
            ],
            ignore_index=True,
        )

        combined = (
            combined
            .drop_duplicates(
                subset=["pdf_url"],
                keep="last",
            )
            .reset_index(drop=True)
        )

    combined.to_csv(
        RAG_TRIAGE_CACHE,
        index=False,
    )

    return combined


def get_cached_rag_matches(
    current_df,
    cache_df,
):

    if cache_df.empty:

        return pd.DataFrame()

    current_urls = set(
        current_df[
            "pdf_url"
        ]
        .dropna()
        .astype(str)
    )

    return cache_df[
        cache_df[
            "pdf_url"
        ]
        .astype(str)
        .isin(current_urls)
    ].copy()


def get_uncached_rag_rows(
    merged_df,
    cache_df,
):

    if cache_df.empty:

        return merged_df.copy()

    cached_urls = set(
        cache_df[
            "pdf_url"
        ]
        .dropna()
        .astype(str)
    )

    return merged_df[
        ~merged_df[
            "pdf_url"
        ]
        .astype(str)
        .isin(cached_urls)
    ].copy()


# ============================================================
# MERGE CURRENT RULE TRIAGE + AI CONTEXT
# ============================================================

def build_current_evaluation_data():

    triage_df = (
        load_latest_triage()
    )

    ai_context_df = (
        load_current_ai_context(
            triage_df
        )
    )

    ai_columns = [
        column
        for column in ai_context_df.columns
        if (
            column == "pdf_url"
            or column.startswith("ai_")
        )
    ]

    ai_context_df = (
        ai_context_df[
            ai_columns
        ]
        .drop_duplicates(
            subset=["pdf_url"]
        )
    )

    merged = triage_df.merge(
        ai_context_df,
        on="pdf_url",
        how="inner",
    )

    if merged.empty:

        raise RuntimeError(
            "No matching rows were found between the current "
            "triage results and AI document context cache."
        )

    return merged


# ============================================================
# BUILD RAG QUERY
# ============================================================

def build_rag_query(row):

    return f"""
Document type:
{value(row, "ai_document_type", value(row, "document_type", "Unknown"))}

Document purpose:
{value(row, "ai_document_purpose", value(row, "document_purpose", "Unknown"))}

Interaction:
{value(row, "ai_interaction_type", "Unknown")}

PDF necessity:
{value(row, "ai_pdf_necessity", value(row, "pdf_necessity", "Unknown"))}

Signature required:
{value(row, "ai_requires_signature", "Unknown")}

Staff workflow:
{value(row, "ai_requires_staff_action", "Unknown")}

Official record:
{value(row, "ai_is_official_record", "Unknown")}

Formal publication:
{value(row, "ai_is_formal_publication", "Unknown")}

Download or print value:
{value(row, "ai_download_print_value", "Unknown")}

Fixed layout value:
{value(row, "ai_fixed_layout_value", "Unknown")}

Web content suitability:
{value(row, "ai_web_content_suitability", "Unknown")}

Scanned:
{value(row, "likely_scanned", "Unknown")}

Complex layout:
{value(row, "likely_complex_layout", "Unknown")}

Form fields:
{value(row, "form_field_count", "Unknown")}

Tables:
{value(row, "table_like_count", "Unknown")}

Likely source:
{value(row, "source_application_hint", "Unknown")}

Accessibility remediation decision for this PDF.
"""


# ============================================================
# RETRIEVE GUIDANCE
# ============================================================

def retrieve_guidance(row):

    query = build_rag_query(
        row
    )

    return retrieve(
        query,
        top_k=RAG_TOP_K,
    )


def format_guidance(results):

    sections = []

    for index, item in enumerate(
        results,
        start=1,
    ):

        sections.append(
            f"""
GUIDANCE {index}

Source:
{item.get("source_name", "Unknown source")}

Source type:
{item.get("source_type", "")}

Source URL:
{item.get("source_url", "")}

Retrieval similarity:
{item.get("similarity_score", 0):.3f}

Guidance:
{item.get("text", "")}
"""
        )

    return "\n".join(
        sections
    )


# ============================================================
# BUILD MODEL EVIDENCE
# ============================================================

def build_document_evidence(
    row,
    retrieved_guidance,
):

    return f"""
============================================================
DOCUMENT
============================================================

Filename:
{value(row, "filename")}

PDF URL:
{value(row, "pdf_url")}

Source page:
{value(row, "source_page")}


============================================================
DETERMINISTIC PDF ANALYZER
============================================================

Page count:
{value(row, "page_count", "Unknown")}

Text characters:
{value(row, "text_characters", "Unknown")}

Image count:
{value(row, "image_count", "Unknown")}

Form fields:
{value(row, "form_field_count", "Unknown")}

Table-like structures:
{value(row, "table_like_count", "Unknown")}

Likely scanned:
{value(row, "likely_scanned", "Unknown")}

Complex layout:
{value(row, "likely_complex_layout", "Unknown")}

PDF tags:
{value(row, "has_tags", "Unknown")}

Document language:
{value(row, "document_language", "Unknown")}

Likely source application:
{value(row, "source_application_hint", "Unknown")}


============================================================
RULE-BASED MARIS
============================================================

Document type:
{value(row, "document_type", "Unknown")}

Purpose:
{value(row, "document_purpose", "Unknown")}

PDF necessity:
{value(row, "pdf_necessity", "Unknown")}

Original action:
{value(row, "recommended_action", "Unknown")}

Original priority:
{value(row, "priority", "Unknown")}

Original confidence:
{value(row, "recommendation_confidence", "Unknown")}

Original reason:
{value(row, "recommendation_reason", "Unknown")}


============================================================
AI DOCUMENT UNDERSTANDING
============================================================

AI type:
{value(row, "ai_document_type", "Unknown")}

AI purpose:
{value(row, "ai_document_purpose", "Unknown")}

Interaction:
{value(row, "ai_interaction_type", "Unknown")}

Signature:
{value(row, "ai_requires_signature", "Unknown")}

Staff action:
{value(row, "ai_requires_staff_action", "Unknown")}

Official record:
{value(row, "ai_is_official_record", "Unknown")}

Formal publication:
{value(row, "ai_is_formal_publication", "Unknown")}

Download / print value:
{value(row, "ai_download_print_value", "Unknown")}

Fixed-layout value:
{value(row, "ai_fixed_layout_value", "Unknown")}

Web suitability:
{value(row, "ai_web_content_suitability", "Unknown")}

AI PDF necessity:
{value(row, "ai_pdf_necessity", "Unknown")}

AI context confidence:
{value(row, "ai_confidence", "Unknown")}

AI evidence summary:
{value(row, "ai_evidence_summary", "Unknown")}


============================================================
RETRIEVED GUIDANCE
============================================================

{format_guidance(retrieved_guidance)}


============================================================
TASK
============================================================

Choose the most appropriate Maris remediation pathway.

Use the retrieved guidance to constrain the recommendation.

Do not automatically follow the rule-based action.

Do not automatically follow PDF necessity.

Do not invent accessibility failures.

If the available evidence cannot safely support a stronger
decision, use Specialist Review or Keep / Review.

Return a structured decision.
"""


# ============================================================
# MODEL CALL
# ============================================================

def get_rag_decision(
    client,
    row,
    guidance,
):

    evidence = (
        build_document_evidence(
            row,
            guidance,
        )
    )

    response = (
        client.responses.parse(
            model=MODEL,

            input=[
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": evidence,
                },
            ],

            text_format=
                RAGTriageDecision,
        )
    )

    result = response.output_parsed

    if result is None:

        raise RuntimeError(
            "Model did not return "
            "structured RAG triage output."
        )

    return result


# ============================================================
# GUIDANCE PROVENANCE
# ============================================================

def guidance_ids(
    guidance
):

    return json.dumps(
        [
            item.get(
                "id",
                "",
            )
            for item in guidance
        ],
        ensure_ascii=False,
    )


def guidance_sources(
    guidance
):

    return json.dumps(
        [
            {
                "id":
                    item.get(
                        "id",
                        "",
                    ),

                "source":
                    item.get(
                        "source_name",
                        "",
                    ),

                "url":
                    item.get(
                        "source_url",
                        "",
                    ),

                "score":
                    round(
                        float(
                            item.get(
                                "similarity_score",
                                0,
                            )
                        ),
                        4,
                    ),
            }
            for item in guidance
        ],
        ensure_ascii=False,
    )


# ============================================================
# PAID CALL CONFIRMATION
# ============================================================

def confirm_paid_calls(count):

    if count <= 0:
        return True

    print()
    print(
        "----------------------------------------"
    )
    print(
        "PAID RAG TRIAGE CONFIRMATION"
    )
    print(
        "----------------------------------------"
    )
    print()
    print(
        f"{count} PDF(s) require a new RAG triage decision."
    )
    print(
        f"Estimated OpenAI API calls: {count}"
    )
    print()
    print(
        "Local retrieval is free."
    )
    print(
        "Cached RAG decisions will NOT be charged again."
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

    merged_df = (
        build_current_evaluation_data()
    )

    rag_cache = (
        load_rag_cache()
    )

    cached_matches = (
        get_cached_rag_matches(
            merged_df,
            rag_cache,
        )
    )

    uncached_df = (
        get_uncached_rag_rows(
            merged_df,
            rag_cache,
        )
    )

    total_current = len(
        merged_df
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
        "MARIS RAG TRIAGE ADVISOR"
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
        f"Cached RAG decisions: {cached_count}"
    )
    print(
        f"New PDFs requiring RAG triage: {new_count}"
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
            "All PDFs in the current run already have "
            "cached RAG triage decisions."
        )
        print()
        print(
            f"RAG cache:\n{RAG_TRIAGE_CACHE}"
        )
        print(
            "========================================"
        )

        return cached_matches

    # --------------------------------------------------------
    # CONFIRM PAYMENT
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
            value(
                row,
                "filename",
                "Untitled PDF",
            )
        )

        print(
            f"[{position}/{total_new}] "
            f"{filename}"
        )

        try:

            guidance = (
                retrieve_guidance(
                    row
                )
            )

            print(
                "    Retrieved:"
            )

            for item in guidance:

                print(
                    "      - "
                    f"{item['id']} "
                    f"({item['similarity_score']:.3f})"
                )

            decision = (
                get_rag_decision(
                    client,
                    row,
                    guidance,
                )
            )

            original_action = (
                value(
                    row,
                    "recommended_action",
                    "Unknown",
                )
            )

            record = {
                "pdf_url":
                    value(
                        row,
                        "pdf_url",
                    ),

                "filename":
                    filename,

                "rag_status":
                    "SUCCESS",

                "rule_action":
                    original_action,

                "rag_action":
                    decision.recommended_action,

                "action_changed_from_rule":
                    (
                        original_action
                        != decision.recommended_action
                    ),

                "rag_priority":
                    decision.priority,

                "rag_confidence":
                    decision.confidence,

                "rag_decision_reason":
                    decision.decision_reason,

                "rag_accessibility_concern":
                    decision.accessibility_concern,

                "rag_guidance_basis":
                    decision.guidance_basis,

                "rag_alternative_action":
                    decision.alternative_action,

                "rag_alternative_reason":
                    decision.alternative_reason,

                "rag_human_review_required":
                    decision.human_review_required,

                "rag_human_review_reason":
                    decision.human_review_reason,

                "retrieved_guidance_ids":
                    guidance_ids(
                        guidance
                    ),

                "retrieved_guidance_sources":
                    guidance_sources(
                        guidance
                    ),

                "rag_error":
                    "",
            }

            records.append(
                record
            )

            print(
                f"    RULE: {original_action}"
            )

            print(
                "    RAG:  "
                f"{decision.recommended_action}"
                f" | {decision.priority}"
                f" | {decision.confidence}"
            )

        except Exception as error:

            print(
                f"    ERROR: {error}"
            )

            records.append(
                {
                    "pdf_url":
                        value(
                            row,
                            "pdf_url",
                        ),

                    "filename":
                        filename,

                    "rag_status":
                        "ERROR",

                    "rule_action":
                        value(
                            row,
                            "recommended_action",
                        ),

                    "rag_action":
                        "",

                    "action_changed_from_rule":
                        "",

                    "rag_priority":
                        "",

                    "rag_confidence":
                        "",

                    "rag_decision_reason":
                        "",

                    "rag_accessibility_concern":
                        "",

                    "rag_guidance_basis":
                        "",

                    "rag_alternative_action":
                        "",

                    "rag_alternative_reason":
                        "",

                    "rag_human_review_required":
                        "",

                    "rag_human_review_reason":
                        "",

                    "retrieved_guidance_ids":
                        "",

                    "retrieved_guidance_sources":
                        "",

                    "rag_error":
                        str(error),
                }
            )

        time.sleep(
            0.2
        )

    # --------------------------------------------------------
    # SAVE TO PERSISTENT CACHE
    # --------------------------------------------------------

    new_results = (
        pd.DataFrame(
            records
        )
    )

    full_cache = (
        save_rag_cache(
            new_results
        )
    )

    current_matches = (
        get_cached_rag_matches(
            merged_df,
            full_cache,
        )
    )

    successful_new = (
        new_results[
            new_results[
                "rag_status"
            ]
            == "SUCCESS"
        ]
        if (
            not new_results.empty
            and "rag_status"
            in new_results.columns
        )
        else pd.DataFrame()
    )

    failed_new = (
        new_results[
            new_results[
                "rag_status"
            ]
            == "ERROR"
        ]
        if (
            not new_results.empty
            and "rag_status"
            in new_results.columns
        )
        else pd.DataFrame()
    )

    print()
    print(
        "========================================"
    )
    print(
        "RAG TRIAGE COMPLETE"
    )
    print(
        "========================================"
    )
    print(
        f"New successful decisions: "
        f"{len(successful_new)}"
    )
    print(
        f"New errors: "
        f"{len(failed_new)}"
    )
    print(
        f"Total cached RAG decisions: "
        f"{len(full_cache)}"
    )
    print(
        f"Current run RAG matches: "
        f"{len(current_matches)}"
    )
    print()
    print(
        f"Permanent RAG cache:\n"
        f"{RAG_TRIAGE_CACHE}"
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