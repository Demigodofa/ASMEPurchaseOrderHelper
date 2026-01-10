import json
import os
import re
from datetime import datetime, timezone


SPEC_RE = re.compile(r"\b(?P<spec>(?:SA|SB|SF|A)-\d+[A-Z]?M?)\b", re.IGNORECASE)
TABLE_REF_RE = re.compile(r"\bT[A4]B[1IL]E\s+(?P<num>\d+)\b", re.IGNORECASE)
NOTE_REF_RE = re.compile(r"\bN[O0]T[E3]\s+(?P<num>\d+)\b", re.IGNORECASE)
SECTION_RE = re.compile(r"^(?P<num>\d+)\.\s+", re.MULTILINE)
RESOLVED_NOTES_RE = re.compile(r"^(?:NOTE|NORE|N0TE|NOT[E3])\s+(?P<num>\d+)\b", re.IGNORECASE)
NOTE_BLOCK_RE = re.compile(
    r"(?:NOTE|NORE|N0TE|NOT[E3])\s*(?P<num>\d+)\s*[-–—]{0,2}\s*",
    re.IGNORECASE,
)


def load_manifest(output_root):
    path = os.path.join(output_root, "manifest.json")
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def load_page_json(output_root, json_rel):
    with open(os.path.join(output_root, json_rel), "r", encoding="utf-8") as handle:
        return json.load(handle)


def load_best_text(output_root, page_entry):
    best_path = page_entry.get("bestTextPath")
    if best_path:
        abs_path = os.path.join(output_root, best_path)
        if os.path.exists(abs_path):
            with open(abs_path, "r", encoding="utf-8") as handle:
                return handle.read()
    return ""


def extract_resolved_note_numbers(text):
    marker = "Resolved Notes (AI-verified)"
    if marker not in text:
        return set()
    section = text.split(marker, 1)[1]
    note_numbers = set()
    for line in section.splitlines():
        match = RESOLVED_NOTES_RE.match(line.strip())
        if match:
            note_numbers.add(match.group("num"))
    return note_numbers


def has_note_block_in_text(text, note_num):
    if not text or not note_num:
        return False
    for line in text.splitlines():
        match = NOTE_BLOCK_RE.search(line)
        if match and match.group("num") == str(note_num):
            return True
    return False


def load_spec_ranges(output_root):
    path = os.path.join(output_root, "spec_range_pass11.json")
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    ranges = []
    for item in data.get("ranges", []):
        if item.get("status") == "missing-range":
            continue
        start = item.get("startGlobalPage")
        end = item.get("endGlobalPage")
        if not start or not end or end < start:
            continue
        ranges.append((item.get("spec"), start, end))
    return ranges


def find_spec_for_page(spec_ranges, global_idx):
    for spec, start, end in spec_ranges:
        if start <= global_idx <= end:
            return spec
    return None


def load_resolved_notes_by_spec(output_root, spec_ranges):
    resolved = {}
    for spec, _, _ in spec_ranges:
        if not spec:
            continue
        spec_path = os.path.join(output_root, "spec_corpus", spec, "spec.txt")
        if not os.path.exists(spec_path):
            continue
        with open(spec_path, "r", encoding="utf-8") as handle:
            text = handle.read()
        resolved[spec] = extract_resolved_note_numbers(text)
    return resolved


def main():
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    output_root = os.path.join(repo_root, "sectionII_partA_data_digitized")

    manifest = load_manifest(output_root)
    page_entries = manifest.get("pages", [])
    spec_ranges = load_spec_ranges(output_root)
    resolved_notes_by_spec = load_resolved_notes_by_spec(output_root, spec_ranges)

    report = {
        "createdUtc": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "pagesTotal": len(page_entries),
            "tableRefs": 0,
            "tableRefGaps": 0,
            "noteRefs": 0,
            "noteRefGaps": 0,
            "sectionRegressions": 0,
        },
        "tableRefGaps": [],
        "noteRefGaps": [],
        "sectionRegressions": [],
    }

    last_section_by_spec = {}

    for idx, entry in enumerate(page_entries):
        page_json = load_page_json(output_root, entry["json"])
        text = load_best_text(output_root, page_json)
        spec_by_range = find_spec_for_page(spec_ranges, page_json.get("globalPageIndex"))
        spec_match = SPEC_RE.search(text[:200])
        spec = spec_match.group("spec").upper() if spec_match else None

        tabula_tables = page_json.get("tabulaTableCount", 0)
        camelot_tables = page_json.get("camelotTableCount", 0)
        pass1_tables = page_json.get("tableCount", 0)
        has_table = tabula_tables > 0 or camelot_tables > 0 or pass1_tables > 0

        # Table reference gaps
        for match in TABLE_REF_RE.finditer(text):
            report["summary"]["tableRefs"] += 1
            if not has_table:
                # Look ahead 2 pages
                found_next = False
                for look_ahead in range(1, 3):
                    if idx + look_ahead >= len(page_entries):
                        break
                    next_json = load_page_json(output_root, page_entries[idx + look_ahead]["json"])
                    if next_json.get("tabulaTableCount", 0) > 0 or next_json.get("tableCount", 0) > 0:
                        found_next = True
                        break
                if not found_next:
                    report["summary"]["tableRefGaps"] += 1
                    report["tableRefGaps"].append(
                        {
                            "globalPageIndex": page_json.get("globalPageIndex"),
                            "sourcePdf": page_json.get("sourcePdf"),
                            "sourcePageNumber": page_json.get("sourcePageNumber"),
                            "reference": match.group(0),
                        }
                    )

        # Note reference gaps
        note_count = (
            page_json.get("noteCount", 0)
            + page_json.get("noteOcrCount", 0)
            + page_json.get("noteOcrHighDpiCount", 0)
        )
        resolved_notes = extract_resolved_note_numbers(text)
        if spec_by_range and spec_by_range in resolved_notes_by_spec:
            resolved_notes |= resolved_notes_by_spec.get(spec_by_range, set())
        for match in NOTE_REF_RE.finditer(text):
            report["summary"]["noteRefs"] += 1
            note_num = match.group("num")
            if note_count == 0 and note_num not in resolved_notes:
                if has_note_block_in_text(text, note_num):
                    continue
                report["summary"]["noteRefGaps"] += 1
                report["noteRefGaps"].append(
                    {
                        "globalPageIndex": page_json.get("globalPageIndex"),
                        "sourcePdf": page_json.get("sourcePdf"),
                        "sourcePageNumber": page_json.get("sourcePageNumber"),
                        "reference": match.group(0),
                    }
                )

        # Section regression checks
        if spec:
            sections = [int(m.group("num")) for m in SECTION_RE.finditer(text)]
            if sections:
                current_min = min(sections)
                last_val = last_section_by_spec.get(spec)
                if last_val is not None and current_min + 2 < last_val:
                    report["summary"]["sectionRegressions"] += 1
                    report["sectionRegressions"].append(
                        {
                            "spec": spec,
                            "globalPageIndex": page_json.get("globalPageIndex"),
                            "sourcePdf": page_json.get("sourcePdf"),
                            "sourcePageNumber": page_json.get("sourcePageNumber"),
                            "lastSection": last_val,
                            "currentMinSection": current_min,
                        }
                    )
                last_section_by_spec[spec] = max(sections)

    out_path = os.path.join(output_root, "crossref_pass9.json")
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)

    print("Cross-reference pass complete.")


if __name__ == "__main__":
    main()
