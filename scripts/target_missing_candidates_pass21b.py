import json
import os
import pathlib
import re
import subprocess
from datetime import datetime, timezone

from PIL import Image
import pytesseract

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / "sectionII_partA_data_digitized"
AI_REVIEW_DIR = DATA / "ai_review"
HIT_LIST = AI_REVIEW_DIR / "missing_no_candidate_hit_list.md"
SPEC_PDFS = DATA / "spec_pdfs"
OUTPUT_DIR = DATA / "missing_target_ocr_full"
OUTPUT_LOG = DATA / "missing_target_pass21b.json"

DEFAULT_TESSERACT = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
MAX_PAGES = int(os.environ.get("MISSING_FULL_SCAN_MAX_PAGES", "0"))

NOTE_RE = re.compile(r"\bNOTE\s*(\d+)\b", re.IGNORECASE)
TABLE_RE = re.compile(r"\bTABLE\s*(\d+)\b", re.IGNORECASE)


def configure_tesseract():
    cmd = os.environ.get("TESSERACT_CMD")
    if cmd and pathlib.Path(cmd).exists():
        pytesseract.pytesseract.tesseract_cmd = cmd
        return
    if pathlib.Path(DEFAULT_TESSERACT).exists():
        pytesseract.pytesseract.tesseract_cmd = DEFAULT_TESSERACT


def get_poppler_bin():
    poppler = ROOT / "tools" / "poppler" / "poppler-25.12.0" / "Library" / "bin"
    if poppler.exists():
        return poppler
    return None


def parse_hit_list(text):
    sections = re.split(r"^##\s+\d+\.\s+", text, flags=re.MULTILINE)
    items = []
    for sec in sections[1:]:
        lines = sec.strip().splitlines()
        if not lines:
            continue
        header = lines[0]
        header_ascii = "".join(ch for ch in header if ch.isascii())
        spec_match = re.match(r"([A-Z0-9\-]+)", header_ascii)
        spec = spec_match.group(1) if spec_match else None
        kind = "note" if "Note" in header_ascii or "NOTE" in header_ascii else "table"
        number_match = re.search(r"(Note|NOTE|Table|TABLE)\s+(\d+)", header_ascii)
        number = int(number_match.group(2)) if number_match else None
        pdf_match = re.search(r"`spec_pdfs/([^`]+)`", sec)
        pdf_name = pdf_match.group(1) if pdf_match else None
        items.append(
            {
                "spec": spec,
                "kind": kind,
                "number": number,
                "pdf": pdf_name,
            }
        )
    return items


def raster_page(pdf_path, page_num, out_path):
    poppler_bin = get_poppler_bin()
    if not poppler_bin:
        raise RuntimeError("Poppler not installed. Run scripts/install_poppler.ps1 first.")
    pdftoppm = poppler_bin / "pdftoppm.exe"
    if not pdftoppm.exists():
        raise RuntimeError("pdftoppm.exe not found in Poppler bin.")
    base = out_path.with_suffix("")
    subprocess.run(
        [
            str(pdftoppm),
            "-r",
            "300",
            "-f",
            str(page_num),
            "-l",
            str(page_num),
            "-png",
            str(pdf_path),
            str(base),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    candidates = list(out_path.parent.glob(base.name + "-*.png"))
    if not candidates:
        raise RuntimeError(f"Raster missing for page {page_num}")
    return candidates[0]


def extract_note_block(text, number):
    lines = text.splitlines()
    capture = []
    in_note = False
    for line in lines:
        match = NOTE_RE.search(line)
        if match and int(match.group(1)) == number:
            in_note = True
            capture.append(line)
            continue
        if in_note:
            if not line.strip():
                break
            if NOTE_RE.search(line):
                break
            capture.append(line)
    return "\n".join(capture).strip() if capture else None


def extract_table_line(text, number):
    for line in text.splitlines():
        match = TABLE_RE.search(line)
        if match and int(match.group(1)) == number:
            return line.strip()
    return None


def merge_into_spec(spec, kind, number, page_num, snippet):
    spec_txt = DATA / "spec_corpus" / spec / "spec.txt"
    if not spec_txt.exists():
        return False
    text = spec_txt.read_text(encoding="utf-8", errors="ignore")
    if kind == "note":
        header = "Resolved Notes (Targeted OCR)"
    else:
        header = "Resolved Tables (Targeted OCR)"
    block = f"{header}\n"
    if header in text:
        block = ""
    entry = f"{kind.upper()} {number} (spec page {page_num})\n{snippet}"
    if entry in text:
        return False
    text = text.rstrip() + "\n\n" + block + entry + "\n"
    spec_txt.write_text(text, encoding="utf-8")
    return True


def main():
    configure_tesseract()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if not HIT_LIST.exists():
        print("Hit list not found.")
        return
    hit_text = HIT_LIST.read_text(encoding="utf-8", errors="ignore")
    items = parse_hit_list(hit_text)

    results = []
    merged = 0
    for item in items:
        spec = item.get("spec")
        pdf_name = item.get("pdf")
        number = item.get("number")
        kind = item.get("kind")
        if not spec or not pdf_name or not number:
            results.append({**item, "status": "skipped_missing_metadata"})
            continue
        pdf_path = SPEC_PDFS / pdf_name
        if not pdf_path.exists():
            results.append({**item, "status": "missing_pdf"})
            continue
        spec_dir = OUTPUT_DIR / spec
        spec_dir.mkdir(parents=True, exist_ok=True)

        # Determine page count via spec pdf length
        from pypdf import PdfReader

        reader = PdfReader(str(pdf_path))
        page_count = len(reader.pages)
        scan_limit = page_count if MAX_PAGES == 0 else min(page_count, MAX_PAGES)

        found = None
        found_page = None
        for page in range(1, scan_limit + 1):
            raster_path = spec_dir / f"page-{page:04d}.png"
            if not raster_path.exists():
                raster_path = raster_page(pdf_path, page, raster_path)
            image = Image.open(raster_path)
            text = pytesseract.image_to_string(image, config="--psm 6")
            if kind == "note":
                block = extract_note_block(text, number)
                if block:
                    found = block
                    found_page = page
                    break
            else:
                line = extract_table_line(text, number)
                if line:
                    found = line
                    found_page = page
                    break
        status = "found" if found else "not_found"
        if found:
            if merge_into_spec(spec, kind, number, found_page, found):
                merged += 1
        results.append(
            {
                **item,
                "status": status,
                "foundPage": found_page,
                "snippet": found,
                "pagesScanned": scan_limit,
            }
        )

    out = {
        "createdUtc": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "items": len(items),
            "found": len([r for r in results if r.get("status") == "found"]),
            "merged": merged,
        },
        "results": results,
    }
    OUTPUT_LOG.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print("Target missing candidates full scan complete.")


if __name__ == "__main__":
    main()
