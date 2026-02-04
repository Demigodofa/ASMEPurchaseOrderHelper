import argparse
import json
from datetime import datetime
from pathlib import Path

from freeze_guard import ensure_not_frozen

SAFE_CLASSES = {"ocr-noise", "orthographic"}
REVIEW_CLASSES = {"numeric", "modal", "structural"}


def choose_majority_variant(variants: list[dict]) -> dict | None:
    safe_variants = [variant for variant in variants if variant.get("class") in SAFE_CLASSES]
    if not safe_variants:
        return None
    safe_variants.sort(
        key=lambda variant: (variant.get("sourceCount", 0), len(variant.get("text", ""))),
        reverse=True,
    )
    return safe_variants[0]


def promotion_reason(missing_sources: list[dict]) -> str:
    if any(entry.get("type") == "boundary_truncation" for entry in missing_sources):
        return "auto-resolvable: boundary_truncation"
    return "auto-resolvable: source_absent"


def main() -> int:
    ensure_not_frozen()
    parser = argparse.ArgumentParser(
        description="Promote auto-resolvable chunk variants into a new best_text corpus."
    )
    parser.add_argument("--classification-dir", required=True, help="Stage1d classification folder.")
    parser.add_argument("--out-promoted", required=True, help="Output best_text_promoted folder.")
    parser.add_argument("--out-review", required=True, help="Output review metadata folder.")
    parser.add_argument("--base-best-text", help="Optional best_text folder for page_map copy.")
    args = parser.parse_args()

    classification_dir = Path(args.classification_dir).resolve()
    out_promoted = Path(args.out_promoted).resolve()
    out_review = Path(args.out_review).resolve()
    out_pages = out_promoted / "pages"
    out_pages.mkdir(parents=True, exist_ok=True)
    out_review.mkdir(parents=True, exist_ok=True)

    if args.base_best_text:
        base_map = Path(args.base_best_text).resolve() / "page_map.json"
        if base_map.exists():
            (out_promoted / "page_map.json").write_text(
                base_map.read_text(encoding="utf-8", errors="ignore"),
                encoding="utf-8",
            )

    summary = {
        "createdAt": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        "pagesProcessed": 0,
        "chunksTotal": 0,
        "chunksPromoted": 0,
        "promotionsByReason": {},
        "promotionsByClass": {},
    }

    review_groups = {}

    for page_path in sorted((classification_dir / "pages").glob("page-*.json")):
        payload = json.loads(page_path.read_text(encoding="utf-8", errors="ignore"))
        spec = payload.get("spec")
        global_page = payload.get("globalPageIndex")
        base_page = payload.get("basePageNumber")
        chunks = payload.get("chunks", [])

        promoted_chunks = []
        page_meta_chunks = []
        for idx, chunk in enumerate(chunks):
            summary["chunksTotal"] += 1
            decision = chunk.get("decision")
            text = chunk.get("text", "")
            promoted = False
            promoted_variant = None
            reason = None
            provenance = []

            if decision == "auto-resolvable":
                promoted_variant = choose_majority_variant(chunk.get("variants", []))
                if promoted_variant:
                    text = promoted_variant.get("text", text)
                    promoted = True
                    reason = promotion_reason(chunk.get("missingSources", []))
                    provenance = promoted_variant.get("sources", [])
                    summary["chunksPromoted"] += 1
                    summary["promotionsByReason"].setdefault(reason, 0)
                    summary["promotionsByReason"][reason] += 1
                    summary["promotionsByClass"].setdefault(promoted_variant.get("class", "unknown"), 0)
                    summary["promotionsByClass"][promoted_variant.get("class", "unknown")] += 1

            if decision == "human-review-required":
                review_classes = set()
                for variant in chunk.get("variants", []):
                    diff_class = variant.get("class")
                    if diff_class in REVIEW_CLASSES:
                        review_classes.add(diff_class)
                if any(entry.get("type") == "true_missing" for entry in chunk.get("missingSources", [])):
                    review_classes.add("true_missing")
                if review_classes:
                    for diff_class in sorted(review_classes):
                        group_key = (spec, diff_class)
                        review_groups.setdefault(group_key, {"pages": set(), "chunks": []})
                        review_groups[group_key]["pages"].add(global_page)
                        review_groups[group_key]["chunks"].append(
                            {
                                "page": global_page,
                                "chunkIndex": idx,
                            }
                        )

            promoted_chunks.append(text or "")
            page_meta_chunks.append(
                {
                    "index": idx,
                    "type": chunk.get("type"),
                    "locked": decision == "locked" or chunk.get("locked", False),
                    "decision": decision,
                    "promoted": promoted,
                    "promotionReason": reason,
                    "promotionSources": sorted(provenance),
                    "promotionClass": promoted_variant.get("class") if promoted_variant else None,
                }
            )

        out_text = "\n".join(promoted_chunks).strip()
        out_pages.joinpath(page_path.name.replace(".json", ".txt")).write_text(
            out_text + ("\n" if out_text else ""), encoding="utf-8"
        )
        out_pages.joinpath(page_path.name).write_text(
            json.dumps(
                {
                    "globalPageIndex": global_page,
                    "basePageNumber": base_page,
                    "spec": spec,
                    "chunks": page_meta_chunks,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        summary["pagesProcessed"] += 1

    combined_lines = []
    for page_path in sorted(out_pages.glob("page-*.txt")):
        page_number = int(page_path.stem.replace("page-", ""))
        text = page_path.read_text(encoding="utf-8", errors="ignore").strip()
        if text:
            combined_lines.append(f"=== Page {page_number} ===")
            combined_lines.append(text)
    (out_promoted / "combined.txt").write_text("\n\n".join(combined_lines), encoding="utf-8")

    (out_promoted / "promotion_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )

    review_index = []
    for (spec, diff_class), group in sorted(review_groups.items()):
        pages = sorted(group["pages"])
        review_index.append(
            {
                "spec": spec,
                "pageStart": pages[0],
                "pageEnd": pages[-1],
                "diffClass": diff_class,
                "pageCount": len(pages),
                "chunkCount": len(group["chunks"]),
                "pages": pages,
                "chunks": group["chunks"],
            }
        )

    (out_review / "review_index.json").write_text(
        json.dumps(
            {
                "createdAt": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                "groups": review_index,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
