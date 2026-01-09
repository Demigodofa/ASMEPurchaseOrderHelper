import json
import os
import re
from datetime import datetime, timezone


SPEC_RE = re.compile(r"\b(?P<spec>(?:SA|SB|SF|A)-\d+[A-Z]?M?)\b", re.IGNORECASE)


def load_best_text(output_root, page_entry):
    best_path = page_entry.get("bestTextPath")
    if not best_path and page_entry.get("json"):
        json_path = os.path.join(output_root, page_entry["json"])
        if os.path.exists(json_path):
            with open(json_path, "r", encoding="utf-8") as handle:
                page_json = json.load(handle)
            best_path = page_json.get("bestTextPath")
            if not best_path:
                return page_json.get("text", "")

    if best_path:
        abs_path = os.path.join(output_root, best_path)
        if os.path.exists(abs_path):
            with open(abs_path, "r", encoding="utf-8") as handle:
                return handle.read()
    return ""


def load_manifest(output_root):
    path = os.path.join(output_root, "manifest.json")
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def load_toc(output_root):
    path = os.path.join(output_root, "toc_pass8c.json")
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def index_first_spec_pages(output_root, pages):
    first = {}
    ordered = []
    for entry in pages:
        text = load_best_text(output_root, entry)
        top_lines = text.replace("\r\n", "\n").split("\n")[:10]
        header_block = " ".join(top_lines)
        match = SPEC_RE.search(header_block)
        if not match:
            continue
        spec = match.group("spec").upper()
        if spec in first:
            continue
        record = {
            "spec": spec,
            "globalPageIndex": entry.get("globalPageIndex"),
            "sourcePdf": entry.get("sourcePdf"),
            "sourcePageNumber": entry.get("sourcePageNumber"),
            "headerSnippet": header_block[:200],
        }
        first[spec] = record
        ordered.append(record)
    ordered.sort(key=lambda r: r["globalPageIndex"])
    return first, ordered


def main():
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    output_root = os.path.join(repo_root, "sectionII_partA_data_digitized")

    manifest = load_manifest(output_root)
    toc = load_toc(output_root)

    pages = manifest.get("pages", [])
    first_map, ordered_starts = index_first_spec_pages(output_root, pages)

    toc_entries = toc.get("entries", [])
    toc_entries_sorted = sorted(toc_entries, key=lambda e: e["tocPageNumber"])

    report = {
        "createdUtc": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "tocEntries": len(toc_entries_sorted),
            "specStartsFound": len(first_map),
            "missingSpecStarts": 0,
            "orderMismatches": 0,
        },
        "entries": [],
        "orderMismatches": [],
    }

    last_start = -1
    for i, entry in enumerate(toc_entries_sorted):
        spec = entry["spec"]
        start = first_map.get(spec)
        if not start:
            report["summary"]["missingSpecStarts"] += 1
        start_global = start["globalPageIndex"] if start else None
        start_source_page = start["sourcePageNumber"] if start else None
        start_source_pdf = start["sourcePdf"] if start else None

        end_global = None
        if start and i + 1 < len(toc_entries_sorted):
            next_spec = toc_entries_sorted[i + 1]["spec"]
            next_start = first_map.get(next_spec)
            if next_start:
                end_global = next_start["globalPageIndex"] - 1

        if start_global is not None and last_start > start_global:
            report["summary"]["orderMismatches"] += 1
            report["orderMismatches"].append(
                {
                    "spec": spec,
                    "startGlobalPage": start_global,
                    "previousStartGlobalPage": last_start,
                }
            )
        if start_global is not None:
            last_start = start_global

        report["entries"].append(
            {
                "spec": spec,
                "tocPageNumber": entry["tocPageNumber"],
                "tocLine": entry.get("tocLine"),
                "startGlobalPage": start_global,
                "startSourcePage": start_source_page,
                "startSourcePdf": start_source_pdf,
                "rangeEndGlobalPage": end_global,
            }
        )

    out_path = os.path.join(output_root, "toc_index_pass10.json")
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)

    print("TOC index pass complete.")


if __name__ == "__main__":
    main()
