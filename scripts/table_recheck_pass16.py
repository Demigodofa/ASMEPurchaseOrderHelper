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
OUTPUT_DIR = DATA / "table_target_ocr"
OUTPUT_LOG = DATA / "table_recheck_pass16.json"
RASTER_DIR = DATA / "raster_poppler"
APPSETTINGS_PATH = ROOT / "PoApp.Ingest.Cli" / "appsettings.json"

TABLE_WORD_RE = re.compile(r"^TABLES?$", re.IGNORECASE)
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


def get_poppler_bin():
    poppler = ROOT / "tools" / "poppler" / "poppler-25.12.0" / "Library" / "bin"
    if poppler.exists():
        return poppler
    return None


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


def alpha_ratio(text):
    if not text:
        return 0.0
    alpha = sum(1 for ch in text if ch.isalpha())
    return alpha / max(1, len(text))


def load_manifest_pages():
    manifest = load_json(MANIFEST_PATH)
    pages = {}
    for page in manifest.get("pages", []):
        pages[page["globalPageIndex"]] = page
    return pages


def find_table_lines(image):
    data = pytesseract.image_to_data(
        image, output_type=pytesseract.Output.DICT, config="--psm 6"
    )
    hits = []
    for i, word in enumerate(data.get("text", [])):
        if not word:
            continue
        if TABLE_WORD_RE.match(word.strip()):
            hits.append(
                {
                    "block": data.get("block_num", [0])[i],
                    "par": data.get("par_num", [0])[i],
                    "line": data.get("line_num", [0])[i],
                    "x": data["left"][i],
                    "y": data["top"][i],
                    "h": data["height"][i],
                }
            )
    return hits


def crop_table_region(image, hits):
    width, height = image.size
    if not hits:
        return None
    top_hit = min(hits, key=lambda h: h["y"])
    y_start = max(0, top_hit["y"] - 10)
    y_end = min(height, y_start + int(height * 0.55))
    if y_end <= y_start:
        return None
    return (0, y_start, width, y_end)


def main():
    configure_tesseract()
    appsettings = load_appsettings()
    pages = load_manifest_pages()
    crossref = load_json(CROSSREF_PATH) if CROSSREF_PATH.exists() else {}
    table_gaps = crossref.get("tableRefGaps", [])
    target_pages = sorted({gap["globalPageIndex"] for gap in table_gaps})

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
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
        hits = find_table_lines(image)
        crop = crop_table_region(image, hits)
        if not crop:
            output_entries.append(
                {
                    "globalPageIndex": global_idx,
                    "tableWordHits": len(hits),
                    "status": "no-table-word-detected",
                }
            )
            continue
        cropped = image.crop(crop)
        text = pytesseract.image_to_string(cropped, config="--psm 6")
        out_path = OUTPUT_DIR / f"page-{global_idx:04d}-table.txt"
        out_path.write_text(text, encoding="utf-8")
        output_entries.append(
            {
                "globalPageIndex": global_idx,
                "tableWordHits": len(hits),
                "cropBox": crop,
                "textPath": str(out_path.relative_to(DATA)),
                "length": len(text),
                "alphaRatio": round(alpha_ratio(text), 3),
            }
        )

    result = {
        "createdUtc": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "targetPages": len(target_pages),
            "pagesProcessed": len(output_entries),
            "tableRegionsOcr": len([p for p in output_entries if p.get("textPath")]),
        },
        "pages": output_entries,
    }
    OUTPUT_LOG.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print("Table recheck pass complete.")


if __name__ == "__main__":
    main()
