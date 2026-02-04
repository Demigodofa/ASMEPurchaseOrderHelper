import argparse
import json
from datetime import datetime
from pathlib import Path

from chunk_lock_utils import chunk_text, detect_spec_header, is_safe_variant
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


def main() -> int:
    ensure_not_frozen()
    parser = argparse.ArgumentParser(
        description="Quilt numbered-item chunks across sources within spec ranges."
    )
    parser.add_argument("--base-best-text", required=True, help="Base best_text pages folder.")
    parser.add_argument("--spec-range", required=True, help="Spec range JSON path.")
    parser.add_argument("--out", required=True, help="Output best_text folder.")
    parser.add_argument("--base-page-map", help="Optional page_map.json for base page numbers.")
    parser.add_argument("--lock-dir", help="Optional lock metadata folder from stage1c.")
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
    parser.add_argument(
        "--chunk-types",
        default="item",
        help="Comma-separated chunk types to process (default: item).",
    )
    parser.add_argument(
        "--min-sim",
        type=float,
        default=0.6,
        help="Deprecated (ignored). Strict variant checks are enforced.",
    )
    parser.add_argument(
        "--min-sim-docx",
        type=float,
        default=0.5,
        help="Deprecated (ignored). Strict variant checks are enforced.",
    )
    args = parser.parse_args()

    base_dir = Path(args.base_best_text).resolve()
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

    lock_dir = Path(args.lock_dir).resolve() if args.lock_dir else None
    allowed_types = {chunk_type.strip() for chunk_type in args.chunk_types.split(",") if chunk_type.strip()}

    summary = {
        "createdAt": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        "pagesProcessed": 0,
        "chunksReplaced": 0,
        "chunksLockedSkipped": 0,
        "replacementsBySource": {},
        "replacementsByVariant": {},
    }

    for spec_range in ranges:
        spec = spec_range.get("spec")
        start = int(spec_range["startGlobalPage"])
        end = int(spec_range["endGlobalPage"])
        for global_page in range(start, end + 1):
            base_page = base_page_map.get(global_page, global_page)
            base_path = base_dir / f"page-{global_page:04d}.txt"
            if not base_path.exists():
                continue
            if lock_dir:
                lock_path = lock_dir / "pages" / f"page-{global_page:04d}.json"
                if lock_path.exists():
                    lock_payload = json.loads(lock_path.read_text(encoding="utf-8", errors="ignore"))
                    chunks = lock_payload.get("chunks", [])
                else:
                    chunks = chunk_text(base_path.read_text(encoding="utf-8", errors="ignore"))
            else:
                chunks = chunk_text(base_path.read_text(encoding="utf-8", errors="ignore"))
            replaced = False

            for idx, chunk in enumerate(chunks):
                if not chunk.get("text"):
                    continue
                if chunk.get("locked"):
                    summary["chunksLockedSkipped"] += 1
                    continue
                if chunk.get("type") not in allowed_types:
                    continue
                base_text = chunk["text"]
                variant_counts = {}
                variant_sources = {}

                is_first = idx == 0
                is_last = idx == len(chunks) - 1
                window = args.adjacent_window if (is_first or is_last) else 0

                for source in sources:
                    mapped_page = source["alignment"].get(base_page)
                    if not mapped_page:
                        continue
                    candidate_pages = range(
                        max(1, mapped_page - window),
                        mapped_page + window + 1,
                    )
                    best_match = None
                    for candidate_page in candidate_pages:
                        candidate_text = read_source_text(source["dir"], candidate_page)
                        if not candidate_text.strip():
                            continue
                        candidate_spec = detect_spec_header(candidate_text)
                        if candidate_spec and spec and candidate_spec != spec:
                            continue
                        for candidate in chunk_text(candidate_text):
                            if candidate["type"] != chunk.get("type"):
                                continue
                            if not candidate.get("text"):
                                continue
                            if not is_safe_variant(base_text, candidate["text"]):
                                continue
                            if not best_match or len(candidate["text"]) > len(best_match):
                                best_match = candidate["text"]
                    if best_match:
                        variant_counts[best_match] = variant_counts.get(best_match, 0) + 1
                        variant_sources.setdefault(best_match, []).append(source["label"])

                if variant_counts:
                    sorted_variants = sorted(
                        variant_counts.items(), key=lambda item: (item[1], len(item[0])), reverse=True
                    )
                    top_text, top_count = sorted_variants[0]
                    second_count = sorted_variants[1][1] if len(sorted_variants) > 1 else 0
                    if top_count >= 2 and top_count > second_count and top_text != base_text:
                        chunk["text"] = top_text
                        replaced = True
                        summary["chunksReplaced"] += 1
                        summary["replacementsByVariant"].setdefault(top_text, 0)
                        summary["replacementsByVariant"][top_text] += 1
                        for label in variant_sources.get(top_text, []):
                            summary["replacementsBySource"].setdefault(label, 0)
                            summary["replacementsBySource"][label] += 1

            out_text = "\n".join([chunk["text"] for chunk in chunks]).strip()
            out_pages.joinpath(f"page-{global_page:04d}.txt").write_text(
                out_text + "\n" if out_text else "", encoding="utf-8"
            )
            out_pages.joinpath(f"page-{global_page:04d}.json").write_text(
                json.dumps(
                    {
                        "globalPageIndex": global_page,
                        "basePageNumber": base_page,
                        "spec": spec,
                        "replaced": replaced,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            summary["pagesProcessed"] += 1

    combined_path = out_dir / "combined.txt"
    combined_lines = []
    for page_path in sorted(out_pages.glob("page-*.txt")):
        page_number = int(page_path.stem.replace("page-", ""))
        text = page_path.read_text(encoding="utf-8", errors="ignore").strip()
        if text:
            combined_lines.append(f"=== Page {page_number} ===")
            combined_lines.append(text)
    combined_path.write_text("\n\n".join(combined_lines), encoding="utf-8")

    (out_dir / "quilt_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
