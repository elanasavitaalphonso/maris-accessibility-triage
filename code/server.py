from pathlib import Path
from datetime import datetime
import threading
import uuid
import os

import pandas as pd

from dotenv import load_dotenv

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel


# ============================================================
# PATHS
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent

FRONTEND_DIR = BASE_DIR / "frontend"
INDEX_FILE = FRONTEND_DIR / "index.html"

MAX_CRAWL_PAGES = 400


# ============================================================
# ENVIRONMENT
# ============================================================

# Load the project-level .env file explicitly.
#
# This works even when FastAPI is started from:
#
#     pdf-accessibility-triage/code
#
# using:
#
#     fastapi dev server.py
#
load_dotenv(
    BASE_DIR / ".env"
)


# ============================================================
# MARIS MODULES
# ============================================================

import storage_manager


# ============================================================
# FASTAPI
# ============================================================

app = FastAPI(
    title="Maris",
    description=(
        "PDF accessibility remediation planning API"
    ),
)


if FRONTEND_DIR.exists():

    app.mount(
        "/static",
        StaticFiles(
            directory=FRONTEND_DIR
        ),
        name="static",
    )


# ============================================================
# REQUEST MODELS
# ============================================================

class ScanRequest(BaseModel):
    url: str


# ============================================================
# IN-MEMORY JOB STORE
# ============================================================

jobs = {}

jobs_lock = threading.Lock()

stop_events = {}


def update_job(
    job_id,
    **values,
):

    with jobs_lock:

        if job_id not in jobs:
            return

        jobs[job_id].update(
            values
        )


def get_job(
    job_id,
):

    with jobs_lock:

        if job_id not in jobs:
            return None

        return dict(
            jobs[job_id]
        )


# ============================================================
# RUN PATHS
# ============================================================

def get_job_run_paths(
    job,
):

    return (
        storage_manager
        .get_run_paths(
            Path(
                job[
                    "run_dir"
                ]
            )
        )
    )


# ============================================================
# FINAL RESULT MERGING
# ============================================================

def build_final_results(
    job,
):

    # Lazy-load the RAG module only when final results are assembled.
    # This keeps Render startup fast and avoids loading the ML stack
    # before it is actually needed.
    import ai_triage_advisor

    """
    Combine:

        rule-based triage
        +
        AI document understanding
        +
        RAG triage

    into ONE final result table.

    The frontend only sees this final table.
    """

    paths = (
        get_job_run_paths(
            job
        )
    )


    if not paths[
        "triage"
    ].exists():

        return pd.DataFrame()


    base_df = pd.read_csv(
        paths[
            "triage"
        ]
    )


    if base_df.empty:

        return base_df


    # ========================================================
    # AI DOCUMENT UNDERSTANDING
    # ========================================================

    try:

        ai_context = (
            storage_manager
            .load_ai_context_cache()
        )

    except Exception:

        ai_context = (
            pd.DataFrame()
        )


    if (
        not ai_context.empty
        and
        "pdf_url"
        in ai_context.columns
    ):

        ai_columns = [
            column
            for column
            in ai_context.columns
            if (
                column == "pdf_url"
                or
                column.startswith(
                    "ai_"
                )
            )
        ]


        ai_context = (
            ai_context[
                ai_columns
            ]
            .drop_duplicates(
                subset=[
                    "pdf_url"
                ],
                keep="last",
            )
        )


        base_df = (
            base_df.merge(
                ai_context,
                on="pdf_url",
                how="left",
            )
        )


    # ========================================================
    # RAG FINAL TRIAGE
    # ========================================================

    try:

        rag_cache = (
            ai_triage_advisor
            .load_rag_cache()
        )

    except Exception:

        rag_cache = (
            pd.DataFrame()
        )


    if (
        not rag_cache.empty
        and
        "pdf_url"
        in rag_cache.columns
    ):

        # Keep RAG-specific fields while avoiding duplicate
        # copies of filename, document_type, etc.
        rag_columns = [
            column
            for column
            in rag_cache.columns
            if (
                column == "pdf_url"
                or
                column.startswith(
                    "rag_"
                )
                or
                column
                in {
                    "retrieved_guidance",
                    "retrieved_guidance_sources",
                    "guidance_sources",
                    "human_review_required",
                    "human_review_reason",
                    "alternative_action",
                    "alternative_reason",
                }
            )
        ]


        rag_cache = (
            rag_cache[
                rag_columns
            ]
            .drop_duplicates(
                subset=[
                    "pdf_url"
                ],
                keep="last",
            )
        )


        base_df = (
            base_df.merge(
                rag_cache,
                on="pdf_url",
                how="left",
            )
        )


    # ========================================================
    # FINAL RECOMMENDED ACTION
    # ========================================================

    if (
        "rag_action"
        in base_df.columns
    ):

        base_df[
            "final_recommended_action"
        ] = (
            base_df[
                "rag_action"
            ]
            .replace(
                "",
                pd.NA,
            )
            .fillna(
                base_df[
                    "recommended_action"
                ]
            )
        )

    else:

        base_df[
            "final_recommended_action"
        ] = (
            base_df[
                "recommended_action"
            ]
        )


    # ========================================================
    # FINAL PRIORITY
    # ========================================================

    if (
        "rag_priority"
        in base_df.columns
    ):

        base_df[
            "final_priority"
        ] = (
            base_df[
                "rag_priority"
            ]
            .replace(
                "",
                pd.NA,
            )
            .fillna(
                base_df[
                    "priority"
                ]
            )
        )

    else:

        base_df[
            "final_priority"
        ] = (
            base_df[
                "priority"
            ]
        )


    # ========================================================
    # FINAL CONFIDENCE
    # ========================================================

    if (
        "rag_confidence"
        in base_df.columns
    ):

        base_df[
            "final_confidence"
        ] = (
            base_df[
                "rag_confidence"
            ]
            .replace(
                "",
                pd.NA,
            )
            .fillna(
                base_df[
                    "recommendation_confidence"
                ]
            )
        )

    else:

        base_df[
            "final_confidence"
        ] = (
            base_df[
                "recommendation_confidence"
            ]
        )


    # ========================================================
    # FINAL REASON
    # ========================================================

    if (
        "rag_decision_reason"
        in base_df.columns
    ):

        base_df[
            "final_reason"
        ] = (
            base_df[
                "rag_decision_reason"
            ]
            .replace(
                "",
                pd.NA,
            )
            .fillna(
                base_df[
                    "recommendation_reason"
                ]
            )
        )

    else:

        base_df[
            "final_reason"
        ] = (
            base_df[
                "recommendation_reason"
            ]
        )


    return base_df.fillna(
        ""
    )


# ============================================================
# MAIN MARIS PIPELINE
# ============================================================

def run_scan_pipeline(
    job_id,
    url,
    stop_event,
):

    # Immediately mark the job as active so the UI does not remain
    # stuck at "queued" while modules initialize on Render.
    update_job(
        job_id,
        status="running",
        stage="starting",
        stage_label="Starting scan engine",
        progress=1,
        current_document="",
    )

    # Load only the core scan modules first.
    # AI / RAG modules are intentionally delayed until later stages.
    import crawler
    import pdf_analyzer
    import family_detector
    import document_context
    import triage_engine

    job = get_job(
        job_id
    )


    if not job:
        return


    run_id = (
        job[
            "run_id"
        ]
    )


    run_dir = Path(
        job[
            "run_dir"
        ]
    )


    paths = (
        storage_manager
        .get_run_paths(
            run_dir
        )
    )


    started_at = (
        datetime.now()
        .isoformat()
    )


    try:

        # ====================================================
        # RUN METADATA
        # ====================================================

        storage_manager.save_run_metadata(
            run_dir,
            {
                "run_id":
                    run_id,

                "job_id":
                    job_id,

                "url":
                    url,

                "status":
                    "running",

                "started_at":
                    started_at,

                "max_pages":
                    MAX_CRAWL_PAGES,
            },
        )


        # ====================================================
        # 1. DISCOVER PDFs
        # ====================================================

        update_job(
            job_id,
            status="running",
            stage="discovering",
            stage_label=(
                "Discovering PDFs"
            ),
            progress=5,
            stop_requested=False,
            current_document="",
        )


        def crawl_progress(
            pages,
            pdfs,
        ):

            update_job(
                job_id,
                pages_visited=pages,
                pdfs_found=pdfs,
            )


        crawl_stats = crawler.run(
            start_url=url,

            output_file=paths[
                "inventory"
            ],

            max_pages=(
                MAX_CRAWL_PAGES
            ),

            on_progress=(
                crawl_progress
            ),

            should_stop=(
                stop_event.is_set
            ),
        )


        stopped_early = (
            stop_event.is_set()
        )


        update_job(
            job_id,

            pages_visited=(
                crawl_stats[
                    "pages_visited"
                ]
            ),

            pdfs_found=(
                crawl_stats[
                    "pdfs_found"
                ]
            ),

            discovery_stopped_early=(
                stopped_early
            ),

            progress=25,
        )


        # ====================================================
        # NO PDFs
        # ====================================================

        if (
            crawl_stats[
                "pdfs_found"
            ]
            == 0
        ):

            completed_at = (
                datetime.now()
                .isoformat()
            )


            storage_manager.save_run_metadata(
                run_dir,
                {
                    "run_id":
                        run_id,

                    "job_id":
                        job_id,

                    "url":
                        url,

                    "status":
                        "complete",

                    "started_at":
                        started_at,

                    "completed_at":
                        completed_at,

                    "pages_visited":
                        crawl_stats[
                            "pages_visited"
                        ],

                    "pdfs_found":
                        0,

                    "documents_processed":
                        0,

                    "discovery_stopped_early":
                        stopped_early,

                    "action_counts":
                        {},
                },
            )


            storage_manager.update_latest(
                run_dir
            )


            update_job(
                job_id,

                status="complete",

                stage="complete",

                stage_label=(
                    "Scan complete — no PDFs found"
                ),

                progress=100,

                completed_at=(
                    completed_at
                ),

                documents_processed=0,

                action_counts={},
            )


            return


        # ====================================================
        # 2. ANALYZE PDF STRUCTURE
        # ====================================================

        update_job(
            job_id,

            stage="analyzing",

            stage_label=(
                "Analyzing PDFs found so far"
                if stopped_early
                else
                "Analyzing PDF structure"
            ),

            progress=30,

            current_document="",
        )


        def analysis_progress(
            current,
            total,
            filename,
        ):

            if total > 0:

                stage_progress = (
                    30
                    +
                    int(
                        (
                            current
                            / total
                        )
                        * 25
                    )
                )

            else:

                stage_progress = 55


            update_job(
                job_id,

                progress=(
                    stage_progress
                ),

                current_document=(
                    filename
                ),

                analysis_current=(
                    current
                ),

                analysis_total=(
                    total
                ),
            )


        pdf_analyzer.run(
            input_file=paths[
                "inventory"
            ],

            output_file=paths[
                "analysis"
            ],

            on_progress=(
                analysis_progress
            ),
        )


        # ====================================================
        # 3. GROUP SIMILAR DOCUMENTS
        # ====================================================

        update_job(
            job_id,

            stage="grouping",

            stage_label=(
                "Finding similar documents"
            ),

            progress=60,

            current_document="",
        )


        family_detector.run(
            input_file=paths[
                "analysis"
            ],

            output_file=paths[
                "families"
            ],
        )


        # ====================================================
        # 4. INITIAL DOCUMENT CONTEXT
        # ====================================================

        update_job(
            job_id,

            stage="understanding",

            stage_label=(
                "Understanding document context"
            ),

            progress=70,

            current_document="",
        )


        document_context.run(
            analysis_file=paths[
                "analysis"
            ],

            family_file=paths[
                "families"
            ],

            output_file=paths[
                "context"
            ],
        )


        # ====================================================
        # 5. INITIAL RULE TRIAGE
        # ====================================================

        update_job(
            job_id,

            stage="triaging",

            stage_label=(
                "Building initial remediation pathways"
            ),

            progress=80,

            current_document="",
        )


        triage_engine.run(
            analysis_file=paths[
                "analysis"
            ],

            family_file=paths[
                "families"
            ],

            context_file=paths[
                "context"
            ],

            output_file=paths[
                "triage"
            ],
        )


        # ====================================================
        # PREPARE CURRENT RUN FOR AI MODULES
        # ====================================================

        storage_manager.update_latest(
            run_dir
        )


        # ====================================================
        # CHECK API KEY
        # ====================================================

        if not os.getenv(
            "OPENAI_API_KEY"
        ):

            raise RuntimeError(
                "OPENAI_API_KEY is not configured. "
                "Add it to the project .env file "
                "before running Maris."
            )


        # ====================================================
        # 6. AI DOCUMENT UNDERSTANDING
        # ====================================================

        update_job(
            job_id,

            stage="understanding",

            stage_label=(
                "Understanding documents with AI"
            ),

            progress=87,

            current_document="",

            ai_status="running",

            ai_stage=(
                "document_understanding"
            ),

            ai_stage_label=(
                "Understanding document purpose and workflow"
            ),

            ai_error=None,
        )


        # This function already checks the permanent cache.
        #
        # Cached PDFs do not require a new paid call.
        # Load AI document understanding only when this stage begins.
        import ai_document_understanding

        ai_document_understanding.run(
            confirm_cost=False
        )


        # ====================================================
        # 7. RAG + FINAL TRIAGE
        # ====================================================

        update_job(
            job_id,

            stage="triaging",

            stage_label=(
                "Applying accessibility guidance"
            ),

            progress=94,

            current_document="",

            ai_stage=(
                "rag_triage"
            ),

            ai_stage_label=(
                "Retrieving guidance and assigning final pathways"
            ),
        )


        # Local semantic retrieval happens first.
        #
        # The advisor then uses the retrieved accessibility
        # guidance together with document understanding,
        # structural analysis, and the initial rule result.
        #
        # Cached final decisions are reused automatically.
        # Load the heavier RAG / embedding stack only when this stage begins.
        import ai_triage_advisor

        ai_triage_advisor.run(
            confirm_cost=False
        )


        # ====================================================
        # 8. BUILD ONE FINAL RESULT SET
        # ====================================================

        update_job(
            job_id,

            stage="triaging",

            stage_label=(
                "Finalizing Maris recommendations"
            ),

            progress=98,
        )


        final_df = (
            build_final_results(
                get_job(
                    job_id
                )
            )
        )


        if final_df.empty:

            action_counts = {}

        else:

            action_counts = (
                final_df[
                    "final_recommended_action"
                ]
                .value_counts()
                .to_dict()
            )


        completed_at = (
            datetime.now()
            .isoformat()
        )


        # ====================================================
        # SAVE FINAL RUN METADATA
        # ====================================================

        storage_manager.save_run_metadata(
            run_dir,
            {
                "run_id":
                    run_id,

                "job_id":
                    job_id,

                "url":
                    url,

                "status":
                    "complete",

                "started_at":
                    started_at,

                "completed_at":
                    completed_at,

                "pages_visited":
                    crawl_stats[
                        "pages_visited"
                    ],

                "pdfs_found":
                    crawl_stats[
                        "pdfs_found"
                    ],

                "documents_processed":
                    len(
                        final_df
                    ),

                "discovery_stopped_early":
                    stopped_early,

                "action_counts":
                    action_counts,

                "ai_status":
                    "complete",

                "rag_status":
                    "complete",
            },
        )


        storage_manager.update_latest(
            run_dir
        )


        # ====================================================
        # COMPLETE
        # ====================================================

        update_job(
            job_id,

            status="complete",

            stage="complete",

            stage_label=(
                "Final recommendations ready"
            ),

            progress=100,

            current_document="",

            completed_at=(
                completed_at
            ),

            documents_processed=(
                len(
                    final_df
                )
            ),

            action_counts=(
                action_counts
            ),

            ai_status="complete",

            ai_stage="complete",

            ai_stage_label=(
                "Final Maris recommendations ready"
            ),

            ai_completed_at=(
                completed_at
            ),

            ai_error=None,
        )


    except Exception as error:

        update_job(
            job_id,

            status="error",

            stage="error",

            stage_label=(
                "Scan failed"
            ),

            error=str(
                error
            ),

            ai_status="error",

            ai_error=str(
                error
            ),
        )


    finally:

        with jobs_lock:

            stop_events.pop(
                job_id,
                None,
            )


# ============================================================
# FRONTEND
# ============================================================

@app.get("/")
def home():

    if not INDEX_FILE.exists():

        return {
            "message":
                "Maris backend is running."
        }


    return FileResponse(
        INDEX_FILE
    )


# ============================================================
# START SCAN
# ============================================================

@app.post(
    "/api/scan"
)
def start_scan(
    request: ScanRequest,
):

    url = (
        request.url
        .strip()
    )


    if not url:

        raise HTTPException(
            status_code=400,
            detail=(
                "Website URL is required."
            ),
        )


    if not (
        url.startswith(
            "http://"
        )
        or
        url.startswith(
            "https://"
        )
    ):

        url = (
            "https://"
            + url
        )


    run = (
        storage_manager
        .create_run()
    )


    run_id = (
        run[
            "run_id"
        ]
    )


    run_dir = (
        run[
            "run_dir"
        ]
    )


    job_id = str(
        uuid.uuid4()
    )


    stop_event = (
        threading.Event()
    )


    with jobs_lock:

        jobs[
            job_id
        ] = {

            "job_id":
                job_id,

            "run_id":
                run_id,

            "run_dir":
                str(
                    run_dir
                ),

            "url":
                url,

            "status":
                "queued",

            "stage":
                "queued",

            "stage_label":
                "Preparing scan",

            "progress":
                0,

            "pages_visited":
                0,

            "pdfs_found":
                0,

            "current_document":
                "",

            "analysis_current":
                0,

            "analysis_total":
                0,

            "stop_requested":
                False,

            "discovery_stopped_early":
                False,

            "created_at":
                datetime.now()
                .isoformat(),

            "error":
                None,

            "ai_status":
                "waiting",

            "ai_stage":
                "idle",

            "ai_stage_label":
                "",

            "ai_error":
                None,
        }


        stop_events[
            job_id
        ] = (
            stop_event
        )


    thread = (
        threading.Thread(
            target=(
                run_scan_pipeline
            ),

            args=(
                job_id,
                url,
                stop_event,
            ),

            daemon=True,
        )
    )


    thread.start()


    return {
        "job_id":
            job_id,

        "run_id":
            run_id,

        "status":
            "queued",
    }


# ============================================================
# STOP DISCOVERY
# ============================================================

@app.post(
    "/api/scan/{job_id}/stop"
)
def stop_scan_discovery(
    job_id: str,
):

    job = get_job(
        job_id
    )


    if not job:

        raise HTTPException(
            status_code=404,
            detail=(
                "Scan job not found."
            ),
        )


    if (
        job[
            "status"
        ]
        in {
            "complete",
            "error",
        }
    ):

        raise HTTPException(
            status_code=409,
            detail=(
                "This scan has already finished."
            ),
        )


    if (
        job[
            "stage"
        ]
        != "discovering"
    ):

        raise HTTPException(
            status_code=409,
            detail=(
                "PDF discovery has already finished."
            ),
        )


    with jobs_lock:

        stop_event = (
            stop_events.get(
                job_id
            )
        )


    if (
        stop_event
        is None
    ):

        raise HTTPException(
            status_code=409,
            detail=(
                "This scan can no longer be stopped."
            ),
        )


    stop_event.set()


    update_job(
        job_id,

        stop_requested=True,

        stage_label=(
            "Stopping discovery — "
            "preparing to analyze PDFs found so far"
        ),
    )


    return {
        "job_id":
            job_id,

        "status":
            "stopping",

        "pdfs_found":
            job.get(
                "pdfs_found",
                0,
            ),
    }


# ============================================================
# SCAN STATUS
# ============================================================

@app.get(
    "/api/scan/{job_id}"
)
def scan_status(
    job_id: str,
):

    job = get_job(
        job_id
    )


    if not job:

        raise HTTPException(
            status_code=404,
            detail=(
                "Scan job not found."
            ),
        )


    return job


# ============================================================
# FINAL RESULTS
# ============================================================

@app.get(
    "/api/scan/{job_id}/results"
)
def scan_results(
    job_id: str,
):

    job = get_job(
        job_id
    )


    if not job:

        raise HTTPException(
            status_code=404,
            detail=(
                "Scan job not found."
            ),
        )


    if (
        job[
            "status"
        ]
        != "complete"
    ):

        raise HTTPException(
            status_code=409,
            detail=(
                "Scan is not complete yet."
            ),
        )


    paths = (
        get_job_run_paths(
            job
        )
    )


    if not paths[
        "triage"
    ].exists():

        return {
            "run_id":
                job[
                    "run_id"
                ],

            "summary": {
                "documents_processed":
                    0,

                "action_counts":
                    {},
            },

            "documents":
                [],
        }


    # IMPORTANT:
    #
    # This is the ONE result set shown to the user.
    #
    # Rule-based results are retained internally but the
    # visible recommendation uses the RAG decision whenever
    # one exists.
    final_df = (
        build_final_results(
            job
        )
    )


    if final_df.empty:

        counts = {}

    else:

        counts = (
            final_df[
                "final_recommended_action"
            ]
            .value_counts()
            .to_dict()
        )


    return {
        "run_id":
            job[
                "run_id"
            ],

        "summary": {
            "documents_processed":
                len(
                    final_df
                ),

            "action_counts":
                counts,
        },

        "documents":
            final_df.to_dict(
                orient="records"
            ),
    }


# ============================================================
# DOCUMENT FAMILIES
# ============================================================

@app.get(
    "/api/scan/{job_id}/families"
)
def family_results(
    job_id: str,
):

    job = get_job(
        job_id
    )


    if not job:

        raise HTTPException(
            status_code=404,
            detail=(
                "Scan job not found."
            ),
        )


    paths = (
        get_job_run_paths(
            job
        )
    )


    if not paths[
        "families"
    ].exists():

        return {
            "families":
                [],
        }


    family_df = (
        pd.read_csv(
            paths[
                "families"
            ]
        )
        .fillna(
            ""
        )
    )


    return {
        "families":
            family_df.to_dict(
                orient="records"
            ),
    }


# ============================================================
# HEALTH
# ============================================================

@app.get(
    "/api/health"
)
def health():

    return {
        "status":
            "ok",

        "service":
            "Maris",

        "pipeline":
            "single-final-recommendation",

        "storage":
            "persistent-runs-enabled",

        "ai":
            "document-understanding-enabled",

        "rag":
            "enabled",

        "cache":
            "enabled",

        "api_key_loaded":
            bool(
                os.getenv(
                    "OPENAI_API_KEY"
                )
            ),
    } 