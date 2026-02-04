import argparse
import csv
import json
from datetime import datetime
from pathlib import Path


ALLOWED_MISSING_TYPES = {"source_absent", "boundary_truncation", "true_missing"}


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


def build_chunk_lookup(classification_dir: Path) -> dict[tuple[int, int], dict]:
    lookup = {}
    for page_path in classification_dir.joinpath("pages").glob("page-*.json"):
        payload = json.loads(page_path.read_text(encoding="utf-8", errors="ignore"))
        global_page = payload.get("globalPageIndex")
        for idx, chunk in enumerate(payload.get("chunks", [])):
            lookup[(global_page, idx)] = chunk
    return lookup


def normalize_missing_sources(missing_sources) -> list[dict] | None:
    if not missing_sources:
        return []
    normalized = []
    for entry in missing_sources:
        if isinstance(entry, dict):
            label = entry.get("label")
            missing_type = entry.get("type")
            if not label or not missing_type or missing_type not in ALLOWED_MISSING_TYPES:
                return None
            normalized.append({"label": label, "type": missing_type})
        else:
            return None
    return normalized


def build_pattern(chunk: dict) -> tuple[str, list[str], dict[str, list[str]]] | None:
    present_sources = set()
    for variant in chunk.get("variants", []):
        for label in variant.get("sources", []):
            present_sources.add(label)

    missing_sources = normalize_missing_sources(chunk.get("missingSources"))
    if missing_sources is None:
        return None

    present = sorted(present_sources)
    missing_by_type = {}
    for entry in missing_sources:
        missing_by_type.setdefault(entry["type"], set()).add(entry["label"])
    missing_by_type_sorted = {key: sorted(values) for key, values in missing_by_type.items()}

    if not present and not missing_by_type_sorted:
        return None

    present_key = "+".join(present) if present else "none"
    missing_parts = []
    for missing_type in sorted(missing_by_type_sorted.keys()):
        labels = "+".join(missing_by_type_sorted[missing_type])
        missing_parts.append(f"{missing_type}:{labels}")
    missing_key = "|".join(missing_parts) if missing_parts else "none"
    pattern_key = f"present={present_key};missing={missing_key}"
    return pattern_key, present, missing_by_type_sorted


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build review de-duplication collapse map using review metadata."
    )
    parser.add_argument("--review-index", required=True, help="Path to review_index.json.")
    parser.add_argument("--classification-dir", required=True, help="Stage1d classification folder.")
    parser.add_argument("--out", required=True, help="Output JSON path.")
    parser.add_argument("--csv", help="Optional CSV output path.")
    args = parser.parse_args()

    review_payload = json.loads(Path(args.review_index).read_text(encoding="utf-8", errors="ignore"))
    groups = review_payload.get("groups", [])

    classification_dir = Path(args.classification_dir).resolve()
    subsection_map = build_subsection_map(classification_dir)
    chunk_lookup = build_chunk_lookup(classification_dir)

    aggregates = {}
    skipped = 0
    for entry in groups:
        spec = entry.get("spec")
        diff_class = entry.get("diffClass")
        for chunk_ref in entry.get("chunks", []):
            page = chunk_ref.get("page")
            idx = chunk_ref.get("chunkIndex")
            chunk = chunk_lookup.get((page, idx))
            if not chunk or chunk.get("decision") != "human-review-required":
                skipped += 1
                continue
            pattern = build_pattern(chunk)
            if not pattern:
                skipped += 1
                continue
            pattern_key, present, missing_by_type = pattern
            subsection = subsection_map.get((page, idx), "unknown")
            key = (spec, subsection, diff_class, pattern_key)
            aggregates.setdefault(
                key,
                {
                    "spec": spec,
                    "subsection": subsection,
                    "diffClass": diff_class,
                    "patternKey": pattern_key,
                    "presentSources": present,
                    "missingSources": missing_by_type,
                    "chunks": [],
                    "pages": set(),
                },
            )
            group = aggregates[key]
            group["chunks"].append({"page": page, "chunkIndex": idx})
            group["pages"].add(page)

    collapse_groups = []
    for group in aggregates.values():
        if len(group["chunks"]) < 2:
            continue
        pages = sorted(group["pages"])
        representative = group["chunks"][0]
        collapse_groups.append(
            {
                "spec": group["spec"],
                "subsection": group["subsection"],
                "diffClass": group["diffClass"],
                "patternKey": group["patternKey"],
                "presentSources": group["presentSources"],
                "missingSources": group["missingSources"],
                "representativeChunk": representative,
                "groupSize": len(group["chunks"]),
                "pageStart": pages[0],
                "pageEnd": pages[-1],
                "pages": pages,
                "chunks": group["chunks"],
                "reviewOnceApplyMany": True,
            }
        )

    collapse_groups.sort(
        key=lambda item: (
            item["spec"] or "",
            item["subsection"] or "",
            item["diffClass"] or "",
            -item["groupSize"],
        )
    )

    output = {
        "createdAt": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        "reviewIndex": str(Path(args.review_index).resolve()),
        "classificationDir": str(classification_dir),
        "groupCount": len(collapse_groups),
        "skippedChunks": skipped,
        "groups": collapse_groups,
    }
    Path(args.out).write_text(json.dumps(output, indent=2), encoding="utf-8")

    if args.csv:
        csv_path = Path(args.csv)
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                [
                    "spec",
                    "subsection",
                    "diffClass",
                    "patternKey",
                    "groupSize",
                    "pageStart",
                    "pageEnd",
                    "representativePage",
                    "representativeChunkIndex",
                ]
            )
            for item in collapse_groups:
                writer.writerow(
                    [
                        item.get("spec"),
                        item.get("subsection"),
                        item.get("diffClass"),
                        item.get("patternKey"),
                        item.get("groupSize"),
                        item.get("pageStart"),
                        item.get("pageEnd"),
                        item["representativeChunk"]["page"],
                        item["representativeChunk"]["chunkIndex"],
                    ]
                )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
