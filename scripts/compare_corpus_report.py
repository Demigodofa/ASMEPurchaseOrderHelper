import argparse
import csv
import json
import re
from datetime import datetime
from pathlib import Path

from chunk_lock_utils import normalize_for_compare


PAGE_HEADER_RE = re.compile(r"^=== Page (\d+) ===$")


def load_spec_text_pages(path: Path) -> dict[int, str]:
    if not path.exists():
        return {}
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    pages = {}
    current_page = None
    buffer = []
    for line in lines:
        match = PAGE_HEADER_RE.match(line.strip())
        if match:
            if current_page is not None:
                pages[current_page] = "\n".join(buffer).strip()
            current_page = int(match.group(1))
            buffer = []
        else:
            buffer.append(line)
    if current_page is not None:
        pages[current_page] = "\n".join(buffer).strip()
    return pages


def build_part_report(label: str, current_root: Path, final_root: Path, spec_range_path: Path) -> dict:
    spec_data = json.loads(spec_range_path.read_text(encoding="utf-8", errors="ignore"))
    ranges = [
        r
        for r in spec_data.get("ranges", [])
        if r.get("startGlobalPage") and r.get("endGlobalPage")
    ]

    specs = []
    totals = {
        "specCount": 0,
        "pageCount": 0,
        "currentTextPages": 0,
        "finalTextPages": 0,
        "newTextPages": 0,
        "missingTextPages": 0,
        "changedPages": 0,
        "identicalPages": 0,
        "currentChars": 0,
        "finalChars": 0,
    }

    for spec_range in ranges:
        spec = spec_range.get("spec")
        start = int(spec_range["startGlobalPage"])
        end = int(spec_range["endGlobalPage"])
        page_count = end - start + 1

        current_spec_path = current_root / spec / "spec.txt"
        current_pages = load_spec_text_pages(current_spec_path)

        current_text_pages = 0
        final_text_pages = 0
        new_text_pages = 0
        missing_text_pages = 0
        changed_pages = 0
        identical_pages = 0
        current_chars = 0
        final_chars = 0

        for page in range(start, end + 1):
            current_text = current_pages.get(page, "")
            current_text = current_text.strip()
            final_path = final_root / f"page-{page:04d}.txt"
            final_text = ""
            if final_path.exists():
                final_text = final_path.read_text(encoding="utf-8", errors="ignore").strip()

            if current_text:
                current_text_pages += 1
                current_chars += len(current_text)
            if final_text:
                final_text_pages += 1
                final_chars += len(final_text)

            if not current_text and final_text:
                new_text_pages += 1
            if current_text and not final_text:
                missing_text_pages += 1
            if current_text and final_text:
                if normalize_for_compare(current_text) == normalize_for_compare(final_text):
                    identical_pages += 1
                else:
                    changed_pages += 1

        specs.append(
            {
                "spec": spec,
                "rangeStart": start,
                "rangeEnd": end,
                "pageCount": page_count,
                "currentTextPages": current_text_pages,
                "finalTextPages": final_text_pages,
                "newTextPages": new_text_pages,
                "missingTextPages": missing_text_pages,
                "changedPages": changed_pages,
                "identicalPages": identical_pages,
                "currentChars": current_chars,
                "finalChars": final_chars,
                "charDelta": final_chars - current_chars,
                "currentSpecPath": str(current_spec_path),
            }
        )

        totals["specCount"] += 1
        totals["pageCount"] += page_count
        totals["currentTextPages"] += current_text_pages
        totals["finalTextPages"] += final_text_pages
        totals["newTextPages"] += new_text_pages
        totals["missingTextPages"] += missing_text_pages
        totals["changedPages"] += changed_pages
        totals["identicalPages"] += identical_pages
        totals["currentChars"] += current_chars
        totals["finalChars"] += final_chars

    return {
        "label": label,
        "currentCorpus": str(current_root),
        "finalBestText": str(final_root),
        "specRange": str(spec_range_path),
        "totals": totals,
        "specs": specs,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare current spec corpus to final best_text for per-spec changes."
    )
    parser.add_argument(
        "--part",
        action="append",
        default=[],
        help="Part spec: label|currentCorpus|finalBestTextPages|specRange",
    )
    parser.add_argument("--out", required=True, help="Output JSON path.")
    parser.add_argument("--csv", help="Optional CSV output path.")
    args = parser.parse_args()

    parts = []
    for part_spec in args.part:
        label, current_root, final_root, spec_range = part_spec.split("|", 3)
        parts.append(
            build_part_report(
                label,
                Path(current_root).resolve(),
                Path(final_root).resolve(),
                Path(spec_range).resolve(),
            )
        )

    output = {
        "createdAt": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        "parts": parts,
    }
    Path(args.out).write_text(json.dumps(output, indent=2), encoding="utf-8")

    if args.csv:
        csv_path = Path(args.csv)
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                [
                    "part",
                    "spec",
                    "rangeStart",
                    "rangeEnd",
                    "pageCount",
                    "currentTextPages",
                    "finalTextPages",
                    "newTextPages",
                    "missingTextPages",
                    "changedPages",
                    "identicalPages",
                    "currentChars",
                    "finalChars",
                    "charDelta",
                    "currentSpecPath",
                ]
            )
            for part in parts:
                for spec in part["specs"]:
                    writer.writerow(
                        [
                            part["label"],
                            spec["spec"],
                            spec["rangeStart"],
                            spec["rangeEnd"],
                            spec["pageCount"],
                            spec["currentTextPages"],
                            spec["finalTextPages"],
                            spec["newTextPages"],
                            spec["missingTextPages"],
                            spec["changedPages"],
                            spec["identicalPages"],
                            spec["currentChars"],
                            spec["finalChars"],
                            spec["charDelta"],
                            spec["currentSpecPath"],
                        ]
                    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
