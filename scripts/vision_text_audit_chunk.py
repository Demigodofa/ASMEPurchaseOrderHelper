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
BEST_TEXT_DIR = DATA / "best_text" / "pages"
OUTPUT_DIR = DATA / "section_text_checks"
OUTPUT_PATH = DATA / "section_text_audit_chunk.json"
APPSETTINGS_PATH = ROOT / "PoApp.Ingest.Cli" / "appsettings.json"

DEFAULT_TESSERACT = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
CHEM_TOKENS = {
    "C",
    "SI",
    "MN",
    "P",
    "S",
    "CR",
    "NI",
    "MO",
    "CU",
    "AL",
    "TI",
    "V",
    "NB",
    "CB",
    "W",
    "B",
    "CO",
    "N",
    "PB",
    "SN",
}


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


def weird_char_ratio(text):
    if not text:
        return 0.0
    weird = sum(1 for ch in text if ch in "$@#^~`|")
    return weird / max(1, len(text))


def extract_chem_tokens(text):
    tokens = set(re.findall(r"\b[A-Z]{1,2}\b", text.upper()))
    return {t for t in tokens if t in CHEM_TOKENS}


def get_best_text(global_idx):
    path = BEST_TEXT_DIR / f"page-{global_idx:04d}.txt"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def main():
    configure_tesseract()
    appsettings = load_appsettings()
    manifest = load_json(MANIFEST_PATH)
    page_map = {p.get("globalPageIndex"): p for p in manifest.get("pages", [])}

    start_page = int(os.environ.get("START_PAGE", "800"))
    page_count = int(os.environ.get("PAGE_COUNT", "20"))
    target_pages = list(range(start_page, start_page + page_count))

    results = []
    summary = {
        "pagesChecked": 0,
        "bestTextLowAlpha": 0,
        "visionLowAlpha": 0,
        "bestTextWeirdCharHits": 0,
        "visionWeirdCharHits": 0,
        "chemTokenMissingInBestText": 0,
        "chemTokenMissingInVision": 0,
    }

    for global_idx in target_pages:
        page_info = page_map.get(global_idx)
        if not page_info:
            continue
        page_info = dict(page_info)
        page_info["sourcePdfPath"] = resolve_pdf_path(appsettings, page_info["sourcePdf"])
        image_path = ensure_raster(page_info)
        image = Image.open(image_path)
        vision_text = pytesseract.image_to_string(image, config="--psm 6")
        vision_out = OUTPUT_DIR / f"page-{global_idx:04d}-vision.txt"
        vision_out.write_text(vision_text, encoding="utf-8")

        best_text = get_best_text(global_idx)
        best_alpha = alpha_ratio(best_text)
        vision_alpha = alpha_ratio(vision_text)
        best_weird = weird_char_ratio(best_text)
        vision_weird = weird_char_ratio(vision_text)

        best_tokens = extract_chem_tokens(best_text)
        vision_tokens = extract_chem_tokens(vision_text)
        missing_in_best = sorted(vision_tokens - best_tokens)
        missing_in_vision = sorted(best_tokens - vision_tokens)

        if best_alpha < 0.5:
            summary["bestTextLowAlpha"] += 1
        if vision_alpha < 0.5:
            summary["visionLowAlpha"] += 1
        if best_weird > 0:
            summary["bestTextWeirdCharHits"] += 1
        if vision_weird > 0:
            summary["visionWeirdCharHits"] += 1
        if missing_in_best:
            summary["chemTokenMissingInBestText"] += 1
        if missing_in_vision:
            summary["chemTokenMissingInVision"] += 1

        summary["pagesChecked"] += 1

        results.append(
            {
                "globalPageIndex": global_idx,
                "sourcePdf": page_info["sourcePdf"],
                "sourcePageNumber": page_info["sourcePageNumber"],
                "bestTextAlphaRatio": round(best_alpha, 3),
                "visionAlphaRatio": round(vision_alpha, 3),
                "bestTextWeirdCharRatio": round(best_weird, 4),
                "visionWeirdCharRatio": round(vision_weird, 4),
                "chemTokensBestText": sorted(best_tokens),
                "chemTokensVision": sorted(vision_tokens),
                "missingChemInBestText": missing_in_best,
                "missingChemInVision": missing_in_vision,
                "visionTextPath": str(vision_out.relative_to(DATA)),
            }
        )

    report = {
        "createdUtc": datetime.now(timezone.utc).isoformat(),
        "startPage": start_page,
        "pageCount": page_count,
        "summary": summary,
        "pages": results,
    }
    OUTPUT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
