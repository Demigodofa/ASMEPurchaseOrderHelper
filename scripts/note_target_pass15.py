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
MANIFEST_PATH = DATA / "manifest.json"
CROSSREF_PATH = DATA / "crossref_pass9.json"
OUTPUT_DIR = DATA / "note_target_ocr"
OUTPUT_LOG = DATA / "note_target_pass15.json"
RASTER_DIR = DATA / "raster_poppler"
APPSETTINGS_PATH = ROOT / "PoApp.Ingest.Cli" / "appsettings.json"

NOTE_WORD = "NOTE"
NOTE_WORD_ALT = "NOTES"
NOTE_NUM_RE = re.compile(r"\d+")
DEFAULT_TESSERACT = r"C:\Program Files\Tesseract-OCR\tesseract.exe"


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


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


def load_appsettings():
    if APPSETTINGS_PATH.exists():
        return json.loads(APPSETTINGS_PATH.read_text(encoding="utf-8"))
    return {}


def resolve_pdf_path(appsettings, source_pdf):
    pdf_files = appsettings.get("Paths", {}).get("PdfFiles") or []
    for entry in pdf_files:
        if entry.endswith(source_pdf):
            return entry
    pdf_root = appsettings.get("Paths", {}).get("PdfSourceRoot")
    if pdf_root:
        candidate = pathlib.Path(pdf_root) / source_pdf
        if candidate.exists():
            return str(candidate)
    desktop = pathlib.Path(os.path.expanduser("~")) / "Desktop" / source_pdf
    return str(desktop)


def ensure_raster(page_info):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    base_name = f"page-{page_info['globalPageIndex']:04d}"
    existing = list(RASTER_DIR.glob(f"{base_name}-*.png"))
    if existing:
        return existing[0]
    poppler_bin = get_poppler_bin()
    if not poppler_bin:
        raise RuntimeError("Poppler not installed. Run scripts/install_poppler.ps1 first.")
    pdftoppm = poppler_bin / "pdftoppm.exe"
    if not pdftoppm.exists():
        raise RuntimeError("pdftoppm.exe not found in Poppler bin.")
    output_base = RASTER_DIR / base_name
    RASTER_DIR.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            str(pdftoppm),
            "-r",
            "400",
            "-f",
            str(page_info["sourcePageNumber"]),
            "-l",
            str(page_info["sourcePageNumber"]),
            "-png",
            str(pathlib.Path(page_info["sourcePdfPath"])),
            str(output_base),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    candidates = list(RASTER_DIR.glob(f"{base_name}-*.png"))
    if not candidates:
        raise RuntimeError(f"Raster missing after pdftoppm: {output_base}")
    return candidates[0]


def load_manifest_pages():
    manifest = load_json(MANIFEST_PATH)
    pages = {}
    for page in manifest.get("pages", []):
        pages[page["globalPageIndex"]] = page
    return pages


def find_note_headers(image):
    data = pytesseract.image_to_data(
        image, output_type=pytesseract.Output.DICT, config="--psm 6"
    )
    headers = []
    for i, word in enumerate(data.get("text", [])):
        if not word:
            continue
        normalized = word.strip().upper()
        note_number = None
        if normalized.startswith(NOTE_WORD) or normalized.startswith(NOTE_WORD_ALT):
            digits = NOTE_NUM_RE.findall(normalized)
            if digits:
                note_number = int(digits[0])
            elif i + 1 < len(data["text"]):
                next_word = data["text"][i + 1].strip()
                digits = NOTE_NUM_RE.findall(next_word)
                if digits:
                    note_number = int(digits[0])
        if note_number is None:
            continue
        x = data["left"][i]
        y = data["top"][i]
        h = data["height"][i]
        headers.append(
            {
                "noteNumber": note_number,
                "x": x,
                "y": y,
                "h": h,
            }
        )
    headers.sort(key=lambda h: h["y"])
    return headers


def crop_note_regions(image, headers):
    regions = []
    if not headers:
        return regions
    width, height = image.size
    for idx, header in enumerate(headers):
        y_start = max(0, header["y"] - 10)
        if idx + 1 < len(headers):
            y_end = headers[idx + 1]["y"] - 10
        else:
            y_end = min(height, header["y"] + int(height * 0.45))
        y_end = max(y_end, y_start + 50)
        box = (0, y_start, width, y_end)
        regions.append({"noteNumber": header["noteNumber"], "box": box})
    return regions


def ocr_region(image, region):
    cropped = image.crop(region["box"])
    text = pytesseract.image_to_string(cropped, config="--psm 6")
    return text.strip()


def main():
    configure_tesseract()
    appsettings = load_appsettings()
    pages = load_manifest_pages()
    crossref = load_json(CROSSREF_PATH) if CROSSREF_PATH.exists() else {}
    note_gaps = crossref.get("noteRefGaps", [])
    target_pages = sorted({gap["globalPageIndex"] for gap in note_gaps})

    output_entries = []
    for global_idx in target_pages:
        page_info = pages.get(global_idx)
        if not page_info:
            continue
        source_pdf = page_info["sourcePdf"]
        page_info["sourcePdfPath"] = resolve_pdf_path(appsettings, source_pdf)
        try:
            image_path = ensure_raster(page_info)
        except Exception as exc:
            output_entries.append(
                {
                    "globalPageIndex": global_idx,
                    "error": str(exc),
                }
            )
            continue
        image = Image.open(image_path)
        headers = find_note_headers(image)
        regions = crop_note_regions(image, headers)
        page_outputs = []
        for region in regions:
            text = ocr_region(image, region)
            out_path = OUTPUT_DIR / f"page-{global_idx:04d}-note-{region['noteNumber']:02d}.txt"
            out_path.write_text(text, encoding="utf-8")
            page_outputs.append(
                {
                    "noteNumber": region["noteNumber"],
                    "textPath": str(out_path.relative_to(DATA)),
                    "length": len(text),
                }
            )
        output_entries.append(
            {
                "globalPageIndex": global_idx,
                "noteHeaders": headers,
                "notesExtracted": len(page_outputs),
                "outputs": page_outputs,
            }
        )

    result = {
        "createdUtc": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "targetPages": len(target_pages),
            "pagesProcessed": len(output_entries),
            "notesExtracted": sum(item.get("notesExtracted", 0) for item in output_entries),
        },
        "pages": output_entries,
    }
    OUTPUT_LOG.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print("Note target pass complete.")


if __name__ == "__main__":
    main()
