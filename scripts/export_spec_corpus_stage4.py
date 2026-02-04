import argparse
import json
import pathlib
import re
from datetime import datetime, timezone


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8", errors="ignore"))


def build_spec_ranges(spec_range_path):
    spec_data = load_json(spec_range_path)
    ranges = []
    for item in spec_data.get("ranges", []):
        if item.get("status") == "missing-range":
            continue
        start = item.get("startGlobalPage")
        end = item.get("endGlobalPage")
        if not start or not end or end < start:
            continue
        ranges.append({"spec": item["spec"], "start": start, "end": end})
    return ranges


def load_manifest_pages(manifest_path):
    manifest = load_json(manifest_path)
    pages = {}
    for page in manifest.get("pages", []):
        pages[page["globalPageIndex"]] = page
    return pages


def extract_footer_page_number(text):
    if not text:
        return None
    lines = text.replace("\r\n", "\n").split("\n")
    footer_re = re.compile(r"^\d{1,4}$")
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        if footer_re.match(line):
            return int(line)
    return None


def main():
    parser = argparse.ArgumentParser(description="Export spec corpus using rebuild best_text.")
    parser.add_argument("--manifest", required=True, help="Path to manifest.json.")
    parser.add_argument("--spec-range", required=True, help="Path to spec_range_pass11.json.")
    parser.add_argument("--best-text", required=True, help="Folder with best_text/pages.")
    parser.add_argument("--out", required=True, help="Output spec_corpus folder.")
    parser.add_argument(
        "--data-root",
        required=False,
        help="Root folder for relative text paths (defaults to sectionII_partA_data_digitized).",
    )
    args = parser.parse_args()

    manifest_pages = load_manifest_pages(pathlib.Path(args.manifest))
    ranges = build_spec_ranges(pathlib.Path(args.spec_range))
    best_text_dir = pathlib.Path(args.best_text).resolve()
    output_dir = pathlib.Path(args.out)
    if args.data_root:
        data_root = pathlib.Path(args.data_root).resolve()
    else:
        data_root = best_text_dir
        if len(best_text_dir.parents) >= 4:
            data_root = best_text_dir.parents[3]
    output_dir.mkdir(parents=True, exist_ok=True)
    output_index = output_dir / "spec_corpus_index.json"

    index = []
    for spec_range in ranges:
        spec = spec_range["spec"]
        spec_dir = output_dir / spec
        spec_dir.mkdir(parents=True, exist_ok=True)
        spec_pages = []
        combined_lines = []
        for idx in range(spec_range["start"], spec_range["end"] + 1):
            page = manifest_pages.get(idx)
            if not page:
                continue
            text_path = best_text_dir / f"page-{idx:04d}.txt"
            text = ""
            if text_path.exists():
                text = text_path.read_text(encoding="utf-8", errors="ignore")
            footer_page_number = extract_footer_page_number(text)
            spec_pages.append(
                {
                    "globalPageIndex": idx,
                    "sourcePdf": page["sourcePdf"],
                    "sourcePageNumber": page["sourcePageNumber"],
                    "footerPageNumber": footer_page_number,
                    "textPath": str(text_path.relative_to(data_root)) if text_path.exists() else None,
                    "assets": {},
                }
            )
            if text:
                combined_lines.append(f"=== Page {idx} ===")
                combined_lines.append(text.strip())

        spec_json = {
            "createdUtc": datetime.now(timezone.utc).isoformat(),
            "spec": spec,
            "rangeStart": spec_range["start"],
            "rangeEnd": spec_range["end"],
            "pages": spec_pages,
        }
        (spec_dir / "spec.json").write_text(
            json.dumps(spec_json, indent=2), encoding="utf-8"
        )
        (spec_dir / "spec.txt").write_text("\n\n".join(combined_lines), encoding="utf-8")

        index.append(
            {
                "spec": spec,
                "rangeStart": spec_range["start"],
                "rangeEnd": spec_range["end"],
                "pageCount": len(spec_pages),
                "path": str((spec_dir / "spec.json").relative_to(output_dir)),
            }
        )

    output_index.write_text(json.dumps(index, indent=2), encoding="utf-8")
    print("Spec corpus export complete.")


if __name__ == "__main__":
    main()
