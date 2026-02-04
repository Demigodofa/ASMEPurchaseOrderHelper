import argparse
import csv
import json
from datetime import datetime
from pathlib import Path


def build_collapse_lookup(collapse_map: dict) -> dict[tuple[str, str, str, int, int], dict]:
    lookup = {}
    for group in collapse_map.get("groups", []):
        rep = group.get("representativeChunk", {})
        key = (
            group.get("subsection"),
            group.get("diffClass"),
            group.get("patternKey"),
            rep.get("page"),
            rep.get("chunkIndex"),
        )
        lookup[key] = group
    return lookup


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate approval templates for review groups from collapse map metadata."
    )
    parser.add_argument("--top-groups", required=True, help="Path to top_review_groups.json.")
    parser.add_argument("--collapse-map", required=True, help="Path to collapse_map.json.")
    parser.add_argument("--out", required=True, help="Output JSON path.")
    parser.add_argument("--csv", help="Optional CSV output path.")
    args = parser.parse_args()

    top_payload = json.loads(Path(args.top_groups).read_text(encoding="utf-8", errors="ignore"))
    collapse_payload = json.loads(Path(args.collapse_map).read_text(encoding="utf-8", errors="ignore"))
    collapse_lookup = build_collapse_lookup(collapse_payload)

    templates = []
    for group in top_payload.get("groups", []):
        rep = group.get("representativeChunk", {})
        key = (
            group.get("subsection"),
            group.get("diffClass"),
            group.get("patternKey"),
            rep.get("page"),
            rep.get("chunkIndex"),
        )
        collapse = collapse_lookup.get(key)
        group_size = group.get("groupSize")
        if collapse and collapse.get("groupSize") is not None:
            group_size = collapse.get("groupSize")

        templates.append(
            {
                "group_id": group.get("groupId"),
                "representative_chunk": {
                    "page": rep.get("page"),
                    "chunkIndex": rep.get("chunkIndex"),
                },
                "subsection_id": group.get("subsection"),
                "diff_class": group.get("diffClass"),
                "source_presence_pattern": group.get("patternKey"),
                "group_size": group_size,
                "decision": None,
                "reviewer_id": None,
                "decision_timestamp": None,
                "notes": None,
            }
        )

    out_payload = {
        "createdAt": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        "topGroups": str(Path(args.top_groups).resolve()),
        "collapseMap": str(Path(args.collapse_map).resolve()),
        "templates": templates,
    }
    Path(args.out).write_text(json.dumps(out_payload, indent=2), encoding="utf-8")

    if args.csv:
        csv_path = Path(args.csv)
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                [
                    "group_id",
                    "representative_chunk",
                    "subsection_id",
                    "diff_class",
                    "source_presence_pattern",
                    "group_size",
                    "decision",
                    "reviewer_id",
                    "decision_timestamp",
                    "notes",
                ]
            )
            for item in templates:
                rep = item["representative_chunk"]
                rep_value = (
                    f"{rep.get('page')}:{rep.get('chunkIndex')}"
                    if rep.get("page") is not None and rep.get("chunkIndex") is not None
                    else ""
                )
                writer.writerow(
                    [
                        item.get("group_id"),
                        rep_value,
                        item.get("subsection_id"),
                        item.get("diff_class"),
                        item.get("source_presence_pattern"),
                        item.get("group_size"),
                        item.get("decision"),
                        item.get("reviewer_id"),
                        item.get("decision_timestamp"),
                        item.get("notes"),
                    ]
                )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
