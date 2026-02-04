import argparse
import csv
import json
from datetime import datetime
from pathlib import Path


DIFF_CLASSES = ["numeric", "modal", "structural", "true_missing"]


def build_subsection_map(classification_dir: Path) -> dict[tuple[int, int], str]:
    pages = sorted(classification_dir.joinpath("pages").glob("page-*.json"))
    subsection_map = {}
    state = {}
    for page_path in pages:
        payload = json.loads(page_path.read_text(encoding="utf-8", errors="ignore"))
        spec = payload.get("spec") or "unknown"
        global_page = payload.get("globalPageIndex")
        if spec not in state:
            state[spec] = {"counter": 0, "current": None}
        for idx, chunk in enumerate(payload.get("chunks", [])):
            if chunk.get("type") == "heading":
                state[spec]["counter"] += 1
                state[spec]["current"] = f"h-{state[spec]['counter']:04d}-{global_page:04d}-{idx:03d}"
            subsection_map[(global_page, idx)] = state[spec]["current"] or "unknown"
    return subsection_map


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build review queue with subsection identifiers from classification metadata."
    )
    parser.add_argument("--review-index", required=True, help="Path to review_index.json.")
    parser.add_argument("--classification-dir", required=True, help="Stage1d classification folder.")
    parser.add_argument("--out", required=True, help="Output JSON path.")
    parser.add_argument("--csv", help="Optional CSV output path.")
    args = parser.parse_args()

    review_payload = json.loads(Path(args.review_index).read_text(encoding="utf-8", errors="ignore"))
    groups = review_payload.get("groups", [])

    subsection_map = build_subsection_map(Path(args.classification_dir).resolve())

    aggregates = {}
    for entry in groups:
        spec = entry.get("spec")
        diff_class = entry.get("diffClass")
        if diff_class not in DIFF_CLASSES:
            continue
        for chunk_ref in entry.get("chunks", []):
            page = chunk_ref.get("page")
            chunk_index = chunk_ref.get("chunkIndex")
            subsection = subsection_map.get((page, chunk_index), "unknown")
            key = (spec, subsection)
            aggregates.setdefault(
                key,
                {
                    "spec": spec,
                    "subsection": subsection,
                    "pageStart": None,
                    "pageEnd": None,
                    "totalChunks": 0,
                    "diffCounts": {cls: 0 for cls in DIFF_CLASSES},
                },
            )
            aggregate = aggregates[key]
            aggregate["totalChunks"] += 1
            aggregate["diffCounts"][diff_class] += 1
            if page is not None:
                if aggregate["pageStart"] is None or page < aggregate["pageStart"]:
                    aggregate["pageStart"] = page
                if aggregate["pageEnd"] is None or page > aggregate["pageEnd"]:
                    aggregate["pageEnd"] = page

    ranked = sorted(
        aggregates.values(),
        key=lambda item: (
            -item["diffCounts"]["numeric"],
            -item["diffCounts"]["modal"],
            -item["diffCounts"]["structural"],
            -item["diffCounts"]["true_missing"],
            item["spec"] or "",
            item["subsection"] or "",
        ),
    )

    output = {
        "createdAt": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        "reviewIndex": str(Path(args.review_index).resolve()),
        "classificationDir": str(Path(args.classification_dir).resolve()),
        "subsectionStrategy": "latest-heading-chunk-id",
        "groups": ranked,
    }
    Path(args.out).write_text(json.dumps(output, indent=2), encoding="utf-8")

    if args.csv:
        csv_path = Path(args.csv)
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                ["spec", "subsection", "pageStart", "pageEnd", "totalChunks"]
                + [f"{cls}Count" for cls in DIFF_CLASSES]
            )
            for item in ranked:
                row = [
                    item.get("spec"),
                    item.get("subsection"),
                    item.get("pageStart"),
                    item.get("pageEnd"),
                    item.get("totalChunks"),
                ] + [item["diffCounts"][cls] for cls in DIFF_CLASSES]
                writer.writerow(row)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
