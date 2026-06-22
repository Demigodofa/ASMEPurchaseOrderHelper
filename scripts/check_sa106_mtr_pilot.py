import argparse
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path

import fitz
import numpy as np
from PIL import Image

try:
    from rapidocr_onnxruntime import RapidOCR
except Exception:  # pragma: no cover - optional local OCR fallback
    RapidOCR = None


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

RAPID_OCR = None


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


def get_rapid_ocr():
    global RAPID_OCR
    if RapidOCR is None:
        return None
    if RAPID_OCR is None:
        RAPID_OCR = RapidOCR()
    return RAPID_OCR


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
            rapid_words, rapid_method = extract_words_rapidocr(page)
            if rapid_words:
                return rapid_words, f"{method};{rapid_method}"
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


def transform_rotated_point(x: float, y: float, angle: int, width: int, height: int) -> tuple[float, float]:
    if angle == 0:
        return x, y
    if angle == 90:
        return width - y, x
    if angle == 180:
        return width - x, height - y
    if angle == 270:
        return y, height - x
    raise ValueError(angle)


def transform_rotated_box(box: list[list[float]], angle: int, width: int, height: int, scale: float) -> list[float]:
    points = [transform_rotated_point(point[0], point[1], angle, width, height) for point in box]
    return [
        min(point[0] for point in points) / scale,
        min(point[1] for point in points) / scale,
        max(point[0] for point in points) / scale,
        max(point[1] for point in points) / scale,
    ]


def rapidocr_rotation_score(result: list) -> float:
    text = " ".join(item[1] for item in (result or [])).upper()
    confidence = sum(float(item[2]) for item in (result or [])) / max(1, len(result or []))
    weighted_terms = {
        "CERTIFIED": 7,
        "TEST REPORT": 10,
        "MATERIAL": 8,
        "SEAMLESS": 7,
        "TUBULAR": 5,
        "GRADE": 8,
        "A106": 12,
        "SA-106": 14,
        "HEAT": 7,
        "CHEM": 8,
        "TENSILE": 8,
        "YIELD": 8,
        "ELONG": 6,
        "MILL": 4,
        "P.O": 3,
        "DATE": 3,
    }
    term_score = sum(weight for term, weight in weighted_terms.items() if term in text)
    if "PAGE" in text[:120]:
        term_score += 2
    return term_score + confidence * 2 + min(len(result or []), 120) / 50


def split_ocr_line_words(text: str, bbox: list[float], page_index: int, line_index: int) -> list[dict]:
    tokens = [token for token in re.split(r"\s+", text.strip()) if token]
    if not tokens:
        return []
    x0, y0, x1, y1 = bbox
    width = max(1.0, x1 - x0)
    total_chars = sum(max(1, len(token)) for token in tokens)
    cursor = x0
    words = []
    for pos, token in enumerate(tokens):
        token_width = width * max(1, len(token)) / total_chars
        words.append(
            {
                "text": token,
                "bbox": [cursor, y0, min(x1, cursor + token_width), y1],
                "block": line_index,
                "line": 0,
                "word": pos,
                "ocr_order": line_index,
                "page_index": page_index,
            }
        )
        cursor += token_width
    return words


def extract_words_rapidocr(page) -> tuple[list[dict], str]:
    ocr = get_rapid_ocr()
    if ocr is None:
        return [], "rapidocr_unavailable"
    scale = 2.0
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
    base = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    best = None
    for angle in [0, 90, 180, 270]:
        image = base.rotate(angle, expand=True)
        result, _elapsed = ocr(np.array(image))
        result = result or []
        score = rapidocr_rotation_score(result)
        if best is None or score > best["score"]:
            best = {"angle": angle, "result": result, "score": score}
    words = []
    for line_index, item in enumerate(best["result"]):
        box, text, score = item
        if float(score) < 0.45:
            continue
        bbox = transform_rotated_box(box, best["angle"], pix.width, pix.height, scale)
        words.extend(split_ocr_line_words(text, bbox, page.number, line_index))
    return words, f"rapidocr_angle_{best['angle']}_score_{best['score']:.2f}_lines_{len(best['result'])}"


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
                "ocr_order": min(word.get("ocr_order", 999999) for word in ordered),
            }
        )
    if any("ocr_order" in word for word in words):
        return sorted(lines, key=lambda item: (item["page_index"], item["ocr_order"]))
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
    heat_numbers = sorted(set(re.findall(r"\bEB\d{3,}\b", upper)))
    explicit_heat = None
    for line in lines:
        line_upper = line["text"].upper()
        if "HEAT AFFECTED ZONE" in line_upper:
            continue
        match = re.search(r"\bHEAT(?:\s*(?:NO|NUMBER|#))?\s*[:#]?\s*([A-Z0-9-]{3,})", line_upper)
        if match and match.group(1) not in {"SEE", "REPORT"}:
            explicit_heat = match.group(1)
            break
    heat = explicit_heat or (heat_numbers[0] if heat_numbers else None)
    return {"specification": spec, "grade": grade, "heat_number": heat, "heat_numbers": heat_numbers}


def apply_target_heat(identity: dict, target_heat: str | None) -> dict:
    if not target_heat:
        return identity
    selected_heat = target_heat.upper()
    heat_numbers = [heat.upper() for heat in identity.get("heat_numbers", [])]
    result = {**identity, "target_heat_number": selected_heat, "target_heat_detected": selected_heat in heat_numbers}
    if result["target_heat_detected"]:
        result["heat_number"] = selected_heat
    return result


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
    tensile_rows = extract_tensile_table_rows(lines)
    if tensile_rows:
        findings["tensile_table_rows"] = tensile_rows
    return findings


def numeric_tokens_by_page(lines: list[dict], page_index: int) -> list[dict]:
    tokens = []
    for line in lines:
        if line["page_index"] != page_index:
            continue
        for word in line["words"]:
            text = word["text"]
            if re.fullmatch(r"\d{2,3},\d{3}", text) or re.fullmatch(r"\d{2}\.\d", text):
                tokens.append({"text": text, "bbox": word["bbox"], "page_index": page_index})
    return tokens


def extract_tensile_table_rows(lines: list[dict]) -> list[dict]:
    rows = []
    by_page = sorted(set(line["page_index"] for line in lines))
    for page_index in by_page:
        page_text = " ".join(line["text"].upper() for line in lines if line["page_index"] == page_index)
        if "TENSILE" not in page_text or "YIELD" not in page_text or "ELONG" not in page_text:
            continue
        page_lines = [line for line in lines if line["page_index"] == page_index]
        heat_ids = []
        pipe_ids = []
        for line in page_lines:
            for word in line["words"]:
                token = clean_token(word["text"])
                if re.fullmatch(r"EB\d{3,}", token):
                    heat_ids.append({"value": token, "bbox": word["bbox"], "page_index": page_index})
                elif re.fullmatch(r"\d{4}", token):
                    value = int(token)
                    if 1000 <= value <= 9999:
                        pipe_ids.append({"value": token, "bbox": word["bbox"], "page_index": page_index})
        nums = numeric_tokens_by_page(lines, page_index)
        strengths = [item for item in nums if "," in item["text"]]
        elongations = [item for item in nums if "." in item["text"] and float(item["text"]) >= 10.0]
        pair_count = len(strengths) // 2
        for idx in range(pair_count):
            first = strengths[idx * 2]
            second = strengths[idx * 2 + 1]
            first_value = parse_strength_number(first["text"])
            second_value = parse_strength_number(second["text"])
            if not first_value or not second_value:
                continue
            tensile, yield_strength = (first, second) if first_value["psi"] >= second_value["psi"] else (second, first)
            row = {
                "row_index": idx + 1,
                "heat": heat_ids[idx]["value"] if idx < len(heat_ids) else None,
                "pipe": pipe_ids[idx]["value"] if idx < len(pipe_ids) else None,
                "tensile_strength": {
                    **parse_strength_number(tensile["text"]),
                    "page_index": page_index,
                    "bbox": tensile["bbox"],
                },
                "yield_strength": {
                    **parse_strength_number(yield_strength["text"]),
                    "page_index": page_index,
                    "bbox": yield_strength["bbox"],
                },
                "elongation": None,
            }
            if idx < len(elongations):
                row["elongation"] = {
                    "raw": elongations[idx]["text"],
                    "value": float(elongations[idx]["text"]),
                    "page_index": page_index,
                    "bbox": elongations[idx]["bbox"],
                }
            rows.append(row)
    return rows


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


def compare_strength_rows(metadata: dict, grade: str, rows: list[dict]) -> dict:
    strength = metadata["mechanical_requirements"]["strength"][grade]
    items = []
    for row in rows:
        for key, req_key in [("tensile_strength", "tensile_strength_min"), ("yield_strength", "yield_strength_min")]:
            extracted = row.get(key)
            req = strength[req_key]
            item = {
                "field": f"row_{row['row_index']}_{key}",
                "requirement": {"rule": "min", "psi": req["psi"]},
                "extracted": extracted,
                "heat": row.get("heat"),
                "pipe": row.get("pipe"),
            }
            if not extracted or "psi" not in extracted:
                item["status"] = "missing"
            else:
                item["status"] = "pass" if extracted["psi"] >= req["psi"] else "fail"
            items.append(item)
        if row.get("elongation"):
            items.append(
                {
                    "field": f"row_{row['row_index']}_elongation",
                    "status": "needs_review",
                    "extracted": row["elongation"],
                    "heat": row.get("heat"),
                    "pipe": row.get("pipe"),
                    "reason": metadata["mechanical_requirements"]["elongation"]["auto_check_status"],
                }
            )
        else:
            items.append({"field": f"row_{row['row_index']}_elongation", "status": "missing", "heat": row.get("heat"), "pipe": row.get("pipe")})
    statuses = {item["status"] for item in items}
    status = "fail" if "fail" in statuses else "needs_review" if statuses & {"missing", "needs_review"} else "pass"
    return {"status": status, "items": items}


def compare_mechanical(metadata: dict, identity: dict, mechanical: dict, target_heat: str | None = None) -> dict:
    grade = identity.get("grade")
    target_rows = mechanical.get("tensile_table_rows", [])
    if target_heat:
        selected_heat = target_heat.upper()
        target_rows = [row for row in target_rows if (row.get("heat") or "").upper() == selected_heat]
        if not target_rows:
            parsed_heats = sorted({row.get("heat") for row in mechanical.get("tensile_table_rows", []) if row.get("heat")})
            return {
                "status": "needs_review",
                "reason": "target_heat_not_found_in_tensile_rows",
                "target_heat": selected_heat,
                "parsed_heats": parsed_heats,
                "items": [],
            }
    if grade not in {"A", "B", "C"}:
        items = []
        for row in target_rows:
            for field in ["tensile_strength", "yield_strength", "elongation"]:
                extracted = row.get(field)
                if extracted:
                    items.append(
                        {
                            "field": f"row_{row['row_index']}_{field}",
                            "status": "needs_review",
                            "extracted": extracted,
                            "reason": "missing_or_unsupported_grade",
                            "heat": row.get("heat"),
                            "pipe": row.get("pipe"),
                        }
                    )
        return {"status": "needs_review", "reason": "missing_or_unsupported_grade", "items": items}
    if target_rows:
        return compare_strength_rows(metadata, grade, target_rows)
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
    parser.add_argument("--start-page", type=int, default=1, help="1-based first PDF page to process.")
    parser.add_argument("--end-page", type=int, default=None, help="1-based last PDF page to process.")
    parser.add_argument("--target-heat", default=None, help="Limit mechanical row checks/highlights to this heat/product identifier.")
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
        page_number = page_index + 1
        if page_number < args.start_page:
            continue
        if args.end_page is not None and page_number > args.end_page:
            continue
        words, method = extract_words(page, args.force_ocr)
        page_methods.append({"page_index": page_index, "method": method, "word_count": len(words)})
        all_lines.extend(build_lines(words, page_index))

    identity = apply_target_heat(extract_identity(all_lines), args.target_heat)
    chemistry = extract_chemistry(all_lines)
    mechanical = extract_mechanical(all_lines)
    report = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "mtr_path": str(mtr_path),
        "metadata_path": str(metadata_path),
        "page_filter": {"start_page": args.start_page, "end_page": args.end_page, "target_heat": args.target_heat},
        "page_methods": page_methods,
        "identity": identity,
        "chemistry_extraction": chemistry,
        "mechanical_extraction": mechanical,
        "chemistry_check": compare_chemistry(metadata, identity, chemistry),
        "mechanical_check": compare_mechanical(metadata, identity, mechanical, args.target_heat),
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
