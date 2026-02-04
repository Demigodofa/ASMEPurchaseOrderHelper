import json
import os
import pathlib
import subprocess
from datetime import datetime, timezone

from PIL import Image
import pytesseract

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / "sectionII_partA_data_digitized"
MANIFEST_PATH = DATA / "manifest.json"
OUTPUT_DIR = DATA / "tesseract_abbyy"
RASTER_DIR = OUTPUT_DIR / "raster"
OUTPUT_LOG = OUTPUT_DIR / "tesseract_abbyy_passA1.json"
APPSETTINGS_PATH = ROOT / "PoApp.Ingest.Cli" / "appsettings.json"
PDF_NAME = "2025 OCR SECT II PART A BEGINNING TO SA-450.pdf"

DEFAULT_TESSERACT = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
DEFAULT_MAX_PAGES = 50
DEFAULT_BATCH_SIZE = 10


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


def ensure_raster(page_info, force=False):
    base_name = f"page-{page_info['globalPageIndex']:04d}"
    existing = list(RASTER_DIR.glob(f"{base_name}-*.png"))
    if force and existing:
        for path in existing:
            try:
                path.unlink()
            except OSError:
                pass
        existing = []
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
            "600",
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
    pages = [
        page
        for page in manifest.get("pages", [])
        if page.get("sourcePdf") == PDF_NAME
    ]
    return sorted(pages, key=lambda p: p["globalPageIndex"])


def main():
    configure_tesseract()
    appsettings = load_appsettings()
    pages = load_manifest_pages()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    processed = {}
    if OUTPUT_LOG.exists():
        existing = load_json(OUTPUT_LOG)
        for entry in existing.get("pages", []):
            processed[entry["globalPageIndex"]] = entry

    remaining_all = [p for p in pages if p["globalPageIndex"] not in processed]
    max_pages = int(os.environ.get("ABBYY_TESSERACT_MAX_PAGES", DEFAULT_MAX_PAGES))
    batch_size = int(os.environ.get("ABBYY_TESSERACT_BATCH_SIZE", DEFAULT_BATCH_SIZE))
    remaining = remaining_all
    if max_pages > 0:
        remaining = remaining_all[:max_pages]

    output_entries = list(processed.values())
    processed_this_run = 0
    for page_info in remaining:
        source_pdf = page_info["sourcePdf"]
        page_info["sourcePdfPath"] = resolve_pdf_path(appsettings, source_pdf)
        try:
            image_path = ensure_raster(page_info)
        except Exception as exc:
            output_entries.append(
                {
                    "globalPageIndex": page_info["globalPageIndex"],
                    "error": str(exc),
                }
            )
            processed_this_run += 1
            continue
        try:
            image = Image.open(image_path)
            image.load()
        except (OSError, SyntaxError) as exc:
            try:
                image_path = ensure_raster(page_info, force=True)
                image = Image.open(image_path)
                image.load()
            except Exception as retry_exc:
                output_entries.append(
                    {
                        "globalPageIndex": page_info["globalPageIndex"],
                        "error": f"Raster load failed: {exc}; retry failed: {retry_exc}",
                    }
                )
                processed_this_run += 1
                continue
        text = pytesseract.image_to_string(image, config="--psm 6")
        out_path = OUTPUT_DIR / f"page-{page_info['globalPageIndex']:04d}.txt"
        out_path.write_text(text, encoding="utf-8")
        output_entries.append(
            {
                "globalPageIndex": page_info["globalPageIndex"],
                "sourcePageNumber": page_info["sourcePageNumber"],
                "textPath": str(out_path.relative_to(DATA)),
                "length": len(text),
                "alphaRatio": round(alpha_ratio(text), 3),
            }
        )
        processed_this_run += 1
        if processed_this_run % batch_size == 0:
            write_log(output_entries, len(pages), max_pages, batch_size)

    write_log(output_entries, len(pages), max_pages, batch_size)
    print("Tesseract ABBYY pass A1 complete.")


def write_log(output_entries, total_pages, max_pages, batch_size):
    result = {
        "createdUtc": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "totalPages": total_pages,
            "pagesProcessed": len(output_entries),
            "remainingPages": max(0, total_pages - len(output_entries)),
            "maxPagesPerRun": max_pages,
            "batchSize": batch_size,
        },
        "pages": sorted(output_entries, key=lambda p: p["globalPageIndex"]),
    }
    OUTPUT_LOG.write_text(json.dumps(result, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
