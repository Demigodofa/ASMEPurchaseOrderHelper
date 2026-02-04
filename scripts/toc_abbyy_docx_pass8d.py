import json
import os
import pathlib
import re
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / "sectionII_partA_data_digitized"

DEFAULT_MANIFEST = DATA / "abbyy_docx" / "abbyy_docx_manifest.json"
ABBYY_MANIFEST_PATH = pathlib.Path(
    os.environ.get("ABBYY_DOCX_MANIFEST", DEFAULT_MANIFEST)
)
OUTPUT_PATH = DATA / os.environ.get("ABBYY_TOC_OUTPUT", "toc_abbyy_docx_pass8d.json")

TOC_HEADER_RE = re.compile(r"\bTABLE OF CONTENTS\b|\bCONTENTS\b", re.IGNORECASE)
SPEC_RE = re.compile(r"\bSA-\d{1,4}[A-Z]?\b")
PAGE_RE = re.compile(r"(\d{1,4})\s*$")
MAX_EMPTY_PAGES = int(os.environ.get("ABBYY_TOC_MAX_EMPTY_PAGES", "2"))


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def read_page_text(text_path):
    path = DATA / text_path
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def is_toc_header(text):
    return bool(TOC_HEADER_RE.search(text))


def parse_toc_lines(text):
    entries = []
    for line in text.splitlines():
        if not SPEC_RE.search(line):
            continue
        spec_match = SPEC_RE.search(line)
        spec = spec_match.group(0).upper()
        page_match = PAGE_RE.search(line)
        toc_page = int(page_match.group(1)) if page_match else None
        entries.append({"spec": spec, "tocLine": line.strip(), "tocPageNumber": toc_page})
    return entries


def main():
    if not ABBYY_MANIFEST_PATH.exists():
        raise FileNotFoundError(f"ABBYY manifest not found: {ABBYY_MANIFEST_PATH}")
    manifest = load_json(ABBYY_MANIFEST_PATH)
    pages = manifest.get("pages", [])

    toc_pages = []
    collecting = False
    empty_count = 0

    for page in pages:
        text = read_page_text(page.get("textPath", ""))
        if not text:
            if collecting:
                empty_count += 1
            if empty_count > MAX_EMPTY_PAGES:
                break
            continue
        if is_toc_header(text):
            collecting = True
            empty_count = 0
        if not collecting:
            continue
        entries = parse_toc_lines(text)
        if entries:
            toc_pages.append(
                {
                    "abbyyPageIndex": page.get("abbyyPageIndex"),
                    "textPath": page.get("textPath"),
                    "entries": entries,
                }
            )
            empty_count = 0
        else:
            empty_count += 1
            if empty_count > MAX_EMPTY_PAGES:
                break

    flat_entries = []
    for page in toc_pages:
        for entry in page["entries"]:
            flat_entries.append(
                {
                    "spec": entry["spec"],
                    "tocPageNumber": entry["tocPageNumber"],
                    "tocLine": entry["tocLine"],
                    "abbyyPageIndex": page["abbyyPageIndex"],
                    "textPath": page["textPath"],
                }
            )

    result = {
        "createdUtc": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "pagesScanned": len(pages),
            "tocPages": len(toc_pages),
            "entries": len(flat_entries),
            "manifestPath": str(ABBYY_MANIFEST_PATH),
        },
        "pages": toc_pages,
        "entries": flat_entries,
    }
    OUTPUT_PATH.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print("ABBYY TOC pass 8d complete.")


if __name__ == "__main__":
    main()
