import csv
import json
import pathlib
import re
from datetime import datetime, timezone


ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
SPEC_CORPUS_DIR = ROOT / "sectionII_partA_data_digitized" / "spec_corpus"
SPEC_INDEX_PATH = SPEC_CORPUS_DIR / "spec_corpus_index.json"

ORDERING_ITEMS_JSON = DATA_DIR / "ordering-items-by-spec.json"
ORDERING_ITEMS_CSV = DATA_DIR / "ordering-items-by-spec.csv"
ORDERING_REQUIRED_JSON = DATA_DIR / "ordering-required-fields.json"
ORDERING_REQUIRED_CSV = DATA_DIR / "ordering-required-fields.csv"

MATERIALS_JSON = DATA_DIR / "materials.json"
MATERIALS_FERROUS_JSON = DATA_DIR / "materials-ferrous.json"
MATERIALS_NONFERROUS_JSON = DATA_DIR / "materials-nonferrous.json"
MATERIALS_ELECTRODE_JSON = DATA_DIR / "materials-electrode.json"


ORDERING_HEADER_RE = re.compile(
    r"(?s)(?P<section>\d+)\s*\.?\s*(Ordering\s*Information|Ordering\s*Requirements|Information\s*for\s*Ordering)",
    re.IGNORECASE,
)
NEXT_SECTION_RE = re.compile(r"\b\d+\s*\.(?!\s*\d)\s+[A-Z]", re.IGNORECASE)
NEXT_SECTION_NODOT_RE = re.compile(r"\b\d+\s+(?!\s*\d)\s+[A-Z]", re.IGNORECASE)


def load_json(path):
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_whitespace(text):
    return re.sub(r"\s+", " ", text).strip()


def clean_ordering_item(text):
    if not text:
        return ""
    cleaned = re.sub(r"(\w)-\s+(\w)", r"\1\2", text)
    cleaned = re.sub(r"\bship-ment\b", "shipment", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bre-quirements\b", "requirements", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\brequire-ments\b", "requirements", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+\d+$", "", cleaned)
    return normalize_whitespace(cleaned)


def parse_ordering_items(text, section_number):
    if not text or not section_number:
        return []
    normalized = normalize_whitespace(text)
    item_pattern = re.compile(
        r"\b"
        + re.escape(section_number)
        + r"\s*\.\s*\d+(?:\s*\.\s*\d+)*\b",
        re.IGNORECASE,
    )
    matches = list(item_pattern.finditer(normalized))
    items = []
    for idx, match in enumerate(matches):
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(normalized)
        if end <= start:
            continue
        item_text = normalized[start:end].strip()
        if not item_text:
            continue
        item_text = clean_ordering_item(item_text)
        if not item_text:
            continue
        if item_text.lower().startswith("information items to be considered"):
            continue
        items.append(item_text)
    return items


def extract_ordering_items(text):
    if not text:
        return []
    normalized = text.replace("\r\n", "\n")
    items = []
    for match in ORDERING_HEADER_RE.finditer(normalized):
        section = match.group("section")
        if not section:
            continue
        start = match.end()
        tail = normalized[start:]
        next_section = NEXT_SECTION_RE.search(tail)
        next_section_nodot = NEXT_SECTION_NODOT_RE.search(tail)
        if next_section and next_section_nodot:
            end = start + min(next_section.start(), next_section_nodot.start())
        elif next_section:
            end = start + next_section.start()
        elif next_section_nodot:
            end = start + next_section_nodot.start()
        else:
            end = len(normalized)
        if end <= start:
            continue
        body = normalized[start:end]
        items.extend(parse_ordering_items(body, section))
    return items


def load_spec_text(spec):
    spec_path = SPEC_CORPUS_DIR / spec / "spec.txt"
    if not spec_path.exists():
        return None
    text = spec_path.read_text(encoding="utf-8", errors="ignore")
    return re.sub(r"^=== Page .*? ===$", "", text, flags=re.MULTILINE).strip()


def update_ordering_items_from_spec_corpus():
    ordering_items = load_json(ORDERING_ITEMS_JSON) or {}
    index = load_json(SPEC_INDEX_PATH) or []

    updated_specs = []
    for entry in index:
        spec = entry.get("spec")
        if not spec:
            continue
        existing = ordering_items.get(spec, [])
        if existing:
            continue
        text = load_spec_text(spec)
        if not text:
            continue
        items = extract_ordering_items(text)
        if not items:
            continue
        ordering_items[spec] = items
        updated_specs.append({"spec": spec, "count": len(items)})

    ORDERING_ITEMS_JSON.write_text(
        json.dumps(ordering_items, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    with ORDERING_ITEMS_CSV.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["SpecDesignation", "OrderingItem"])
        for spec in sorted(ordering_items.keys()):
            for item in ordering_items[spec]:
                writer.writerow([spec, item])

    return ordering_items, updated_specs


def expand_required_fields(ordering_items):
    required_map = load_json(ORDERING_REQUIRED_JSON) or {}
    updated_specs = []

    grade_re = re.compile(r"\b(grade|class|type|uns)\b", re.IGNORECASE)
    quantity_re = re.compile(
        r"\b(quantity|quantities|number of pieces|number of lengths|pieces|weight|lbs?|pounds|tons?|kg|kilograms)\b",
        re.IGNORECASE,
    )
    length_re = re.compile(
        r"\b(length|lengths|random length|random lengths|cut length|specific length)\b",
        re.IGNORECASE,
    )
    size_re = re.compile(
        r"\b(size|o\.d\.|od|outside diameter|inside diameter|thickness|wall|diameter|nps)\b",
        re.IGNORECASE,
    )
    end_finish_re = re.compile(
        r"\b(end finish|ends|plain end|bevel(?:ed|led)|threaded|grooved)\b",
        re.IGNORECASE,
    )
    manufacture_re = re.compile(
        r"\b(seamless|welded|manufacture|hot-finished|cold-drawn|electric[- ]resistance|electric[- ]fusion)\b",
        re.IGNORECASE,
    )
    test_report_re = re.compile(
        r"\b(test report|certificat|certification|heat analysis|cmtr|mtr)\b",
        re.IGNORECASE,
    )
    heat_treat_re = re.compile(
        r"\b(heat treatment|heat treated|normalize|normalized|quenched|tempered|solution anneal|annealed|stress relieve)\b",
        re.IGNORECASE,
    )
    impact_re = re.compile(
        r"\b(impact test|charpy|notch toughness|toughness|cvn)\b",
        re.IGNORECASE,
    )
    nde_re = re.compile(
        r"\b(ultrasonic|radiographic|magnetic particle|liquid penetrant|eddy current|nondestructive)\b",
        re.IGNORECASE,
    )
    supplementary_re = re.compile(
        r"\b(supplementary requirement\(s\)?|supplementary requirements?)\b",
        re.IGNORECASE,
    )
    chem_re = re.compile(
        r"\b(chemical analysis|heat analysis|product analysis|chemistry)\b",
        re.IGNORECASE,
    )

    for spec, items in ordering_items.items():
        existing = required_map.get(spec, [])
        required = list(existing)
        required_set = {item.lower() for item in required}

        def ensure(label):
            if label.lower() not in required_set:
                required.append(label)
                required_set.add(label.lower())

        for item in items or []:
            if quantity_re.search(item):
                ensure("Quantity")
            if length_re.search(item):
                ensure("Length (specific or random)")
            if size_re.search(item):
                ensure("Size / OD / Thickness")
            if end_finish_re.search(item):
                ensure("End Finish")
            if grade_re.search(item):
                ensure("Grade / Class / Type")
            if manufacture_re.search(item):
                ensure("Manufacture (seamless/welded)")
            if test_report_re.search(item):
                ensure("Test Report")
            if heat_treat_re.search(item):
                ensure("Heat Treatment")
            if impact_re.search(item):
                ensure("Impact Test / Toughness")
            if nde_re.search(item):
                ensure("NDE / Examination")
            if supplementary_re.search(item):
                ensure("Supplementary Requirements")
            if chem_re.search(item):
                ensure("Chemical Analysis")

        if required != existing:
            required_map[spec] = required
            updated_specs.append(spec)

    ORDERING_REQUIRED_JSON.write_text(
        json.dumps(required_map, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    with ORDERING_REQUIRED_CSV.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["SpecDesignation", "RequiredField"])
        for spec in sorted(required_map.keys()):
            for field in required_map[spec]:
                writer.writerow([spec, field])

    return required_map, updated_specs


def write_missing_ordering_report(ordering_items):
    materials_data = load_json(MATERIALS_JSON)
    if not materials_data:
        return None

    missing = []
    for material in materials_data.get("Materials", []):
        spec = material.get("SpecDesignation")
        if not spec:
            continue
        items = ordering_items.get(spec, [])
        if not items:
            missing.append({"spec": spec, "orderingItemCount": 0})

    report = {
        "createdUtc": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "totalSpecs": len(materials_data.get("Materials", [])),
            "missingOrderingInfo": len(missing),
        },
        "missingSpecs": sorted(missing, key=lambda m: m["spec"]),
    }

    missing_json = DATA_DIR / "ordering-missing-by-spec.json"
    missing_csv = DATA_DIR / "ordering-missing-by-spec.csv"
    missing_json.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    with missing_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["SpecDesignation", "OrderingItemCount"])
        for entry in report["missingSpecs"]:
            writer.writerow([entry["spec"], entry["orderingItemCount"]])

    return report


def update_materials(ordering_items):
    materials_data = load_json(MATERIALS_JSON)
    if not materials_data:
        return None

    for material in materials_data.get("Materials", []):
        spec = material.get("SpecDesignation")
        if not spec or spec not in ordering_items:
            continue
        material["OrderingInfoItems"] = ordering_items[spec]

    MATERIALS_JSON.write_text(
        json.dumps(materials_data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    materials = materials_data.get("Materials", [])
    write_material_subset(materials, MATERIALS_FERROUS_JSON, category=1)
    write_material_subset(materials, MATERIALS_NONFERROUS_JSON, category=2)
    write_material_subset(materials, MATERIALS_ELECTRODE_JSON, category=3)

    return materials_data


def write_material_subset(materials, path, category):
    subset = [m for m in materials if m.get("Category") == category]
    path.write_text(
        json.dumps({"Materials": subset}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def configure_paths(spec_corpus_dir: str | None, data_dir: str | None):
    global DATA_DIR
    global SPEC_CORPUS_DIR
    global SPEC_INDEX_PATH
    global ORDERING_ITEMS_JSON
    global ORDERING_ITEMS_CSV
    global ORDERING_REQUIRED_JSON
    global ORDERING_REQUIRED_CSV
    global MATERIALS_JSON
    global MATERIALS_FERROUS_JSON
    global MATERIALS_NONFERROUS_JSON
    global MATERIALS_ELECTRODE_JSON

    if data_dir:
        DATA_DIR = pathlib.Path(data_dir).resolve()
    if spec_corpus_dir:
        SPEC_CORPUS_DIR = pathlib.Path(spec_corpus_dir).resolve()
    SPEC_INDEX_PATH = SPEC_CORPUS_DIR / "spec_corpus_index.json"

    ORDERING_ITEMS_JSON = DATA_DIR / "ordering-items-by-spec.json"
    ORDERING_ITEMS_CSV = DATA_DIR / "ordering-items-by-spec.csv"
    ORDERING_REQUIRED_JSON = DATA_DIR / "ordering-required-fields.json"
    ORDERING_REQUIRED_CSV = DATA_DIR / "ordering-required-fields.csv"

    MATERIALS_JSON = DATA_DIR / "materials.json"
    MATERIALS_FERROUS_JSON = DATA_DIR / "materials-ferrous.json"
    MATERIALS_NONFERROUS_JSON = DATA_DIR / "materials-nonferrous.json"
    MATERIALS_ELECTRODE_JSON = DATA_DIR / "materials-electrode.json"


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Update ordering info datasets from a spec_corpus directory."
    )
    parser.add_argument(
        "--spec-corpus",
        help="Optional spec_corpus root (defaults to sectionII_partA_data_digitized/spec_corpus).",
    )
    parser.add_argument("--data-dir", help="Optional data output directory (defaults to data/).")
    args = parser.parse_args()

    configure_paths(args.spec_corpus, args.data_dir)

    ordering_items, updated_specs = update_ordering_items_from_spec_corpus()
    required_map, required_updated = expand_required_fields(ordering_items)
    materials_data = update_materials(ordering_items)
    missing_report = write_missing_ordering_report(ordering_items)

    summary = {
        "updatedOrderingSpecs": updated_specs,
        "requiredFieldsUpdatedCount": len(required_updated),
        "materialsUpdated": bool(materials_data),
        "missingOrderingInfoCount": missing_report["summary"]["missingOrderingInfo"] if missing_report else 0,
        "ranAtUtc": datetime.now(timezone.utc).isoformat(),
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
