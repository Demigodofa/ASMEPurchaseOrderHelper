import argparse
import json
import math
import os
from pathlib import Path

from freeze_guard import ensure_not_frozen

def normalize_text(text: str, max_chars: int = 4000) -> str:
    text = text.lower()
    cleaned = []
    for ch in text:
        if ch.isalpha() or ch.isspace():
            cleaned.append(ch)
    normalized = "".join(cleaned)
    normalized = " ".join(normalized.split())
    return normalized[:max_chars]


def token_set(text: str, max_tokens: int = 800) -> set[str]:
    if not text:
        return set()
    tokens = text.split()
    return set(tokens[:max_tokens])


def jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    if not a or not b:
        return 0.0
    intersection = len(a & b)
    union = len(a | b)
    return intersection / union if union else 0.0


def load_pages(source_dir: Path) -> list[dict]:
    pages_dir = source_dir / "pages"
    pdf_text_dir = source_dir / "pdf_text"
    ocr_dir = source_dir / "ocr"
    pages = []
    for page_meta in sorted(pages_dir.glob("page-*.json")):
        payload = json.loads(page_meta.read_text(encoding="ascii", errors="ignore"))
        page_number = payload.get("pageNumber")
        ocr_text_path = payload.get("ocrTextPath")
        pdf_text_path = payload.get("pdfTextPath")
        ocr_text = ""
        if ocr_text_path:
            path = source_dir / ocr_text_path
            if path.exists():
                ocr_text = path.read_text(encoding="utf-8", errors="ignore")
        pdf_text = ""
        if pdf_text_path:
            path = source_dir / pdf_text_path
            if path.exists():
                pdf_text = path.read_text(encoding="utf-8", errors="ignore")
        if not pdf_text and pdf_text_dir.exists():
            fallback = pdf_text_dir / f"page-{page_number:04d}.txt"
            if fallback.exists():
                pdf_text = fallback.read_text(encoding="utf-8", errors="ignore")
        if not ocr_text and ocr_dir.exists():
            fallback = ocr_dir / f"page-{page_number:04d}.txt"
            if fallback.exists():
                ocr_text = fallback.read_text(encoding="utf-8", errors="ignore")

        preferred_text = ocr_text.strip() or pdf_text.strip()
        normalized = normalize_text(preferred_text)
        pages.append(
            {
                "pageNumber": page_number,
                "detectedPageNumber": payload.get("detectedPageNumber"),
                "detectedPageNumberPdf": payload.get("detectedPageNumberPdf"),
                "text": preferred_text,
                "normText": normalized,
                "tokens": token_set(normalized),
            }
        )
    return pages


def align_sources(base_pages: list[dict], other_pages: list[dict]) -> dict:
    base_by_detected = {}
    for page in base_pages:
        for key in ("detectedPageNumber", "detectedPageNumberPdf"):
            value = page.get(key)
            if value:
                base_by_detected.setdefault(value, []).append(page)

    base_count = len(base_pages)
    other_count = len(other_pages)
    matches = []
    matched_scores = []

    for idx, other in enumerate(other_pages, start=1):
        detected = other.get("detectedPageNumber") or other.get("detectedPageNumberPdf")
        candidates = []
        method = "window"
        if detected and detected in base_by_detected:
            candidates = base_by_detected[detected]
            method = "page_number"
        else:
            approx = int(round((idx / other_count) * base_count))
            window = 25
            start = max(1, approx - window)
            end = min(base_count, approx + window)
            candidates = base_pages[start - 1 : end]

        best = None
        best_score = -1.0
        for base in candidates:
            score = jaccard(other["tokens"], base["tokens"])
            if score > best_score:
                best_score = score
                best = base

        matches.append(
            {
                "otherPageNumber": other["pageNumber"],
                "basePageNumber": best["pageNumber"] if best else None,
                "detectedPageNumber": detected,
                "method": method,
                "score": round(best_score, 4),
            }
        )
        if best_score >= 0:
            matched_scores.append(best_score)

    avg_score = sum(matched_scores) / len(matched_scores) if matched_scores else 0.0
    summary = {
        "basePages": base_count,
        "otherPages": other_count,
        "averageScore": round(avg_score, 4),
    }
    return {"summary": summary, "matches": matches}


def main() -> int:
    ensure_not_frozen()
    parser = argparse.ArgumentParser(description="Align page packets between sources.")
    parser.add_argument("--base", required=True, help="Base source folder with page packets.")
    parser.add_argument("--other", required=True, help="Other source folder with page packets.")
    parser.add_argument("--out", required=True, help="Output JSON path.")
    args = parser.parse_args()

    base_dir = Path(args.base).resolve()
    other_dir = Path(args.other).resolve()
    out_path = Path(args.out).resolve()

    base_pages = load_pages(base_dir)
    other_pages = load_pages(other_dir)
    alignment = align_sources(base_pages, other_pages)

    payload = {
        "generatedAt": datetime_now(),
        "baseSource": str(base_dir),
        "otherSource": str(other_dir),
        "summary": alignment["summary"],
        "matches": alignment["matches"],
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="ascii")
    return 0


def datetime_now() -> str:
    from datetime import datetime

    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


if __name__ == "__main__":
    raise SystemExit(main())
