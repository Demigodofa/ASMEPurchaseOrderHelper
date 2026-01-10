import json
import pathlib
import re
from datetime import datetime, timezone


ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / "sectionII_partA_data_digitized"

MANIFEST_PATH = DATA / "manifest.json"
SPEC_RANGE_PATH = DATA / "spec_range_pass11.json"
CROSSREF_PATH = DATA / "crossref_pass9.json"
TOC_INDEX_PATH = DATA / "toc_index_pass10.json"
OUTPUT_PATH = DATA / "confidence_recheck_pass14.json"

BEST_TEXT_DIR = DATA / "best_text" / "pages"
OCR_DIR = DATA / "ocr"
NOTE_OCR_DIRS = [
    DATA / "note_ocr",
    DATA / "note_ocr_highdpi",
    DATA / "note_target_ocr",
    DATA / "gap_ocr_highdpi",
]

NOTE_HEADER_RE = re.compile(r"^\s*(?:NOTE|NORE|N0TE|NOT[E3])\s*(\d+)\b", re.IGNORECASE)
NOTE_HEADER_ANY_RE = re.compile(
    r"\b(?:NOTE|NORE|N0TE|NOT[E3])\s*(\d+)\b", re.IGNORECASE
)
SPEC_RE = re.compile(r"\bSA-\d+[A-Z]?\b|\bA-\d+[A-Z]?\b")


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def alpha_ratio(text):
    if not text:
        return 0.0
    alpha = sum(1 for ch in text if ch.isalpha())
    return alpha / max(1, len(text))


def load_manifest_pages():
    manifest = load_json(MANIFEST_PATH)
    pages = {}
    for page in manifest.get("pages", []):
        pages[page["globalPageIndex"]] = page
    return pages


def load_text_for_page(global_idx):
    path = BEST_TEXT_DIR / f"page-{global_idx:04d}.txt"
    if path.exists():
        return path.read_text(encoding="utf-8", errors="ignore"), "best_text"
    path = OCR_DIR / f"page-{global_idx:04d}.txt"
    if path.exists():
        return path.read_text(encoding="utf-8", errors="ignore"), "ocr"
    for note_dir in NOTE_OCR_DIRS:
        path = note_dir / f"page-{global_idx:04d}.txt"
        if path.exists():
            return path.read_text(encoding="utf-8", errors="ignore"), note_dir.name
    return "", None


def extract_note_blocks(text):
    if not text:
        return []

    normalized = text.replace("\r\n", "\n")
    matches = list(NOTE_HEADER_ANY_RE.finditer(normalized))
    if not matches:
        return []

    blocks = []
    for idx, match in enumerate(matches):
        start = match.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(normalized)
        block = normalized[start:end].strip()
        if block:
            blocks.append(block)

    return blocks


def load_target_note_files(global_idx):
    notes = []
    target_dir = DATA / "note_target_ocr"
    if not target_dir.exists():
        return notes
    pattern = f"page-{global_idx:04d}-note-*.txt"
    for path in target_dir.glob(pattern):
        match = re.search(r"note-(\d+)\.txt$", path.name)
        note_num = int(match.group(1)) if match else None
        text = path.read_text(encoding="utf-8", errors="ignore").strip()
        if not text:
            continue
        notes.append(
            {
                "text": text,
                "source": "note_target_ocr",
                "noteNumber": note_num if note_num is not None else parse_note_number(text),
                "length": len(text),
                "alphaRatio": round(alpha_ratio(text), 3),
            }
        )
    return notes


def parse_note_number(text):
    match = NOTE_HEADER_ANY_RE.search(text)
    if match:
        return int(match.group(1))
    return None


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


def build_toc_checks(pages):
    if not TOC_INDEX_PATH.exists():
        return []
    toc = load_json(TOC_INDEX_PATH)
    checks = []
    for entry in toc.get("entries", []):
        spec = entry.get("spec")
        start = entry.get("startGlobalPage")
        if not spec or not start or start not in pages:
            continue
        text, source = load_text_for_page(start)
        present = spec in text
        checks.append(
            {
                "spec": spec,
                "startGlobalPage": start,
                "specPresentOnStartPage": present,
                "textSource": source,
            }
        )
    return checks


def evaluate_note_reference(gap, spec_ranges):
    global_idx = gap.get("globalPageIndex")
    ref = gap.get("reference", "")
    match = NOTE_HEADER_RE.search(ref)
    note_number = int(match.group(1)) if match else None
    if not note_number:
        return None
    spec = find_spec_for_page(spec_ranges, global_idx)
    window = range(max(1, global_idx - 6), global_idx + 7)
    candidates = []
    for idx in window:
        text, source = load_text_for_page(idx)
        if not text:
            continue
        for block in extract_note_blocks(text):
            header_match = NOTE_HEADER_RE.match(block.splitlines()[0])
            if not header_match:
                continue
            if int(header_match.group(1)) != note_number:
                continue
            ratio = alpha_ratio(block)
            candidates.append(
                {
                    "globalPageIndex": idx,
                    "noteText": block,
                    "textSource": source,
                    "alphaRatio": round(ratio, 3),
                    "length": len(block),
                }
            )
        # include per-note OCR files if present
        for note in load_target_note_files(idx):
            if note.get("noteNumber") != note_number:
                continue
            candidates.append(
                {
                    "globalPageIndex": idx,
                    "noteText": note["text"],
                    "textSource": note["source"],
                    "alphaRatio": note["alphaRatio"],
                    "length": note["length"],
                }
            )
    if not candidates:
        return {
            "globalPageIndex": global_idx,
            "reference": ref,
            "spec": spec,
            "status": "missing",
        }
    best = max(candidates, key=lambda c: (c["alphaRatio"], c["length"]))
    confidence = 0.0
    # Anchors-only confidence (no content inference): note number match + spec range + proximity.
    confidence += 0.7  # note number match implied by candidate selection
    if spec:
        confidence += 0.2
    if best["globalPageIndex"] == global_idx:
        confidence += 0.1
    status = "verified" if confidence >= 0.95 else "needs_recheck"
    return {
        "globalPageIndex": global_idx,
        "reference": ref,
        "spec": spec,
        "status": status,
        "confidence": round(confidence, 2),
        "candidate": best,
    }


def main():
    pages = load_manifest_pages()
    spec_ranges = build_spec_ranges()
    crossref = load_json(CROSSREF_PATH) if CROSSREF_PATH.exists() else {}

    note_gaps = crossref.get("noteRefGaps", [])
    note_checks = []
    for gap in note_gaps:
        result = evaluate_note_reference(gap, spec_ranges)
        if result:
            note_checks.append(result)

    toc_checks = build_toc_checks(pages)

    verified = [item for item in note_checks if item["status"] == "verified"]
    needs_recheck = [item for item in note_checks if item["status"] == "needs_recheck"]
    missing = [item for item in note_checks if item["status"] == "missing"]

    output = {
        "createdUtc": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "noteRefsChecked": len(note_checks),
            "noteVerified": len(verified),
            "noteNeedsRecheck": len(needs_recheck),
            "noteMissing": len(missing),
            "tocChecks": len(toc_checks),
            "tocSpecPresentCount": len([c for c in toc_checks if c["specPresentOnStartPage"]]),
        },
        "noteChecks": note_checks,
        "tocChecks": toc_checks,
    }
    OUTPUT_PATH.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print("Confidence recheck pass complete.")


if __name__ == "__main__":
    main()
