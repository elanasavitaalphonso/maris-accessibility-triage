from pathlib import Path
from urllib.parse import urlparse
import json

import pandas as pd


# --------------------------------------------------
# DEFAULT PATHS
# --------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent

DEFAULT_ANALYSIS_FILE = BASE_DIR / "outputfiles" / "pdf_analysis.csv"
DEFAULT_FAMILY_FILE = BASE_DIR / "outputfiles" / "pdf_document_families.csv"
DEFAULT_CONTEXT_FILE = BASE_DIR / "outputfiles" / "pdf_document_context.csv"
DEFAULT_OUTPUT_FILE = BASE_DIR / "outputfiles" / "pdf_triage_results.csv"


# --------------------------------------------------
# HELPERS
# --------------------------------------------------

def to_bool(value):
    return str(value).strip().lower() == "true"


def to_number(value):
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0


def signal_list_to_json(signals):
    return json.dumps(signals, ensure_ascii=False)


def normalize_confidence(value):

    value = str(value).strip().title()

    if value in {
        "High",
        "Medium",
        "Low",
    }:
        return value

    return "Low"


def base_domain(url):

    hostname = urlparse(
        str(url)
    ).hostname

    if not hostname:
        return ""

    hostname = hostname.lower()

    parts = hostname.split(".")

    if len(parts) >= 2:
        return ".".join(parts[-2:])

    return hostname


def is_external_document(row):

    pdf_domain = base_domain(
        row.get("pdf_url", "")
    )

    source_domain = base_domain(
        row.get("source_page", "")
    )

    return (
        bool(pdf_domain)
        and bool(source_domain)
        and pdf_domain != source_domain
    )


# --------------------------------------------------
# ACCESSIBILITY EVIDENCE
# --------------------------------------------------

def collect_accessibility_evidence(row):

    signals = []

    has_tags = to_bool(
        row.get("has_tags")
    )

    language = str(
        row.get(
            "document_language",
            "",
        )
    ).strip()

    scanned = to_bool(
        row.get(
            "likely_scanned"
        )
    )

    complex_layout = to_bool(
        row.get(
            "likely_complex_layout"
        )
    )

    form_fields = int(
        to_number(
            row.get(
                "form_field_count"
            )
        )
    )

    table_count = int(
        to_number(
            row.get(
                "table_like_count"
            )
        )
    )

    image_count = int(
        to_number(
            row.get(
                "image_count"
            )
        )
    )

    page_count = int(
        to_number(
            row.get(
                "page_count"
            )
        )
    )

    if has_tags:
        signals.append(
            "PDF tags detected"
        )
    else:
        signals.append(
            "No PDF tags detected"
        )

    if language:
        signals.append(
            f"Document language detected: {language}"
        )
    else:
        signals.append(
            "No document language detected"
        )

    if scanned:
        signals.append(
            "Document appears scanned or image-based"
        )

    if complex_layout:
        signals.append(
            "Complex layout indicators detected"
        )

    if form_fields > 0:
        signals.append(
            f"{form_fields} interactive form field(s) detected"
        )

    if table_count > 0:
        signals.append(
            f"{table_count} table-like structure(s) detected"
        )

    if image_count > 0:
        signals.append(
            f"{image_count} image(s) detected"
        )

    if page_count > 0:
        signals.append(
            f"{page_count}-page document"
        )

    return signals


# --------------------------------------------------
# STRUCTURAL GAP
# --------------------------------------------------

def has_known_structure_gap(row):

    has_tags = to_bool(
        row.get(
            "has_tags"
        )
    )

    language = str(
        row.get(
            "document_language",
            "",
        )
    ).strip()

    scanned = to_bool(
        row.get(
            "likely_scanned"
        )
    )

    return (
        not has_tags
        or not language
        or scanned
    )


# --------------------------------------------------
# EDITABLE SOURCE
# --------------------------------------------------

def editable_source_hint(row):

    source_hint = str(
        row.get(
            "source_application_hint",
            "Unknown",
        )
    ).strip()

    valid_sources = {
        "Microsoft Word",
        "Microsoft PowerPoint",
        "Adobe InDesign",
        "LaTeX",
    }

    if source_hint in valid_sources:
        return source_hint

    return ""


# --------------------------------------------------
# FAMILY SIGNAL
# --------------------------------------------------

def strong_family_signal(row):

    family_id = str(
        row.get(
            "family_id",
            "UNIQUE",
        )
    ).strip()

    family_size = int(
        to_number(
            row.get(
                "family_size"
            )
        )
    )

    family_confidence = normalize_confidence(
        row.get(
            "family_confidence",
            "Low",
        )
    )

    return (
        family_id != "UNIQUE"
        and family_size >= 2
        and family_confidence == "High"
    )


# --------------------------------------------------
# TRIAGE
# --------------------------------------------------

def determine_action(row):

    document_type = str(
        row.get(
            "document_type",
            "General Document",
        )
    ).strip()

    document_purpose = str(
        row.get(
            "document_purpose",
            "INFORM",
        )
    ).strip()

    purpose_confidence = normalize_confidence(
        row.get(
            "purpose_confidence",
            "Low",
        )
    )

    pdf_necessity = str(
        row.get(
            "pdf_necessity",
            "UNKNOWN",
        )
    ).strip().upper()

    necessity_confidence = normalize_confidence(
        row.get(
            "pdf_necessity_confidence",
            "Low",
        )
    )

    source_hint = editable_source_hint(
        row
    )

    scanned = to_bool(
        row.get(
            "likely_scanned"
        )
    )

    complex_layout = to_bool(
        row.get(
            "likely_complex_layout"
        )
    )

    form_fields = int(
        to_number(
            row.get(
                "form_field_count"
            )
        )
    )

    structure_gap = has_known_structure_gap(
        row
    )

    family_is_strong = strong_family_signal(
        row
    )

    family_size = int(
        to_number(
            row.get(
                "family_size"
            )
        )
    )

    accessibility_signals = (
        collect_accessibility_evidence(
            row
        )
    )

    # --------------------------------------------------
    # 1. EXTERNAL DOCUMENT
    # --------------------------------------------------

    if is_external_document(row):

        signals = [
            "PDF is hosted on a different domain from the source webpage",
            "Remediation ownership may belong to another organization",
        ]

        signals.extend(
            accessibility_signals
        )

        return (
            "External Owner Review",
            "Low",
            "High",
            "The PDF appears to be externally hosted, so remediation ownership should be confirmed before work is assigned.",
            signals,
            "Confirm who owns the document and whether the external publisher should remediate, replace, or provide an accessible alternative.",
        )

    # --------------------------------------------------
    # 2. MAPS / SPATIAL INFORMATION
    # --------------------------------------------------

    if document_purpose == "PROVIDE_DIRECTIONS":

        signals = [
            "Primary purpose is providing directions or spatial information",
            "Equivalent non-visual navigation cannot be verified automatically",
        ]

        signals.extend(
            accessibility_signals
        )

        return (
            "Specialist Review",
            "High",
            "High",
            "Maps and spatial information require human judgment to determine whether an equivalent accessible experience is available.",
            signals,
            "Verify that equivalent textual directions or another accessible navigation method communicates the same essential information.",
        )

    # --------------------------------------------------
    # 3. DATA-COLLECTION / FORM WORKFLOW
    # --------------------------------------------------

    if document_purpose == "COLLECT_INFORMATION":

        # Complex forms should not be automatically routed.
        if complex_layout:

            signals = [
                "Primary purpose is collecting or submitting information",
                "Complex layout indicators were detected",
                "The interaction requires manual evaluation",
            ]

            if form_fields > 0:
                signals.append(
                    f"{form_fields} interactive form field(s) detected"
                )

            signals.extend(
                accessibility_signals
            )

            return (
                "Specialist Review",
                "High",
                "High",
                "The document represents a data-entry workflow with enough structural complexity that automation should not decide between web conversion and PDF remediation.",
                signals,
                "Review the workflow, field labels, instructions, focus order, keyboard behavior, validation, and any requirement to preserve the PDF format.",
            )

        # Scanned forms require human review because the actual
        # controls/workflow cannot be reliably inspected.
        if scanned:

            signals = [
                "Primary purpose is collecting or submitting information",
                "Document appears scanned or image-based",
                "The form workflow cannot be reliably evaluated automatically",
            ]

            signals.extend(
                accessibility_signals
            )

            return (
                "Specialist Review",
                "High",
                "High",
                "The document appears to be a scanned form or data-collection document, so its interaction and remediation path require manual review.",
                signals,
                "Determine whether the workflow should become an accessible web form or whether an accessible PDF form must be created.",
            )

        # A strong data-collection purpose is enough to make the
        # document a WEB FORM CANDIDATE.
        #
        # We are not claiming replacement is mandatory.
        if purpose_confidence in {
            "High",
            "Medium",
        }:

            signals = [
                "Primary purpose is collecting or submitting user information",
                "The workflow is a strong candidate for accessible web interaction",
            ]

            if form_fields > 0:
                signals.append(
                    "Interactive PDF fields confirm a data-entry workflow"
                )

            if pdf_necessity == "UNKNOWN":
                signals.append(
                    "No fixed-PDF requirement has been established automatically"
                )

            signals.extend(
                accessibility_signals
            )

            return (
                "Convert to Web Form",
                "High",
                purpose_confidence,
                "The document appears to represent a user data-entry workflow, making it a strong candidate for an accessible web form unless a fixed-PDF requirement must be preserved.",
                signals,
                "Evaluate rebuilding the workflow as accessible HTML with labels, instructions, keyboard access, validation, and accessible error handling. Confirm any legal, signature, archival, or operational reason the PDF must remain.",
            )

    # --------------------------------------------------
    # 4. EVENT / PROMOTIONAL INFORMATION
    # --------------------------------------------------

    if (
        document_purpose == "PROMOTE_EVENT"
        and purpose_confidence in {
            "High",
            "Medium",
        }
    ):

        signals = [
            "Primary purpose is event or promotional information",
            "The information is naturally suited to web publication",
        ]

        signals.extend(
            accessibility_signals
        )

        return (
            "Convert to HTML",
            "Medium",
            purpose_confidence,
            "The PDF primarily communicates event or promotional information that can usually be delivered directly as accessible web content.",
            signals,
            "Publish the event information as accessible HTML. Retain a downloadable flyer only if there is a separate need for one.",
        )

    # --------------------------------------------------
    # 5. OTHER STRONG INFORMATIONAL HTML CANDIDATES
    # --------------------------------------------------

    if (
        document_purpose == "INFORM"
        and pdf_necessity == "LOW"
        and purpose_confidence in {
            "High",
            "Medium",
        }
    ):

        signals = [
            "Primary purpose is informational",
            "No strong fixed-PDF requirement was identified",
        ]

        signals.extend(
            accessibility_signals
        )

        return (
            "Convert to HTML",
            "Medium",
            "Medium",
            "The document appears primarily intended to communicate information on the web and no strong fixed-document requirement was identified.",
            signals,
            "Evaluate publishing this information as accessible HTML rather than maintaining it only as a PDF.",
        )

    # --------------------------------------------------
    # 6. LOW-CONFIDENCE INFORMATION
    # --------------------------------------------------

    if (
        document_purpose == "INFORM"
        and purpose_confidence == "Low"
    ):

        signals = [
            "Document appears informational",
            "Purpose classification confidence is low",
            "More document understanding is needed before conversion is recommended",
        ]

        signals.extend(
            accessibility_signals
        )

        return (
            "Keep / Review",
            "Low",
            "Low",
            "The available metadata suggests informational content but is not strong enough to justify automatic HTML conversion.",
            signals,
            "Review the document's actual purpose. If it is ordinary web information, consider publishing it as HTML.",
        )

    # --------------------------------------------------
    # 7. UNKNOWN PDF NECESSITY FOR NON-FORM CONTENT
    # --------------------------------------------------

    if pdf_necessity == "UNKNOWN":

        signals = [
            f"Primary purpose: {document_purpose}",
            "Whether the PDF format is required could not be determined automatically",
        ]

        if source_hint:
            signals.append(
                f"Likely editable source: {source_hint}"
            )

        signals.extend(
            accessibility_signals
        )

        if structure_gap:

            return (
                "Specialist Review",
                "Medium",
                "Medium",
                "Accessibility issues are present, but the system cannot determine whether this content should remain a PDF.",
                signals,
                "Confirm the document's business or official format requirements, then choose HTML conversion, source repair, or direct PDF remediation.",
            )

        return (
            "Keep / Review",
            "Low",
            "Medium",
            "The PDF format may or may not be necessary and no strong automated remediation signal was established.",
            signals,
            "Review whether the PDF serves a required fixed-document purpose before assigning remediation work.",
        )

    # --------------------------------------------------
    # 8. PDF SHOULD REMAIN + EDITABLE SOURCE
    # --------------------------------------------------

    if (
        pdf_necessity in {
            "HIGH",
            "MEDIUM",
        }
        and source_hint
        and structure_gap
    ):

        signals = [
            f"PDF necessity: {pdf_necessity}",
            f"Likely editable source application: {source_hint}",
            "A known structural accessibility gap was detected",
        ]

        if family_is_strong:

            signals.append(
                f"Part of a high-confidence family of {family_size} similar PDFs"
            )

            signals.append(
                "A shared source/template correction may improve multiple documents"
            )

        signals.extend(
            accessibility_signals
        )

        return (
            "Fix Source & Re-export",
            "High" if family_is_strong else "Medium",
            "High" if family_is_strong else "Medium",
            "The document appears to have value as a PDF, and an editable source provides a better place to correct structural accessibility problems.",
            signals,
            f"Locate the original {source_hint} file or template, correct accessibility there, export a new tagged PDF, and verify the resulting document.",
        )

    # --------------------------------------------------
    # 9. PDF SHOULD REMAIN + NO EDITABLE SOURCE
    # --------------------------------------------------

    if (
        pdf_necessity in {
            "HIGH",
            "MEDIUM",
        }
        and structure_gap
        and not source_hint
    ):

        # Highly complex direct remediation deserves specialist review.
        if complex_layout:

            signals = [
                f"PDF necessity: {pdf_necessity}",
                "No reliable editable source was identified",
                "Complex layout indicators were detected",
                "Structural accessibility issues are present",
            ]

            signals.extend(
                accessibility_signals
            )

            return (
                "Specialist Review",
                "High",
                "Medium",
                "The document appears worth preserving as a PDF but contains complex accessibility issues without a clear source-level repair path.",
                signals,
                "Have an accessibility specialist evaluate reading order, tags, tables, figures, alternative text, and the most appropriate remediation method.",
            )

        signals = [
            f"PDF necessity: {pdf_necessity}",
            "No reliable editable source application was identified",
            "A known structural accessibility gap was detected",
        ]

        signals.extend(
            accessibility_signals
        )

        return (
            "Remediate PDF",
            "Medium",
            "Medium",
            "The document appears to have value as a PDF, but no reliable source-level repair path was identified.",
            signals,
            "Remediate the PDF directly and manually verify tags, reading order, headings, lists, tables, alternative text, links, and document language as applicable.",
        )

    # --------------------------------------------------
    # 10. COMPLEX DOCUMENT
    # --------------------------------------------------

    if complex_layout:

        signals = [
            "Complex layout indicators were detected",
            "No stronger automated remediation path was established",
        ]

        signals.extend(
            accessibility_signals
        )

        return (
            "Specialist Review",
            "Medium",
            "Medium",
            "The document contains structural complexity that cannot be evaluated reliably from current automated evidence alone.",
            signals,
            "Review reading order, tables, figures, headings, alternative text, and overall semantic structure manually.",
        )

    # --------------------------------------------------
    # 11. PDF APPEARS APPROPRIATE
    # --------------------------------------------------

    if (
        pdf_necessity in {
            "HIGH",
            "MEDIUM",
        }
        and not structure_gap
    ):

        signals = [
            f"PDF necessity: {pdf_necessity}",
            "No known structural accessibility gap was detected by the current analyzer",
        ]

        signals.extend(
            accessibility_signals
        )

        return (
            "Keep / Review",
            "Low",
            "Medium",
            "The document appears to have a legitimate fixed-document use and the current analyzer did not detect a strong remediation signal.",
            signals,
            "Keep the PDF provisionally and complete required manual accessibility checks before treating it as accessible.",
        )

    # --------------------------------------------------
    # 12. FALLBACK
    # --------------------------------------------------

    signals = [
        "No strong automated remediation pathway was established",
    ]

    signals.extend(
        accessibility_signals
    )

    return (
        "Keep / Review",
        "Low",
        "Low",
        "The available evidence is not strong enough to justify automatic conversion or remediation.",
        signals,
        "Review the document's purpose and remaining accessibility requirements before assigning remediation work.",
    )


# --------------------------------------------------
# PRIORITY
# --------------------------------------------------

def calculate_priority(
    row,
    action_priority,
):

    score = 0

    if action_priority == "High":
        score += 3

    elif action_priority == "Medium":
        score += 2

    else:
        score += 1

    if to_bool(
        row.get(
            "likely_scanned"
        )
    ):
        score += 2

    if (
        to_number(
            row.get(
                "form_field_count"
            )
        )
        > 0
    ):
        score += 1

    if has_known_structure_gap(
        row
    ):
        score += 1

    if strong_family_signal(
        row
    ):
        score += 1

    document_purpose = str(
        row.get(
            "document_purpose",
            "",
        )
    )

    if document_purpose in {
        "COLLECT_INFORMATION",
        "PROVIDE_DIRECTIONS",
    }:
        score += 1

    if score >= 6:
        return "High"

    if score >= 3:
        return "Medium"

    return "Low"


# --------------------------------------------------
# LOAD CONTEXT
# --------------------------------------------------

def load_context_file(
    context_file,
):

    context_file = Path(
        context_file
    )

    if not context_file.exists():

        raise FileNotFoundError(
            "Document context file not found. "
            "Run document_context.py before triage_engine.py. "
            f"Expected: {context_file}"
        )

    return pd.read_csv(
        context_file
    )


# --------------------------------------------------
# RUN
# --------------------------------------------------

def run(
    analysis_file=DEFAULT_ANALYSIS_FILE,
    family_file=DEFAULT_FAMILY_FILE,
    output_file=DEFAULT_OUTPUT_FILE,
    context_file=DEFAULT_CONTEXT_FILE,
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

    context_file = Path(
        context_file
    )

    output_file.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    # --------------------------------------------------
    # ANALYSIS DATA
    # --------------------------------------------------

    analysis_df = pd.read_csv(
        analysis_file
    )

    analysis_df = analysis_df[
        analysis_df[
            "analysis_status"
        ]
        == "SUCCESS"
    ].copy()

    # --------------------------------------------------
    # CONTEXT DATA
    # --------------------------------------------------

    context_df = load_context_file(
        context_file
    )

    context_columns = [
        column
        for column in [
            "pdf_url",
            "document_type",
            "document_purpose",
            "purpose_confidence",
            "purpose_signals",
            "pdf_necessity",
            "pdf_necessity_confidence",
            "pdf_necessity_signals",
            "decision_basis",
        ]
        if column in context_df.columns
    ]

    if "pdf_url" not in context_columns:

        raise ValueError(
            "pdf_document_context.csv does not contain pdf_url."
        )

    context_subset = (
        context_df[
            context_columns
        ]
        .drop_duplicates(
            subset=["pdf_url"]
        )
        .copy()
    )

    merged = analysis_df.merge(
        context_subset,
        on="pdf_url",
        how="left",
    )

    # --------------------------------------------------
    # FAMILY DATA
    # --------------------------------------------------

    if family_file.exists():

        family_df = pd.read_csv(
            family_file
        )

    else:

        family_df = pd.DataFrame()

    family_columns = [
        "pdf_url",
        "family_id",
        "family_name",
        "family_size",
        "family_similarity",
        "family_confidence",
    ]

    if not family_df.empty:

        available = [
            column
            for column in family_columns
            if column in family_df.columns
        ]

        if "pdf_url" in available:

            family_subset = (
                family_df[
                    available
                ]
                .drop_duplicates(
                    subset=["pdf_url"]
                )
            )

            merged = merged.merge(
                family_subset,
                on="pdf_url",
                how="left",
            )

    # --------------------------------------------------
    # DEFAULT VALUES
    # --------------------------------------------------

    defaults = {
        "family_id": "UNIQUE",
        "family_name": "Unique / Unclassified",
        "family_size": 1,
        "family_similarity": 0,
        "family_confidence": "Low",
        "document_type": "General Document",
        "document_purpose": "INFORM",
        "purpose_confidence": "Low",
        "pdf_necessity": "UNKNOWN",
        "pdf_necessity_confidence": "Low",
    }

    for column, default in defaults.items():

        if column not in merged.columns:
            merged[column] = default

        else:
            merged[column] = (
                merged[column]
                .fillna(default)
            )

    # --------------------------------------------------
    # TRIAGE
    # --------------------------------------------------

    results = []

    for _, row in merged.iterrows():

        (
            action,
            action_priority,
            recommendation_confidence,
            reason,
            signals,
            next_step,
        ) = determine_action(
            row
        )

        final_priority = (
            calculate_priority(
                row,
                action_priority,
            )
        )

        result = row.to_dict()

        result[
            "recommended_action"
        ] = action

        result[
            "priority"
        ] = final_priority

        result[
            "recommendation_confidence"
        ] = recommendation_confidence

        result[
            "recommendation_reason"
        ] = reason

        result[
            "recommendation_signals"
        ] = signal_list_to_json(
            signals
        )

        result[
            "recommended_next_step"
        ] = next_step

        results.append(
            result
        )

    output_df = pd.DataFrame(
        results
    )

    output_df.to_csv(
        output_file,
        index=False,
    )

    return output_df


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
        "MARIS TRIAGE ENGINE COMPLETE"
    )
    print(
        "========================================"
    )

    print(
        f"Documents processed: {len(result_df)}"
    )

    print()
    print(
        "Recommended actions:"
    )

    print(
        result_df[
            "recommended_action"
        ]
        .value_counts()
        .to_string()
    )

    print()
    print(
        "Priorities:"
    )

    print(
        result_df[
            "priority"
        ]
        .value_counts()
        .to_string()
    )

    print()
    print(
        "Recommendation confidence:"
    )

    print(
        result_df[
            "recommendation_confidence"
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