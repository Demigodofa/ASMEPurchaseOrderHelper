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
BEST_TEXT_DIR = DATA / "best_text" / "pages"
OUTPUT_DIR = DATA / "section_regression_checks"
OUTPUT_PATH = DATA / "section_regression_vision_audit.json"
APPSETTINGS_PATH = ROOT / "PoApp.Ingest.Cli" / "appsettings.json"

SPEC_RE = re.compile(r"\b(?P<spec>(?:SA|SB|SF|A)-\d+[A-Z]?M?)\b", re.IGNORECASE)
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
    existing = list(OUTPUT_DIR.glob(f"{base_name}-full-*.png"))
    if existing:
        return existing[0]
    poppler_bin = get_poppler_bin()
    if not poppler_bin:
        raise RuntimeError("Poppler not installed. Run scripts/install_poppler.ps1 first.")
    pdftoppm = poppler_bin / "pdftoppm.exe"
    if not pdftoppm.exists():
        raise RuntimeError("pdftoppm.exe not found in Poppler bin.")
    output_base = OUTPUT_DIR / f"{base_name}-full"
    subprocess.run(
        [
            str(pdftoppm),
            "-r",
            "200",
            "-f",
            str(page_info["sourcePageNumber"]),
            "-l",
            str(page_info["sourcePageNumber"]),
            "-png",
            str(page_info["sourcePdfPath"]),
            str(output_base),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    candidates = list(OUTPUT_DIR.glob(f"{base_name}-full-*.png"))
    if not candidates:
        raise RuntimeError(f"Raster missing after pdftoppm: {output_base}")
    return candidates[0]


def alpha_ratio(text):
    if not text:
        return 0.0
    alpha = sum(1 for ch in text if ch.isalpha())
    return alpha / max(1, len(text))


def get_best_text(global_idx):
    path = BEST_TEXT_DIR / f"page-{global_idx:04d}.txt"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def extract_spec_from_text(text):
    match = SPEC_RE.search(text[:250])
    if match:
        return match.group("spec").upper()
    return None


def main():
    configure_tesseract()
    appsettings = load_appsettings()
    manifest = load_json(MANIFEST_PATH)
    crossref = load_json(CROSSREF_PATH) if CROSSREF_PATH.exists() else {}

    page_map = {p.get("globalPageIndex"): p for p in manifest.get("pages", [])}
    regressions = crossref.get("sectionRegressions", [])

    max_pages = int(os.environ.get("VISION_AUDIT_PAGES", "50"))
    target = regressions[:max_pages]

    results = []
    summary = {
        "pagesChecked": 0,
        "specMismatch": 0,
        "specMissingInBestText": 0,
        "specMissingInVision": 0,
        "bestTextDollarCount": 0,
        "visionDollarCount": 0,
        "lowAlphaBestText": 0,
        "lowAlphaVision": 0,
    }

    for item in target:
        global_idx = item.get("globalPageIndex")
        page_info = page_map.get(global_idx)
        if not page_info:
            continue
        page_info = dict(page_info)
        page_info["sourcePdfPath"] = resolve_pdf_path(appsettings, page_info["sourcePdf"])
        image_path = ensure_raster(page_info)
        image = Image.open(image_path)
        width, height = image.size
        crop = image.crop((0, 0, width, int(height * 0.22)))
        crop_path = OUTPUT_DIR / f"page-{global_idx:04d}-top.png"
        crop.save(crop_path)

        vision_text = pytesseract.image_to_string(crop, config="--psm 6")
        best_text = get_best_text(global_idx)
        vision_spec = extract_spec_from_text(vision_text)
        best_spec = extract_spec_from_text(best_text)

        vision_dollars = vision_text.count("$")
        best_dollars = best_text.count("$")
        vision_alpha = alpha_ratio(vision_text)
        best_alpha = alpha_ratio(best_text)

        if best_spec and vision_spec and best_spec != vision_spec:
            summary["specMismatch"] += 1
        if not best_spec and vision_spec:
            summary["specMissingInBestText"] += 1
        if best_spec and not vision_spec:
            summary["specMissingInVision"] += 1
        if best_alpha < 0.5:
            summary["lowAlphaBestText"] += 1
        if vision_alpha < 0.5:
            summary["lowAlphaVision"] += 1

        summary["bestTextDollarCount"] += best_dollars
        summary["visionDollarCount"] += vision_dollars
        summary["pagesChecked"] += 1

        results.append(
            {
                "globalPageIndex": global_idx,
                "sourcePdf": page_info["sourcePdf"],
                "sourcePageNumber": page_info["sourcePageNumber"],
                "bestTextSpec": best_spec,
                "visionSpec": vision_spec,
                "bestTextDollarCount": best_dollars,
                "visionDollarCount": vision_dollars,
                "bestTextAlphaRatio": round(best_alpha, 3),
                "visionAlphaRatio": round(vision_alpha, 3),
                "cropPath": str(crop_path.relative_to(DATA)),
            }
        )

    report = {
        "createdUtc": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
        "pages": results,
    }
    OUTPUT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
