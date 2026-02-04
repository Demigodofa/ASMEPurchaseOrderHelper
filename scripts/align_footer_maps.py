import argparse
import csv
import json
from datetime import datetime
from pathlib import Path


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8", errors="ignore"))


def build_footer_lookup(entries: list[dict]) -> dict[int, dict]:
    lookup = {}
    for entry in entries:
        footer = entry.get("footerNumber")
        if footer is None:
            continue
        if footer not in lookup:
            lookup[footer] = entry
    return lookup


def detect_best_offset(
    left_footers: set[int],
    right_footers: set[int],
    min_offset: int,
    max_offset: int,
) -> tuple[int, int]:
    best_overlap = -1
    best_offset = 0
    for offset in range(min_offset, max_offset + 1):
        mapped = {value + offset for value in left_footers}
        overlap = len(mapped & right_footers)
        if overlap > best_overlap or (overlap == best_overlap and abs(offset) < abs(best_offset)):
            best_overlap = overlap
            best_offset = offset
    return best_offset, best_overlap


def main() -> int:
    parser = argparse.ArgumentParser(description="Align footer maps by footer page number.")
    parser.add_argument("--left", required=True, help="Left footer_map.json")
    parser.add_argument("--right", required=True, help="Right footer_map.json")
    parser.add_argument("--out", required=True, help="Output JSON path")
    parser.add_argument("--csv", help="Optional CSV output path")
    parser.add_argument("--offset", type=int, help="Optional offset to apply to left footers.")
    parser.add_argument("--min-offset", type=int, default=-2000, help="Min offset for auto-detect.")
    parser.add_argument("--max-offset", type=int, default=2000, help="Max offset for auto-detect.")
    parser.add_argument(
        "--min-overlap", type=int, default=10, help="Min overlap to accept auto-offset."
    )
    parser.add_argument(
        "--min-gain",
        type=int,
        default=5,
        help="Min overlap gain vs baseline to accept auto-offset.",
    )
    parser.add_argument(
        "--min-footer", type=int, default=1, help="Min footer to consider for offset detection."
    )
    parser.add_argument(
        "--max-footer",
        type=int,
        default=5000,
        help="Max footer to consider for offset detection.",
    )
    args = parser.parse_args()

    left_path = Path(args.left).resolve()
    right_path = Path(args.right).resolve()
    out_path = Path(args.out).resolve()

    left = load_json(left_path)
    right = load_json(right_path)

    left_lookup = build_footer_lookup(left.get("entries", []))
    right_lookup = build_footer_lookup(right.get("entries", []))

    left_set = {value for value in left_lookup if args.min_footer <= value <= args.max_footer}
    right_set = {value for value in right_lookup if args.min_footer <= value <= args.max_footer}

    baseline_overlap = len(left_set & right_set)
    detected_offset, detected_overlap = detect_best_offset(
        left_set, right_set, args.min_offset, args.max_offset
    )

    offset_to_apply = args.offset
    offset_reason = "manual" if args.offset is not None else "none"
    if offset_to_apply is None:
        if detected_overlap >= args.min_overlap and detected_overlap >= baseline_overlap + args.min_gain:
            offset_to_apply = detected_offset
            offset_reason = "auto"
        else:
            offset_to_apply = 0
            offset_reason = "baseline"

    common = []
    for footer in left_lookup:
        normalized = footer + offset_to_apply
        if normalized in right_lookup:
            common.append(normalized)
    common = sorted(set(common))
    aligned = []
    for footer in common:
        left_footer = footer - offset_to_apply
        aligned.append(
            {
                "footerNumber": footer,
                "leftFooterNumber": left_footer,
                "rightFooterNumber": footer,
                "leftPage": left_lookup[left_footer].get("pageNumber"),
                "rightPage": right_lookup[footer].get("pageNumber"),
                "leftLabeledTextPath": left_lookup[left_footer].get("labeledTextPath"),
                "rightLabeledTextPath": right_lookup[footer].get("labeledTextPath"),
            }
        )

    report = {
        "createdAt": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        "leftMap": str(left_path),
        "rightMap": str(right_path),
        "commonFooters": len(common),
        "offsetApplied": offset_to_apply,
        "offsetReason": offset_reason,
        "offsetDetected": detected_offset,
        "offsetBaselineOverlap": baseline_overlap,
        "offsetDetectedOverlap": detected_overlap,
        "aligned": aligned,
    }
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    if args.csv:
        csv_path = Path(args.csv).resolve()
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                [
                    "footerNumber",
                    "leftFooterNumber",
                    "rightFooterNumber",
                    "leftPage",
                    "rightPage",
                    "leftLabeledTextPath",
                    "rightLabeledTextPath",
                ]
            )
            for entry in aligned:
                writer.writerow(
                    [
                        entry.get("footerNumber"),
                        entry.get("leftFooterNumber"),
                        entry.get("rightFooterNumber"),
                        entry.get("leftPage"),
                        entry.get("rightPage"),
                        entry.get("leftLabeledTextPath"),
                        entry.get("rightLabeledTextPath"),
                    ]
                )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
