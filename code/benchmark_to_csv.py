import json
import csv
from pathlib import Path


# --------------------------------------------------
# SETTINGS
# --------------------------------------------------

INPUT_FILE = "../json-files/dataset.json"
OUTPUT_FILE = "../outputfiles/pdf_accessibility_benchmark.csv"

# --------------------------------------------------
# LOAD DATA
# --------------------------------------------------

def load_dataset():
    with open(INPUT_FILE, "r", encoding="utf-8") as file:
        return json.load(file)


# --------------------------------------------------
# FLATTEN DATASET
# --------------------------------------------------

def flatten_dataset(data):

    rows = []

    tasks = data.get("tasks", {})

    for criterion, labels in tasks.items():

        for label, documents in labels.items():

            for document in documents:

                rows.append({
                    "criterion": criterion,
                    "label": label,
                    "openalex_id": document.get("openalex_id", ""),
                    "title": document.get("title", ""),
                    "year": document.get("year", ""),
                    "venue": document.get("venue", ""),
                    "doi": document.get("doi", ""),
                    "type": document.get("type", ""),
                    "pdf_path": document.get("pdf_path", ""),
                    "input_pdf_count": len(
                        document.get("input_pdfs", [])
                    ),
                    "html_page_count": len(
                        document.get("html_pages", [])
                    ),
                    "image_file_count": len(
                        document.get("image_files", [])
                    )
                })

    return rows


# --------------------------------------------------
# SAVE CSV
# --------------------------------------------------

def save_csv(rows):

    if not rows:
        print("No benchmark records found.")
        return

    fieldnames = list(rows[0].keys())

    with open(
        OUTPUT_FILE,
        "w",
        newline="",
        encoding="utf-8"
    ) as file:

        writer = csv.DictWriter(
            file,
            fieldnames=fieldnames
        )

        writer.writeheader()
        writer.writerows(rows)


# --------------------------------------------------
# SUMMARY
# --------------------------------------------------

def print_summary(rows):

    print()
    print("==============================")
    print("BENCHMARK CONVERSION COMPLETE")
    print("==============================")

    print(f"Records created: {len(rows)}")

    criteria = sorted(
        set(row["criterion"] for row in rows)
    )

    print(f"Accessibility criteria: {len(criteria)}")

    print()

    for criterion in criteria:

        criterion_rows = [
            row
            for row in rows
            if row["criterion"] == criterion
        ]

        print(
            f"{criterion}: "
            f"{len(criterion_rows)} records"
        )

    print()
    print(f"Saved to: {OUTPUT_FILE}")
    print("==============================")


# --------------------------------------------------
# MAIN
# --------------------------------------------------

def main():

    if not Path(INPUT_FILE).exists():

        print(
            f"Could not find {INPUT_FILE}"
        )

        print(
            "Place dataset.json in the same folder "
            "as this script."
        )

        return

    data = load_dataset()

    rows = flatten_dataset(data)

    save_csv(rows)

    print_summary(rows)


if __name__ == "__main__":
    main()