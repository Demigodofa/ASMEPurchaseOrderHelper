import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "sectionII_partA_data_digitized"


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def read_text_from_entry(entry):
    text_path = entry.get("textPath")
    if not text_path:
        return ""
    abs_path = DATA / text_path
    if not abs_path.exists():
        return ""
    return abs_path.read_text(encoding="utf-8", errors="ignore")


def page_key(entry, fallback_index):
    footer = entry.get("footerPageNumber")
    if footer is not None:
        return ("footer", int(footer))
    global_idx = entry.get("globalPageIndex")
    if global_idx is not None:
        return ("global", int(global_idx))
    source_pdf = entry.get("sourcePdf")
    source_page = entry.get("sourcePageNumber")
    if source_pdf and source_page is not None:
        return ("source", source_pdf, int(source_page))
    return ("index", fallback_index)


def should_replace(existing_text, new_text):
    existing_len = len(existing_text.strip())
    new_len = len(new_text.strip())
    if existing_len == 0 and new_len > 0:
        return True
    if existing_len < 200 and new_len > existing_len:
        return True
    return False


def sort_key(entry):
    footer = entry.get("footerPageNumber")
    if footer is not None:
        return (0, int(footer))
    source_page = entry.get("sourcePageNumber")
    if source_page is not None:
        return (1, int(source_page))
    global_idx = entry.get("globalPageIndex")
    if global_idx is not None:
        return (2, int(global_idx))
    return (3, 0)


def collect_specs(path: Path):
    if not path.exists():
        return []
    return [p.name for p in path.iterdir() if p.is_dir()]


def merge_spec(spec, sources, output_dir):
    merged_pages = {}
    merged_text = {}
    base_json = None

    for source_label, source_dir in sources:
        spec_dir = source_dir / spec
        spec_json_path = spec_dir / "spec.json"
        if not spec_json_path.exists():
            continue
        spec_json = load_json(spec_json_path)
        if base_json is None and source_label == "base":
            base_json = spec_json
        for idx, entry in enumerate(spec_json.get("pages", [])):
            key = page_key(entry, idx)
            text = read_text_from_entry(entry)
            if key not in merged_pages:
                merged_pages[key] = entry
                merged_text[key] = text
                continue
            if should_replace(merged_text[key], text):
                merged_pages[key] = entry
                merged_text[key] = text

    if not merged_pages:
        return None

    pages = [merged_pages[key] for key in merged_pages.keys()]
    pages = sorted(pages, key=sort_key)

    spec_dir = output_dir / spec
    spec_dir.mkdir(parents=True, exist_ok=True)

    combined_lines = []
    for entry in pages:
        text = read_text_from_entry(entry).strip()
        if not text:
            continue
        label = entry.get("globalPageIndex")
        if label is None:
            label = entry.get("footerPageNumber")
        if label is None:
            label = entry.get("sourcePageNumber")
        if label is None:
            label = "unknown"
        combined_lines.append(f"=== Page {label} ===")
        combined_lines.append(text)

    spec_json = {
        "createdUtc": datetime.now(timezone.utc).isoformat(),
        "spec": spec,
        "rangeStart": None,
        "rangeEnd": None,
        "pages": pages,
    }

    if base_json:
        spec_json["rangeStart"] = base_json.get("rangeStart")
        spec_json["rangeEnd"] = base_json.get("rangeEnd")

    global_indices = [
        entry.get("globalPageIndex")
        for entry in pages
        if entry.get("globalPageIndex") is not None
    ]
    if global_indices:
        spec_json["rangeStart"] = min(global_indices)
        spec_json["rangeEnd"] = max(global_indices)

    (spec_dir / "spec.json").write_text(
        json.dumps(spec_json, indent=2), encoding="utf-8"
    )
    (spec_dir / "spec.txt").write_text(
        "\n\n".join(combined_lines), encoding="utf-8"
    )

    return {
        "spec": spec,
        "rangeStart": spec_json["rangeStart"],
        "rangeEnd": spec_json["rangeEnd"],
        "pageCount": len(pages),
        "path": str((spec_dir / "spec.json").relative_to(DATA)),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True, help="Base spec_corpus directory (relative to data root)")
    parser.add_argument(
        "--secondary",
        action="append",
        default=[],
        help="Secondary spec_corpus directories (relative to data root)",
    )
    parser.add_argument("--output", required=True, help="Output directory (relative to data root)")
    args = parser.parse_args()

    base_dir = DATA / args.base
    secondary_dirs = [DATA / s for s in args.secondary]
    output_dir = DATA / args.output
    output_dir.mkdir(parents=True, exist_ok=True)

    sources = [("base", base_dir)] + [(f"secondary_{i}", d) for i, d in enumerate(secondary_dirs, start=1)]

    specs = set()
    for _, source_dir in sources:
        specs.update(collect_specs(source_dir))

    index = []
    for spec in sorted(specs):
        result = merge_spec(spec, sources, output_dir)
        if result:
            index.append(result)

    (output_dir / "spec_corpus_index.json").write_text(
        json.dumps(index, indent=2), encoding="utf-8"
    )
    print(f"Merged spec corpus: {len(index)} specs -> {output_dir}")


if __name__ == "__main__":
    main()
