import argparse
import json
from datetime import datetime
from pathlib import Path

from chunk_lock_utils import (
    chunk_text,
    detect_spec_header,
    extract_modals,
    extract_numbers,
    extract_units,
    normalize_for_compare,
)
from freeze_guard import ensure_not_frozen


def load_alignment_map(path: Path) -> dict[int, int]:
    payload = json.loads(path.read_text(encoding="ascii", errors="ignore"))
    mapping = {}
    for match in payload.get("matches", []):
        base_page = match.get("basePageNumber")
        other_page = match.get("otherPageNumber")
        if base_page and other_page:
            mapping[int(base_page)] = int(other_page)
    return mapping


def load_base_page_map(path: Path | None) -> dict[int, int]:
    if not path:
        return {}
    payload = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    return {int(m["globalPageIndex"]): int(m["basePageNumber"]) for m in payload.get("mappings", [])}


def read_source_text(source_dir: Path, page_number: int) -> str:
    page_meta = source_dir / "pages" / f"page-{page_number:04d}.json"
    if not page_meta.exists():
        return ""
    payload = json.loads(page_meta.read_text(encoding="ascii", errors="ignore"))
    text = ""
    text_path = payload.get("pdfTextPath")
    if text_path:
        path = source_dir / text_path
        if path.exists():
            text = path.read_text(encoding="utf-8", errors="ignore")
    if not text.strip():
        ocr_path = payload.get("ocrTextPath")
        if ocr_path:
            path = source_dir / ocr_path
            if path.exists():
                text = path.read_text(encoding="utf-8", errors="ignore")
    return text


def token_set(text: str) -> set[str]:
    normalized = normalize_for_compare(text)
    return set(normalized.split()) if normalized else set()


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def classify_variant(base_text: str, variant_text: str) -> str:
    if not variant_text:
        return "missing"
    if extract_numbers(base_text) != extract_numbers(variant_text):
        return "numeric"
    if extract_units(base_text) != extract_units(variant_text):
        return "numeric"
    if extract_modals(base_text) != extract_modals(variant_text):
        return "modal"
    if normalize_for_compare(base_text) == normalize_for_compare(variant_text):
        return "ocr-noise"
    similarity = jaccard(token_set(base_text), token_set(variant_text))
    if similarity >= 0.9:
        return "orthographic"
    return "structural"


def choose_best_candidate(base_chunk: dict, candidates: list[dict], min_sim: float) -> tuple[dict | None, float]:
    base_tokens = token_set(base_chunk.get("text", ""))
    if not base_tokens:
        return None, 0.0
    best = None
    best_score = 0.0
    for candidate in candidates:
        cand_text = candidate.get("text", "")
        cand_tokens = token_set(cand_text)
        if not cand_tokens:
            continue
        score = jaccard(base_tokens, cand_tokens)
        if score > best_score:
            best_score = score
            best = candidate
    if best_score < min_sim:
        return None, best_score
    return best, best_score


def decision_for_chunk(
    variant_classes: set[str],
    has_safe_match: bool,
    missing_types: set[str],
) -> str:
    if not has_safe_match:
        return "human-review-required"
    if any(cls in {"numeric", "modal", "structural"} for cls in variant_classes):
        return "human-review-required"
    if missing_types - {"source_absent"}:
        return "human-review-required"
    if variant_classes.issubset({"ocr-noise", "orthographic"}):
        return "auto-resolvable"
    return "human-review-required"


def main() -> int:
    ensure_not_frozen()
    parser = argparse.ArgumentParser(
        description="Classify unlocked chunk variants without modifying text."
    )
    parser.add_argument("--base-best-text", required=True, help="Base best_text pages folder.")
    parser.add_argument("--spec-range", required=True, help="Spec range JSON path.")
    parser.add_argument("--lock-dir", required=True, help="Lock metadata folder from stage1c.")
    parser.add_argument("--out", required=True, help="Output folder for classification metadata.")
    parser.add_argument("--base-page-map", help="Optional page_map.json for base page numbers.")
    parser.add_argument(
        "--source",
        action="append",
        default=[],
        help="Source spec: dir|alignment|label",
    )
    parser.add_argument(
        "--adjacent-window",
        type=int,
        default=1,
        help="Candidate page window around mapped page.",
    )
    parser.add_argument("--min-sim", type=float, default=0.55, help="Min Jaccard match for items/paragraphs.")
    parser.add_argument("--min-sim-table", type=float, default=0.45, help="Min Jaccard match for tables.")
    parser.add_argument("--min-sim-heading", type=float, default=0.7, help="Min Jaccard match for headings.")
    parser.add_argument(
        "--partial-sim",
        type=float,
        default=0.25,
        help="Min Jaccard score to flag boundary truncation candidates.",
    )
    args = parser.parse_args()

    base_dir = Path(args.base_best_text).resolve()
    lock_dir = Path(args.lock_dir).resolve()
    out_dir = Path(args.out).resolve()
    out_pages = out_dir / "pages"
    out_pages.mkdir(parents=True, exist_ok=True)

    spec_data = json.loads(Path(args.spec_range).read_text(encoding="utf-8", errors="ignore"))
    ranges = [r for r in spec_data.get("ranges", []) if r.get("startGlobalPage") and r.get("endGlobalPage")]

    base_page_map = load_base_page_map(Path(args.base_page_map)) if args.base_page_map else {}

    sources = []
    for spec in args.source:
        parts = spec.split("|")
        if len(parts) != 3:
            raise ValueError("Source spec must be dir|alignment|label")
        sources.append(
            {
                "dir": Path(parts[0]).resolve(),
                "alignment": load_alignment_map(Path(parts[1]).resolve()),
                "label": parts[2],
            }
        )

    summary = {
        "createdAt": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        "pagesProcessed": 0,
        "chunksTotal": 0,
        "chunksLocked": 0,
        "chunksClassified": 0,
        "decisionCounts": {"auto-resolvable": 0, "human-review-required": 0},
        "classCounts": {},
    }

    type_thresholds = {
        "table": args.min_sim_table,
        "heading": args.min_sim_heading,
    }

    for spec_range in ranges:
        spec = spec_range.get("spec")
        start = int(spec_range["startGlobalPage"])
        end = int(spec_range["endGlobalPage"])
        for global_page in range(start, end + 1):
            base_page = base_page_map.get(global_page, global_page)
            base_path = base_dir / f"page-{global_page:04d}.txt"
            lock_path = lock_dir / "pages" / f"page-{global_page:04d}.json"
            if not base_path.exists() or not lock_path.exists():
                continue
            lock_payload = json.loads(lock_path.read_text(encoding="utf-8", errors="ignore"))
            chunks = lock_payload.get("chunks", [])

            output_chunks = []
            for idx, chunk in enumerate(chunks):
                summary["chunksTotal"] += 1
                if chunk.get("locked"):
                    summary["chunksLocked"] += 1
                    output_chunks.append(
                        {
                            "index": idx,
                            "type": chunk.get("type"),
                            "locked": True,
                            "text": chunk.get("text"),
                            "variants": [],
                            "missingSources": [],
                            "decision": "locked",
                        }
                    )
                    continue

                if not chunk.get("text"):
                    output_chunks.append(
                        {
                            "index": idx,
                            "type": chunk.get("type"),
                            "locked": False,
                            "text": chunk.get("text"),
                            "variants": [],
                            "missingSources": [],
                            "decision": "human-review-required",
                        }
                    )
                    summary["chunksClassified"] += 1
                    summary["decisionCounts"]["human-review-required"] += 1
                    continue

                min_sim = type_thresholds.get(chunk.get("type"), args.min_sim)
                variant_sources = {}
                missing_sources = []
                variant_classes = set()
                is_boundary = idx == 0 or idx == (len(chunks) - 1)
                safe_match = False

                for source in sources:
                    mapped_page = source["alignment"].get(base_page)
                    if not mapped_page:
                        missing_sources.append({"label": source["label"], "type": "source_absent"})
                        continue
                    candidate_pages = range(
                        max(1, mapped_page - args.adjacent_window),
                        mapped_page + args.adjacent_window + 1,
                    )
                    best_candidate = None
                    best_score = 0.0
                    for candidate_page in candidate_pages:
                        candidate_text = read_source_text(source["dir"], candidate_page)
                        if not candidate_text.strip():
                            continue
                        candidate_spec = detect_spec_header(candidate_text)
                        if candidate_spec and spec and candidate_spec != spec:
                            continue
                        candidate_chunks = chunk_text(candidate_text)
                        candidate, score = choose_best_candidate(chunk, candidate_chunks, min_sim)
                        if candidate:
                            best_candidate = candidate
                            best_score = score
                            break
                        if score > best_score:
                            best_score = score
                    if not best_candidate:
                        if is_boundary and best_score >= args.partial_sim:
                            missing_sources.append({"label": source["label"], "type": "boundary_truncation"})
                        else:
                            missing_sources.append({"label": source["label"], "type": "source_absent"})
                        continue
                    variant_text = best_candidate.get("text", "")
                    variant_sources.setdefault(variant_text, [])
                    variant_sources[variant_text].append(source["label"])

                variants = []
                variant_counts = {}
                for variant_text, labels in variant_sources.items():
                    diff_class = classify_variant(chunk["text"], variant_text)
                    variant_classes.add(diff_class)
                    if diff_class in {"ocr-noise", "orthographic"}:
                        safe_match = True
                    variant_counts[variant_text] = len(labels)
                    summary["classCounts"].setdefault(diff_class, 0)
                    summary["classCounts"][diff_class] += len(labels)
                    variants.append(
                        {
                            "text": variant_text,
                            "class": diff_class,
                            "sources": sorted(labels),
                            "sourceCount": len(labels),
                        }
                    )

                if missing_sources:
                    if not safe_match:
                        for entry in missing_sources:
                            if entry["type"] == "source_absent":
                                entry["type"] = "true_missing"
                    for entry in missing_sources:
                        summary["classCounts"].setdefault(entry["type"], 0)
                        summary["classCounts"][entry["type"]] += 1

                missing_types = {entry["type"] for entry in missing_sources}
                decision = decision_for_chunk(variant_classes, safe_match, missing_types)
                if decision in summary["decisionCounts"]:
                    summary["decisionCounts"][decision] += 1
                else:
                    summary["decisionCounts"][decision] = 1
                summary["chunksClassified"] += 1

                output_chunks.append(
                    {
                        "index": idx,
                        "type": chunk.get("type"),
                        "locked": False,
                        "text": chunk.get("text"),
                        "variants": variants,
                        "missingSources": missing_sources,
                        "decision": decision,
                    }
                )

            out_pages.joinpath(f"page-{global_page:04d}.json").write_text(
                json.dumps(
                    {
                        "globalPageIndex": global_page,
                        "basePageNumber": base_page,
                        "spec": spec,
                        "chunks": output_chunks,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            summary["pagesProcessed"] += 1

    (out_dir / "classification_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
