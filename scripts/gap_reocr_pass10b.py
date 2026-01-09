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
    crossref_path = os.path.join(output_root, "crossref_pass9.json")
    manifest_path = os.path.join(output_root, "manifest.json")
    out_dir = os.path.join(output_root, "gap_ocr_highdpi")
    os.makedirs(out_dir, exist_ok=True)

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

    with open(crossref_path, "r", encoding="utf-8") as handle:
        crossref = json.load(handle)
    with open(manifest_path, "r", encoding="utf-8") as handle:
        manifest = json.load(handle)

    page_map = {p.get("globalPageIndex"): p for p in manifest.get("pages", [])}
    pdf_map = {os.path.basename(p): p for p in manifest.get("sourcePdfs", [])}

    gap_counts = {}
    for entry in crossref.get("tableRefGaps", []):
        gap_counts[entry["globalPageIndex"]] = gap_counts.get(entry["globalPageIndex"], 0) + 1
    for entry in crossref.get("noteRefGaps", []):
        gap_counts[entry["globalPageIndex"]] = gap_counts.get(entry["globalPageIndex"], 0) + 1

    top_pages = sorted(gap_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:20]

    report = {
        "createdUtc": datetime.now(timezone.utc).isoformat(),
        "pagesProcessed": 0,
        "topPages": [],
    }

    for page_index, gap_count in top_pages:
        page_entry = page_map.get(page_index)
        if not page_entry:
            continue

        json_path = os.path.join(output_root, page_entry["json"])
        with open(json_path, "r", encoding="utf-8") as handle:
            page_json = json.load(handle)

        source_pdf = page_json.get("sourcePdf")
        source_page = page_json.get("sourcePageNumber")
        pdf_path = pdf_map.get(source_pdf)
        if not pdf_path or not source_page:
            continue

        base_name = f"page-{page_index:04d}"
        out_prefix = os.path.join(out_dir, base_name)
        expected_png = out_prefix + "-1.png"
        if not os.path.exists(expected_png):
            render_poppler(pdftoppm, pdf_path, source_page, out_prefix, dpi=300)

        png_candidates = [n for n in os.listdir(out_dir) if n.startswith(base_name + "-") and n.endswith(".png")]
        if not png_candidates and os.path.exists(expected_png):
            png_candidates = [os.path.basename(expected_png)]
        if not png_candidates:
            continue

        image_path = os.path.join(out_dir, png_candidates[0])
        image = Image.open(image_path)
        ocr_text = pytesseract.image_to_string(image, config="--psm 6")

        out_txt = os.path.join(out_dir, f"{base_name}.txt")
        with open(out_txt, "w", encoding="utf-8") as handle:
            handle.write(ocr_text)

        page_json["gapOcrHighDpiPath"] = f"gap_ocr_highdpi/{base_name}.txt"
        page_json["gapOcrHighDpiLength"] = len(ocr_text)

        with open(json_path, "w", encoding="utf-8") as handle:
            json.dump(page_json, handle, indent=2)

        report["pagesProcessed"] += 1
        report["topPages"].append(
            {
                "globalPageIndex": page_index,
                "gapCount": gap_count,
                "sourcePdf": source_pdf,
                "sourcePageNumber": source_page,
                "gapOcrHighDpiPath": page_json["gapOcrHighDpiPath"],
            }
        )

    report_path = os.path.join(output_root, "gap_reocr_pass10b.json")
    with open(report_path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)

    print("Gap re-OCR pass complete.")


if __name__ == "__main__":
    main()
