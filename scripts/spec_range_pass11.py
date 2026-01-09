import json
import os
import re
from datetime import datetime, timezone


SPEC_RE = re.compile(r"\b(?P<spec>(?:SA|SB|SF|A)-\d+[A-Z]?M?)\b", re.IGNORECASE)


def load_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


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


def detect_spec(text):
    if not text:
        return None
    top_lines = text.replace("\r\n", "\n").split("\n")[:10]
    for line in top_lines:
        line_norm = re.sub(r"\s+", " ", line.strip())
        if not line_norm:
            continue
        if "TABLE" in line_norm.upper():
            continue
        match = SPEC_RE.search(line_norm)
        if not match:
            continue
        spec = match.group("spec").upper()
        if line_norm.startswith(spec) or "SPECIFICATION" in line_norm.upper() or "ASME" in line_norm.upper():
            return spec
    header_block = " ".join(top_lines)
    match = SPEC_RE.search(header_block)
    return match.group("spec").upper() if match else None


def main():
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    output_root = os.path.join(repo_root, "sectionII_partA_data_digitized")
    toc_index_path = os.path.join(output_root, "toc_index_pass10.json")
    manifest_path = os.path.join(output_root, "manifest.json")

    toc_index = load_json(toc_index_path)
    manifest = load_json(manifest_path)
    pages = manifest.get("pages", [])

    page_by_global = {p.get("globalPageIndex"): p for p in pages}

    report = {
        "createdUtc": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "specsChecked": 0,
            "rangesMissing": 0,
            "rangeIntrusions": 0,
            "emptyBestTextPages": 0,
        },
        "ranges": [],
        "intrusions": [],
    }

    for entry in toc_index.get("entries", []):
        spec = entry.get("spec")
        start = entry.get("startGlobalPage")
        end = entry.get("rangeEndGlobalPage")
        if start is None or end is None or end < start:
            report["summary"]["rangesMissing"] += 1
            report["ranges"].append(
                {
                    "spec": spec,
                    "startGlobalPage": start,
                    "endGlobalPage": end,
                    "status": "missing-range",
                }
            )
            continue

        report["summary"]["specsChecked"] += 1
        empty_pages = 0
        intrusions = []
        for g in range(start, end + 1):
            page_entry = page_by_global.get(g)
            if not page_entry:
                continue
            text = load_best_text(output_root, page_entry)
            if not text.strip():
                empty_pages += 1
            detected = detect_spec(text)
            if detected and detected != spec:
                intrusions.append(
                    {
                        "globalPageIndex": g,
                        "detectedSpec": detected,
                        "sourcePdf": page_entry.get("sourcePdf"),
                        "sourcePageNumber": page_entry.get("sourcePageNumber"),
                    }
                )

        report["summary"]["emptyBestTextPages"] += empty_pages
        if intrusions:
            report["summary"]["rangeIntrusions"] += 1
            report["intrusions"].append(
                {
                    "spec": spec,
                    "startGlobalPage": start,
                    "endGlobalPage": end,
                    "intrusions": intrusions,
                }
            )

        report["ranges"].append(
            {
                "spec": spec,
                "startGlobalPage": start,
                "endGlobalPage": end,
                "emptyBestTextPages": empty_pages,
                "intrusionCount": len(intrusions),
            }
        )

    out_path = os.path.join(output_root, "spec_range_pass11.json")
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)

    print("Spec range pass complete.")


if __name__ == "__main__":
    main()
