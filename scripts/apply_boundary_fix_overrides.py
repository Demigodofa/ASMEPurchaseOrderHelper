import argparse
import csv
import json
from datetime import datetime
from pathlib import Path


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8", errors="ignore"))


def build_footer_ranges(toc_entries: list[dict]) -> list[tuple[str, int, int | None]]:
    sorted_entries = sorted(toc_entries, key=lambda e: e.get("tocPageNumber") or 0)
    ranges = []
    for i, entry in enumerate(sorted_entries):
        start = entry.get("tocPageNumber")
        if start is None:
            continue
        end = None
        for j in range(i + 1, len(sorted_entries)):
            next_start = sorted_entries[j].get("tocPageNumber")
            if next_start is not None:
                end = next_start - 1
                break
        ranges.append((entry["spec"], start, end))
    return ranges


def find_spec_by_footer(ranges: list[tuple[str, int, int | None]], page_num: int | None) -> str | None:
    if page_num is None:
        return None
    for spec, start, end in ranges:
        if end is None:
            if page_num >= start:
                return spec
        elif start <= page_num <= end:
            return spec
    return None


def in_toc_range(toc_index_lookup: dict, spec: str | None, page: int | None) -> bool:
    if not spec or page is None:
        return False
    entry = toc_index_lookup.get(spec)
    if not entry:
        return False
    start = entry.get("startGlobalPage")
    end = entry.get("rangeEndGlobalPage")
    if start is None or end is None:
        return False
    return start <= page <= end


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Apply footer/TOC overrides to boundary fix list entries."
    )
    parser.add_argument("--fix", required=True, help="Boundary fix list JSON path.")
    parser.add_argument("--toc-index", required=True, help="TOC index JSON path.")
    parser.add_argument("--toc-entries", required=True, help="TOC entries JSON path.")
    parser.add_argument("--out", required=True, help="Output JSON path.")
    parser.add_argument("--csv", help="Optional CSV output path.")
    args = parser.parse_args()

    fix_path = Path(args.fix).resolve()
    toc_index_path = Path(args.toc_index).resolve()
    toc_entries_path = Path(args.toc_entries).resolve()
    out_path = Path(args.out).resolve()

    fix_payload = load_json(fix_path)
    toc_index = load_json(toc_index_path)
    toc_entries = load_json(toc_entries_path).get("entries", [])

    toc_lookup = {entry.get("spec"): entry for entry in toc_index.get("entries", [])}
    footer_ranges = build_footer_ranges(toc_entries)

    overrides_applied = 0
    updated_entries = []

    for entry in fix_payload.get("entries", []):
        updated = dict(entry)
        action = updated.get("action")
        if action == "move_to_spec":
            target = updated.get("target_spec")
            page = updated.get("page")
            footer_page = updated.get("footer_page_number")

            if not in_toc_range(toc_lookup, target, page):
                if footer_page is None:
                    updated["action"] = "drop_page"
                    updated["override_reason"] = "no_footer_page_number"
                    overrides_applied += 1
                else:
                    spec_by_footer = find_spec_by_footer(footer_ranges, footer_page)
                    if spec_by_footer and spec_by_footer != target:
                        updated["original_target_spec"] = target
                        updated["target_spec"] = spec_by_footer
                        updated["override_reason"] = "footer_page_number_match"
                        overrides_applied += 1
                    elif spec_by_footer is None:
                        updated["action"] = "needs_manual_mapping"
                        updated["override_reason"] = "footer_page_number_unmapped"
                        overrides_applied += 1

        updated_entries.append(updated)

    output = {
        "createdAt": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        "sourceFixList": str(fix_path),
        "tocIndex": str(toc_index_path),
        "tocEntries": str(toc_entries_path),
        "overridesApplied": overrides_applied,
        "entries": updated_entries,
    }
    out_path.write_text(json.dumps(output, indent=2), encoding="utf-8")

    if args.csv:
        csv_path = Path(args.csv).resolve()
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                [
                    "group_id",
                    "spec",
                    "action",
                    "target_spec",
                    "original_target_spec",
                    "override_reason",
                    "page",
                    "chunkIndex",
                    "source_pdf",
                    "source_page_number",
                    "footer_page_number",
                    "notes",
                ]
            )
            for entry in updated_entries:
                writer.writerow(
                    [
                        entry.get("group_id"),
                        entry.get("spec"),
                        entry.get("action"),
                        entry.get("target_spec"),
                        entry.get("original_target_spec"),
                        entry.get("override_reason"),
                        entry.get("page"),
                        entry.get("chunkIndex"),
                        entry.get("source_pdf"),
                        entry.get("source_page_number"),
                        entry.get("footer_page_number"),
                        entry.get("notes"),
                    ]
                )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
