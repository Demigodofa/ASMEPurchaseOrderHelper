import argparse
import csv
import json
from datetime import datetime
from pathlib import Path


DIFF_CLASSES = ["numeric", "modal", "structural", "true_missing"]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a human-review prioritization queue from review_index.json."
    )
    parser.add_argument("--review-index", required=True, help="Path to review_index.json.")
    parser.add_argument("--out", required=True, help="Output JSON path.")
    parser.add_argument("--csv", help="Optional CSV output path.")
    args = parser.parse_args()

    payload = json.loads(Path(args.review_index).read_text(encoding="utf-8", errors="ignore"))
    groups = payload.get("groups", [])

    aggregates = {}
    for entry in groups:
        spec = entry.get("spec")
        subsection = entry.get("subsection") or "unknown"
        diff_class = entry.get("diffClass")
        if diff_class not in DIFF_CLASSES:
            continue
        key = (spec, subsection)
        aggregates.setdefault(
            key,
            {
                "spec": spec,
                "subsection": subsection,
                "pageStart": entry.get("pageStart"),
                "pageEnd": entry.get("pageEnd"),
                "totalChunks": 0,
                "diffCounts": {cls: 0 for cls in DIFF_CLASSES},
            },
        )
        aggregate = aggregates[key]
        aggregate["totalChunks"] += entry.get("chunkCount", 0)
        aggregate["diffCounts"][diff_class] += entry.get("chunkCount", 0)
        if entry.get("pageStart") is not None:
            if aggregate["pageStart"] is None or entry["pageStart"] < aggregate["pageStart"]:
                aggregate["pageStart"] = entry["pageStart"]
        if entry.get("pageEnd") is not None:
            if aggregate["pageEnd"] is None or entry["pageEnd"] > aggregate["pageEnd"]:
                aggregate["pageEnd"] = entry["pageEnd"]

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
