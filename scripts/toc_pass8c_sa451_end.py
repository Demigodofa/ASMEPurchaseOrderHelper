import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pdfplumber


SPEC_RE = re.compile(r"\b(?P<spec>(?:SA|SB|SF)-\d+[A-Z]?M?)\b", re.IGNORECASE)
PAGE_RE = re.compile(r"(\d{1,4})\s*$")


def collapse_digit_spaces(prefix: str, line: str) -> str:
    pattern = rf"{prefix}\d(?:[\d ]*\d)"
    return re.sub(pattern, lambda m: m.group(0).replace(" ", ""), line)


def normalize_spec_codes(line: str) -> str:
    line = line.replace("\uFFFD", "").replace("�", "")
    # Fix missing space after spec numbers (e.g., SA-941Terminology).
    line = re.sub(r"\b((?:SA|SB|SF)-\d+)(?=[A-Za-z])", r"\1 ", line)
    # Collapse only internal digit spaces inside spec codes (e.g., SA-4 79 -> SA-479).
    line = collapse_digit_spaces("SA-", line)
    line = collapse_digit_spaces("SB-", line)
    line = collapse_digit_spaces("SF-", line)
    return line


def extract_toc_entries(pdf_path: Path, page_count: int) -> list[dict]:
    entries = []
    start_page = None

    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages[:80]):
            text = page.extract_text() or ""
            top = " ".join(text.split("\n")[:5]).upper()
            if "SPECIFICATIONS LISTED BY MATERIALS" in top:
                start_page = i + 1
                break

        if start_page is None:
            raise RuntimeError(
                "Could not locate 'SPECIFICATIONS LISTED BY MATERIALS' header."
            )

        for page_idx in range(start_page - 1, start_page - 1 + page_count):
            if page_idx >= len(pdf.pages):
                break
            text = pdf.pages[page_idx].extract_text() or ""
            lines = [normalize_spec_codes(line).strip() for line in text.split("\n")]

            current_spec = None
            current_text = []
            for line in lines:
                if not line:
                    continue
                upper = line.upper()
                if upper.startswith("SPECIFICATIONS LISTED BY MATERIALS"):
                    continue
                if re.match(r"^\(\d+\)$", line):
                    continue

                match = SPEC_RE.search(line)
                if match and line.startswith(match.group("spec")):
                    if current_spec:
                        current_spec = None
                        current_text = []
                    current_spec = match.group("spec").upper()
                    current_text = [line]
                elif current_spec:
                    current_text.append(line)

                if current_spec:
                    page_match = PAGE_RE.search(line)
                    if page_match:
                        toc_page = int(page_match.group(1))
                        toc_line = " ".join(current_text)
                        base_spec = current_spec[:-1] if current_spec.endswith("M") else current_spec
                        entries.append(
                            {
                                "spec": base_spec,
                                "tocPageNumber": toc_page,
                                "tocLine": toc_line,
                                "tocSourcePage": page_idx + 1,
                            }
                        )
                        current_spec = None
                        current_text = []

    seen = set()
    unique = []
    for entry in entries:
        if entry["spec"] in seen:
            continue
        seen.add(entry["spec"])
        unique.append(entry)

    unique.sort(key=lambda e: e["tocPageNumber"])
    return unique


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract 'Specifications Listed by Materials' TOC entries from SA-451+ PDF."
    )
    parser.add_argument("--pdf", required=True, help="Path to the SA-451+ PDF.")
    parser.add_argument(
        "--out",
        required=True,
        help="Output JSON path for TOC entries.",
    )
    parser.add_argument(
        "--pages",
        type=int,
        default=8,
        help="Number of TOC pages to parse starting at the header page.",
    )
    args = parser.parse_args()

    pdf_path = Path(args.pdf).resolve()
    out_path = Path(args.out).resolve()

    entries = extract_toc_entries(pdf_path, page_count=args.pages)
    payload = {
        "createdUtc": datetime.now(timezone.utc).isoformat(),
        "sourcePdf": str(pdf_path),
        "entries": entries,
    }
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"TOC entries: {len(entries)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
