import json
import pathlib
import re
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / "sectionII_partA_data_digitized"
AI_REVIEW_PATH = DATA / "ai_review" / "spec_corpus_ai_review.json"
SPEC_CORPUS_DIR = DATA / "spec_corpus"
OUTPUT_LOG = DATA / "merge_ai_verified_notes_pass20.json"

NOTE_HEADER_RE = re.compile(r"^\s*NOTE\s*(\d+)\b", re.IGNORECASE)
RESOLVED_SECTION_RE = re.compile(r"Resolved Notes \(AI-verified\)", re.IGNORECASE)

MIN_CONFIDENCE = 0.90


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8", errors="ignore"))


def find_note_block(spec_text, page_index, note_number):
    marker = f"=== Page {page_index} ==="
    if marker not in spec_text:
        return None
    page_section = spec_text.split(marker, 1)[1]
    # Stop at next page marker if present
    next_marker = re.search(r"^=== Page \\d+ ===", page_section, re.MULTILINE)
    if next_marker:
        page_section = page_section[: next_marker.start()]
    lines = page_section.splitlines()
    capture = []
    in_note = False
    for line in lines:
        header_match = NOTE_HEADER_RE.match(line)
        if header_match:
            if in_note:
                break
            if int(header_match.group(1)) == note_number:
                in_note = True
                capture.append(line)
                continue
        if in_note:
            if not line.strip():
                break
            capture.append(line)
    if capture:
        return "\n".join(capture).strip()
    return None


def load_existing_resolved(spec_text):
    resolved = set()
    if not RESOLVED_SECTION_RE.search(spec_text):
        return resolved
    section = RESOLVED_SECTION_RE.split(spec_text, 1)[1]
    for line in section.splitlines():
        match = re.match(r"NOTE\s+(\d+)\s+\(page\s+(\d+)\)", line.strip(), re.IGNORECASE)
        if match:
            resolved.add((int(match.group(1)), int(match.group(2))))
    return resolved


def main():
    if not AI_REVIEW_PATH.exists():
        print("AI review file not found.")
        return

    ai_review = load_json(AI_REVIEW_PATH)
    specs = ai_review.get("specs", [])
    merged_specs = 0
    merged_notes = 0
    missing_blocks = 0

    for spec_entry in specs:
        spec = spec_entry.get("spec")
        if not spec:
            continue
        spec_dir = SPEC_CORPUS_DIR / spec
        spec_txt = spec_dir / "spec.txt"
        if not spec_txt.exists():
            continue
        spec_text = spec_txt.read_text(encoding="utf-8", errors="ignore")
        verified = []
        for item in spec_entry.get("missingItems", []):
            if item.get("status") != "candidate_verified":
                # Accept needs_verification if confidence meets threshold.
                if item.get("status") != "needs_verification":
                    continue
            if item.get("kind") != "note":
                continue
            candidate = item.get("bestCandidate") or {}
            note_number = item.get("noteNumber") or item.get("number")
            if candidate:
                confidence = candidate.get("confidence")
                if confidence is not None and confidence < MIN_CONFIDENCE:
                    continue
                candidate = dict(candidate)
                candidate["noteNumber"] = int(note_number) if note_number and str(note_number).isdigit() else None
                candidate["candidatePage"] = candidate.get("candidatePage") or candidate.get("globalPageIndex") or item.get("gap", {}).get("globalPageIndex")
                verified.append(candidate)
        if not verified:
            continue

        existing_block = "\n\nResolved Notes (AI-verified)\n"
        existing = load_existing_resolved(spec_text)
        if RESOLVED_SECTION_RE.search(spec_text):
            existing_block = ""

        appended = []
        for candidate in verified:
            note_number = candidate.get("noteNumber")
            candidate_page = candidate.get("candidatePage")
            if not note_number or not candidate_page:
                continue
            if (note_number, candidate_page) in existing:
                continue
            note_block = find_note_block(spec_text, candidate_page, note_number)
            if not note_block:
                missing_blocks += 1
                note_block = candidate.get("evidence", {}).get("snippet", "").strip()
            if not note_block:
                continue
            appended.append(f"NOTE {note_number} (page {candidate_page})\n{note_block}")
            merged_notes += 1

        if appended:
            spec_text = spec_text.rstrip() + existing_block + "\n\n".join(appended) + "\n"
            spec_txt.write_text(spec_text, encoding="utf-8")
            merged_specs += 1

    result = {
        "createdUtc": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "specsUpdated": merged_specs,
            "notesMerged": merged_notes,
            "missingNoteBlocks": missing_blocks,
        },
    }
    OUTPUT_LOG.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print("Merge AI verified notes pass complete.")


if __name__ == "__main__":
    main()
