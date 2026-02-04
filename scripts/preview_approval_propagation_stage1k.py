import argparse
import csv
import json
from datetime import datetime
from pathlib import Path


VALID_DECISIONS = {"approve", "reject", "defer"}


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


def normalize_decision(value: str | None) -> str:
    if not value:
        return "defer"
    lowered = value.strip().lower()
    return lowered if lowered in VALID_DECISIONS else "defer"


def build_preview_entry(template: dict, collapse: dict | None) -> dict:
    rep = template.get("representative_chunk", {})
    entry = {
        "group_id": template.get("group_id"),
        "spec": template.get("spec"),
        "subsection_id": template.get("subsection_id"),
        "diff_class": template.get("diff_class"),
        "source_presence_pattern": template.get("source_presence_pattern"),
        "group_size": template.get("group_size"),
        "representative_chunk": {
            "page": rep.get("page"),
            "chunkIndex": rep.get("chunkIndex"),
        },
        "pageStart": None,
        "pageEnd": None,
    }
    if collapse:
        entry["spec"] = collapse.get("spec", entry["spec"])
        entry["subsection_id"] = collapse.get("subsection", entry["subsection_id"])
        entry["diff_class"] = collapse.get("diffClass", entry["diff_class"])
        entry["source_presence_pattern"] = collapse.get("patternKey", entry["source_presence_pattern"])
        entry["group_size"] = collapse.get("groupSize", entry["group_size"])
        entry["pageStart"] = collapse.get("pageStart")
        entry["pageEnd"] = collapse.get("pageEnd")
    return entry


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate a dry-run propagation preview from approval templates."
    )
    parser.add_argument("--templates", required=True, help="Path to approval_templates.json.")
    parser.add_argument("--collapse-map", required=True, help="Path to collapse_map.json.")
    parser.add_argument("--out", required=True, help="Output JSON path.")
    parser.add_argument("--csv", help="Optional CSV output path.")
    args = parser.parse_args()

    templates_payload = json.loads(Path(args.templates).read_text(encoding="utf-8", errors="ignore"))
    collapse_payload = json.loads(Path(args.collapse_map).read_text(encoding="utf-8", errors="ignore"))
    collapse_lookup = build_collapse_lookup(collapse_payload)

    approved = []
    rejected = []
    deferred = []
    unmatched = 0

    for template in templates_payload.get("templates", []):
        decision = normalize_decision(template.get("decision"))
        rep = template.get("representative_chunk", {})
        key = (
            template.get("subsection_id"),
            template.get("diff_class"),
            template.get("source_presence_pattern"),
            rep.get("page"),
            rep.get("chunkIndex"),
        )
        collapse = collapse_lookup.get(key)
        if not collapse:
            unmatched += 1

        entry = build_preview_entry(template, collapse)
        if decision == "approve":
            approved.append(entry)
        elif decision == "reject":
            rejected.append(entry)
        else:
            deferred.append(entry)

    output = {
        "createdAt": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        "approvalTemplates": str(Path(args.templates).resolve()),
        "collapseMap": str(Path(args.collapse_map).resolve()),
        "unmatchedTemplates": unmatched,
        "approved_preview": approved,
        "rejected_preview": rejected,
        "deferred_preview": deferred,
    }
    Path(args.out).write_text(json.dumps(output, indent=2), encoding="utf-8")

    if args.csv:
        csv_path = Path(args.csv)
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                [
                    "decision",
                    "group_id",
                    "spec",
                    "subsection_id",
                    "diff_class",
                    "source_presence_pattern",
                    "group_size",
                    "pageStart",
                    "pageEnd",
                    "representativePage",
                    "representativeChunkIndex",
                ]
            )
            for decision, items in (
                ("approve", approved),
                ("reject", rejected),
                ("defer", deferred),
            ):
                for item in items:
                    rep = item["representative_chunk"]
                    writer.writerow(
                        [
                            decision,
                            item.get("group_id"),
                            item.get("spec"),
                            item.get("subsection_id"),
                            item.get("diff_class"),
                            item.get("source_presence_pattern"),
                            item.get("group_size"),
                            item.get("pageStart"),
                            item.get("pageEnd"),
                            rep.get("page"),
                            rep.get("chunkIndex"),
                        ]
                    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
