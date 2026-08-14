from pathlib import Path
import json
import re

import pandas as pd


# --------------------------------------------------
# DEFAULT PATHS
# --------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent

DEFAULT_ANALYSIS_FILE = BASE_DIR / "outputfiles" / "pdf_analysis.csv"
DEFAULT_FAMILY_FILE = BASE_DIR / "outputfiles" / "pdf_document_families.csv"
DEFAULT_OUTPUT_FILE = BASE_DIR / "outputfiles" / "pdf_document_context.csv"


# --------------------------------------------------
# BASIC HELPERS
# --------------------------------------------------

def clean_text(value):
    """
    Normalize human-readable text while preserving word boundaries.
    """

    if value is None:
        return ""

    value = str(value).lower()

    value = re.sub(r"https?://", " ", value)
    value = re.sub(r"[_\-]+", " ", value)
    value = re.sub(r"\.pdf\b", " ", value)
    value = re.sub(r"[^\w\s]", " ", value)
    value = re.sub(r"\s+", " ", value)

    return value.strip()


def clean_source_page(value):
    """
    Normalize a source URL separately.

    Source-page context is useful, but it is weaker evidence than
    the PDF's own filename/title/subject.
    """

    if value is None:
        return ""

    value = str(value).lower()

    value = re.sub(r"https?://", " ", value)
    value = re.sub(r"[/?#=&_.\-]+", " ", value)
    value = re.sub(r"[^\w\s]", " ", value)
    value = re.sub(r"\s+", " ", value)

    return value.strip()


def to_number(value):
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0


def to_bool(value):
    return str(value).strip().lower() == "true"


def signals_to_json(signals):
    return json.dumps(signals, ensure_ascii=False)


def phrase_present(text, phrase):
    """
    Match complete words / phrases rather than arbitrary substrings.

    Example:
        "form" matches "form"
        "form" does NOT match "information"
    """

    text = clean_text(text)
    phrase = clean_text(phrase)

    if not text or not phrase:
        return False

    pattern = r"(?<!\w)" + re.escape(phrase) + r"(?!\w)"

    return re.search(pattern, text, flags=re.IGNORECASE) is not None


def contains_any(text, phrases):
    return any(
        phrase_present(text, phrase)
        for phrase in phrases
    )


# --------------------------------------------------
# DOCUMENT TEXT
# --------------------------------------------------

def build_primary_text(row):
    """
    Strongest evidence for identifying the document itself.

    We intentionally exclude source_page here because a page may link
    to many completely different PDFs.
    """

    values = [
        clean_text(row.get("filename", "")),
        clean_text(row.get("title", "")),
        clean_text(row.get("subject", "")),
    ]

    return " ".join(
        value for value in values if value
    )


def build_source_context(row):
    """
    Weaker contextual evidence from the webpage where the PDF was found.
    """

    return clean_source_page(
        row.get("source_page", "")
    )


# --------------------------------------------------
# DOCUMENT TYPE CLASSIFICATION
# --------------------------------------------------

def classify_document_type(row):
    """
    Estimate what kind of document this is.

    IMPORTANT:
    Document TYPE and document PURPOSE are different concepts.

    Example:
        Type: Brochure / Booklet
        Purpose: REFERENCE
    """

    primary_text = build_primary_text(row)
    source_context = build_source_context(row)

    form_fields = int(
        to_number(
            row.get("form_field_count", 0)
        )
    )

    # --------------------------------------------------
    # FORM
    # --------------------------------------------------

    strong_form_terms = [
        "application form",
        "registration form",
        "request form",
        "intake form",
        "enrollment form",
        "consent form",
        "authorization form",
        "feedback form",
        "referral form",
        "order form",
        "submission form",
        "questionnaire",
        "survey",
        "attestation",
    ]

    weaker_form_terms = [
        "application",
        "registration",
        "enrollment",
        "intake",
    ]

    if form_fields > 0:
        return "Form"

    if contains_any(
        primary_text,
        strong_form_terms,
    ):
        return "Form"

    # Only allow weaker terms when they occur in the PDF's own
    # filename/title/subject, never just because the hosting page
    # happens to contain the word.
    if contains_any(
        primary_text,
        weaker_form_terms,
    ):
        return "Possible Form"

    # --------------------------------------------------
    # MAP / DIRECTIONS
    # --------------------------------------------------

    if contains_any(
        primary_text,
        [
            "campus map",
            "parking map",
            "map",
            "directions",
            "wayfinding",
            "floor plan",
            "site plan",
        ],
    ):
        return "Map / Directions"

    # --------------------------------------------------
    # EVENT / PROMOTIONAL
    # --------------------------------------------------

    if contains_any(
        primary_text,
        [
            "flyer",
            "poster",
            "hackathon",
            "symposium",
            "conference",
            "workshop",
            "seminar",
            "lecture",
            "open house",
            "event",
        ],
    ):
        return "Event / Promotional Material"

    # Source-page event context may be useful, but only when the PDF
    # itself also looks short and image-oriented.
    page_count = int(
        to_number(
            row.get("page_count", 0)
        )
    )

    image_count = int(
        to_number(
            row.get("image_count", 0)
        )
    )

    if (
        contains_any(
            source_context,
            [
                "events",
                "event",
                "conference",
                "symposium",
            ],
        )
        and page_count <= 2
        and image_count > 0
    ):
        return "Possible Event / Promotional Material"

    # --------------------------------------------------
    # BROCHURE / BOOKLET
    # --------------------------------------------------

    if contains_any(
        primary_text,
        [
            "brochure",
            "booklet",
            "pamphlet",
        ],
    ):
        return "Brochure / Booklet"

    # --------------------------------------------------
    # REPORT
    # --------------------------------------------------

    if contains_any(
        primary_text,
        [
            "annual report",
            "biennial report",
            "assessment report",
            "research report",
            "financial report",
            "report",
        ],
    ):
        return "Report"

    # --------------------------------------------------
    # POLICY / PROCEDURE
    # --------------------------------------------------

    if contains_any(
        primary_text,
        [
            "policy",
            "procedure",
            "protocol",
            "guideline",
            "standards",
        ],
    ):
        return "Policy / Procedure"

    # --------------------------------------------------
    # MEETING MATERIAL
    # --------------------------------------------------

    if contains_any(
        primary_text,
        [
            "meeting minutes",
            "minutes",
            "agenda",
        ],
    ):
        return "Meeting Material"

    # --------------------------------------------------
    # NEWSLETTER / PERIODICAL
    # --------------------------------------------------

    if contains_any(
        primary_text,
        [
            "newsletter",
            "journal",
            "magazine",
            "bulletin",
        ],
    ):
        return "Newsletter / Periodical"

    # --------------------------------------------------
    # GUIDE / HANDBOOK
    # --------------------------------------------------

    if contains_any(
        primary_text,
        [
            "handbook",
            "resource guide",
            "orientation guide",
            "manual",
            "guide",
            "instructions",
        ],
    ):
        return "Guide / Handbook"

    # --------------------------------------------------
    # OFFICIAL RECORD
    # --------------------------------------------------

    if contains_any(
        primary_text,
        [
            "certificate",
            "certification",
            "official record",
            "transcript",
            "diploma",
        ],
    ):
        return "Official Record"

    # --------------------------------------------------
    # CV / RESUME
    # --------------------------------------------------

    if contains_any(
        primary_text,
        [
            "curriculum vitae",
            "resume",
        ],
    ):
        return "CV / Resume"

    # --------------------------------------------------
    # FACT SHEET
    # --------------------------------------------------

    if contains_any(
        primary_text,
        [
            "fact sheet",
            "factsheet",
            "quick facts",
        ],
    ):
        return "Fact Sheet"

    return "General Document"


# --------------------------------------------------
# DOCUMENT PURPOSE
# --------------------------------------------------

def determine_document_purpose(
    row,
    document_type,
):
    """
    Determine the document's likely primary purpose.

    Values:

        INFORM
        PROMOTE_EVENT
        COLLECT_INFORMATION
        PROVIDE_DIRECTIONS
        REFERENCE
        OFFICIAL_RECORD
        FORMAL_PUBLICATION
        INSTRUCT
        UNKNOWN
    """

    form_fields = int(
        to_number(
            row.get("form_field_count", 0)
        )
    )

    signals = []

    # --------------------------------------------------
    # COLLECT INFORMATION
    # --------------------------------------------------

    if document_type == "Form":

        if form_fields > 0:
            signals.append(
                f"{form_fields} interactive PDF form field(s) detected"
            )

        signals.append(
            "Document evidence strongly indicates a form, application, questionnaire, or submission workflow"
        )

        return (
            "COLLECT_INFORMATION",
            "High",
            signals,
        )

    if document_type == "Possible Form":

        signals.append(
            "Filename/title suggests an application, registration, enrollment, or intake document"
        )

        signals.append(
            "No interactive PDF fields were detected"
        )

        return (
            "COLLECT_INFORMATION",
            "Medium",
            signals,
        )

    # --------------------------------------------------
    # DIRECTIONS
    # --------------------------------------------------

    if document_type == "Map / Directions":

        signals.append(
            "Document evidence indicates maps, directions, parking, or wayfinding"
        )

        return (
            "PROVIDE_DIRECTIONS",
            "High",
            signals,
        )

    # --------------------------------------------------
    # EVENT PROMOTION
    # --------------------------------------------------

    if document_type == "Event / Promotional Material":

        signals.append(
            "Filename/title identifies event or promotional content"
        )

        return (
            "PROMOTE_EVENT",
            "High",
            signals,
        )

    if document_type == "Possible Event / Promotional Material":

        signals.append(
            "Source page suggests event content and the PDF is short and image-oriented"
        )

        return (
            "PROMOTE_EVENT",
            "Low",
            signals,
        )

    # --------------------------------------------------
    # OFFICIAL RECORD
    # --------------------------------------------------

    if document_type == "Official Record":

        signals.append(
            "Document appears to function as an official or fixed record"
        )

        return (
            "OFFICIAL_RECORD",
            "High",
            signals,
        )

    # --------------------------------------------------
    # FORMAL PUBLICATION
    # --------------------------------------------------

    if document_type in {
        "Report",
        "Newsletter / Periodical",
    }:

        signals.append(
            f"Document classified as {document_type}"
        )

        return (
            "FORMAL_PUBLICATION",
            "Medium",
            signals,
        )

    # --------------------------------------------------
    # REFERENCE
    # --------------------------------------------------

    if document_type in {
        "Brochure / Booklet",
        "Guide / Handbook",
    }:

        signals.append(
            f"Document classified as {document_type}"
        )

        return (
            "REFERENCE",
            "Medium",
            signals,
        )

    # --------------------------------------------------
    # INSTRUCTION / POLICY
    # --------------------------------------------------

    if document_type == "Policy / Procedure":

        signals.append(
            "Document appears to communicate policy, procedure, protocol, or guidance"
        )

        return (
            "INSTRUCT",
            "Medium",
            signals,
        )

    # --------------------------------------------------
    # INFORM
    # --------------------------------------------------

    if document_type in {
        "Meeting Material",
        "Fact Sheet",
        "CV / Resume",
    }:

        signals.append(
            f"Document classified as {document_type}"
        )

        return (
            "INFORM",
            "Medium",
            signals,
        )

    # --------------------------------------------------
    # GENERAL DOCUMENT
    # --------------------------------------------------

    signals.append(
        "Available metadata does not establish a more specialized workflow"
    )

    return (
        "INFORM",
        "Low",
        signals,
    )


# --------------------------------------------------
# PDF NECESSITY
# --------------------------------------------------

def determine_pdf_necessity(
    row,
    document_type,
    document_purpose,
    purpose_confidence,
):
    """
    Estimate whether PDF appears necessary as the delivery format.

    This is NOT an accessibility score.

    Values:

        LOW
        MEDIUM
        HIGH
        UNKNOWN
    """

    signals = []

    form_fields = int(
        to_number(
            row.get("form_field_count", 0)
        )
    )

    # --------------------------------------------------
    # EVENT PROMOTION
    # --------------------------------------------------

    if document_purpose == "PROMOTE_EVENT":

        signals.append(
            "Primary purpose appears to be event promotion or event information"
        )

        signals.append(
            "No fixed-document requirement is evident from current metadata"
        )

        return (
            "LOW",
            (
                "High"
                if purpose_confidence == "High"
                else "Low"
            ),
            signals,
        )

    # --------------------------------------------------
    # DATA COLLECTION
    # --------------------------------------------------

    if document_purpose == "COLLECT_INFORMATION":

        signals.append(
            "Primary purpose appears to involve collecting or submitting user information"
        )

        if form_fields > 0:
            signals.append(
                "Interactive form controls confirm a data-entry workflow"
            )

        signals.append(
            "Whether a fixed PDF workflow is legally or operationally required cannot be established automatically"
        )

        return (
            "UNKNOWN",
            "Medium",
            signals,
        )

    # --------------------------------------------------
    # SIMPLE INFORMATIONAL CONTENT
    # --------------------------------------------------

    if document_type in {
        "Meeting Material",
        "Fact Sheet",
    }:

        signals.append(
            f"{document_type} is primarily informational"
        )

        signals.append(
            "No fixed-document requirement was identified"
        )

        return (
            "LOW",
            "Medium",
            signals,
        )

    # --------------------------------------------------
    # OFFICIAL RECORD
    # --------------------------------------------------

    if document_purpose == "OFFICIAL_RECORD":

        signals.append(
            "Document appears to serve as an official or fixed record"
        )

        return (
            "HIGH",
            "High",
            signals,
        )

    # --------------------------------------------------
    # FORMAL PUBLICATION
    # --------------------------------------------------

    if document_purpose == "FORMAL_PUBLICATION":

        signals.append(
            "Document appears to be a formal publication"
        )

        signals.append(
            "Formal publications may have legitimate print, download, archival, or fixed-layout uses"
        )

        return (
            "MEDIUM",
            "Medium",
            signals,
        )

    # --------------------------------------------------
    # REFERENCE
    # --------------------------------------------------

    if document_purpose == "REFERENCE":

        signals.append(
            "Document appears to function as a reference resource"
        )

        signals.append(
            "Reference documents may have legitimate offline or printable uses"
        )

        return (
            "MEDIUM",
            "Low",
            signals,
        )

    # --------------------------------------------------
    # MAPS / DIRECTIONS
    # --------------------------------------------------

    if document_purpose == "PROVIDE_DIRECTIONS":

        signals.append(
            "Document contains spatial or directional information"
        )

        signals.append(
            "The need for fixed visual presentation cannot be established automatically"
        )

        return (
            "UNKNOWN",
            "High",
            signals,
        )

    # --------------------------------------------------
    # POLICIES / PROCEDURES
    # --------------------------------------------------

    if document_purpose == "INSTRUCT":

        signals.append(
            "Document communicates policy, procedure, instructions, or guidance"
        )

        signals.append(
            "Current metadata cannot establish whether an official fixed version must be retained"
        )

        return (
            "UNKNOWN",
            "Medium",
            signals,
        )

    # --------------------------------------------------
    # GENERAL INFORMATION
    # --------------------------------------------------

    if document_purpose == "INFORM":

        signals.append(
            "Document appears primarily informational"
        )

        signals.append(
            "No strong fixed-document requirement was identified from available metadata"
        )

        return (
            "LOW",
            "Low",
            signals,
        )

    # --------------------------------------------------
    # FALLBACK
    # --------------------------------------------------

    signals.append(
        "Available evidence is insufficient to determine whether PDF format is necessary"
    )

    return (
        "UNKNOWN",
        "Low",
        signals,
    )


# --------------------------------------------------
# DECISION BASIS
# --------------------------------------------------

def build_decision_basis(
    document_type,
    document_purpose,
    purpose_confidence,
    pdf_necessity,
    necessity_confidence,
):
    return (
        f"Document classified as '{document_type}'. "
        f"Primary purpose inferred as '{document_purpose}' "
        f"with {purpose_confidence.lower()} confidence. "
        f"PDF necessity estimated as '{pdf_necessity}' "
        f"with {necessity_confidence.lower()} confidence."
    )


# --------------------------------------------------
# ANALYZE ONE DOCUMENT
# --------------------------------------------------

def analyze_document_context(row):

    document_type = classify_document_type(
        row
    )

    (
        document_purpose,
        purpose_confidence,
        purpose_signals,
    ) = determine_document_purpose(
        row,
        document_type,
    )

    (
        pdf_necessity,
        necessity_confidence,
        necessity_signals,
    ) = determine_pdf_necessity(
        row,
        document_type,
        document_purpose,
        purpose_confidence,
    )

    decision_basis = build_decision_basis(
        document_type,
        document_purpose,
        purpose_confidence,
        pdf_necessity,
        necessity_confidence,
    )

    return {
        "document_type": document_type,
        "document_purpose": document_purpose,
        "purpose_confidence": purpose_confidence,
        "purpose_signals": signals_to_json(
            purpose_signals
        ),
        "pdf_necessity": pdf_necessity,
        "pdf_necessity_confidence": necessity_confidence,
        "pdf_necessity_signals": signals_to_json(
            necessity_signals
        ),
        "decision_basis": decision_basis,
    }


# --------------------------------------------------
# FAMILY INFORMATION
# --------------------------------------------------

def merge_family_information(
    df,
    family_file,
):

    family_file = Path(
        family_file
    )

    if not family_file.exists():
        return df

    try:
        family_df = pd.read_csv(
            family_file
        )
    except Exception:
        return df

    if family_df.empty:
        return df

    family_columns = [
        column
        for column in [
            "pdf_url",
            "family_id",
            "family_name",
            "family_size",
            "family_similarity",
            "family_confidence",
        ]
        if column in family_df.columns
    ]

    if "pdf_url" not in family_columns:
        return df

    family_subset = (
        family_df[
            family_columns
        ]
        .drop_duplicates(
            subset=["pdf_url"]
        )
        .copy()
    )

    return df.merge(
        family_subset,
        on="pdf_url",
        how="left",
    )


# --------------------------------------------------
# RUN
# --------------------------------------------------

def run(
    analysis_file=DEFAULT_ANALYSIS_FILE,
    family_file=DEFAULT_FAMILY_FILE,
    output_file=DEFAULT_OUTPUT_FILE,
):

    analysis_file = Path(
        analysis_file
    )

    family_file = Path(
        family_file
    )

    output_file = Path(
        output_file
    )

    output_file.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    if not analysis_file.exists():

        raise FileNotFoundError(
            f"Analysis file not found: {analysis_file}"
        )

    df = pd.read_csv(
        analysis_file
    )

    if "analysis_status" in df.columns:

        df = df[
            df["analysis_status"] == "SUCCESS"
        ].copy()

    df.reset_index(
        drop=True,
        inplace=True,
    )

    if df.empty:

        empty_columns = [
            "institution",
            "filename",
            "pdf_url",
            "source_page",
            "document_type",
            "document_purpose",
            "purpose_confidence",
            "purpose_signals",
            "pdf_necessity",
            "pdf_necessity_confidence",
            "pdf_necessity_signals",
            "decision_basis",
        ]

        empty_df = pd.DataFrame(
            columns=empty_columns
        )

        empty_df.to_csv(
            output_file,
            index=False,
        )

        return empty_df

    # --------------------------------------------------
    # DOCUMENT CONTEXT
    # --------------------------------------------------

    context_records = []

    for _, row in df.iterrows():

        context_records.append(
            analyze_document_context(
                row
            )
        )

    context_df = pd.DataFrame(
        context_records
    )

    result = pd.concat(
        [
            df.reset_index(drop=True),
            context_df.reset_index(drop=True),
        ],
        axis=1,
    )

    # --------------------------------------------------
    # FAMILY INFORMATION
    # --------------------------------------------------

    result = merge_family_information(
        result,
        family_file,
    )

    # --------------------------------------------------
    # SAVE
    # --------------------------------------------------

    result.to_csv(
        output_file,
        index=False,
    )

    return result


# --------------------------------------------------
# COMMAND LINE
# --------------------------------------------------

if __name__ == "__main__":

    result_df = run()

    print()
    print(
        "========================================"
    )
    print(
        "DOCUMENT CONTEXT ANALYSIS COMPLETE"
    )
    print(
        "========================================"
    )

    print(
        f"Documents analyzed: {len(result_df)}"
    )

    if not result_df.empty:

        print()
        print(
            "Document types:"
        )

        print(
            result_df[
                "document_type"
            ]
            .value_counts()
            .to_string()
        )

        print()
        print(
            "Document purposes:"
        )

        print(
            result_df[
                "document_purpose"
            ]
            .value_counts()
            .to_string()
        )

        print()
        print(
            "PDF necessity:"
        )

        print(
            result_df[
                "pdf_necessity"
            ]
            .value_counts()
            .to_string()
        )

    print()

    print(
        f"Saved to: {DEFAULT_OUTPUT_FILE}"
    )

    print(
        "========================================"
    )