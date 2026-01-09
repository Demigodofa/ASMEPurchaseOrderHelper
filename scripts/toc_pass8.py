import json
import os
import re
from datetime import datetime, timezone


SPEC_RE = re.compile(r"\b(?P<spec>(?:SA|SB|SF|A)-\d+[A-Z]?M?)\b", re.IGNORECASE)


def load_manifest(output_root):
    path = os.path.join(output_root, "manifest.json")
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def extract_toc_entries(pages):
    entries = []
    for page in pages:
        text = page.get("text", "")
        if "TABLE OF CONTENTS" not in text.upper():
            continue
        lines = text.replace("\r\n", "\n").split("\n")
        for line in lines:
            match = SPEC_RE.search(line)
            if not match:
                continue
            page_match = re.search(r"(\d{1,4})\s*$", line.strip())
            if not page_match:
                continue
            entries.append(
                {
                    "spec": match.group("spec").upper(),
                    "pageText": line.strip(),
                    "tocPageNumber": int(page_match.group(1)),
                }
            )
    return entries


def index_first_spec_pages(pages):
    first = {}
    for page in pages:
        text = page.get("text", "")
        top_lines = text.replace("\r\n", "\n").split("\n")[:10]
        header_block = " ".join(top_lines)
        match = SPEC_RE.search(header_block)
        if not match:
            continue
        spec = match.group("spec").upper()
        if spec not in first:
            first[spec] = {
                "globalPageIndex": page.get("globalPageIndex"),
                "sourcePdf": page.get("sourcePdf"),
                "sourcePageNumber": page.get("sourcePageNumber"),
                "headerSnippet": header_block[:200],
            }
    return first


def main():
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    output_root = os.path.join(repo_root, "sectionII_partA_data_digitized")

    manifest = load_manifest(output_root)

    pages = []
    for page_entry in manifest.get("pages", []):
        json_path = os.path.join(output_root, page_entry["json"])
        with open(json_path, "r", encoding="utf-8") as handle:
            pages.append(json.load(handle))

    toc_entries = extract_toc_entries(pages)
    first_pages = index_first_spec_pages(pages)

    toc_report = {
        "createdUtc": datetime.now(timezone.utc).isoformat(),
        "entries": [],
        "summary": {
            "tocEntries": len(toc_entries),
            "specsFoundInHeaders": len(first_pages),
            "missingSpecsFromHeaders": 0,
        },
    }

    missing = 0
    for entry in toc_entries:
        spec = entry["spec"]
        found = first_pages.get(spec)
        if not found:
            missing += 1
        toc_report["entries"].append(
            {
                "spec": spec,
                "tocPageNumber": entry["tocPageNumber"],
                "tocLine": entry["pageText"],
                "foundHeader": found is not None,
                "foundHeaderPage": found,
            }
        )

    toc_report["summary"]["missingSpecsFromHeaders"] = missing

    out_path = os.path.join(output_root, "toc_pass8.json")
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(toc_report, handle, indent=2)

    print("TOC pass complete.")


if __name__ == "__main__":
    main()
