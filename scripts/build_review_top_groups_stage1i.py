import argparse
import csv
import json
from datetime import datetime
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate a top-N largest review groups report from collapse_map.json."
    )
    parser.add_argument("--collapse-map", required=True, help="Path to collapse_map.json.")
    parser.add_argument("--out", required=True, help="Output JSON path.")
    parser.add_argument("--csv", help="Optional CSV output path.")
    parser.add_argument("--top", type=int, default=25, help="Top N groups to emit.")
    args = parser.parse_args()

    payload = json.loads(Path(args.collapse_map).read_text(encoding="utf-8", errors="ignore"))
    groups = payload.get("groups", [])

    ranked = sorted(groups, key=lambda item: item.get("groupSize", 0), reverse=True)
    top_groups = ranked[: max(args.top, 0)]

    output_groups = []
    for idx, group in enumerate(top_groups, start=1):
        rep = group.get("representativeChunk", {})
        output_groups.append(
            {
                "groupId": f"group-{idx:03d}",
                "subsection": group.get("subsection"),
                "diffClass": group.get("diffClass"),
                "patternKey": group.get("patternKey"),
                "groupSize": group.get("groupSize"),
                "representativeChunk": {
                    "page": rep.get("page"),
                    "chunkIndex": rep.get("chunkIndex"),
                },
            }
        )

    out_payload = {
        "createdAt": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        "collapseMap": str(Path(args.collapse_map).resolve()),
        "topN": args.top,
        "groups": output_groups,
    }
    Path(args.out).write_text(json.dumps(out_payload, indent=2), encoding="utf-8")

    if args.csv:
        csv_path = Path(args.csv)
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                [
                    "groupId",
                    "subsection",
                    "diffClass",
                    "patternKey",
                    "groupSize",
                    "representativePage",
                    "representativeChunkIndex",
                ]
            )
            for group in output_groups:
                rep = group["representativeChunk"]
                writer.writerow(
                    [
                        group["groupId"],
                        group.get("subsection"),
                        group.get("diffClass"),
                        group.get("patternKey"),
                        group.get("groupSize"),
                        rep.get("page"),
                        rep.get("chunkIndex"),
                    ]
                )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
