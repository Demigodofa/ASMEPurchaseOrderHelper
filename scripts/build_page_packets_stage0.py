import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from pypdf import PdfReader


def format_path(path: Path) -> str:
    return path.as_posix()


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def resolve_tesseract(explicit: str | None) -> Path:
    candidates = []
    if explicit:
        candidates.append(Path(explicit))
    which = shutil_which("tesseract")
    if which:
        candidates.append(Path(which))
    candidates.append(Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"))
    for candidate in candidates:
        if candidate and candidate.exists():
            return candidate
    raise FileNotFoundError(
        "tesseract executable not found (PATH or C:\\Program Files\\Tesseract-OCR\\tesseract.exe)."
    )


def resolve_pdftoppm(explicit: str | None, repo_root: Path) -> Path:
    candidates = []
    if explicit:
        candidates.append(Path(explicit))
    which = shutil_which("pdftoppm")
    if which:
        candidates.append(Path(which))
    candidates.append(
        repo_root / "tools" / "poppler" / "poppler-25.12.0" / "Library" / "bin" / "pdftoppm.exe"
    )
    for candidate in candidates:
        if candidate and candidate.exists():
            return candidate
    raise FileNotFoundError("pdftoppm executable not found (PATH or tools/poppler).")


def shutil_which(executable: str) -> str | None:
    for path in os.environ.get("PATH", "").split(os.pathsep):
        candidate = Path(path) / executable
        if candidate.exists():
            return str(candidate)
        if sys.platform == "win32":
            candidate = Path(path) / f"{executable}.exe"
            if candidate.exists():
                return str(candidate)
    return None


def alpha_ratio(text: str) -> float:
    if not text:
        return 0.0
    alpha = sum(1 for ch in text if ch.isalpha())
    total = sum(1 for ch in text if not ch.isspace())
    if total == 0:
        return 0.0
    return alpha / total


def parse_tsv_metrics(tsv_path: Path) -> dict:
    words = []
    word_count = 0
    conf_total = 0.0
    conf_min = None
    low_conf_count = 0
    with tsv_path.open("r", encoding="utf-8", errors="ignore") as handle:
        header = True
        for line in handle:
            if header:
                header = False
                continue
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 12:
                continue
            level = parts[0]
            text = parts[11]
            conf_raw = parts[10]
            if level != "5" or not text:
                continue
            try:
                conf = float(conf_raw)
            except ValueError:
                continue
            if conf < 0:
                continue
            word_count += 1
            conf_total += conf
            if conf_min is None or conf < conf_min:
                conf_min = conf
            if conf < 50:
                low_conf_count += 1
            words.append(text)
    avg_conf = conf_total / word_count if word_count else 0.0
    return {
        "wordCount": word_count,
        "avgWordConf": round(avg_conf, 3),
        "minWordConf": round(conf_min, 3) if conf_min is not None else 0.0,
        "lowConfWordCount": low_conf_count,
        "textFromTsv": " ".join(words).strip(),
    }


def run_pdftoppm(
    pdftoppm: Path, pdf_path: Path, dpi: int, page: int, image_path: Path
) -> None:
    cmd = [
        str(pdftoppm),
        "-r",
        str(dpi),
        "-f",
        str(page),
        "-l",
        str(page),
        "-png",
        "-singlefile",
        str(pdf_path),
        str(image_path.with_suffix("")),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def run_tesseract(
    tesseract: Path, image_path: Path, output_base: Path, dpi: int, lang: str
) -> None:
    cmd = [
        str(tesseract),
        str(image_path),
        str(output_base),
        "--dpi",
        str(dpi),
        "--psm",
        "1",
        "--oem",
        "1",
        "-l",
        lang,
        "-c",
        "tessedit_create_tsv=1",
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def build_page_packets(
    pdf_path: Path,
    output_root: Path,
    label: str,
    dpi: int,
    lang: str,
    first_page: int,
    last_page: int,
    skip_existing: bool,
    tesseract_path: Path,
    pdftoppm_path: Path,
    ocr_mode: str,
) -> None:
    pages_dir = output_root / "pages"
    images_dir = output_root / "images"
    ocr_dir = output_root / "ocr"
    pdf_text_dir = output_root / "pdf_text"
    pages_dir.mkdir(parents=True, exist_ok=True)
    images_dir.mkdir(parents=True, exist_ok=True)
    ocr_dir.mkdir(parents=True, exist_ok=True)
    pdf_text_dir.mkdir(parents=True, exist_ok=True)

    reader = PdfReader(str(pdf_path))
    page_count = len(reader.pages)
    if first_page < 1 or first_page > page_count:
        raise ValueError(f"first_page {first_page} is out of range (1..{page_count}).")
    if last_page < first_page or last_page > page_count:
        raise ValueError(f"last_page {last_page} is out of range (1..{page_count}).")

    source_manifest = {
        "sourceLabel": label,
        "sourcePdf": format_path(pdf_path),
        "pdfSha256": sha256_file(pdf_path),
        "pageCount": page_count,
        "dpi": dpi,
        "lang": lang,
        "ocrMode": ocr_mode,
        "createdAt": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        "pagesDir": "pages",
        "imagesDir": "images",
        "ocrDir": "ocr",
        "pdfTextDir": "pdf_text",
    }
    (output_root / "source_manifest.json").write_text(
        json.dumps(source_manifest, indent=2), encoding="ascii"
    )

    for page in range(first_page, last_page + 1):
        image_path = images_dir / f"page-{page:04d}.png"
        ocr_base = ocr_dir / f"page-{page:04d}"
        ocr_txt = ocr_base.with_suffix(".txt")
        ocr_tsv = ocr_base.with_suffix(".tsv")
        pdf_text_path = pdf_text_dir / f"page-{page:04d}.txt"
        page_meta = pages_dir / f"page-{page:04d}.json"

        pdf_text = ""
        try:
            pdf_text = reader.pages[page - 1].extract_text() or ""
        except Exception:
            pdf_text = ""
        pdf_text_path.write_text(pdf_text, encoding="utf-8", errors="ignore")
        pdf_text_length = len(pdf_text)
        pdf_alpha_ratio = round(alpha_ratio(pdf_text), 4)
        low_confidence = pdf_text_length < 300 or pdf_alpha_ratio < 0.2

        do_ocr = ocr_mode == "all" or (ocr_mode == "low" and low_confidence)
        if do_ocr:
            ocr_outputs_exist = image_path.exists() and ocr_txt.exists() and ocr_tsv.exists()
            if not (skip_existing and ocr_outputs_exist):
                run_pdftoppm(pdftoppm_path, pdf_path, dpi, page, image_path)
                run_tesseract(tesseract_path, image_path, ocr_base, dpi, lang)

        text = ""
        if ocr_txt.exists():
            text = ocr_txt.read_text(encoding="utf-8", errors="ignore")
        tsv_metrics = parse_tsv_metrics(ocr_tsv) if ocr_tsv.exists() else {}
        if not text.strip():
            text = tsv_metrics.get("textFromTsv", "")

        page_payload = {
            "pageNumber": page,
            "sourceLabel": label,
            "sourcePdf": format_path(pdf_path),
            "imagePath": os.path.relpath(image_path, output_root),
            "ocrTextPath": os.path.relpath(ocr_txt, output_root),
            "ocrTsvPath": os.path.relpath(ocr_tsv, output_root),
            "dpi": dpi,
            "ocrEngine": "tesseract",
            "textLength": len(text),
            "alphaRatio": round(alpha_ratio(text), 4),
            "pdfTextPath": os.path.relpath(pdf_text_path, output_root),
            "pdfTextLength": pdf_text_length,
            "pdfAlphaRatio": pdf_alpha_ratio,
            "lowConfidenceCandidate": low_confidence,
        }
        page_payload.update(tsv_metrics)
        page_payload["detectedPageNumber"] = detect_page_number(text)
        page_payload["detectedPageNumberPdf"] = detect_page_number(pdf_text)
        page_meta.write_text(json.dumps(page_payload, indent=2), encoding="ascii")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build per-page OCR packets for a PDF source.")
    parser.add_argument("--pdf", required=True, help="Path to the source PDF.")
    parser.add_argument("--out", required=True, help="Output root folder.")
    parser.add_argument("--label", required=True, help="Source label used in metadata.")
    parser.add_argument("--dpi", type=int, default=400, help="Raster DPI (default: 400).")
    parser.add_argument("--lang", default="eng", help="Tesseract language (default: eng).")
    parser.add_argument("--first-page", type=int, default=1, help="First page to process (1-based).")
    parser.add_argument("--last-page", type=int, default=0, help="Last page to process (0 = end).")
    parser.add_argument("--skip-existing", action="store_true", help="Skip pages with existing outputs.")
    parser.add_argument("--tesseract", help="Explicit path to tesseract.exe.")
    parser.add_argument("--pdftoppm", help="Explicit path to pdftoppm.exe.")
    parser.add_argument(
        "--ocr-mode",
        default="low",
        choices=["low", "all", "none"],
        help="OCR mode: low (default) only on low-confidence pages, all, or none.",
    )
    args = parser.parse_args()

    pdf_path = Path(args.pdf).resolve()
    output_root = Path(args.out).resolve()

    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    repo_root = Path(__file__).resolve().parents[1]
    tesseract_path = resolve_tesseract(args.tesseract)
    pdftoppm_path = resolve_pdftoppm(args.pdftoppm, repo_root)

    reader = PdfReader(str(pdf_path))
    page_count = len(reader.pages)
    last_page = args.last_page if args.last_page > 0 else page_count

    build_page_packets(
        pdf_path=pdf_path,
        output_root=output_root,
        label=args.label,
        dpi=args.dpi,
        lang=args.lang,
        first_page=args.first_page,
        last_page=last_page,
        skip_existing=args.skip_existing,
        tesseract_path=tesseract_path,
        pdftoppm_path=pdftoppm_path,
        ocr_mode=args.ocr_mode,
    )
    return 0


def detect_page_number(text: str) -> int | None:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return None
    candidates = []
    scan_lines = lines[:8] + lines[-8:]
    for line in scan_lines:
        if re.fullmatch(r"\d{1,4}", line):
            candidates.append(int(line))
            continue
        match = re.search(r"\bpage\s+(\d{1,4})\b", line, re.IGNORECASE)
        if match:
            candidates.append(int(match.group(1)))
    if not candidates:
        return None
    for value in candidates:
        if 1 <= value <= 5000:
            return value
    return None


if __name__ == "__main__":
    raise SystemExit(main())
