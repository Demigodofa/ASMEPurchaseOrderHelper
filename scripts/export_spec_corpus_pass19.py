import json
import pathlib
import re
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / "sectionII_partA_data_digitized"
MANIFEST_PATH = DATA / "manifest.json"
SPEC_RANGE_PATH = DATA / "spec_range_pass11.json"
OUTPUT_DIR = DATA / "spec_corpus"
OUTPUT_INDEX = OUTPUT_DIR / "spec_corpus_index.json"

BEST_TEXT_DIR = DATA / "best_text" / "pages"
TABLES_TABULA_DIR = DATA / "tables_tabula"
CAMELLOT_DIR = DATA / "camelot_tables"
NOTE_TARGET_DIR = DATA / "note_target_ocr"


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_manifest_pages():
    manifest = load_json(MANIFEST_PATH)
    pages = {}
    for page in manifest.get("pages", []):
        pages[page["globalPageIndex"]] = page
    return pages


def build_spec_ranges():
    spec_data = load_json(SPEC_RANGE_PATH)
    ranges = []
    for item in spec_data.get("ranges", []):
        if item.get("status") == "missing-range":
            continue
        start = item.get("startGlobalPage")
        end = item.get("endGlobalPage")
        if not start or not end or end < start:
            continue
        ranges.append({"spec": item["spec"], "start": start, "end": end})
    return ranges


def gather_page_assets(global_idx):
    assets = {}
    tabula_json = TABLES_TABULA_DIR / f"page-{global_idx:04d}.json"
    tabula_csv = TABLES_TABULA_DIR / f"page-{global_idx:04d}.csv"
    camelot_csv = CAMELLOT_DIR / f"page-{global_idx:04d}.csv"
    camelot_json = CAMELLOT_DIR / f"page-{global_idx:04d}.json"
    if tabula_json.exists():
        assets["tabulaTablesJson"] = str(tabula_json.relative_to(DATA))
    if tabula_csv.exists():
        assets["tabulaTablesCsv"] = str(tabula_csv.relative_to(DATA))
    if camelot_json.exists():
        assets["camelotTablesJson"] = str(camelot_json.relative_to(DATA))
    if camelot_csv.exists():
        assets["camelotTablesCsv"] = str(camelot_csv.relative_to(DATA))

    note_files = []
    for path in NOTE_TARGET_DIR.glob(f"page-{global_idx:04d}-note-*.txt"):
        note_files.append(str(path.relative_to(DATA)))
    if note_files:
        assets["noteTargetFiles"] = sorted(note_files)
    return assets




def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    pages = load_manifest_pages()
    ranges = build_spec_ranges()

    index = []
    for spec_range in ranges:
        spec = spec_range["spec"]
        spec_dir = OUTPUT_DIR / spec
        spec_dir.mkdir(parents=True, exist_ok=True)
        spec_pages = []
        combined_lines = []
        for idx in range(spec_range["start"], spec_range["end"] + 1):
            page = pages.get(idx)
            if not page:
                continue
            text_path = BEST_TEXT_DIR / f"page-{idx:04d}.txt"
            text = ""
            if text_path.exists():
                text = text_path.read_text(encoding="utf-8", errors="ignore")
            assets = gather_page_assets(idx)
            spec_pages.append(
                {
                    "globalPageIndex": idx,
                    "sourcePdf": page["sourcePdf"],
                    "sourcePageNumber": page["sourcePageNumber"],
                    "textPath": str(text_path.relative_to(DATA)) if text_path.exists() else None,
                    "assets": assets,
                }
            )
            if text:
                combined_lines.append(f"=== Page {idx} ===")
                combined_lines.append(text.strip())

        spec_json = {
            "createdUtc": datetime.now(timezone.utc).isoformat(),
            "spec": spec,
            "rangeStart": spec_range["start"],
            "rangeEnd": spec_range["end"],
            "pages": spec_pages,
        }
        (spec_dir / "spec.json").write_text(
            json.dumps(spec_json, indent=2), encoding="utf-8"
        )
        (spec_dir / "spec.txt").write_text(
            "\n\n".join(combined_lines), encoding="utf-8"
        )

        index.append(
            {
                "spec": spec,
                "rangeStart": spec_range["start"],
                "rangeEnd": spec_range["end"],
                "pageCount": len(spec_pages),
                "path": str((spec_dir / "spec.json").relative_to(DATA)),
            }
        )

    OUTPUT_INDEX.write_text(json.dumps(index, indent=2), encoding="utf-8")
    print("Spec corpus export complete.")


if __name__ == "__main__":
    main()
