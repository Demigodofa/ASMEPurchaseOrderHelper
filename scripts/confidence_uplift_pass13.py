import csv
import json
import pathlib
import re
from difflib import SequenceMatcher
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / "sectionII_partA_data_digitized"

MANIFEST_PATH = DATA / "manifest.json"
CROSSREF_PATH = DATA / "crossref_pass9.json"
SPEC_RANGE_PATH = DATA / "spec_range_pass11.json"
OUTPUT_PATH = DATA / "confidence_uplift_pass13.json"

BEST_TEXT_DIR = DATA / "best_text" / "pages"
NOTE_OCR_DIRS = [
    DATA / "note_ocr",
    DATA / "note_ocr_highdpi",
]
TABLE_DIRS = [
    DATA / "tables_tabula",
    DATA / "camelot_tables",
]

NOTE_HEADER_RE = re.compile(r"^\s*NOTES?\b", re.IGNORECASE)
NOTE_NUM_RE = re.compile(r"\bNOTE\s*(\d+)\b", re.IGNORECASE)
SECTION_RE = re.compile(r"^\s*(\d+)(?:\.\d+)*\s+[A-Z]")


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_text(text):
    cleaned = re.sub(r"[^A-Z0-9]+", " ", text.upper())
    return re.sub(r"\s+", " ", cleaned).strip()


def load_manifest_pages():
    manifest = load_json(MANIFEST_PATH)
    pages = {}
    for page in manifest.get("pages", []):
        pages[page["globalPageIndex"]] = page
    return pages


def iter_page_texts(pages, base_dir):
    for global_idx, page in pages.items():
        path = base_dir / pathlib.Path(page["text"]).name
        if path.exists():
            yield global_idx, path.read_text(encoding="utf-8", errors="ignore")


def extract_notes_from_text(text):
    lines = text.splitlines()
    notes = []
    current = []
    for line in lines:
        if NOTE_HEADER_RE.match(line):
            if current:
                notes.append("\n".join(current).strip())
            current = [line]
            continue
        if current:
            if not line.strip():
                notes.append("\n".join(current).strip())
                current = []
                continue
            if SECTION_RE.match(line):
                notes.append("\n".join(current).strip())
                current = []
                continue
            current.append(line)
    if current:
        notes.append("\n".join(current).strip())
    return [note for note in notes if note]


def extract_note_numbers(text):
    return {int(m.group(1)) for m in NOTE_NUM_RE.finditer(text)}


def build_note_pool(pages):
    notes = []
    for global_idx, text in iter_page_texts(pages, BEST_TEXT_DIR):
        for note in extract_notes_from_text(text):
            notes.append(
                {
                    "globalPageIndex": global_idx,
                    "source": "best_text",
                    "text": note,
                    "norm": normalize_text(note),
                    "noteNumbers": sorted(extract_note_numbers(note)),
                }
            )
    for note_dir in NOTE_OCR_DIRS:
        if not note_dir.exists():
            continue
        for path in note_dir.glob("page-*.txt"):
            match = re.search(r"page-(\d+)\.txt", path.name)
            if not match:
                continue
            global_idx = int(match.group(1))
            text = path.read_text(encoding="utf-8", errors="ignore")
            for note in extract_notes_from_text(text):
                notes.append(
                    {
                        "globalPageIndex": global_idx,
                        "source": note_dir.name,
                        "text": note,
                        "norm": normalize_text(note),
                        "noteNumbers": sorted(extract_note_numbers(note)),
                    }
                )
    return notes


def cluster_notes(notes, similarity_threshold=0.86):
    clusters = []
    for note in notes:
        assigned = False
        for cluster in clusters:
            rep = cluster["representative"]["norm"]
            score = SequenceMatcher(None, rep, note["norm"]).ratio()
            if score >= similarity_threshold:
                cluster["members"].append(note)
                assigned = True
                break
        if not assigned:
            clusters.append({"representative": note, "members": [note]})
    return clusters


def parse_table_header(rows):
    best = None
    best_alpha = 0
    for row in rows[:3]:
        joined = " ".join(cell for cell in row if cell)
        if not joined:
            continue
        alpha = sum(ch.isalpha() for ch in joined)
        if alpha > best_alpha:
            best_alpha = alpha
            best = row
    if not best:
        return None
    header_text = " ".join(cell.strip() for cell in best if cell)
    if not header_text:
        return None
    return normalize_text(header_text)


def load_table_headers():
    headers = {}
    for table_dir in TABLE_DIRS:
        if not table_dir.exists():
            continue
        for path in table_dir.glob("page-*.csv"):
            match = re.search(r"page-(\d+)\.csv", path.name)
            if not match:
                continue
            global_idx = int(match.group(1))
            try:
                with path.open("r", encoding="utf-8", errors="ignore", newline="") as fh:
                    rows = list(csv.reader(fh))
            except Exception:
                continue
            header = parse_table_header(rows)
            if header:
                headers.setdefault(global_idx, []).append(
                    {"header": header, "columns": max(len(r) for r in rows) if rows else 0}
                )
    return headers


def build_spec_ranges():
    if not SPEC_RANGE_PATH.exists():
        return []
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


def find_spec_for_page(spec_ranges, global_idx):
    for spec_range in spec_ranges:
        if spec_range["start"] <= global_idx <= spec_range["end"]:
            return spec_range["spec"]
    return None


def detect_section_gaps(pages):
    gaps = []
    last_section = None
    last_page = None
    for global_idx in sorted(pages.keys()):
        text_path = BEST_TEXT_DIR / f"page-{global_idx:04d}.txt"
        if not text_path.exists():
            continue
        text = text_path.read_text(encoding="utf-8", errors="ignore")
        section_numbers = []
        for line in text.splitlines():
            match = SECTION_RE.match(line)
            if match:
                section_numbers.append(int(match.group(1)))
        if not section_numbers:
            continue
        current = min(section_numbers)
        if last_section is not None and current > last_section + 1:
            gaps.append(
                {
                    "expectedNext": last_section + 1,
                    "observed": current,
                    "gapStartPage": last_page,
                    "gapEndPage": global_idx,
                }
            )
        last_section = current
        last_page = global_idx
    return gaps


def main():
    pages = load_manifest_pages()
    notes = build_note_pool(pages)
    clusters = cluster_notes(notes)
    spec_ranges = build_spec_ranges()
    crossref = load_json(CROSSREF_PATH) if CROSSREF_PATH.exists() else {}

    note_gaps = crossref.get("noteRefGaps", [])
    table_gaps = crossref.get("tableRefGaps", [])

    suggestions = []
    for gap in note_gaps:
        global_idx = gap.get("globalPageIndex")
        ref = gap.get("reference", "")
        match = NOTE_NUM_RE.search(ref)
        note_number = int(match.group(1)) if match else None
        window = range(max(1, global_idx - 10), min(global_idx + 10, len(pages)) + 1)
        candidates = [
            note
            for note in notes
            if note["globalPageIndex"] in window
            and (note_number is None or note_number in note["noteNumbers"])
        ]
        best = None
        for note in candidates:
            score = SequenceMatcher(None, normalize_text(ref), note["norm"]).ratio()
            if not best or score > best["score"]:
                best = {"score": score, "note": note}
        if best and best["score"] >= 0.6:
            suggestions.append(
                {
                    "globalPageIndex": global_idx,
                    "reference": ref,
                    "suggestedNoteText": best["note"]["text"],
                    "sourcePage": best["note"]["globalPageIndex"],
                    "source": best["note"]["source"],
                    "score": round(best["score"], 2),
                    "spec": find_spec_for_page(spec_ranges, global_idx),
                }
            )

    table_headers = load_table_headers()
    table_schema_flags = []
    for gap in table_gaps:
        global_idx = gap.get("globalPageIndex")
        headers = table_headers.get(global_idx, [])
        if not headers:
            table_schema_flags.append(
                {
                    "globalPageIndex": global_idx,
                    "reason": "table-reference-without-table-extract",
                    "spec": find_spec_for_page(spec_ranges, global_idx),
                }
            )
            continue
        max_cols = max(h["columns"] for h in headers)
        for header in headers:
            if header["columns"] < max(3, max_cols - 1):
                table_schema_flags.append(
                    {
                        "globalPageIndex": global_idx,
                        "header": header["header"],
                        "columns": header["columns"],
                        "maxColumnsOnPage": max_cols,
                        "spec": find_spec_for_page(spec_ranges, global_idx),
                    }
                )

    section_gaps = detect_section_gaps(pages)

    output = {
        "createdUtc": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "notePoolCount": len(notes),
            "noteClusters": len(clusters),
            "noteGapSuggestions": len(suggestions),
            "tableSchemaFlags": len(table_schema_flags),
            "sectionGapSignals": len(section_gaps),
        },
        "noteGapSuggestions": suggestions,
        "tableSchemaFlags": table_schema_flags,
        "sectionGapSignals": section_gaps,
    }
    OUTPUT_PATH.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print("Confidence uplift pass complete.")


if __name__ == "__main__":
    main()
