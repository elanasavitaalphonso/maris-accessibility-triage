from pathlib import Path
from datetime import datetime
import json
import shutil
import uuid

import pandas as pd


# ============================================================
# PATHS
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent

OUTPUT_DIR = BASE_DIR / "outputfiles"

LATEST_DIR = OUTPUT_DIR / "latest"
RUNS_DIR = OUTPUT_DIR / "runs"
CACHE_DIR = OUTPUT_DIR / "cache"

AI_CONTEXT_CACHE = (
    CACHE_DIR
    / "pdf_ai_document_context.csv"
)

AI_TRIAGE_CACHE = (
    CACHE_DIR
    / "pdf_ai_triage_advice.csv"
)


# ============================================================
# DIRECTORY SETUP
# ============================================================

def ensure_storage():

    for directory in [
        OUTPUT_DIR,
        LATEST_DIR,
        RUNS_DIR,
        CACHE_DIR,
    ]:

        directory.mkdir(
            parents=True,
            exist_ok=True,
        )


# ============================================================
# CREATE RUN
# ============================================================

def create_run():

    ensure_storage()

    timestamp = datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )

    short_id = str(
        uuid.uuid4()
    )[:8]

    run_id = (
        f"{timestamp}_{short_id}"
    )

    run_dir = (
        RUNS_DIR
        / run_id
    )

    run_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    return {
        "run_id": run_id,
        "run_dir": run_dir,
    }


# ============================================================
# RUN FILE PATHS
# ============================================================

def get_run_paths(run_dir):

    run_dir = Path(
        run_dir
    )

    return {
        "inventory":
            run_dir
            / "pdf_inventory.csv",

        "analysis":
            run_dir
            / "pdf_analysis.csv",

        "families":
            run_dir
            / "pdf_document_families.csv",

        "context":
            run_dir
            / "pdf_document_context.csv",

        "triage":
            run_dir
            / "pdf_triage_results.csv",

        "metadata":
            run_dir
            / "run_metadata.json",
    }


# ============================================================
# SAVE RUN METADATA
# ============================================================

def save_run_metadata(
    run_dir,
    metadata,
):

    paths = get_run_paths(
        run_dir
    )

    with open(
        paths["metadata"],
        "w",
        encoding="utf-8",
    ) as file:

        json.dump(
            metadata,
            file,
            indent=2,
            ensure_ascii=False,
            default=str,
        )


# ============================================================
# COPY RUN TO LATEST
# ============================================================

def update_latest(
    run_dir
):

    ensure_storage()

    run_dir = Path(
        run_dir
    )

    if LATEST_DIR.exists():

        for item in (
            LATEST_DIR.iterdir()
        ):

            if item.is_file():
                item.unlink()

            elif item.is_dir():
                shutil.rmtree(
                    item
                )

    for source in (
        run_dir.iterdir()
    ):

        destination = (
            LATEST_DIR
            / source.name
        )

        if source.is_file():

            shutil.copy2(
                source,
                destination,
            )

        elif source.is_dir():

            shutil.copytree(
                source,
                destination,
            )


# ============================================================
# CACHE HELPERS
# ============================================================

def load_cache(
    cache_file
):

    cache_file = Path(
        cache_file
    )

    if not cache_file.exists():

        return pd.DataFrame()

    try:

        return pd.read_csv(
            cache_file
        )

    except Exception:

        return pd.DataFrame()


def save_cache(
    df,
    cache_file
):

    ensure_storage()

    cache_file = Path(
        cache_file
    )

    df.to_csv(
        cache_file,
        index=False,
    )


# ============================================================
# UPSERT CACHE
# ============================================================

def upsert_cache(
    new_df,
    cache_file,
    key="pdf_url",
):

    ensure_storage()

    if new_df is None:
        return load_cache(
            cache_file
        )

    if new_df.empty:
        return load_cache(
            cache_file
        )

    if key not in new_df.columns:

        raise ValueError(
            f"Cache input is missing key column: {key}"
        )

    existing = load_cache(
        cache_file
    )

    if existing.empty:

        combined = (
            new_df
            .drop_duplicates(
                subset=[key],
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
                subset=[key],
                keep="last",
            )
            .reset_index(
                drop=True
            )
        )

    save_cache(
        combined,
        cache_file,
    )

    return combined


# ============================================================
# AI DOCUMENT CONTEXT CACHE
# ============================================================

def load_ai_context_cache():

    return load_cache(
        AI_CONTEXT_CACHE
    )


def save_ai_context_results(
    new_df
):

    return upsert_cache(
        new_df,
        AI_CONTEXT_CACHE,
        key="pdf_url",
    )


# ============================================================
# AI TRIAGE CACHE
# ============================================================

def load_ai_triage_cache():

    return load_cache(
        AI_TRIAGE_CACHE
    )


def save_ai_triage_results(
    new_df
):

    return upsert_cache(
        new_df,
        AI_TRIAGE_CACHE,
        key="pdf_url",
    )


# ============================================================
# FIND UNCACHED PDFS
# ============================================================

def find_uncached_rows(
    input_df,
    cache_df,
    key="pdf_url",
):

    if input_df.empty:

        return input_df.copy()

    if cache_df.empty:

        return input_df.copy()

    if key not in input_df.columns:

        raise ValueError(
            f"Input dataframe is missing: {key}"
        )

    if key not in cache_df.columns:

        return input_df.copy()

    cached_values = set(
        cache_df[
            key
        ]
        .dropna()
        .astype(str)
        .tolist()
    )

    uncached = input_df[
        ~input_df[
            key
        ]
        .astype(str)
        .isin(
            cached_values
        )
    ].copy()

    return uncached


# ============================================================
# REUSE CACHE
# ============================================================

def get_cached_matches(
    input_df,
    cache_df,
    key="pdf_url",
):

    if (
        input_df.empty
        or cache_df.empty
    ):

        return pd.DataFrame()

    if (
        key not in input_df.columns
        or key not in cache_df.columns
    ):

        return pd.DataFrame()

    keys = set(
        input_df[
            key
        ]
        .dropna()
        .astype(str)
    )

    matches = cache_df[
        cache_df[
            key
        ]
        .astype(str)
        .isin(keys)
    ].copy()

    return matches


# ============================================================
# MIGRATE OLD AI FILES
# ============================================================

def migrate_existing_ai_files():

    ensure_storage()

    old_context = (
        OUTPUT_DIR
        / "pdf_ai_document_context.csv"
    )

    old_triage = (
        OUTPUT_DIR
        / "pdf_ai_triage_advice.csv"
    )

    migrated = []

    if old_context.exists():

        try:

            df = pd.read_csv(
                old_context
            )

            if (
                not df.empty
                and "pdf_url"
                in df.columns
            ):

                save_ai_context_results(
                    df
                )

                migrated.append(
                    (
                        "AI document context",
                        len(df),
                    )
                )

        except Exception as error:

            print(
                "Could not migrate "
                "AI document context:"
            )

            print(
                error
            )

    if old_triage.exists():

        try:

            df = pd.read_csv(
                old_triage
            )

            if (
                not df.empty
                and "pdf_url"
                in df.columns
            ):

                save_ai_triage_results(
                    df
                )

                migrated.append(
                    (
                        "AI triage advice",
                        len(df),
                    )
                )

        except Exception as error:

            print(
                "Could not migrate "
                "AI triage cache:"
            )

            print(
                error
            )

    return migrated


# ============================================================
# CLI TEST
# ============================================================

if __name__ == "__main__":

    print()

    print(
        "========================================"
    )

    print(
        "MARIS STORAGE MANAGER"
    )

    print(
        "========================================"
    )

    ensure_storage()

    print(
        f"Latest:\n{LATEST_DIR}"
    )

    print()

    print(
        f"Runs:\n{RUNS_DIR}"
    )

    print()

    print(
        f"Cache:\n{CACHE_DIR}"
    )

    print()

    migrated = (
        migrate_existing_ai_files()
    )

    if migrated:

        print(
            "Migrated existing AI results:"
        )

        for name, count in migrated:

            print(
                f"  {name}: {count}"
            )

    else:

        print(
            "No existing AI files "
            "needed migration."
        )

    print()

    context_cache = (
        load_ai_context_cache()
    )

    triage_cache = (
        load_ai_triage_cache()
    )

    print(
        "AI context cache rows:"
        f" {len(context_cache)}"
    )

    print(
        "AI triage cache rows:"
        f" {len(triage_cache)}"
    )

    print()

    print(
        "========================================"
    )

    print(
        "STORAGE READY"
    )

    print(
        "========================================"
    )