import json
import os
import re
from datetime import datetime, timezone

import fitz  # PyMuPDF
import pytesseract
from PIL import Image
import io


DEFAULT_TESSERACT = r"C:\Program Files\Tesseract-OCR\tesseract.exe"


def ensure_tesseract():
    if os.path.exists(DEFAULT_TESSERACT):
        pytesseract.pytesseract.tesseract_cmd = DEFAULT_TESSERACT


def load_manifest(output_root):
    manifest_path = os.path.join(output_root, "manifest.json")
    with open(manifest_path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def is_low_confidence(text):
    if not text:
        return True
    length = len(text)
    alpha = len(re.findall(r"[A-Za-z]", text))
    alpha_ratio = alpha / max(1, length)
    return length < 300 or alpha_ratio < 0.2


def render_page(doc, page_index, zoom=2.0):
    page = doc.load_page(page_index)
    matrix = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=matrix, alpha=False)
    return pix.tobytes("png")


def main():
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    output_root = os.path.join(repo_root, "sectionII_partA_data_digitized")
    ocr_dir = os.path.join(output_root, "ocr")
    os.makedirs(ocr_dir, exist_ok=True)

    ensure_tesseract()
    manifest = load_manifest(output_root)

    # Map source PDF names to full paths
    pdf_paths = {os.path.basename(p): p for p in manifest.get("sourcePdfs", [])}

    ocr_log = {
        "createdUtc": datetime.now(timezone.utc).isoformat(),
        "lowConfidenceThreshold": {"minLength": 300, "minAlphaRatio": 0.2},
        "processedPages": 0,
        "ocrAppliedPages": 0,
    }

    for page_entry in manifest.get("pages", []):
        json_path = os.path.join(output_root, page_entry["json"])
        with open(json_path, "r", encoding="utf-8") as handle:
            page_json = json.load(handle)

        text = page_json.get("text", "")
        if not is_low_confidence(text):
            continue

        source_pdf = page_json.get("sourcePdf")
        source_page = page_json.get("sourcePageNumber", 1)
        pdf_path = pdf_paths.get(source_pdf)
        if not pdf_path or not os.path.exists(pdf_path):
            continue

        doc = fitz.open(pdf_path)
        try:
            image_bytes = render_page(doc, source_page - 1)
        finally:
            doc.close()

        image = Image.open(io.BytesIO(image_bytes))
        ocr_text = pytesseract.image_to_string(image)
        base_name = f"page-{page_json.get('globalPageIndex', 0):04d}"
        ocr_path = os.path.join(ocr_dir, f"{base_name}.txt")
        with open(ocr_path, "w", encoding="utf-8") as handle:
            handle.write(ocr_text)

        page_json["ocrTextPath"] = f"ocr/{base_name}.txt"
        page_json["ocrTextLength"] = len(ocr_text)
        page_json["ocrApplied"] = True

        with open(json_path, "w", encoding="utf-8") as handle:
            json.dump(page_json, handle, indent=2)

        ocr_log["processedPages"] += 1
        ocr_log["ocrAppliedPages"] += 1

    log_path = os.path.join(output_root, "ocr_pass2_log.json")
    with open(log_path, "w", encoding="utf-8") as handle:
        json.dump(ocr_log, handle, indent=2)

    print("OCR pass complete.")


if __name__ == "__main__":
    main()
