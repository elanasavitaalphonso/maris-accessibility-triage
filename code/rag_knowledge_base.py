from pathlib import Path
import json
import math
import re

import numpy as np
from sentence_transformers import SentenceTransformer


# ============================================================
# PATHS
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent
RAG_DIR = BASE_DIR / "rag"

KNOWLEDGE_FILE = RAG_DIR / "maris_accessibility_knowledge.json"
EMBEDDINGS_FILE = RAG_DIR / "maris_accessibility_embeddings.npy"


# ============================================================
# MODEL
# ============================================================

EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"


# ============================================================
# AUTHORITATIVE KNOWLEDGE BASE
# ============================================================
#
# IMPORTANT:
# These are concise paraphrased knowledge chunks, not long copied
# passages. Each chunk keeps its authoritative source URL so later
# Maris can show provenance.
#
# We are starting small on purpose. RAG quality depends more on
# curated relevant chunks than dumping entire standards into a
# vector database.
# ============================================================

KNOWLEDGE_CHUNKS = [

    # --------------------------------------------------------
    # HTML / PDF FORMAT CHOICE
    # --------------------------------------------------------

    {
        "id": "digitalgov-html-first-001",
        "source_name": "Digital.gov",
        "source_type": "Federal web publishing guidance",
        "source_url": (
            "https://digital.gov/2024/12/31/"
            "reduce-remove-remediate-pdfs-and-government-websites"
        ),
        "topics": [
            "html",
            "pdf necessity",
            "informational content",
            "web publishing",
        ],
        "text": (
            "For information primarily intended to be consumed on the web, "
            "organizations should consider reducing reliance on PDFs and "
            "publishing content in accessible HTML when practical. PDF should "
            "be retained when the fixed or downloadable format provides a "
            "meaningful purpose, such as printing, offline use, preservation, "
            "or another legitimate document-format need."
        ),
    },

    {
        "id": "digitalgov-reduce-remove-remediate-002",
        "source_name": "Digital.gov",
        "source_type": "Federal web publishing guidance",
        "source_url": (
            "https://digital.gov/2024/12/31/"
            "reduce-remove-remediate-pdfs-and-government-websites"
        ),
        "topics": [
            "pdf backlog",
            "remediation planning",
            "archive",
            "remove",
        ],
        "text": (
            "PDF accessibility management is not limited to remediating every "
            "file. Organizations can reduce the PDF inventory, remove obsolete "
            "content, improve publishing practices, and remediate documents "
            "that still need to remain available."
        ),
    },

    # --------------------------------------------------------
    # SECTION 508 PDF GUIDANCE
    # --------------------------------------------------------

    {
        "id": "section508-accessible-pdf-001",
        "source_name": "Section508.gov",
        "source_type": "Federal Section 508 guidance",
        "source_url": "https://www.section508.gov/create/pdfs/",
        "topics": [
            "pdf remediation",
            "section 508",
            "accessible pdf",
        ],
        "text": (
            "PDF is an acceptable electronic document format when the document "
            "is created and tested for accessibility. Section 508 guidance "
            "provides processes for creating and remediating accessible PDFs "
            "rather than treating PDF itself as inherently prohibited."
        ),
    },

    {
        "id": "section508-source-authoring-002",
        "source_name": "Section508.gov",
        "source_type": "Federal Section 508 guidance",
        "source_url": "https://www.section508.gov/create/documents/",
        "topics": [
            "fix source",
            "re-export",
            "word",
            "authoring",
            "semantic structure",
        ],
        "text": (
            "Accessibility should be built into the original authoring "
            "document where possible. Correct heading structure, lists, tables, "
            "alternative text, and related document semantics in the editable "
            "source before creating the final electronic document."
        ),
    },

    {
        "id": "section508-pdf-testing-003",
        "source_name": "Section508.gov",
        "source_type": "Federal Section 508 testing guidance",
        "source_url": (
            "https://www.section508.gov/training/pdfs/aed-cop-pdf02/"
        ),
        "topics": [
            "manual testing",
            "automated testing",
            "pdf review",
            "specialist review",
        ],
        "text": (
            "Automated accessibility checking is only part of PDF evaluation. "
            "Document properties, content structure, and accessibility features "
            "must also be examined. Human testing remains important where "
            "automated tools cannot determine whether document meaning and "
            "navigation are correct."
        ),
    },

    # --------------------------------------------------------
    # WCAG / PDF STRUCTURE
    # --------------------------------------------------------

    {
        "id": "wcag-reading-order-001",
        "source_name": "W3C",
        "source_type": "WCAG 2.2 PDF Technique",
        "source_url": (
            "https://www.w3.org/WAI/WCAG22/Techniques/pdf/PDF3"
        ),
        "topics": [
            "reading order",
            "semantic sequence",
            "specialist review",
        ],
        "text": (
            "PDF content should have a logical reading and tab order that is "
            "consistent with the meaning of the document. Visual layout alone "
            "does not establish an accessible reading sequence, so complicated "
            "layouts may require manual verification."
        ),
    },

    {
        "id": "wcag-pdf-forms-002",
        "source_name": "W3C",
        "source_type": "WCAG 2.2 PDF Technique",
        "source_url": (
            "https://www.w3.org/WAI/WCAG22/Techniques/pdf/PDF23"
        ),
        "topics": [
            "forms",
            "keyboard",
            "interactive pdf",
            "web form",
        ],
        "text": (
            "Interactive PDF form controls must support accessible operation, "
            "including keyboard interaction. Form fields require appropriate "
            "programmatic structure and should be tested as an interaction "
            "workflow, not evaluated only by their visual appearance."
        ),
    },

    {
        "id": "wcag-pdf-tables-003",
        "source_name": "W3C",
        "source_type": "WCAG 2.2 PDF Technique",
        "source_url": (
            "https://www.w3.org/WAI/WCAG22/Techniques/pdf/PDF6"
        ),
        "topics": [
            "tables",
            "table semantics",
            "complex document",
        ],
        "text": (
            "Data tables in PDF need semantic table markup so relationships "
            "between headers and cells can be understood by assistive "
            "technology. Complex tables may require manual verification because "
            "visual rows and columns do not prove correct programmatic structure."
        ),
    },

    {
        "id": "wcag-pdf-lists-004",
        "source_name": "W3C",
        "source_type": "WCAG 2.2 PDF Technique",
        "source_url": (
            "https://www.w3.org/WAI/WCAG22/Techniques/pdf/PDF21"
        ),
        "topics": [
            "lists",
            "semantic structure",
            "tags",
        ],
        "text": (
            "Lists in tagged PDF should use appropriate list structure rather "
            "than relying only on visual bullets or indentation. Semantic "
            "structure is part of making document relationships available to "
            "assistive technology."
        ),
    },

    {
        "id": "wcag-pdf-title-005",
        "source_name": "W3C",
        "source_type": "WCAG 2.2 PDF Technique",
        "source_url": (
            "https://www.w3.org/WAI/WCAG22/Techniques/pdf/PDF18"
        ),
        "topics": [
            "document title",
            "metadata",
            "pdf properties",
        ],
        "text": (
            "PDF documents should provide a descriptive document title through "
            "the PDF title metadata so assistive technologies and users can "
            "identify the document meaningfully."
        ),
    },

    # --------------------------------------------------------
    # WCAG PRINCIPLES
    # --------------------------------------------------------

    {
        "id": "wcag-non-text-001",
        "source_name": "W3C",
        "source_type": "WCAG 2.2",
        "source_url": "https://www.w3.org/TR/WCAG22/",
        "topics": [
            "images",
            "maps",
            "charts",
            "alt text",
            "non-text content",
        ],
        "text": (
            "Meaningful non-text content must have a text alternative that "
            "serves an equivalent purpose. For complex graphics such as maps, "
            "charts, and diagrams, a short image label may not be sufficient; "
            "the essential information conveyed visually must be available in "
            "an accessible form."
        ),
    },

    {
        "id": "wcag-info-relationships-002",
        "source_name": "W3C",
        "source_type": "WCAG 2.2",
        "source_url": "https://www.w3.org/TR/WCAG22/",
        "topics": [
            "headings",
            "structure",
            "relationships",
            "semantic markup",
        ],
        "text": (
            "Information, structure, and relationships that are communicated "
            "through visual presentation should also be programmatically "
            "determinable or available in text. This includes relationships "
            "such as headings, lists, labels, and table structure."
        ),
    },

    # --------------------------------------------------------
    # MAPS / SPATIAL CONTENT
    # --------------------------------------------------------

    {
        "id": "maps-specialist-001",
        "source_name": "W3C",
        "source_type": "WCAG-derived decision guidance",
        "source_url": "https://www.w3.org/TR/WCAG22/",
        "topics": [
            "maps",
            "directions",
            "spatial navigation",
            "specialist review",
        ],
        "text": (
            "Maps and other spatial graphics carry meaning through visual "
            "relationships. An accessibility review should determine whether "
            "equivalent textual directions, location information, or another "
            "accessible alternative communicates the essential spatial content. "
            "Automated image counts cannot determine this equivalence."
        ),
    },

    # --------------------------------------------------------
    # FORMS / WORKFLOWS
    # --------------------------------------------------------

    {
        "id": "forms-web-candidate-001",
        "source_name": "W3C",
        "source_type": "WCAG form guidance",
        "source_url": "https://www.w3.org/WAI/tutorials/forms/",
        "topics": [
            "web form",
            "labels",
            "instructions",
            "validation",
            "data collection",
        ],
        "text": (
            "Accessible web forms support programmatic labels, clear "
            "instructions, keyboard interaction, understandable validation, and "
            "accessible error feedback. A PDF whose main purpose is collecting "
            "user information may be a candidate for a web form when the "
            "business workflow can reasonably be implemented online."
        ),
    },

    {
        "id": "forms-signature-review-002",
        "source_name": "Maris Decision Matrix",
        "source_type": "Project decision rule derived from accessibility guidance",
        "source_url": "",
        "topics": [
            "signature",
            "attestation",
            "staff workflow",
            "specialist review",
            "web form",
        ],
        "text": (
            "When a form includes signatures, attestations, internal staff "
            "sections, approval steps, eligibility decisions, or other official "
            "workflow requirements, Maris should not automatically replace the "
            "PDF with a web form. Human confirmation is needed to determine "
            "whether those workflow requirements can be implemented accessibly "
            "online."
        ),
    },

    # --------------------------------------------------------
    # FORMAL PUBLICATIONS / RECORDS
    # --------------------------------------------------------

    {
        "id": "formal-publication-001",
        "source_name": "Maris Decision Matrix",
        "source_type": "Project decision rule informed by federal guidance",
        "source_url": (
            "https://www.section508.gov/create/pdfs/"
        ),
        "topics": [
            "formal publication",
            "catalog",
            "annual report",
            "strategic plan",
            "pdf necessity",
        ],
        "text": (
            "Formal publications such as catalogs, annual reports, strategic "
            "plans, and similar institutional publications may have meaningful "
            "download, print, archival, or fixed-layout value. Their publication "
            "status alone does not prove that PDF is required, but it is stronger "
            "evidence for retaining an accessible PDF than ordinary web content."
        ),
    },

    {
        "id": "official-record-001",
        "source_name": "Maris Decision Matrix",
        "source_type": "Project decision rule",
        "source_url": "",
        "topics": [
            "official record",
            "meeting minutes",
            "record retention",
            "keep review",
        ],
        "text": (
            "When a document serves as an institutional or official record, "
            "stable representation and retention may matter. Maris should avoid "
            "automatically recommending HTML replacement solely because the "
            "document contains readable informational text. Accessibility of the "
            "retained record still needs to be evaluated."
        ),
    },

    # --------------------------------------------------------
    # SOURCE REMEDIATION
    # --------------------------------------------------------

    {
        "id": "fix-source-001",
        "source_name": "Section508.gov",
        "source_type": "Federal document authoring guidance",
        "source_url": "https://www.section508.gov/create/documents/",
        "topics": [
            "fix source",
            "re-export",
            "word",
            "indesign",
            "powerpoint",
            "template",
        ],
        "text": (
            "When an editable authoring source is available, accessibility "
            "problems involving headings, lists, tables, alternative text, and "
            "other semantic structure are generally better corrected in the "
            "source document before generating a new accessible PDF."
        ),
    },

    # --------------------------------------------------------
    # DIRECT PDF REMEDIATION
    # --------------------------------------------------------

    {
        "id": "remediate-pdf-001",
        "source_name": "Section508.gov",
        "source_type": "Federal PDF remediation guidance",
        "source_url": (
            "https://www.section508.gov/training/pdfs/aed-cop-pdf00/"
        ),
        "topics": [
            "remediate pdf",
            "acrobat",
            "tags",
            "source unavailable",
        ],
        "text": (
            "Existing PDFs can be remediated directly when they need to remain "
            "available and rebuilding from an editable source is not practical. "
            "Direct remediation may include correcting tags and other document "
            "structure, followed by accessibility testing."
        ),
    },

    # --------------------------------------------------------
    # HUMAN REVIEW
    # --------------------------------------------------------

    {
        "id": "human-review-001",
        "source_name": "Section508.gov",
        "source_type": "Federal testing guidance",
        "source_url": (
            "https://www.section508.gov/test/testing-overview/"
        ),
        "topics": [
            "human review",
            "manual testing",
            "uncertainty",
            "cannot tell",
        ],
        "text": (
            "Accessibility evaluation may require automated, manual, or hybrid "
            "testing. When automated evidence cannot establish whether content "
            "meaning, interaction, or semantic relationships are accessible, "
            "the appropriate result is human review rather than an unsupported "
            "claim of conformance."
        ),
    },

    # --------------------------------------------------------
    # ACCESS BOARD
    # --------------------------------------------------------

    {
        "id": "access-board-electronic-documents-001",
        "source_name": "U.S. Access Board",
        "source_type": "Revised Section 508 Standards",
        "source_url": "https://www.access-board.gov/ict/about/",
        "topics": [
            "section 508",
            "electronic documents",
            "ict",
            "legal framework",
        ],
        "text": (
            "The Revised Section 508 Standards address accessibility of "
            "information and communication technology, including electronic "
            "documents. Accessibility requirements are based on the functions "
            "and content being provided rather than treating a particular file "
            "format as automatically compliant or noncompliant."
        ),
    },

    {
        "id": "access-board-testing-baseline-002",
        "source_name": "U.S. Access Board",
        "source_type": "ICT Testing Baseline guidance",
        "source_url": (
            "https://www.access-board.gov/news/2024/09/30/"
            "new-ict-testing-baseline-for-documents-released/"
        ),
        "topics": [
            "testing baseline",
            "electronic documents",
            "section 508",
            "manual testing",
        ],
        "text": (
            "The ICT Testing Baseline for Documents establishes minimum testing "
            "and evaluation guidance for determining whether non-web electronic "
            "documents meet applicable Section 508 requirements. This supports "
            "a structured testing process rather than relying on a single "
            "automated accessibility score."
        ),
    },
]


# ============================================================
# HELPERS
# ============================================================

def normalize_text(value):

    value = str(value or "").lower()

    value = re.sub(
        r"\s+",
        " ",
        value,
    )

    return value.strip()


def build_embedding_text(chunk):

    topics = " ".join(
        chunk.get(
            "topics",
            [],
        )
    )

    return (
        f"{topics}. "
        f"{chunk['text']}"
    )


# ============================================================
# BUILD KNOWLEDGE FILE
# ============================================================

def build_knowledge_base():

    RAG_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    with open(
        KNOWLEDGE_FILE,
        "w",
        encoding="utf-8",
    ) as file:

        json.dump(
            KNOWLEDGE_CHUNKS,
            file,
            indent=2,
            ensure_ascii=False,
        )

    print(
        f"Knowledge base saved to:\n"
        f"{KNOWLEDGE_FILE}"
    )


# ============================================================
# BUILD EMBEDDINGS
# ============================================================

def build_embeddings():

    model = SentenceTransformer(
        EMBEDDING_MODEL_NAME
    )

    texts = [
        build_embedding_text(
            chunk
        )
        for chunk in KNOWLEDGE_CHUNKS
    ]

    embeddings = model.encode(
        texts,
        normalize_embeddings=True,
        show_progress_bar=True,
    )

    np.save(
        EMBEDDINGS_FILE,
        embeddings,
    )

    print()

    print(
        f"Embeddings saved to:\n"
        f"{EMBEDDINGS_FILE}"
    )


# ============================================================
# LOAD
# ============================================================

def load_knowledge_base():

    if not KNOWLEDGE_FILE.exists():

        raise FileNotFoundError(
            "Knowledge base does not exist. "
            "Run rag_knowledge_base.py first."
        )

    if not EMBEDDINGS_FILE.exists():

        raise FileNotFoundError(
            "Knowledge embeddings do not exist. "
            "Run rag_knowledge_base.py first."
        )

    with open(
        KNOWLEDGE_FILE,
        "r",
        encoding="utf-8",
    ) as file:

        chunks = json.load(
            file
        )

    embeddings = np.load(
        EMBEDDINGS_FILE
    )

    return (
        chunks,
        embeddings,
    )


# ============================================================
# RETRIEVE
# ============================================================

def retrieve(
    query,
    top_k=5,
):

    chunks, embeddings = (
        load_knowledge_base()
    )

    model = SentenceTransformer(
        EMBEDDING_MODEL_NAME
    )

    query_embedding = model.encode(
        [query],
        normalize_embeddings=True,
    )[0]

    scores = np.dot(
        embeddings,
        query_embedding,
    )

    ranked_indexes = np.argsort(
        scores
    )[::-1]

    results = []

    for index in ranked_indexes[
        :top_k
    ]:

        chunk = dict(
            chunks[index]
        )

        chunk[
            "similarity_score"
        ] = float(
            scores[index]
        )

        results.append(
            chunk
        )

    return results


# ============================================================
# QUICK TEST
# ============================================================

def test_retrieval():

    queries = [

        (
            "A PDF form collects applicant information, "
            "requires signatures and staff eligibility review."
        ),

        (
            "An institutional committee meeting minutes PDF "
            "serves as an official record."
        ),

        (
            "A public event flyer contains information that "
            "could be published on a webpage."
        ),

        (
            "A campus map contains spatial directions and "
            "parking information."
        ),

        (
            "A formal academic catalog should remain "
            "downloadable but has accessibility problems."
        ),
    ]

    print()

    print(
        "========================================"
    )

    print(
        "MARIS RAG RETRIEVAL TEST"
    )

    print(
        "========================================"
    )

    for query in queries:

        print()
        print(
            "QUERY:"
        )
        print(
            query
        )

        print()

        results = retrieve(
            query,
            top_k=3,
        )

        for position, result in enumerate(
            results,
            start=1,
        ):

            score = result[
                "similarity_score"
            ]

            print(
                f"{position}. "
                f"{result['id']} "
                f"({score:.3f})"
            )

            print(
                f"   Source: "
                f"{result['source_name']}"
            )

            print(
                f"   {result['text']}"
            )

            print()


# ============================================================
# CLI
# ============================================================

if __name__ == "__main__":

    print()

    print(
        "========================================"
    )

    print(
        "BUILDING MARIS RAG KNOWLEDGE BASE"
    )

    print(
        "========================================"
    )

    print(
        f"Chunks: {len(KNOWLEDGE_CHUNKS)}"
    )

    print(
        f"Embedding model: "
        f"{EMBEDDING_MODEL_NAME}"
    )

    print()

    build_knowledge_base()

    print()

    build_embeddings()

    test_retrieval()

    print()

    print(
        "========================================"
    )

    print(
        "RAG KNOWLEDGE BASE COMPLETE"
    )

    print(
        "========================================"
    )