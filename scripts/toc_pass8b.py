import json
import os
import re
from datetime import datetime, timezone


SPEC_RE = re.compile(r"\b(?P<spec>(?:SA|SB|SF|A)-\d+[A-Z]?M?)\b", re.IGNORECASE)
PAGE_RE = re.compile(r"(?P<page>\d{1,4})\s*$")


def load_manifest(output_root):
    path = os.path.join(output_root, "manifest.json")
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def load_page_text(output_root, page_entry):
    best_path = page_entry.get("bestTextPath")
    if best_path:
        abs_best = os.path.join(output_root, best_path)
        if os.path.exists(abs_best):
            with open(abs_best, "r", encoding="utf-8") as handle:
                return handle.read()
    json_path = os.path.join(output_root, page_entry["json"])
    with open(json_path, "r", encoding="utf-8") as handle:
        page_json = json.load(handle)
    return page_json.get("text", "")


def normalize_line(line):
    return re.sub(r"\s+", " ", line.strip())


def extract_toc_entries(text):
    entries = []
    lines = text.replace("\r\n", "\n").split("\n")
    for line in lines:
        norm = normalize_line(line)
        if not norm:
            continue
        # Strip BPVC year to avoid false page number matches
        scrubbed = re.sub(r"ASME\s+BPVC\.II\.A-2025", "", norm, flags=re.IGNORECASE)
        scrubbed = re.sub(r"BPVC\.II\.A-2025", "", scrubbed, flags=re.IGNORECASE)
        match = SPEC_RE.search(scrubbed)
        if not match:
            continue
        spec = match.group("spec").upper()
        if spec == "A-2025":
            continue
        # Require leader dots or spacing + a distinct page number token
        if not (re.search(r"\.{2,}", scrubbed) or re.search(r"\s{2,}\d{1,4}\s*$", scrubbed)):
            continue
        numbers = [int(n) for n in re.findall(r"\d{1,4}", scrubbed)]
        spec_num = int(re.findall(r"\d{1,4}", spec)[0])
        if len(numbers) < 2:
            continue
        page_num = numbers[-1]
        if page_num == spec_num:
            continue
        entries.append(
            {
                "spec": spec,
                "tocLine": norm,
                "tocPageNumber": page_num,
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
    for entry in manifest.get("pages", []):
        text = load_page_text(output_root, entry)
        page = {
            "globalPageIndex": entry.get("globalPageIndex"),
            "sourcePdf": entry.get("sourcePdf"),
            "sourcePageNumber": entry.get("sourcePageNumber"),
            "text": text,
        }
        pages.append(page)

    # Prefer explicit TOC range: page 3-15 of first PDF
    first_pdf = manifest.get("sourcePdfs", [None])[0]
    first_pdf_name = os.path.basename(first_pdf) if first_pdf else None
    toc_pages = [
        p
        for p in pages
        if p.get("sourcePdf") == first_pdf_name
        and 3 <= int(p.get("sourcePageNumber", 0)) <= 15
    ]

    entries = []
    for toc_page in toc_pages:
        entries.extend(extract_toc_entries(toc_page["text"]))

    # De-dupe by spec + page number
    dedup = {}
    for entry in entries:
        key = (entry["spec"], entry["tocPageNumber"])
        dedup[key] = entry
    entries = list(dedup.values())

    first_pages = index_first_spec_pages(pages)

    toc_report = {
        "createdUtc": datetime.now(timezone.utc).isoformat(),
        "entries": [],
        "summary": {
            "tocEntries": len(entries),
            "specsFoundInHeaders": len(first_pages),
            "missingSpecsFromHeaders": 0,
        },
    }

    missing = 0
    for entry in sorted(entries, key=lambda e: (e["spec"], e["tocPageNumber"])):
        spec = entry["spec"]
        found = first_pages.get(spec)
        if not found:
            missing += 1
        toc_report["entries"].append(
            {
                "spec": spec,
                "tocPageNumber": entry["tocPageNumber"],
                "tocLine": entry["tocLine"],
                "foundHeader": found is not None,
                "foundHeaderPage": found,
            }
        )

    toc_report["summary"]["missingSpecsFromHeaders"] = missing

    out_path = os.path.join(output_root, "toc_pass8b.json")
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(toc_report, handle, indent=2)

    print("TOC pass 8b complete.")


if __name__ == "__main__":
    main()
