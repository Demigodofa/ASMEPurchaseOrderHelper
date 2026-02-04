import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path


SPEC_RE = re.compile(r"\b(?P<spec>(?:SA|SB|SF)-\d+[A-Z]?M?)\b", re.IGNORECASE)


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8", errors="ignore"))


def load_best_text(output_root: Path, page_entry: dict) -> str:
    best_path = page_entry.get("bestTextPath")
    if not best_path and page_entry.get("json"):
        json_path = output_root / page_entry["json"]
        if json_path.exists():
            page_json = load_json(json_path)
            best_path = page_json.get("bestTextPath")
            if not best_path:
                return page_json.get("text", "")

    if best_path:
        abs_path = output_root / best_path
        if abs_path.exists():
            return abs_path.read_text(encoding="utf-8", errors="ignore")
    return ""


def index_first_spec_pages(output_root: Path, pages: list[dict]) -> dict:
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
        if spec.endswith("M"):
            spec = spec[:-1]
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
    return first


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build TOC index using a provided TOC entries JSON."
    )
    parser.add_argument(
        "--toc",
        required=True,
        help="Path to TOC entries JSON (from toc_pass8c_sa451_end.py).",
    )
    parser.add_argument(
        "--output-root",
        required=True,
        help="Root folder containing manifest.json and page JSON/text.",
    )
    parser.add_argument("--out", required=True, help="Output TOC index JSON path.")
    args = parser.parse_args()

    toc_path = Path(args.toc).resolve()
    output_root = Path(args.output_root).resolve()
    out_path = Path(args.out).resolve()

    toc_payload = load_json(toc_path)
    toc_entries = toc_payload.get("entries", [])

    manifest_path = output_root / "manifest.json"
    manifest = load_json(manifest_path)
    pages = manifest.get("pages", [])

    first_map = index_first_spec_pages(output_root, pages)
    toc_entries_sorted = sorted(toc_entries, key=lambda e: e.get("tocPageNumber") or 0)

    report = {
        "createdUtc": datetime.now(timezone.utc).isoformat(),
        "tocSource": str(toc_path),
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
                "tocPageNumber": entry.get("tocPageNumber"),
                "tocLine": entry.get("tocLine"),
                "tocSourcePage": entry.get("tocSourcePage"),
                "startGlobalPage": start_global,
                "startSourcePage": start_source_page,
                "startSourcePdf": start_source_pdf,
                "rangeEndGlobalPage": end_global,
            }
        )

    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("TOC index pass complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
