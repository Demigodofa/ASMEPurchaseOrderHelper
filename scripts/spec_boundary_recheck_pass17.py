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
SPEC_RANGE_PATH = DATA / "spec_range_pass11.json"
OUTPUT_LOG = DATA / "spec_boundary_recheck_pass17.json"
RASTER_DIR = DATA / "raster_poppler"
APPSETTINGS_PATH = ROOT / "PoApp.Ingest.Cli" / "appsettings.json"

DEFAULT_TESSERACT = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
SPEC_RE = re.compile(r"\b(?:SA|A)-\d+[A-Z]?\b", re.IGNORECASE)
SECTION_RE = re.compile(r"^\s*(\d+)(?:\.\d+)*\s+[A-Z]")
DEFAULT_BATCH_SIZE = 25
DEFAULT_MAX_PAGES = 50


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


def ocr_top_region(image):
    width, height = image.size
    crop = (0, 0, width, int(height * 0.25))
    text = pytesseract.image_to_string(image.crop(crop), config="--psm 6")
    return text


def parse_sections(text):
    sections = []
    for line in text.splitlines():
        match = SECTION_RE.match(line)
        if match:
            sections.append(int(match.group(1)))
    return sorted(set(sections))


def main():
    configure_tesseract()
    appsettings = load_appsettings()
    pages = load_manifest_pages()

    batch_size = int(os.environ.get("SPEC_BOUNDARY_BATCH_SIZE", DEFAULT_BATCH_SIZE))
    max_pages = int(os.environ.get("SPEC_BOUNDARY_MAX_PAGES", DEFAULT_MAX_PAGES))

    spec_data = load_json(SPEC_RANGE_PATH) if SPEC_RANGE_PATH.exists() else {}
    intrusions = spec_data.get("intrusions", [])
    targets = {}
    for entry in intrusions:
        expected_spec = entry.get("spec")
        for intrusion in entry.get("intrusions", []):
            idx = intrusion.get("globalPageIndex")
            if not idx:
                continue
            targets.setdefault(idx, []).append(
                {
                    "expectedSpec": expected_spec,
                    "detectedSpec": intrusion.get("detectedSpec"),
                }
            )

    existing = {}
    if OUTPUT_LOG.exists():
        existing_data = load_json(OUTPUT_LOG)
        for item in existing_data.get("pages", []):
            existing[item["globalPageIndex"]] = item

    output_entries = list(existing.values())
    processed = set(existing.keys())

    remaining = [(idx, entries) for idx, entries in sorted(targets.items()) if idx not in processed]
    if max_pages and max_pages > 0:
        remaining = remaining[:max_pages]

    processed_this_run = 0
    for global_idx, entries in remaining:
        page_info = pages.get(global_idx)
        if not page_info:
            output_entries.append(
                {
                    "globalPageIndex": global_idx,
                    "error": "page_missing_in_manifest",
                    "expectedSpecs": sorted(
                        {entry.get("expectedSpec") for entry in entries if entry.get("expectedSpec")}
                    ),
                    "detectedSpecs": [],
                    "detectedSections": [],
                    "matchExpected": False,
                }
            )
            processed_this_run += 1
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
        text = ocr_top_region(image)
        specs = sorted({m.group(0).upper() for m in SPEC_RE.finditer(text)})
        sections = parse_sections(text)
        expected = sorted(
            {entry.get("expectedSpec") for entry in entries if entry.get("expectedSpec")}
        )
        output_entries.append(
            {
                "globalPageIndex": global_idx,
                "expectedSpecs": expected,
                "detectedSpecs": specs,
                "detectedSections": sections,
                "matchExpected": any(spec in expected for spec in specs) if expected else False,
            }
        )
        processed_this_run += 1
        if processed_this_run % batch_size == 0:
            result = {
                "createdUtc": datetime.now(timezone.utc).isoformat(),
                "summary": {
                    "targetPages": len(targets),
                    "pagesProcessed": len(output_entries),
                    "specHeaderHits": len([p for p in output_entries if p.get("detectedSpecs")]),
                    "expectedMatches": len([p for p in output_entries if p.get("matchExpected")]),
                    "remainingPages": max(0, len(remaining) - processed_this_run),
                    "batchSize": batch_size,
                    "maxPagesPerRun": max_pages,
                },
                "pages": sorted(output_entries, key=lambda p: p["globalPageIndex"]),
            }
            OUTPUT_LOG.write_text(json.dumps(result, indent=2), encoding="utf-8")

    result = {
        "createdUtc": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "targetPages": len(targets),
            "pagesProcessed": len(output_entries),
            "specHeaderHits": len([p for p in output_entries if p.get("detectedSpecs")]),
            "expectedMatches": len([p for p in output_entries if p.get("matchExpected")]),
            "remainingPages": max(0, len(remaining) - processed_this_run),
            "batchSize": batch_size,
            "maxPagesPerRun": max_pages,
        },
        "pages": sorted(output_entries, key=lambda p: p["globalPageIndex"]),
    }
    OUTPUT_LOG.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print("Spec boundary recheck pass complete.")


if __name__ == "__main__":
    main()
