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
        description="Lock chunk text that reaches consensus across sources within spec ranges."
    )
    parser.add_argument("--base-best-text", required=True, help="Base best_text pages folder.")
    parser.add_argument("--spec-range", required=True, help="Spec range JSON path.")
    parser.add_argument("--out", required=True, help="Output folder for lock metadata.")
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
    parser.add_argument(
        "--min-matches",
        type=int,
        default=2,
        help="Minimum number of sources required to lock a chunk.",
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

    summary = {
        "createdAt": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        "pagesProcessed": 0,
        "chunksTotal": 0,
        "chunksLocked": 0,
        "lockedByType": {},
        "lockedBySource": {},
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
            base_text = base_path.read_text(encoding="utf-8", errors="ignore")
            chunks = chunk_text(base_text)

            for chunk in chunks:
                summary["chunksTotal"] += 1
                chunk["locked"] = False
                chunk["sources"] = []
                chunk["matches"] = {}
                if not chunk.get("text"):
                    continue
                source_matches = {}

                for source in sources:
                    mapped_page = source["alignment"].get(base_page)
                    if not mapped_page:
                        continue
                    candidate_pages = range(
                        max(1, mapped_page - args.adjacent_window),
                        mapped_page + args.adjacent_window + 1,
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
                            if candidate["type"] != chunk["type"]:
                                continue
                            if not is_safe_variant(chunk["text"], candidate["text"]):
                                continue
                            if not best_match or len(candidate["text"]) > len(best_match):
                                best_match = candidate["text"]
                    if best_match:
                        source_matches[source["label"]] = best_match

                if len(source_matches) >= args.min_matches:
                    chunk["locked"] = True
                    chunk["sources"] = sorted(source_matches.keys())
                    chunk["matches"] = source_matches
                    summary["chunksLocked"] += 1
                    summary["lockedByType"].setdefault(chunk["type"], 0)
                    summary["lockedByType"][chunk["type"]] += 1
                    for label in chunk["sources"]:
                        summary["lockedBySource"].setdefault(label, 0)
                        summary["lockedBySource"][label] += 1

            out_pages.joinpath(f"page-{global_page:04d}.json").write_text(
                json.dumps(
                    {
                        "globalPageIndex": global_page,
                        "basePageNumber": base_page,
                        "spec": spec,
                        "chunks": chunks,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            summary["pagesProcessed"] += 1

    (out_dir / "lock_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
