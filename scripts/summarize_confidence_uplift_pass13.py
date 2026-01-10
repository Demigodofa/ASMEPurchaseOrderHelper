import json
import pathlib
from collections import Counter, defaultdict
from datetime import datetime, timezone


ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / "sectionII_partA_data_digitized"

PASS13_PATH = DATA / "confidence_uplift_pass13.json"
SPEC_RANGE_PATH = DATA / "spec_range_pass11.json"
OUTPUT_PATH = DATA / "confidence_uplift_priorities.json"


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def build_spec_ranges():
    spec_data = load_json(SPEC_RANGE_PATH)
    ranges = []
    for item in spec_data.get("ranges", []):
        start = item.get("startGlobalPage")
        end = item.get("endGlobalPage")
        if start is None or end is None:
            continue
        ranges.append((item.get("spec"), start, end))
    return ranges


def find_spec_for_page(spec_ranges, page_idx):
    for spec, start, end in spec_ranges:
        if spec and start <= page_idx <= end:
            return spec
    return None


def summarize_table_flags(flags, spec_ranges):
    counts = Counter()
    pages_by_spec = defaultdict(set)
    unmapped = 0

    for flag in flags:
        spec = flag.get("spec") or find_spec_for_page(spec_ranges, flag.get("globalPageIndex", -1))
        if not spec:
            unmapped += 1
            continue
        counts[spec] += 1
        pages_by_spec[spec].add(flag.get("globalPageIndex"))

    top_specs = [
        {
            "spec": spec,
            "count": count,
            "pages": sorted(pages_by_spec[spec]),
        }
        for spec, count in counts.most_common(15)
    ]

    return {
        "total": len(flags),
        "unmapped": unmapped,
        "topSpecs": top_specs,
    }


def summarize_section_gaps(gaps, spec_ranges):
    counts = Counter()
    pages_by_spec = defaultdict(set)
    unmapped = 0

    for gap in gaps:
        page = gap.get("gapStartPage")
        if page is None:
            continue
        spec = find_spec_for_page(spec_ranges, page)
        if not spec:
            unmapped += 1
            continue
        counts[spec] += 1
        pages_by_spec[spec].add(page)

    top_specs = [
        {
            "spec": spec,
            "count": count,
            "gapStartPages": sorted(pages_by_spec[spec]),
        }
        for spec, count in counts.most_common(15)
    ]

    return {
        "total": len(gaps),
        "unmapped": unmapped,
        "topSpecs": top_specs,
    }


def main():
    pass13 = load_json(PASS13_PATH)
    spec_ranges = build_spec_ranges()

    table_flags = pass13.get("tableSchemaFlags", [])
    section_gaps = pass13.get("sectionGapSignals", [])

    report = {
        "createdUtc": datetime.now(timezone.utc).isoformat(),
        "sourceCreatedUtc": pass13.get("createdUtc"),
        "summary": pass13.get("summary"),
        "tableSchemaFlags": summarize_table_flags(table_flags, spec_ranges),
        "sectionGapSignals": summarize_section_gaps(section_gaps, spec_ranges),
    }

    OUTPUT_PATH.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print(json.dumps(report["summary"], indent=2))


if __name__ == "__main__":
    main()
