import json
import os
import re
from datetime import datetime, timezone
from PIL import Image
import pytesseract
import fitz  # PyMuPDF
import io


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


def main():
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    output_root = os.path.join(repo_root, "sectionII_partA_data_digitized")
    validation_path = os.path.join(output_root, "validation_pass4.json")
    manifest_path = os.path.join(output_root, "manifest.json")
    notes_dir = os.path.join(output_root, "note_ocr")
    os.makedirs(notes_dir, exist_ok=True)

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
        base_name = f"page-{page_index:04d}"
        poppler_path = os.path.join(output_root, "raster_poppler", f"{base_name}-1.png")
        fallback_path = os.path.join(output_root, "raster_low_conf", f"{base_name}.png")

        image_path = poppler_path if os.path.exists(poppler_path) else fallback_path
        image = None
        if os.path.exists(image_path):
            image = Image.open(image_path)
        else:
            source_pdf = page.get("sourcePdf")
            source_page = page.get("sourcePageNumber")
            pdf_path = pdf_map.get(source_pdf)
            if pdf_path and source_page:
                doc = fitz.open(pdf_path)
                try:
                    page_obj = doc.load_page(source_page - 1)
                    pix = page_obj.get_pixmap(matrix=fitz.Matrix(200 / 72.0, 200 / 72.0), alpha=False)
                    image = Image.open(io.BytesIO(pix.tobytes("png")))
                finally:
                    doc.close()

        if image is None:
            continue
        ocr_text = pytesseract.image_to_string(image)
        notes = extract_notes(ocr_text)

        out_path = os.path.join(notes_dir, f"{base_name}.txt")
        with open(out_path, "w", encoding="utf-8") as handle:
            handle.write(ocr_text)

        json_rel = page_map.get(page_index)
        page_json_path = os.path.join(output_root, json_rel) if json_rel else None
        if page_json_path and os.path.exists(page_json_path):
            with open(page_json_path, "r", encoding="utf-8") as handle:
                page_json = json.load(handle)
            page_json["noteOcrPath"] = f"note_ocr/{base_name}.txt"
            page_json["noteOcrCount"] = len(notes)
            page_json["noteOcrNotes"] = notes
            with open(page_json_path, "w", encoding="utf-8") as handle:
                json.dump(page_json, handle, indent=2)

        report["pagesProcessed"] += 1
        report["notesFound"] += len(notes)
        if notes:
            report["pagesWithNotes"] += 1

    report_path = os.path.join(output_root, "note_gap_pass7.json")
    with open(report_path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)

    print("Note gap pass complete.")


if __name__ == "__main__":
    main()
