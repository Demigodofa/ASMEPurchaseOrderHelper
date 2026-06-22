import argparse
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path

import fitz


DEFAULT_METADATA = Path("data/private/sa106_mtr_pilot/metadata/sa106_acceptance_metadata.json")
DEFAULT_OUTPUT_ROOT = Path("data/private/sa106_mtr_pilot/mtr_runs")

ELEMENTS = {
    "carbon": {"symbol": "C", "aliases": ["C", "CARBON"]},
    "manganese": {"symbol": "Mn", "aliases": ["MN", "MANGANESE"]},
    "phosphorus": {"symbol": "P", "aliases": ["P", "PHOSPHORUS", "PHOS"]},
    "sulfur": {"symbol": "S", "aliases": ["S", "SULFUR", "SULPHUR"]},
    "silicon": {"symbol": "Si", "aliases": ["SI", "SILICON"]},
    "chromium": {"symbol": "Cr", "aliases": ["CR", "CHROMIUM"]},
    "copper": {"symbol": "Cu", "aliases": ["CU", "COPPER"]},
    "molybdenum": {"symbol": "Mo", "aliases": ["MO", "MOLYBDENUM"]},
    "nickel": {"symbol": "Ni", "aliases": ["NI", "NICKEL"]},
    "vanadium": {"symbol": "V", "aliases": ["V", "VANADIUM"]},
}


def clean_token(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9.%<>/-]+", "", text).upper()


def parse_decimal(text: str) -> float | None:
    cleaned = text.replace(",", ".").replace("%", "").strip()
    cleaned = re.sub(r"^[<>]=?", "", cleaned)
    match = re.search(r"\d+(?:\.\d+)?", cleaned)
    if not match:
        return None
    value = float(match.group(0))
    if value > 1.0 and value <= 100.0 and "." not in match.group(0):
        return value
    return value


def parse_strength_number(text: str) -> dict | None:
    nums = re.findall(r"\d+(?:,\d{3})*(?:\.\d+)?", text)
    if not nums:
        return None
    value = float(nums[0].replace(",", ""))
    upper = text.upper()
    if "MPA" in upper:
        return {"raw": text, "mpa": value, "psi": value * 145.0377}
    if "KSI" in upper or value < 1000:
        return {"raw": text, "ksi": value, "psi": value * 1000}
    return {"raw": text, "psi": value}


def word_bbox(word: dict) -> list[float]:
    return word["bbox"]


def union_bbox(boxes: list[list[float]]) -> list[float]:
    return [
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    ]


def open_input_as_pdf(path: Path) -> fitz.Document:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return fitz.open(path)
    image_doc = fitz.open(path)
    pdf_bytes = image_doc.convert_to_pdf()
    return fitz.open("pdf", pdf_bytes)


def extract_words(page, use_ocr: bool) -> tuple[list[dict], str]:
    method = "native"
    words_raw = page.get_text("words")
    text = page.get_text("text") or ""
    if use_ocr or len(text.strip()) < 50 or len(words_raw) < 10:
        try:
            textpage = page.get_textpage_ocr(flags=0, language="eng", dpi=300, full=True)
            words_raw = page.get_text("words", textpage=textpage)
            text = page.get_text("text", textpage=textpage) or ""
            method = "ocr"
        except Exception as exc:  # OCR availability varies by machine.
            method = f"native_ocr_failed:{type(exc).__name__}:{exc}"
    words = [
        {
            "text": item[4],
            "bbox": [float(item[0]), float(item[1]), float(item[2]), float(item[3])],
            "block": int(item[5]),
            "line": int(item[6]),
            "word": int(item[7]),
        }
        for item in words_raw
    ]
    return words, method


def build_lines(words: list[dict], page_index: int) -> list[dict]:
    groups = {}
    for word in words:
        groups.setdefault((word["block"], word["line"]), []).append(word)
    lines = []
    for (_, _), line_words in groups.items():
        ordered = sorted(line_words, key=lambda item: (item["bbox"][1], item["bbox"][0]))
        boxes = [word_bbox(word) for word in ordered]
        lines.append(
            {
                "page_index": page_index,
                "text": " ".join(word["text"] for word in ordered),
                "words": ordered,
                "bbox": union_bbox(boxes),
            }
        )
    return sorted(lines, key=lambda item: (item["page_index"], item["bbox"][1], item["bbox"][0]))


def element_from_token(token: str) -> str | None:
    cleaned = clean_token(token)
    for key, meta in ELEMENTS.items():
        if cleaned in meta["aliases"]:
            return key
    return None


def extract_identity(lines: list[dict]) -> dict:
    text = "\n".join(line["text"] for line in lines)
    upper = text.upper()
    spec = None
    if re.search(r"\bS?A\s*[-/]?\s*106(?:M)?\b", upper) or "A106" in upper:
        spec = "SA-106"
    grade = None
    grade_patterns = [
        r"\bGR(?:ADE)?\.?\s*([ABC])\b",
        r"\bSA\s*[-/]?\s*106(?:/SA-106M)?\s*(?:GR(?:ADE)?\.?)?\s*([ABC])\b",
        r"\bA106(?:/A106M)?\s*(?:GR(?:ADE)?\.?)?\s*([ABC])\b",
    ]
    for pattern in grade_patterns:
        match = re.search(pattern, upper)
        if match:
            grade = match.group(1)
            break
    heat = None
    heat_match = re.search(r"\bHEAT(?:\s*(?:NO|NUMBER|#))?\s*[:#]?\s*([A-Z0-9-]{3,})", upper)
    if heat_match:
        heat = heat_match.group(1)
    return {"specification": spec, "grade": grade, "heat_number": heat}


def find_numeric_line_after(lines: list[dict], start_idx: int, limit: int = 4) -> dict | None:
    for line in lines[start_idx + 1 : start_idx + 1 + limit]:
        nums = [word for word in line["words"] if parse_decimal(word["text"]) is not None]
        if len(nums) >= 2:
            return line
    return None


def extract_chemistry(lines: list[dict]) -> dict:
    findings = {}

    # Pattern 1: a header line with many element symbols and a following numeric row.
    for idx, line in enumerate(lines):
        headers = []
        for word in line["words"]:
            element = element_from_token(word["text"])
            if element and element not in [item["element"] for item in headers]:
                headers.append({"element": element, "x": (word["bbox"][0] + word["bbox"][2]) / 2, "bbox": word["bbox"]})
        if len(headers) < 4:
            continue
        value_line = find_numeric_line_after(lines, idx)
        if not value_line:
            continue
        numeric_words = [word for word in value_line["words"] if parse_decimal(word["text"]) is not None]
        if len(numeric_words) < min(4, len(headers)):
            continue
        used = set()
        for header in headers:
            best = None
            best_dist = math.inf
            for pos, word in enumerate(numeric_words):
                if pos in used:
                    continue
                center = (word["bbox"][0] + word["bbox"][2]) / 2
                dist = abs(center - header["x"])
                if dist < best_dist:
                    best = (pos, word)
                    best_dist = dist
            if best:
                used.add(best[0])
                value = parse_decimal(best[1]["text"])
                if value is not None:
                    findings.setdefault(
                        header["element"],
                        {
                            "value": value,
                            "raw": best[1]["text"],
                            "page_index": value_line["page_index"],
                            "bbox": best[1]["bbox"],
                            "method": "header_value_row",
                        },
                    )

    # Pattern 2: direct pairs like "C 0.21" or "Carbon: 0.21".
    for line in lines:
        words = line["words"]
        for pos, word in enumerate(words[:-1]):
            element = element_from_token(word["text"])
            if not element or element in findings:
                continue
            value = parse_decimal(words[pos + 1]["text"])
            if value is None:
                continue
            findings[element] = {
                "value": value,
                "raw": words[pos + 1]["text"],
                "page_index": line["page_index"],
                "bbox": words[pos + 1]["bbox"],
                "method": "adjacent_pair",
            }
    return findings


def extract_mechanical(lines: list[dict]) -> dict:
    findings = {}
    patterns = {
        "tensile_strength": [r"TENSILE", r"\bUTS\b", r"\bTS\b"],
        "yield_strength": [r"YIELD", r"\bYS\b"],
        "elongation": [r"ELONG", r"\bEL\b"],
    }
    for line in lines:
        upper = line["text"].upper()
        for key, pats in patterns.items():
            if key in findings or not any(re.search(pattern, upper) for pattern in pats):
                continue
            if key == "elongation":
                nums = re.findall(r"\d+(?:\.\d+)?", line["text"])
                if nums:
                    findings[key] = {
                        "value": float(nums[-1]),
                        "raw": line["text"],
                        "page_index": line["page_index"],
                        "bbox": line["bbox"],
                        "method": "line_keyword",
                    }
            else:
                strength = parse_strength_number(line["text"])
                if strength:
                    findings[key] = {
                        **strength,
                        "page_index": line["page_index"],
                        "bbox": line["bbox"],
                        "method": "line_keyword",
                    }
    return findings


def compare_requirement(requirement: dict, value: float) -> dict:
    qualifier = requirement["qualifier"]
    grade_req = requirement["grade_requirement"]
    if qualifier == "range":
        ok = grade_req["min"] <= value <= grade_req["max"]
        return {"status": "pass" if ok else "fail", "rule": "range", "min": grade_req["min"], "max": grade_req["max"]}
    limit = grade_req.get("value")
    if qualifier == "max":
        ok = value <= limit
        return {"status": "pass" if ok else "fail", "rule": "max", "limit": limit}
    if qualifier == "min":
        ok = value >= limit
        return {"status": "pass" if ok else "fail", "rule": "min", "limit": limit}
    return {"status": "needs_review", "rule": qualifier}


def compare_chemistry(metadata: dict, identity: dict, chemistry: dict) -> dict:
    grade = identity.get("grade")
    if grade not in {"A", "B", "C"}:
        return {"status": "needs_review", "reason": "missing_or_unsupported_grade", "items": []}
    requirements = metadata["chemical_requirements"]["requirements"]
    items = []
    for element, requirement in requirements.items():
        extracted = chemistry.get(element)
        grade_requirement = requirement["by_grade"][grade]
        item = {
            "field": element,
            "requirement": {"qualifier": requirement["qualifier"], "grade_requirement": grade_requirement},
            "extracted": extracted,
        }
        if not extracted:
            item["status"] = "missing"
        else:
            item.update(compare_requirement(item["requirement"], extracted["value"]))
        items.append(item)

    residual_keys = ["chromium", "copper", "molybdenum", "nickel", "vanadium"]
    if all(key in chemistry for key in residual_keys):
        combined = sum(chemistry[key]["value"] for key in residual_keys)
        raw_notes = " ".join(metadata["chemical_requirements"]["notes"].get("raw_ocr_footnote_lines", []))
        note_match = re.search(r"not exceed\s+(\d+(?:\.\d+)?)\s*%", raw_notes, re.I)
        if note_match:
            limit = float(note_match.group(1))
            items.append(
                {
                    "field": "residual_elements_combined",
                    "extracted": {"value": combined},
                    "rule": "combined_max",
                    "limit": limit,
                    "status": "pass" if combined <= limit else "fail",
                }
            )

    statuses = {item["status"] for item in items}
    status = "fail" if "fail" in statuses else "needs_review" if statuses & {"missing", "needs_review"} else "pass"
    return {"status": status, "items": items}


def compare_mechanical(metadata: dict, identity: dict, mechanical: dict) -> dict:
    grade = identity.get("grade")
    if grade not in {"A", "B", "C"}:
        return {"status": "needs_review", "reason": "missing_or_unsupported_grade", "items": []}
    strength = metadata["mechanical_requirements"]["strength"][grade]
    items = []
    for key, req_key in [("tensile_strength", "tensile_strength_min"), ("yield_strength", "yield_strength_min")]:
        extracted = mechanical.get(key)
        req = strength[req_key]
        item = {"field": key, "requirement": {"rule": "min", "psi": req["psi"]}, "extracted": extracted}
        if not extracted or "psi" not in extracted:
            item["status"] = "missing"
        else:
            item["status"] = "pass" if extracted["psi"] >= req["psi"] else "fail"
        items.append(item)
    if "elongation" in mechanical:
        items.append(
            {
                "field": "elongation",
                "status": "needs_review",
                "extracted": mechanical["elongation"],
                "reason": metadata["mechanical_requirements"]["elongation"]["auto_check_status"],
            }
        )
    else:
        items.append({"field": "elongation", "status": "missing"})
    statuses = {item["status"] for item in items}
    status = "fail" if "fail" in statuses else "needs_review" if statuses & {"missing", "needs_review"} else "pass"
    return {"status": status, "items": items}


def add_highlights(doc, report: dict):
    colors = {"pass": (0.2, 0.8, 0.2), "fail": (1, 0.1, 0.1), "missing": (1, 0.8, 0), "needs_review": (1, 0.8, 0)}
    for group in ["chemistry_check", "mechanical_check"]:
        for item in report[group].get("items", []):
            extracted = item.get("extracted") or {}
            bbox = extracted.get("bbox")
            page_index = extracted.get("page_index")
            if bbox is None or page_index is None:
                continue
            page = doc[page_index]
            annot = page.add_rect_annot(fitz.Rect(bbox))
            annot.set_colors(stroke=colors.get(item["status"], (1, 0.8, 0)))
            annot.set_border(width=1.2)
            annot.set_info(content=f"{item['field']}: {item['status']}")
            annot.update()


def main() -> int:
    parser = argparse.ArgumentParser(description="Check a scanned/text MTR against the private SA-106 pilot metadata.")
    parser.add_argument("--mtr", required=True, help="MTR PDF or image path.")
    parser.add_argument("--metadata", default=str(DEFAULT_METADATA), help="SA-106 acceptance metadata JSON.")
    parser.add_argument("--out-root", default=str(DEFAULT_OUTPUT_ROOT), help="Private output root.")
    parser.add_argument("--force-ocr", action="store_true", help="Force OCR even if a text layer exists.")
    args = parser.parse_args()

    mtr_path = Path(args.mtr)
    metadata_path = Path(args.metadata)
    if not mtr_path.exists():
        raise FileNotFoundError(mtr_path)
    if not metadata_path.exists():
        raise FileNotFoundError(metadata_path)

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    doc = open_input_as_pdf(mtr_path)
    all_lines = []
    page_methods = []
    for page_index, page in enumerate(doc):
        words, method = extract_words(page, args.force_ocr)
        page_methods.append({"page_index": page_index, "method": method, "word_count": len(words)})
        all_lines.extend(build_lines(words, page_index))

    identity = extract_identity(all_lines)
    chemistry = extract_chemistry(all_lines)
    mechanical = extract_mechanical(all_lines)
    report = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "mtr_path": str(mtr_path),
        "metadata_path": str(metadata_path),
        "page_methods": page_methods,
        "identity": identity,
        "chemistry_extraction": chemistry,
        "mechanical_extraction": mechanical,
        "chemistry_check": compare_chemistry(metadata, identity, chemistry),
        "mechanical_check": compare_mechanical(metadata, identity, mechanical),
    }
    statuses = {report["chemistry_check"]["status"], report["mechanical_check"]["status"]}
    report["overall_status"] = "fail" if "fail" in statuses else "needs_review" if "needs_review" in statuses else "pass"

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = Path(args.out_root) / f"{mtr_path.stem}_{stamp}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "mtr_check_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (out / "mtr_extracted_lines.json").write_text(json.dumps({"lines": all_lines}, indent=2), encoding="utf-8")
    add_highlights(doc, report)
    doc.save(out / "highlighted_mtr.pdf")
    print(json.dumps({"output": str(out), "overall_status": report["overall_status"], "identity": identity, "page_methods": page_methods}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
