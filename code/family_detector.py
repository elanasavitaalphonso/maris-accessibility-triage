from pathlib import Path
import re

import pandas as pd
import numpy as np

from sklearn.cluster import DBSCAN
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import StandardScaler
from sklearn.metrics.pairwise import cosine_distances


# --------------------------------------------------
# DEFAULTS (used only when running this file directly)
# --------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent

DEFAULT_INPUT_FILE = BASE_DIR / "outputfiles" / "pdf_analysis.csv"
DEFAULT_OUTPUT_FILE = BASE_DIR / "outputfiles" / "pdf_document_families.csv"


# --------------------------------------------------
# TEXT CLEANING
# --------------------------------------------------

def clean_text(value):
    value = str(value).lower()
    value = re.sub(r"\.pdf$", "", value)
    value = re.sub(r"[_\-]+", " ", value)
    value = re.sub(r"\b(19|20)\d{2}\b", " ", value)
    value = re.sub(r"\d+", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


# --------------------------------------------------
# FILENAME PATTERN
# --------------------------------------------------

def filename_pattern(filename):
    value = str(filename).lower()
    value = re.sub(r"\.pdf$", "", value)
    value = re.sub(r"\b\d{1,4}\b", " ", value)
    value = re.sub(r"[_\-]+", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


# --------------------------------------------------
# SOURCE PATH PATTERN
# --------------------------------------------------

def source_path_pattern(url):
    url = str(url).lower()
    url = re.sub(r"https?://", "", url)
    url = re.sub(r"\?.*$", "", url)
    parts = url.split("/")
    return " ".join(parts[:5])


# --------------------------------------------------
# TEXT FEATURES
# --------------------------------------------------

def build_template_text(row):
    filename = filename_pattern(row.get("filename", ""))
    title = clean_text(row.get("title", ""))
    source_path = source_path_pattern(row.get("source_page", ""))
    source_hint = clean_text(row.get("source_application_hint", ""))

    return f"{filename} {filename} {source_path} {source_path} {source_hint} {title}"


# --------------------------------------------------
# STRUCTURAL FEATURES
# --------------------------------------------------

def build_structural_features(df):
    numeric_columns = [
        "page_count", "images_per_page", "form_field_count", "table_like_count",
        "font_family_count", "heading_like_count", "text_per_page", "metadata_score",
    ]

    structure_df = df[numeric_columns].apply(pd.to_numeric, errors="coerce").fillna(0)

    scaler = StandardScaler()
    return scaler.fit_transform(structure_df)


# --------------------------------------------------
# BOOLEAN FEATURES
# --------------------------------------------------

def bool_value(value):
    return 1 if str(value).strip().lower() == "true" else 0


def build_boolean_features(df):
    columns = ["has_tags", "likely_scanned", "has_bookmarks", "likely_complex_layout"]

    values = []
    for _, row in df.iterrows():
        values.append([bool_value(row[column]) for column in columns])

    return np.array(values)


# --------------------------------------------------
# FAMILY NAME
# --------------------------------------------------

def create_family_name(group):
    words = []

    stop_words = {
        "pdf", "upstate", "medical", "university", "document",
        "documents", "final", "web", "website", "file",
    }

    for filename in group["filename"]:
        cleaned = filename_pattern(filename)
        for word in cleaned.split():
            if len(word) > 2 and word not in stop_words:
                words.append(word)

    if not words:
        return "Document Family"

    counts = pd.Series(words).value_counts()
    top_words = list(counts.head(3).index)

    return " ".join(word.title() for word in top_words)


# --------------------------------------------------
# CONFIDENCE
# --------------------------------------------------

def calculate_confidence(family_size, similarity):
    if family_size >= 3 and similarity >= 0.78:
        return "High"
    if family_size >= 2 and similarity >= 0.65:
        return "Medium"
    return "Low"


# --------------------------------------------------
# RUN (callable)
# --------------------------------------------------

def run(input_file=DEFAULT_INPUT_FILE, output_file=DEFAULT_OUTPUT_FILE):
    """
    Cluster successfully-analyzed PDFs (from `input_file`) into document
    families using filename/source/structure similarity, and write the
    result to `output_file`.

    Returns the resulting DataFrame.
    """

    input_file = Path(input_file)
    output_file = Path(output_file)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(input_file)
    df = df[df["analysis_status"] == "SUCCESS"].copy()
    df.reset_index(drop=True, inplace=True)

    if df.empty:
        empty_columns = [
            "filename", "pdf_url", "source_page",
            "page_count", "images_per_page", "image_count", "table_like_count",
            "form_field_count", "font_family_count", "heading_like_count",
            "has_tags", "likely_scanned", "likely_complex_layout", "source_application_hint",
            "family_id", "family_name", "family_size", "family_similarity", "family_confidence",
        ]
        empty_df = pd.DataFrame(columns=empty_columns)
        empty_df.to_csv(output_file, index=False)
        return empty_df

    # --------------------------------
    # TEMPLATE TEXT
    # --------------------------------

    df["template_text"] = df.apply(build_template_text, axis=1)

    vectorizer = TfidfVectorizer(stop_words="english", ngram_range=(1, 3), min_df=1)
    text_matrix = vectorizer.fit_transform(df["template_text"])
    text_distance = cosine_distances(text_matrix)

    # --------------------------------
    # STRUCTURAL DISTANCE
    # --------------------------------

    structural_features = build_structural_features(df)
    boolean_features = build_boolean_features(df)

    structure_vector = np.hstack([structural_features, boolean_features])

    structure_distance = np.linalg.norm(
        structure_vector[:, None] - structure_vector[None, :], axis=2
    )

    max_distance = structure_distance.max()
    if max_distance > 0:
        structure_distance = structure_distance / max_distance

    # --------------------------------
    # COMBINED DISTANCE
    # --------------------------------

    combined_distance = 0.45 * text_distance + 0.55 * structure_distance

    # --------------------------------
    # DBSCAN
    # --------------------------------

    model = DBSCAN(eps=0.29, min_samples=2, metric="precomputed")
    clusters = model.fit_predict(combined_distance)
    df["cluster_id"] = clusters

    # --------------------------------
    # FAMILY IDs
    # --------------------------------

    family_map = {}
    counter = 1
    for cluster_id in sorted(df["cluster_id"].unique()):
        if cluster_id == -1:
            continue
        family_map[cluster_id] = f"F{counter:03d}"
        counter += 1

    df["family_id"] = df["cluster_id"].apply(lambda cluster: family_map.get(cluster, "UNIQUE"))

    # --------------------------------
    # FAMILY SIZE
    # --------------------------------

    sizes = (
        df[df["family_id"] != "UNIQUE"]
        .groupby("family_id")
        .size()
        .to_dict()
    )

    df["family_size"] = df["family_id"].apply(lambda family: sizes.get(family, 1))

    # --------------------------------
    # FAMILY NAMES
    # --------------------------------

    names = {}
    for family_id in df["family_id"].unique():
        if family_id == "UNIQUE":
            continue
        group = df[df["family_id"] == family_id]
        names[family_id] = create_family_name(group)

    df["family_name"] = df["family_id"].apply(
        lambda family: names.get(family, "Unique / Unclassified")
    )

    # --------------------------------
    # FAMILY SIMILARITY
    # --------------------------------

    family_similarity = {}
    for family_id in df["family_id"].unique():
        if family_id == "UNIQUE":
            continue

        positions = list(df.index[df["family_id"] == family_id])
        distances = []

        for i in range(len(positions)):
            for j in range(i + 1, len(positions)):
                distances.append(combined_distance[positions[i], positions[j]])

        if distances:
            avg_distance = sum(distances) / len(distances)
            similarity = 1 - avg_distance
        else:
            similarity = 0

        family_similarity[family_id] = round(similarity, 3)

    df["family_similarity"] = df["family_id"].apply(
        lambda family: family_similarity.get(family, 0)
    )

    # --------------------------------
    # CONFIDENCE
    # --------------------------------

    df["family_confidence"] = df.apply(
        lambda row: calculate_confidence(row["family_size"], row["family_similarity"]),
        axis=1,
    )

    # --------------------------------
    # OUTPUT
    # --------------------------------

    columns = [
        "filename", "pdf_url", "source_page",
        "page_count", "images_per_page", "image_count", "table_like_count",
        "form_field_count", "font_family_count", "heading_like_count",
        "has_tags", "likely_scanned", "likely_complex_layout", "source_application_hint",
        "family_id", "family_name", "family_size", "family_similarity", "family_confidence",
    ]

    result = df[columns].copy()
    result.to_csv(output_file, index=False)

    return result


# --------------------------------------------------
# STANDALONE CLI USE
# --------------------------------------------------

if __name__ == "__main__":

    result_df = run(DEFAULT_INPUT_FILE, DEFAULT_OUTPUT_FILE)

    grouped = result_df[result_df["family_id"] != "UNIQUE"]

    print()
    print("================================")
    print("TEMPLATE FAMILY DETECTION COMPLETE")
    print("================================")
    print(f"Documents analyzed: {len(result_df)}")
    print(f"Families detected: {grouped['family_id'].nunique()}")
    print(f"Documents in families: {len(grouped)}")
    print(f"Unique documents: {(result_df['family_id'] == 'UNIQUE').sum()}")
    print()
    print(f"Saved to: {DEFAULT_OUTPUT_FILE}")
