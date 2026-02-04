import argparse
import json
from pathlib import Path


def load_manifest(manifest_path: Path) -> dict:
    payload = json.loads(manifest_path.read_text(encoding="utf-8", errors="ignore"))
    lookup = {}
    for page in payload.get("pages", []):
        source_pdf = page.get("sourcePdf")
        source_page = page.get("sourcePageNumber")
        global_idx = page.get("globalPageIndex")
        if source_pdf and source_page and global_idx:
            lookup[(source_pdf, int(source_page))] = int(global_idx)
    return lookup


def load_alignment(alignment_path: Path) -> list[dict]:
    payload = json.loads(alignment_path.read_text(encoding="ascii", errors="ignore"))
    return payload.get("matches", [])


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Map consensus pages to global indices and build best_text output."
    )
    parser.add_argument("--consensus", required=True, help="Consensus output folder (stage 2).")
    parser.add_argument("--manifest", required=True, help="Existing manifest.json path.")
    parser.add_argument("--out", required=True, help="Output best_text root.")
    parser.add_argument(
        "--alignment",
        action="append",
        default=[],
        help="Alignment spec: alignment.json|sourcePdfName",
    )
    args = parser.parse_args()

    consensus_dir = Path(args.consensus).resolve()
    manifest_path = Path(args.manifest).resolve()
    out_dir = Path(args.out).resolve()
    out_pages = out_dir / "pages"
    out_pages.mkdir(parents=True, exist_ok=True)

    manifest_lookup = load_manifest(manifest_path)

    alignment_sources = []
    for spec in args.alignment:
        parts = spec.split("|")
        if len(parts) != 2:
            raise ValueError("Alignment spec must be alignment.json|sourcePdfName")
        alignment_sources.append(
            {"alignment": Path(parts[0]).resolve(), "sourcePdf": parts[1]}
        )

    base_to_candidates = {}
    for source in alignment_sources:
        matches = load_alignment(source["alignment"])
        for match in matches:
            base_page = match.get("basePageNumber")
            other_page = match.get("otherPageNumber")
            score = match.get("score", 0.0)
            if not base_page or not other_page:
                continue
            base_to_candidates.setdefault(int(base_page), []).append(
                {
                    "sourcePdf": source["sourcePdf"],
                    "sourcePageNumber": int(other_page),
                    "score": float(score),
                }
            )

    consensus_pages = sorted((consensus_dir / "pages").glob("page-*.txt"))
    missing = []
    mapped = []
    for page_path in consensus_pages:
        page_number = int(page_path.stem.replace("page-", ""))
        candidates = base_to_candidates.get(page_number, [])
        if not candidates:
            missing.append(page_number)
            continue
        best = max(candidates, key=lambda item: item["score"])
        global_index = manifest_lookup.get(
            (best["sourcePdf"], best["sourcePageNumber"])
        )
        if not global_index:
            missing.append(page_number)
            continue
        text = page_path.read_text(encoding="utf-8", errors="ignore")
        out_pages.joinpath(f"page-{global_index:04d}.txt").write_text(
            text, encoding="utf-8", errors="ignore"
        )
        mapped.append(
            {
                "basePageNumber": page_number,
                "sourcePdf": best["sourcePdf"],
                "sourcePageNumber": best["sourcePageNumber"],
                "globalPageIndex": global_index,
                "score": best["score"],
            }
        )

    combined_path = out_dir / "combined.txt"
    combined_lines = []
    for entry in sorted(mapped, key=lambda item: item["globalPageIndex"]):
        text_path = out_pages / f"page-{entry['globalPageIndex']:04d}.txt"
        if text_path.exists():
            combined_lines.append(f"=== Page {entry['globalPageIndex']} ===")
            combined_lines.append(text_path.read_text(encoding="utf-8", errors="ignore").strip())
    combined_path.write_text("\n\n".join(combined_lines), encoding="utf-8")

    map_payload = {
        "mappedCount": len(mapped),
        "missingBasePages": missing,
        "mappings": mapped,
    }
    (out_dir / "page_map.json").write_text(
        json.dumps(map_payload, indent=2), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
