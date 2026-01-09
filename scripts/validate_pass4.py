import json
import os
import re
from datetime import datetime, timezone

import fitz  # PyMuPDF

RESOLVED_NOTES_RE = re.compile(r"^NOTE\s+(?P<num>\d+)\b", re.IGNORECASE)


def load_manifest(output_root):
    path = os.path.join(output_root, "manifest.json")
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def alpha_ratio(text):
    if not text:
        return 0.0
    alpha = len(re.findall(r"[A-Za-z]", text))
    return alpha / max(1, len(text))


def is_low_confidence(text):
    return len(text) < 300 or alpha_ratio(text) < 0.2


def render_page(pdf_path, page_index, dpi=200):
    zoom = dpi / 72.0
    doc = fitz.open(pdf_path)
    try:
        page = doc.load_page(page_index)
        matrix = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        return pix.tobytes("png")
    finally:
        doc.close()


def load_resolved_notes_by_spec(output_root):
    path = os.path.join(output_root, "spec_range_pass11.json")
    if not os.path.exists(path):
        return {}, []
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
    resolved = {}
    for spec, _, _ in ranges:
        if not spec:
            continue
        spec_path = os.path.join(output_root, "spec_corpus", spec, "spec.txt")
        if not os.path.exists(spec_path):
            continue
        with open(spec_path, "r", encoding="utf-8") as handle:
            text = handle.read()
        if "Resolved Notes (AI-verified)" not in text:
            continue
        section = text.split("Resolved Notes (AI-verified)", 1)[1]
        nums = set()
        for line in section.splitlines():
            match = RESOLVED_NOTES_RE.match(line.strip())
            if match:
                nums.add(match.group("num"))
        if nums:
            resolved[spec] = nums
    return resolved, ranges


def find_spec_for_page(spec_ranges, global_idx):
    for spec, start, end in spec_ranges:
        if start <= global_idx <= end:
            return spec
    return None


def main():
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    output_root = os.path.join(repo_root, "sectionII_partA_data_digitized")
    raster_dir = os.path.join(output_root, "raster_low_conf")
    os.makedirs(raster_dir, exist_ok=True)

    manifest = load_manifest(output_root)
    pdf_paths = {os.path.basename(p): p for p in manifest.get("sourcePdfs", [])}

    report = {
        "createdUtc": datetime.now(timezone.utc).isoformat(),
        "lowConfidenceThreshold": {"minLength": 300, "minAlphaRatio": 0.2},
        "summary": {
            "pagesTotal": 0,
            "lowConfidencePages": 0,
            "tableMentionWithoutTables": 0,
            "noteMentionWithoutNotes": 0,
        },
        "pages": [],
    }

    resolved_notes_by_spec, spec_ranges = load_resolved_notes_by_spec(output_root)

    for page_entry in manifest.get("pages", []):
        json_path = os.path.join(output_root, page_entry["json"])
        with open(json_path, "r", encoding="utf-8") as handle:
            page_json = json.load(handle)

        text = page_json.get("text", "")
        low_conf = is_low_confidence(text)
        table_mention = bool(re.search(r"\bTABLE\b|\bTable\s+\d+", text))
        note_mention = bool(re.search(r"\bNOTE\b|\bNote\s+\d+", text))

        table_files = (
            page_json.get("tabulaTablesPath")
            or page_json.get("tablesMd")
            or page_json.get("tablesTsv")
        )

        table_gap = table_mention and not page_json.get("tabulaTablesPath")
        spec = find_spec_for_page(spec_ranges, page_json.get("globalPageIndex"))
        resolved_notes = resolved_notes_by_spec.get(spec, set()) if spec else set()
        note_gap = note_mention and page_json.get("noteCount", 0) == 0 and not resolved_notes

        raster_path = None
        if low_conf:
            pdf_path = pdf_paths.get(page_json.get("sourcePdf", ""))
            if pdf_path and os.path.exists(pdf_path):
                base_name = f"page-{page_json.get('globalPageIndex', 0):04d}"
                raster_path = os.path.join(raster_dir, f"{base_name}.png")
                if not os.path.exists(raster_path):
                    png = render_page(pdf_path, page_json.get("sourcePageNumber", 1) - 1)
                    with open(raster_path, "wb") as handle:
                        handle.write(png)
                raster_path = f"raster_low_conf/{os.path.basename(raster_path)}"

        report["pages"].append(
            {
                "globalPageIndex": page_json.get("globalPageIndex"),
                "sourcePdf": page_json.get("sourcePdf"),
                "sourcePageNumber": page_json.get("sourcePageNumber"),
                "textLength": len(text),
                "alphaRatio": round(alpha_ratio(text), 4),
                "lowConfidence": low_conf,
                "ocrApplied": page_json.get("ocrApplied", False),
                "tableMention": table_mention,
                "noteMention": note_mention,
                "tableGap": table_gap,
                "noteGap": note_gap,
                "rasterPath": raster_path,
                "tabulaTablesPath": page_json.get("tabulaTablesPath"),
                "tableCountPass1": page_json.get("tableCount", 0),
                "tableCountPass3": page_json.get("tabulaTableCount", 0),
                "tablesMd": page_json.get("tablesMd"),
                "tablesTsv": page_json.get("tablesTsv"),
            }
        )

        report["summary"]["pagesTotal"] += 1
        if low_conf:
            report["summary"]["lowConfidencePages"] += 1
        if table_gap:
            report["summary"]["tableMentionWithoutTables"] += 1
        if note_gap:
            report["summary"]["noteMentionWithoutNotes"] += 1

    report_path = os.path.join(output_root, "validation_pass4.json")
    with open(report_path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)

    print("Validation pass complete.")


if __name__ == "__main__":
    main()
