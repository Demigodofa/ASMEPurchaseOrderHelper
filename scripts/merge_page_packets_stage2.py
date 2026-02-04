import argparse
import json
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
    return set(text.split()[:max_tokens])


def jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    if not a or not b:
        return 0.0
    intersection = len(a & b)
    union = len(a | b)
    return intersection / union if union else 0.0


def load_page_payload(source_dir: Path, page_number: int) -> dict:
    page_meta = source_dir / "pages" / f"page-{page_number:04d}.json"
    payload = json.loads(page_meta.read_text(encoding="ascii", errors="ignore"))
    text = ""
    ocr_text_path = payload.get("ocrTextPath")
    pdf_text_path = payload.get("pdfTextPath")
    if ocr_text_path:
        path = source_dir / ocr_text_path
        if path.exists():
            text = path.read_text(encoding="utf-8", errors="ignore")
    if not text and pdf_text_path:
        path = source_dir / pdf_text_path
        if path.exists():
            text = path.read_text(encoding="utf-8", errors="ignore")
    if not text:
        pdf_fallback = source_dir / "pdf_text" / f"page-{page_number:04d}.txt"
        if pdf_fallback.exists():
            text = pdf_fallback.read_text(encoding="utf-8", errors="ignore")
    normalized = normalize_text(text)
    tokens = token_set(normalized)
    avg_conf = payload.get("avgWordConf", 0.0) or 0.0
    pdf_alpha = payload.get("pdfAlphaRatio", 0.0) or 0.0
    text_length = len(text)
    quality = avg_conf + (pdf_alpha * 100) + min(text_length / 50, 100)
    return {
        "pageNumber": page_number,
        "text": text,
        "normText": normalized,
        "tokens": tokens,
        "avgWordConf": avg_conf,
        "pdfAlphaRatio": pdf_alpha,
        "textLength": text_length,
        "qualityScore": round(quality, 3),
    }


def load_alignment_map(alignment_path: Path) -> dict[int, int]:
    payload = json.loads(alignment_path.read_text(encoding="ascii", errors="ignore"))
    mapping = {}
    for match in payload.get("matches", []):
        base_page = match.get("basePageNumber")
        other_page = match.get("otherPageNumber")
        if base_page and other_page:
            mapping[int(base_page)] = int(other_page)
    return mapping


def main() -> int:
    ensure_not_frozen()
    parser = argparse.ArgumentParser(description="Merge page packets into a consensus corpus.")
    parser.add_argument("--base", required=True, help="Base source folder.")
    parser.add_argument("--out", required=True, help="Output folder for merged pages.")
    parser.add_argument(
        "--other",
        action="append",
        default=[],
        help="Other source spec: dir|alignment|label",
    )
    args = parser.parse_args()

    base_dir = Path(args.base).resolve()
    out_dir = Path(args.out).resolve()
    out_pages = out_dir / "pages"
    out_pages.mkdir(parents=True, exist_ok=True)

    other_specs = []
    for spec in args.other:
        parts = spec.split("|")
        if len(parts) != 3:
            raise ValueError("Other spec must be dir|alignment|label.")
        other_specs.append(
            {
                "dir": Path(parts[0]).resolve(),
                "alignment": Path(parts[1]).resolve(),
                "label": parts[2],
            }
        )

    alignments = {}
    for spec in other_specs:
        alignments[spec["label"]] = load_alignment_map(spec["alignment"])

    base_pages = sorted((base_dir / "pages").glob("page-*.json"))
    summary = {
        "basePages": len(base_pages),
        "sources": ["base"] + [spec["label"] for spec in other_specs],
        "pagesWithMultipleSources": 0,
        "averageConsensusSimilarity": 0.0,
    }

    similarity_total = 0.0
    similarity_count = 0

    for page_meta in base_pages:
        base_payload = json.loads(page_meta.read_text(encoding="ascii", errors="ignore"))
        page_number = int(base_payload["pageNumber"])
        candidates = [{"label": "base", "payload": load_page_payload(base_dir, page_number)}]
        for spec in other_specs:
            mapping = alignments.get(spec["label"], {})
            other_page_number = mapping.get(page_number)
            if not other_page_number:
                continue
            candidates.append(
                {
                    "label": spec["label"],
                    "payload": load_page_payload(spec["dir"], other_page_number),
                }
            )

        if len(candidates) > 1:
            summary["pagesWithMultipleSources"] += 1

        best = max(candidates, key=lambda item: item["payload"]["qualityScore"])
        best_text = best["payload"]["text"]

        base_tokens = candidates[0]["payload"]["tokens"]
        for candidate in candidates[1:]:
            score = jaccard(base_tokens, candidate["payload"]["tokens"])
            similarity_total += score
            similarity_count += 1

        out_text_path = out_pages / f"page-{page_number:04d}.txt"
        out_text_path.write_text(best_text, encoding="utf-8", errors="ignore")
        out_meta = {
            "pageNumber": page_number,
            "selectedSource": best["label"],
            "candidateCount": len(candidates),
            "candidates": [
                {
                    "label": candidate["label"],
                    "qualityScore": candidate["payload"]["qualityScore"],
                    "textLength": candidate["payload"]["textLength"],
                }
                for candidate in candidates
            ],
        }
        (out_pages / f"page-{page_number:04d}.json").write_text(
            json.dumps(out_meta, indent=2),
            encoding="ascii",
        )

    if similarity_count:
        summary["averageConsensusSimilarity"] = round(similarity_total / similarity_count, 4)

    summary_path = out_dir / "merge_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="ascii")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
