import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import fitz


DEFAULT_SOURCE = Path("inputs/originals/2025 ADOBE OCR SECT II PART A BEGINNING TO SA-450.pdf")
DEFAULT_OUTPUT = Path("data/private/sa106_mtr_pilot")
SPEC = "SA-106"
SPEC_LONG = "SA-106/SA-106M"
GRADES = ["A", "B", "C"]


CHEMICAL_ROWS = [
    ("carbon", "Carbon"),
    ("manganese", "Manganese"),
    ("phosphorus", "Phosphorus"),
    ("sulfur", "Sulfur"),
    ("silicon", "Silicon"),
    ("chromium", "Chromium"),
    ("copper", "Copper"),
    ("molybdenum", "Molybdenum"),
    ("nickel", "Nickel"),
    ("vanadium", "Vanadium"),
]


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\xad", "")).strip()


def normalize_number_token(token: str, row_key: str | None = None) -> dict:
    raw = token.strip()
    cleaned = raw.replace(",", "").replace(" ", "").replace("'", "")
    footnote = None
    marker_match = re.search(r"([A-Za-z])$", cleaned)
    if marker_match:
        footnote = marker_match.group(1)
        cleaned = cleaned[:-1]

    # OCR commonly reads superscript footnote B as a trailing 8 on carbon values.
    if row_key == "carbon" and re.fullmatch(r"0\.\d{3}", cleaned) and cleaned.endswith("8"):
        footnote = footnote or "B"
        cleaned = cleaned[:-1]

    if "-" in cleaned:
        lo, hi = cleaned.split("-", 1)
        return {"raw": raw, "min": float(lo), "max": float(hi), "footnote": footnote}
    if re.fullmatch(r"\d+(?:\.\d+)?", cleaned):
        return {"raw": raw, "value": float(cleaned), "footnote": footnote}
    return {"raw": raw, "text": cleaned, "footnote": footnote}


def extract_lines(page) -> list[dict]:
    lines = []
    data = page.get_text("dict")
    for block in data.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            text = clean_text("".join(span.get("text", "") for span in spans))
            if text:
                lines.append({"text": text, "bbox": list(line.get("bbox", []))})
    return lines


def extract_words(page) -> list[dict]:
    return [
        {
            "text": word[4],
            "bbox": [round(word[0], 3), round(word[1], 3), round(word[2], 3), round(word[3], 3)],
            "block": word[5],
            "line": word[6],
            "word": word[7],
        }
        for word in page.get_text("words")
    ]


def find_sa106_range(doc) -> dict:
    sa_pages = []
    for index in range(doc.page_count):
        text = doc.load_page(index).get_text("text") or ""
        if SPEC_LONG in text:
            sa_pages.append(index + 1)

    body_pages = [page for page in sa_pages if page >= 200]
    contiguous = []
    previous = None
    for page in body_pages:
        if previous is None or page == previous + 1:
            contiguous.append(page)
        elif contiguous:
            break
        previous = page

    next_nonblank = None
    for page in range(contiguous[-1] + 1, min(doc.page_count, contiguous[-1] + 10) + 1):
        text = clean_text(doc.load_page(page - 1).get_text("text") or "")
        if text and "INTENTIONALLY LEFT BLANK" not in text.upper():
            next_nonblank = {"page": page, "text_preview": text[:200]}
            break

    return {
        "detected_pages": contiguous,
        "all_hits": sa_pages,
        "next_nonblank_after_range": next_nonblank,
    }


def parse_identity(pages: dict[int, dict]) -> dict:
    cover_text = "\n".join(line["text"] for line in pages[221]["lines"])
    body_text = "\n".join(line["text"] for line in pages[222]["lines"])
    all_text = cover_text + "\n" + body_text
    astm_match = re.search(r"Identical with ASTM Specification ([A-Z0-9/.-]+)", all_text)
    title_match = re.search(r"Specification for\s+(.+?)\s+1\. Scope", body_text, re.I | re.S)
    return {
        "asme_spec": SPEC,
        "designation": SPEC_LONG,
        "edition": "2025",
        "part": "II.A",
        "title": clean_text(title_match.group(1)) if title_match else "Seamless Carbon Steel Pipe for High-Temperature Service",
        "astm_identical": astm_match.group(1) if astm_match else None,
        "source_locators": [
            {"page": 221, "kind": "cover"},
            {"page": 222, "kind": "scope"},
        ],
    }


def collect_numbered_items(lines: list[dict], start_pattern: str, stop_pattern: str) -> list[dict]:
    items = []
    current = None
    start_re = re.compile(start_pattern)
    item_re = re.compile(r"^(?P<id>\d+(?:\.\d+)+)\s+(?P<text>.*)")
    stop_re = re.compile(stop_pattern)
    active = False
    for line in lines:
        text = line["text"]
        if start_re.match(text):
            active = True
            current = {"id": text.split()[0], "text": text.partition(" ")[2], "bbox": line["bbox"]}
            items.append(current)
            continue
        if not active:
            continue
        if stop_re.match(text):
            break
        match = item_re.match(text)
        if match:
            current = {"id": match.group("id"), "text": match.group("text"), "bbox": line["bbox"]}
            items.append(current)
        elif current:
            joiner = "" if current["text"].endswith("-") else " "
            current["text"] = clean_text(current["text"].rstrip("-") + joiner + text)
    return items


def parse_ordering(lines: list[dict]) -> list[dict]:
    items = collect_numbered_items(lines, r"^3\.1\s+", r"^4\.\s+")
    return [
        {
            "id": item["id"],
            "prompt": item["text"],
            "source_locator": {"page": 223, "section": item["id"], "bbox": item["bbox"]},
        }
        for item in items
        if item["id"] != "3.1"
    ]


def parse_chemical(lines: list[dict]) -> dict:
    text_to_index = {line["text"]: idx for idx, line in enumerate(lines)}
    table_start = next(i for i, line in enumerate(lines) if line["text"].startswith("TABLE 1 Chemical"))
    table_lines = lines[table_start:]
    requirements = {}
    for key, label in CHEMICAL_ROWS:
        idx = next(i for i, line in enumerate(table_lines) if line["text"].startswith(label))
        label_line = table_lines[idx]
        values = []
        cursor = idx + 1
        while cursor < len(table_lines) and len(values) < 3:
            token = table_lines[cursor]["text"]
            if re.search(r"\d", token):
                values.append(normalize_number_token(token, key))
            cursor += 1
        qualifier = "range"
        if "max" in label_line["text"].lower():
            qualifier = "max"
        elif "min" in label_line["text"].lower():
            qualifier = "min"
        requirements[key] = {
            "element": label,
            "qualifier": qualifier,
            "by_grade": {grade: values[pos] for pos, grade in enumerate(GRADES)},
            "source_locator": {"page": 223, "table": "1", "row_label": label_line["text"], "bbox": label_line["bbox"]},
        }
    footnote_lines = []
    for line in lines[text_to_index.get("A For each reduction of 0.01 % below the specified carbon maximum, an increase", 0):]:
        if line["text"].startswith("4.3 "):
            break
        if line["text"].startswith(("A ", "8 ", "0 ")) or footnote_lines:
            footnote_lines.append(line["text"])
    return {
        "table": "1",
        "title": "Chemical Requirements",
        "grades": GRADES,
        "requirements": requirements,
        "notes": {
            "carbon_manganese_adjustment": "Captured from Table 1 footnotes; applies by grade and must be evaluated when carbon is below maximum.",
            "residual_elements_combined": "Chromium, copper, molybdenum, nickel, and vanadium have a combined maximum.",
            "raw_ocr_footnote_lines": footnote_lines,
        },
        "source_locator": {"page": 223, "table": "1", "line": "TABLE 1 Chemical Requirements"},
    }


def next_numeric_lines(lines: list[dict], start_index: int, count: int) -> list[dict]:
    found = []
    cursor = start_index
    while cursor < len(lines) and len(found) < count:
        text = lines[cursor]["text"]
        if re.fullmatch(r"\d+(?:\.\d+)?(?:\s+\d{3})?(?:\s+\[\d+[\]\)])?", text):
            found.append(lines[cursor])
        cursor += 1
    return found


def parse_strength_token(token: str) -> dict:
    match = re.search(r"(?P<psi>\d[\d\s]*)\s+\[(?P<mpa>\d+)[\]\)]", token)
    if not match:
        return {"raw": token}
    return {
        "raw": token,
        "psi": int(match.group("psi").replace(" ", "")),
        "mpa": int(match.group("mpa")),
    }


def parse_mechanical(lines: list[dict]) -> dict:
    table_start = next(i for i, line in enumerate(lines) if line["text"].startswith("TABLE 2 Tensile"))
    tensile = {}
    for grade in GRADES:
        idx = next(i for i, line in enumerate(lines) if line["text"] == f"Grade {grade}")
        nums = next_numeric_lines(lines, idx + 1, 2)
        tensile[grade] = {
            "tensile_strength_min": parse_strength_token(nums[0]["text"]),
            "yield_strength_min": parse_strength_token(nums[1]["text"]),
            "source_locator": {"page": 224, "table": "2", "grade": grade, "bbox": lines[idx]["bbox"]},
        }
    elongation_start = next(i for i, line in enumerate(lines) if line["text"].startswith("Elongation in"))
    numbers = []
    for line in lines[elongation_start + 1:]:
        if line["text"].startswith("For longitudinal strip tests"):
            break
        if re.fullmatch(r"\d+(?:\.\d+)?", line["text"]):
            numbers.append(float(line["text"]))
    basic = numbers[:6]
    round_specimen = numbers[6:12]
    deduction_start = next(i for i, line in enumerate(lines) if line["text"].startswith("For transverse strip tests"))
    deductions = []
    for line in lines[deduction_start + 1:]:
        if line["text"].startswith("decrease in"):
            break
        if re.fullmatch(r"\d+(?:\.\d+)?", line["text"]):
            deductions.append(float(line["text"]))
    return {
        "table": "2",
        "title": "Tensile Requirements",
        "strength": tensile,
        "elongation": {
            "basic_minimum_percent_by_grade_orientation": {
                "A": {"longitudinal": basic[0], "transverse": basic[1]},
                "B": {"longitudinal": basic[2], "transverse": basic[3]},
                "C": {"longitudinal": basic[4], "transverse": basic[5]},
            },
            "round_2_in_specimen_percent_by_grade_orientation": {
                "A": {"longitudinal": round_specimen[0], "transverse": round_specimen[1]},
                "B": {"longitudinal": round_specimen[2], "transverse": round_specimen[3]},
                "C": {"longitudinal": round_specimen[4], "transverse": round_specimen[5]},
            },
            "thin_wall_transverse_strip_deduction_percent": {
                "A": deductions[0],
                "B": deductions[1],
                "C": deductions[2],
            },
            "auto_check_status": "conditional_needs_specimen_orientation_wall_thickness_and_area",
        },
        "source_locator": {"page": 224, "table": "2", "line": "TABLE 2 Tensile Requirements", "bbox": lines[table_start]["bbox"]},
    }


def parse_sections(pages: dict[int, dict]) -> dict:
    section_map = {}
    section_re = re.compile(r"^(?P<section>\d{1,2}(?:\.\d+)?)\s+(?P<title>[A-Z][A-Za-z, \-]+)$")
    supplement_re = re.compile(r"^(?P<section>S\d+)\.?\s+(?P<title>.+)$")
    for page_num, page in pages.items():
        for line in page["lines"]:
            match = section_re.match(line["text"]) or supplement_re.match(line["text"])
            if match:
                section_map[match.group("section")] = {
                    "title": clean_text(match.group("title")),
                    "source_locator": {"page": page_num, "bbox": line["bbox"]},
                }
    return section_map


def load_po_comparison() -> dict:
    current = {"spec_definition_ordering_count": None, "material_index": None}
    data_path = Path("data/asme_po_data_imperial_v4.jsonl")
    if data_path.exists():
        for line in data_path.read_text(encoding="utf-8-sig", errors="ignore").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("record_type") == "spec_definition" and row.get("asme_spec") == SPEC:
                current["spec_definition_ordering_count"] = len(row.get("ordering_fields") or [])
                current["spec_definition_title"] = row.get("title")
            if row.get("record_type") == "material_index" and row.get("spec_asme") == SPEC:
                current["material_index"] = row

    old = {"materials_ordering_count": None}
    old_path = Path("old_data/data/materials-ferrous.json")
    if old_path.exists():
        materials = json.loads(old_path.read_text(encoding="utf-8", errors="ignore"))
        for row in materials.get("Materials", []):
            if row.get("SpecDesignation") == SPEC:
                old["materials_ordering_count"] = len(row.get("OrderingInfoItems") or [])
                old["astm_note"] = row.get("AstmNote")
                break
    return {"current_data": current, "old_data": old}


def build_validation(range_info: dict, metadata: dict, comparison: dict) -> dict:
    checks = []

    def add(check_id: str, ok: bool, detail: str):
        checks.append({"id": check_id, "ok": ok, "detail": detail})

    pages = range_info["detected_pages"]
    add("sa106_pages_detected", pages == list(range(221, 230)), f"detected={pages}")
    next_text = (range_info.get("next_nonblank_after_range") or {}).get("text_preview", "")
    add("next_spec_boundary", "SA-134/SA-134M" in next_text, f"next_nonblank={range_info.get('next_nonblank_after_range')}")
    add("ordering_items", len(metadata["ordering_information"]) == 14, f"count={len(metadata['ordering_information'])}")
    add("chemical_rows", len(metadata["chemical_requirements"]["requirements"]) == 10, "expected 10 chemical rows")
    add(
        "chemical_grade_values",
        all(len(row["by_grade"]) == 3 for row in metadata["chemical_requirements"]["requirements"].values()),
        "all chemical rows have Grade A/B/C values",
    )
    add("mechanical_grades", set(metadata["mechanical_requirements"]["strength"].keys()) == set(GRADES), "strength rows cover A/B/C")
    strength_rows = metadata["mechanical_requirements"]["strength"].values()
    add(
        "mechanical_strength_values",
        all(
            "psi" in row["tensile_strength_min"]
            and "psi" in row["yield_strength_min"]
            and row["tensile_strength_min"]["psi"] > row["yield_strength_min"]["psi"]
            for row in strength_rows
        ),
        "all tensile/yield minimums parsed as strength values",
    )
    add(
        "current_po_sa106_empty",
        comparison["current_data"].get("spec_definition_ordering_count") == 0,
        "current tracked PO spec_definition still has empty ordering_fields",
    )
    add(
        "old_po_has_ordering",
        (comparison["old_data"].get("materials_ordering_count") or 0) >= 14,
        f"old_data ordering count={comparison['old_data'].get('materials_ordering_count')}",
    )
    return {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "status": "pass" if all(check["ok"] for check in checks) else "needs_review",
        "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a private SA-106 material acceptance pilot from the 2025 Section II Part A OCR PDF.")
    parser.add_argument("--source", default=str(DEFAULT_SOURCE), help="Source OCR PDF.")
    parser.add_argument("--out", default=str(DEFAULT_OUTPUT), help="Ignored/private output folder.")
    args = parser.parse_args()

    source = Path(args.source)
    out = Path(args.out)
    if not source.exists():
        raise FileNotFoundError(source)

    doc = fitz.open(source)
    range_info = find_sa106_range(doc)
    pages = {}
    for page_num in range_info["detected_pages"]:
        page = doc.load_page(page_num - 1)
        pages[page_num] = {
            "page": page_num,
            "text": page.get_text("text") or "",
            "lines": extract_lines(page),
            "words": extract_words(page),
        }

    metadata = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "source": {
            "path": str(source),
            "document": source.name,
            "page_range": range_info["detected_pages"],
            "boundary": range_info["next_nonblank_after_range"],
            "privacy": "licensed_source_private_local_only",
        },
        "identity": parse_identity(pages),
        "ordering_information": parse_ordering(pages[223]["lines"]),
        "chemical_requirements": parse_chemical(pages[223]["lines"]),
        "mechanical_requirements": parse_mechanical(pages[224]["lines"]),
        "section_index": parse_sections(pages),
        "mtr_check_fields": {
            "material_identity": ["specification", "grade", "product_form", "size", "heat_number"],
            "chemical_values": list(parse_chemical(pages[223]["lines"])["requirements"].keys()),
            "mechanical_values": ["tensile_strength", "yield_strength", "elongation", "hydrostatic_or_nde_status"],
            "conditional_values": ["manufacture_hot_finished_or_cold_drawn", "heat_treatment", "supplementary_requirements", "carbon_equivalent_if_specified"],
        },
        "auto_acceptance_policy": {
            "status": "human_review_required_before_final_acceptance",
            "machine_use": "agent_assisted_mtr_screening_and_highlight_generation",
            "hard_stops": [
                "ambiguous_or_missing_grade",
                "unknown_code_edition",
                "missing_chemistry_or_mechanical_value_needed_for_grade",
                "elongation_basis_missing_when_elongation_is_close_to_limit",
                "supplementary_requirement_claimed_but_not_parsed",
            ],
        },
    }
    comparison = load_po_comparison()
    validation = build_validation(range_info, metadata, comparison)

    (out / "source").mkdir(parents=True, exist_ok=True)
    (out / "metadata").mkdir(parents=True, exist_ok=True)
    (out / "validation").mkdir(parents=True, exist_ok=True)

    source_pages_public = {
        "source": metadata["source"],
        "pages": [
            {
                "page": page_num,
                "text": page_data["text"],
                "lines": page_data["lines"],
                "words": page_data["words"],
            }
            for page_num, page_data in pages.items()
        ],
    }
    (out / "source" / "sa106_source_pages.json").write_text(json.dumps(source_pages_public, indent=2), encoding="utf-8")
    (out / "source" / "sa106_source_pages.txt").write_text(
        "\n\n".join(f"=== Page {page_num} ===\n{pages[page_num]['text'].strip()}" for page_num in pages),
        encoding="utf-8",
    )
    (out / "metadata" / "sa106_acceptance_metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    (out / "validation" / "po_helper_comparison.json").write_text(json.dumps(comparison, indent=2), encoding="utf-8")
    (out / "validation" / "sa106_validation_report.json").write_text(json.dumps(validation, indent=2), encoding="utf-8")

    print(json.dumps({
        "output": str(out),
        "status": validation["status"],
        "pages": range_info["detected_pages"],
        "checks": validation["checks"],
    }, indent=2))
    return 0 if validation["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
