import json
import os
import re
import subprocess
from datetime import datetime, timezone
from PIL import Image
import pytesseract


TESSERACT_EXE = r"C:\Program Files\Tesseract-OCR\tesseract.exe"


def ensure_tesseract():
    if os.path.exists(TESSERACT_EXE):
        pytesseract.pytesseract.tesseract_cmd = TESSERACT_EXE


def extract_notes(text):
    notes = []
    for line in text.splitlines():
        if re.match(r"^(NOTE|NOTES|Note)\b", line.strip()):
            notes.append(line.strip())
    return notes


def render_poppler(pdftoppm, pdf_path, page_num, out_prefix, dpi=300):
    args = [
        pdftoppm,
        "-r",
        str(dpi),
        "-f",
        str(page_num),
        "-l",
        str(page_num),
        "-png",
        pdf_path,
        out_prefix,
    ]
    subprocess.run(args, check=True)


def main():
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    output_root = os.path.join(repo_root, "sectionII_partA_data_digitized")
    validation_path = os.path.join(output_root, "validation_pass4.json")
    manifest_path = os.path.join(output_root, "manifest.json")
    notes_dir = os.path.join(output_root, "note_ocr_highdpi")
    os.makedirs(notes_dir, exist_ok=True)

    pdftoppm = os.path.join(
        repo_root,
        "tools",
        "poppler",
        "poppler-25.12.0",
        "Library",
        "bin",
        "pdftoppm.exe",
    )
    if not os.path.exists(pdftoppm):
        raise FileNotFoundError(f"pdftoppm not found: {pdftoppm}")

    ensure_tesseract()

    with open(validation_path, "r", encoding="utf-8") as handle:
        validation = json.load(handle)
    with open(manifest_path, "r", encoding="utf-8") as handle:
        manifest = json.load(handle)

    page_map = {p.get("globalPageIndex"): p.get("json") for p in manifest.get("pages", [])}
    pdf_map = {os.path.basename(p): p for p in manifest.get("sourcePdfs", [])}

    report = {
        "createdUtc": datetime.now(timezone.utc).isoformat(),
        "pagesProcessed": 0,
        "notesFound": 0,
        "pagesWithNotes": 0,
    }

    for page in validation.get("pages", []):
        if not page.get("noteGap"):
            continue

        page_index = page.get("globalPageIndex", 0)
        json_rel = page_map.get(page_index)
        if not json_rel:
            continue
        page_json_path = os.path.join(output_root, json_rel)
        with open(page_json_path, "r", encoding="utf-8") as handle:
            page_json = json.load(handle)

        if page_json.get("noteOcrCount", 0) > 0:
            continue

        source_pdf = page_json.get("sourcePdf")
        source_page = page_json.get("sourcePageNumber")
        pdf_path = pdf_map.get(source_pdf)
        if not pdf_path or not source_page:
            continue

        base_name = f"page-{page_index:04d}"
        out_prefix = os.path.join(notes_dir, base_name)
        expected_png = out_prefix + "-1.png"
        if not os.path.exists(expected_png):
            render_poppler(pdftoppm, pdf_path, source_page, out_prefix, dpi=300)
        # pdftoppm may output prefix-<page>.png; pick first match
        candidates = []
        for name in os.listdir(notes_dir):
            if name.startswith(base_name + "-") and name.endswith(".png"):
                candidates.append(os.path.join(notes_dir, name))
        if not candidates and os.path.exists(expected_png):
            candidates.append(expected_png)
        if not candidates:
            continue

        image = Image.open(candidates[0])
        ocr_text = pytesseract.image_to_string(image)
        notes = extract_notes(ocr_text)

        out_txt = os.path.join(notes_dir, f"{base_name}.txt")
        with open(out_txt, "w", encoding="utf-8") as handle:
            handle.write(ocr_text)

        page_json["noteOcrHighDpiPath"] = f"note_ocr_highdpi/{base_name}.txt"
        page_json["noteOcrHighDpiCount"] = len(notes)
        page_json["noteOcrHighDpiNotes"] = notes

        with open(page_json_path, "w", encoding="utf-8") as handle:
            json.dump(page_json, handle, indent=2)

        report["pagesProcessed"] += 1
        report["notesFound"] += len(notes)
        if notes:
            report["pagesWithNotes"] += 1

    report_path = os.path.join(output_root, "note_gap_pass7b.json")
    with open(report_path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)

    print("Note gap pass 7b complete.")


if __name__ == "__main__":
    main()
