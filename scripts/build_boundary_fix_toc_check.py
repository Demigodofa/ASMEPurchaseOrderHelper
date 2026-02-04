import argparse
import csv
import json
from datetime import datetime
from pathlib import Path


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8", errors="ignore"))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Cross-check boundary fix moves against TOC-derived ranges."
    )
    parser.add_argument("--fix", required=True, help="Boundary fix list JSON path.")
    parser.add_argument("--toc", required=True, help="TOC index JSON path.")
    parser.add_argument("--out", required=True, help="Output report text path.")
    parser.add_argument("--csv", help="Optional CSV output path.")
    args = parser.parse_args()

    fix_path = Path(args.fix).resolve()
    toc_path = Path(args.toc).resolve()
    out_path = Path(args.out).resolve()

    fix_payload = load_json(fix_path)
    toc_payload = load_json(toc_path)
    toc_lookup = {entry.get("spec"): entry for entry in toc_payload.get("entries", [])}

    entries = fix_payload.get("entries", [])
    moves = [entry for entry in entries if entry.get("action") == "move_to_spec"]

    def toc_range(spec: str):
        entry = toc_lookup.get(spec)
        if not entry:
            return None, None
        return entry.get("startGlobalPage"), entry.get("rangeEndGlobalPage")

    move_in_range = 0
    move_out_of_range = 0
    move_missing_toc = 0

    lines = []
    lines.append("Boundary Fix Cross-Check (TOC)")
    lines.append(f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    lines.append(f"Fix list: {fix_path}")
    lines.append(f"TOC index: {toc_path}")
    lines.append("")

    for entry in moves:
        target = entry.get("target_spec")
        start, end = toc_range(target) if target else (None, None)
        page = entry.get("page")
        in_range = None
        if start is not None and end is not None and page is not None:
            in_range = start <= page <= end
        if start is None or end is None:
            move_missing_toc += 1
        elif in_range:
            move_in_range += 1
        else:
            move_out_of_range += 1

        lines.append(f"- group_id: {entry.get('group_id')}")
        lines.append(f"  current_spec: {entry.get('spec')}")
        lines.append(f"  target_spec: {target}")
        lines.append(f"  representative_chunk: {entry.get('representative_chunk')}")
        if entry.get("footer_page_number") is not None:
            lines.append(f"  footer_page_number: {entry.get('footer_page_number')}")
        if entry.get("source_pdf"):
            lines.append(f"  source_pdf: {entry.get('source_pdf')}")
        if entry.get("source_page_number") is not None:
            lines.append(f"  source_page_number: {entry.get('source_page_number')}")
        if start is not None and end is not None:
            lines.append(f"  toc_range_global: {start}-{end}")
            lines.append(f"  toc_range_contains_page: {in_range}")
        else:
            lines.append("  toc_range_global: missing")
        lines.append("")

    total_entries = len(entries)
    confirm_current = sum(1 for entry in entries if entry.get("action") == "confirm_current")

    summary = [
        f"Entries with notes: {total_entries}",
        f"Moves requested: {len(moves)}",
        f"Confirm current: {confirm_current}",
        f"Moves in TOC range: {move_in_range}",
        f"Moves out of TOC range: {move_out_of_range}",
        f"Moves missing TOC spec: {move_missing_toc}",
    ]
    lines.insert(4, "Summary:")
    lines[5:5] = [f"  {line}" for line in summary]
    lines.insert(5 + len(summary), "")

    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    if args.csv:
        csv_path = Path(args.csv).resolve()
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                [
                    "group_id",
                    "current_spec",
                    "target_spec",
                    "representative_chunk",
                    "page",
                    "chunk_index",
                    "footer_page_number",
                    "source_pdf",
                    "source_page_number",
                    "toc_start_global",
                    "toc_end_global",
                    "toc_contains_page",
                ]
            )
            for entry in moves:
                target = entry.get("target_spec")
                start, end = toc_range(target) if target else (None, None)
                page = entry.get("page")
                in_range = None
                if start is not None and end is not None and page is not None:
                    in_range = start <= page <= end
                writer.writerow(
                    [
                        entry.get("group_id"),
                        entry.get("spec"),
                        target,
                        entry.get("representative_chunk"),
                        entry.get("page"),
                        entry.get("chunkIndex"),
                        entry.get("footer_page_number"),
                        entry.get("source_pdf"),
                        entry.get("source_page_number"),
                        start,
                        end,
                        in_range,
                    ]
                )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
