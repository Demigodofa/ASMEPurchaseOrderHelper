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
VALIDATION_PATH = DATA / "validation_pass4.json"
CROSSREF_PATH = DATA / "crossref_pass9.json"
SPEC_RANGE_PATH = DATA / "spec_range_pass11.json"
OUTPUT_DIR = DATA / "full_ocr_highdpi"
RASTER_DIR = OUTPUT_DIR / "raster"
OUTPUT_LOG = DATA / "full_ocr_highdpi_pass18.json"
APPSETTINGS_PATH = ROOT / "PoApp.Ingest.Cli" / "appsettings.json"

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


def ensure_raster(page_info):
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


def load_manifest_pages():
    manifest = load_json(MANIFEST_PATH)
    pages = {}
    for page in manifest.get("pages", []):
        pages[page["globalPageIndex"]] = page
    return pages


def build_spec_range_set():
    if not SPEC_RANGE_PATH.exists():
        return set()
    spec_data = load_json(SPEC_RANGE_PATH)
    allowed = set()
    for item in spec_data.get("ranges", []):
        if item.get("status") == "missing-range":
            continue
        start = item.get("startGlobalPage")
        end = item.get("endGlobalPage")
        if not start or not end or end < start:
            continue
        allowed.update(range(start, end + 1))
    return allowed


def load_targets():
    validation = load_json(VALIDATION_PATH)
    low_conf = {p["globalPageIndex"] for p in validation.get("pages", []) if p.get("lowConfidence")}
    cross = load_json(CROSSREF_PATH) if CROSSREF_PATH.exists() else {}
    ref_pages = {p["globalPageIndex"] for p in cross.get("noteRefGaps", [])}
    ref_pages |= {p["globalPageIndex"] for p in cross.get("tableRefGaps", [])}
    return sorted(low_conf | ref_pages)


def alpha_ratio(text):
    if not text:
        return 0.0
    alpha = sum(1 for ch in text if ch.isalpha())
    return alpha / max(1, len(text))


def main():
    configure_tesseract()
    appsettings = load_appsettings()
    pages = load_manifest_pages()
    allowed = build_spec_range_set()
    targets = [p for p in load_targets() if not allowed or p in allowed]

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    processed = {}
    if OUTPUT_LOG.exists():
        existing = load_json(OUTPUT_LOG)
        for entry in existing.get("pages", []):
            processed[entry["globalPageIndex"]] = entry

    remaining_all = [p for p in targets if p not in processed]
    max_pages = int(os.environ.get("FULL_OCR_MAX_PAGES", DEFAULT_MAX_PAGES))
    batch_size = int(os.environ.get("FULL_OCR_BATCH_SIZE", DEFAULT_BATCH_SIZE))
    remaining = remaining_all
    if max_pages > 0:
        remaining = remaining_all[:max_pages]

    output_entries = list(processed.values())
    processed_this_run = 0
    for global_idx in remaining:
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
            processed_this_run += 1
            continue
        image = Image.open(image_path)
        text = pytesseract.image_to_string(image, config="--psm 6")
        out_path = OUTPUT_DIR / f"page-{global_idx:04d}.txt"
        out_path.write_text(text, encoding="utf-8")
        output_entries.append(
            {
                "globalPageIndex": global_idx,
                "textPath": str(out_path.relative_to(DATA)),
                "length": len(text),
                "alphaRatio": round(alpha_ratio(text), 3),
            }
        )
        processed_this_run += 1
        if processed_this_run % batch_size == 0:
            total_processed = len(output_entries)
            remaining_pages = max(0, len(targets) - total_processed)
            result = {
                "createdUtc": datetime.now(timezone.utc).isoformat(),
                "summary": {
                    "targetPages": len(targets),
                    "pagesProcessed": total_processed,
                    "remainingPages": remaining_pages,
                    "maxPagesPerRun": max_pages,
                    "batchSize": batch_size,
                },
                "pages": sorted(output_entries, key=lambda p: p["globalPageIndex"]),
            }
            OUTPUT_LOG.write_text(json.dumps(result, indent=2), encoding="utf-8")

    total_processed = len(output_entries)
    remaining_pages = max(0, len(targets) - total_processed)
    result = {
        "createdUtc": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "targetPages": len(targets),
            "pagesProcessed": total_processed,
            "remainingPages": remaining_pages,
            "maxPagesPerRun": max_pages,
            "batchSize": batch_size,
        },
        "pages": sorted(output_entries, key=lambda p: p["globalPageIndex"]),
    }
    OUTPUT_LOG.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print("Full OCR high-DPI pass complete.")


if __name__ == "__main__":
    main()
