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
    r"(?s)(?P<section>\d+)\s*\.\s*Ordering\s*Information", re.IGNORECASE
)
NEXT_SECTION_RE = re.compile(r"\b\d+\s*\.(?!\s*\d)\s+[A-Z]", re.IGNORECASE)


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
        + r"\s*\.\s*\d+(?:\s*\.\s*\d+)?\b",
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
        end = start + next_section.start() if next_section else len(normalized)
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
    manufacture_re = re.compile(
        r"\b(seamless|welded|manufacture|hot-finished|cold-drawn|electric[- ]resistance|electric[- ]fusion)\b",
        re.IGNORECASE,
    )
    test_report_re = re.compile(
        r"\b(test report|certificat|certification|heat analysis|cmtr|mtr)\b",
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
            if grade_re.search(item):
                ensure("Grade / Class / Type")
            if manufacture_re.search(item):
                ensure("Manufacture (seamless/welded)")
            if test_report_re.search(item):
                ensure("Test Report")

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


def main():
    ordering_items, updated_specs = update_ordering_items_from_spec_corpus()
    required_map, required_updated = expand_required_fields(ordering_items)
    materials_data = update_materials(ordering_items)

    summary = {
        "updatedOrderingSpecs": updated_specs,
        "requiredFieldsUpdatedCount": len(required_updated),
        "materialsUpdated": bool(materials_data),
        "ranAtUtc": datetime.now(timezone.utc).isoformat(),
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
