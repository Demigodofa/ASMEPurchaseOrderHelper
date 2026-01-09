import csv
import json
import os
import pathlib
import re
import subprocess
import statistics
from datetime import datetime, timezone

from PIL import Image
import pytesseract


ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / "sectionII_partA_data_digitized"
BEST_TEXT_DIR = DATA / "best_text" / "pages"
PAGES_DIR = DATA / "pages"
OUTPUT_DIR = DATA / "footnote_review"
OUTPUT_REPORT = OUTPUT_DIR / "footnote_review_report.csv"
OUTPUT_INDEX = OUTPUT_DIR / "footnote_review_report.json"

APPSETTINGS = ROOT / "PoApp.Ingest.Cli" / "appsettings.json"
TOC_INDEX = DATA / "toc_index_pass10.json"
CROSSREF = DATA / "crossref_pass9.json"

DEFAULT_TESSERACT = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

NOTE_LINE_RE = re.compile(r"^\s*NOTE\s*(\d+)\b", re.IGNORECASE)
NOTE_REF_RE = re.compile(r"\bNote\s+(?P<num>\d+)\b", re.IGNORECASE)
FOOTNOTE_MARK_RE = re.compile(r"^\s*[\d\u00B9\u00B2\u00B3\u2070\u2074\u2075\u2076\u2077\u2078\u2079]+")


def configure_tesseract():
    cmd = os.environ.get("TESSERACT_CMD")
    if cmd and pathlib.Path(cmd).exists():
        pytesseract.pytesseract.tesseract_cmd = cmd
        return
    if pathlib.Path(DEFAULT_TESSERACT).exists():
        pytesseract.pytesseract.tesseract_cmd = DEFAULT_TESSERACT


def get_poppler_bin():
    poppler = ROOT / "tools" / "poppler" / "poppler-25.12.0" / "Library" / "bin"
    if poppler.exists():
        return poppler
    return None


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8", errors="ignore"))


def load_pdf_map():
    if not APPSETTINGS.exists():
        return {}
    settings = load_json(APPSETTINGS)
    paths = settings.get("Paths", {})
    pdf_files = paths.get("PdfFiles", [])
    pdf_root = paths.get("PdfSourceRoot")

    pdf_map = {}
    for path in pdf_files:
        if not path:
            continue
        p = pathlib.Path(path)
        if p.exists():
            pdf_map[p.name] = p

    if pdf_root:
        root = pathlib.Path(pdf_root)
        if root.exists():
            for p in root.glob("*.pdf"):
                pdf_map.setdefault(p.name, p)

    return pdf_map


def load_ranges():
    toc = load_json(TOC_INDEX)
    ranges = []
    for e in toc.get("entries", []):
        start = e.get("startGlobalPage")
        end = e.get("rangeEndGlobalPage")
        if start is None or end is None or end < start:
            continue
        ranges.append({"spec": e.get("spec"), "start": start, "end": end})
    return ranges


def find_spec_range(ranges, page):
    for r in ranges:
        if r["start"] <= page <= r["end"]:
            return r
    return None


def raster_page(pdf_path, page_num, out_path, dpi=300):
    poppler_bin = get_poppler_bin()
    if not poppler_bin:
        raise RuntimeError("Poppler not installed. Run scripts/install_poppler.ps1 first.")
    pdftoppm = poppler_bin / "pdftoppm.exe"
    if not pdftoppm.exists():
        raise RuntimeError("pdftoppm.exe not found in Poppler bin.")
    base = out_path.with_suffix("")
    subprocess.run(
        [
            str(pdftoppm),
            "-r",
            str(dpi),
            "-f",
            str(page_num),
            "-l",
            str(page_num),
            "-png",
            str(pdf_path),
            str(base),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    candidates = list(out_path.parent.glob(base.name + "-*.png"))
    if not candidates:
        raise RuntimeError(f"Raster missing for page {page_num}")
    return candidates[0]


def extract_footer(image, height_ratio=0.25):
    width, height = image.size
    y0 = int(height * (1 - height_ratio))
    return image.crop((0, y0, width, height))


def has_note_block(text, note_num):
    for line in text.splitlines():
        match = NOTE_LINE_RE.match(line.strip())
        if match and match.group(1) == str(note_num):
            return True
    return False


def footer_candidate(text):
    lines = text.splitlines()
    tail = lines[-40:] if len(lines) > 40 else lines
    for line in tail:
        if FOOTNOTE_MARK_RE.match(line.strip()):
            return True
    return False


def score_footer_superscripts(tsv_text):
    lines = tsv_text.splitlines()
    if not lines:
        return {
            "score": 0.0,
            "digitCount": 0,
            "digitSet": "",
            "smallDigitCount": 0,
            "avgConf": None,
        }

    header = lines[0].split("\t")
    cols = {name: idx for idx, name in enumerate(header)}
    digit_tokens = []
    heights = []

    for line in lines[1:]:
        parts = line.split("\t")
        if len(parts) <= max(cols.values()):
            continue
        text = parts[cols["text"]].strip()
        conf = parts[cols["conf"]].strip()
        if not text or conf == "-1":
            continue
        try:
            height = int(parts[cols["height"]])
        except ValueError:
            continue
        heights.append(height)
        if re.fullmatch(r"\d+", text):
            try:
                conf_val = float(conf)
            except ValueError:
                conf_val = None
            digit_tokens.append((text, height, conf_val))

    if not heights or not digit_tokens:
        return {
            "score": 0.0,
            "digitCount": 0,
            "digitSet": "",
            "smallDigitCount": 0,
            "avgConf": None,
        }

    median_height = statistics.median(heights)
    small_threshold = max(6, int(median_height * 0.6))
    digit_set = {t for t, _, _ in digit_tokens}
    small_digits = [t for t, h, _ in digit_tokens if h <= small_threshold]
    conf_vals = [c for _, _, c in digit_tokens if c is not None]
    avg_conf = statistics.mean(conf_vals) if conf_vals else None

    digit_count_score = min(1.0, len(digit_tokens) / 3.0)
    conf_score = (avg_conf / 100.0) if avg_conf is not None else 0.0
    small_score = len(small_digits) / max(1, len(digit_tokens))
    diversity_bonus = 0.1 if len(digit_set) >= 3 else 0.0

    score = min(1.0, 0.5 * digit_count_score + 0.3 * conf_score + 0.2 * small_score + diversity_bonus)

    return {
        "score": round(score, 3),
        "digitCount": len(digit_tokens),
        "digitSet": ",".join(sorted(digit_set)),
        "smallDigitCount": len(small_digits),
        "avgConf": round(avg_conf, 1) if avg_conf is not None else None,
    }


def main():
    configure_tesseract()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    pdf_map = load_pdf_map()
    ranges = load_ranges()
    crossref = load_json(CROSSREF)

    report_rows = []
    json_rows = []

    for gap in crossref.get("noteRefGaps", []):
        page_idx = gap.get("globalPageIndex")
        if page_idx is None:
            continue
        text_path = BEST_TEXT_DIR / f"page-{page_idx:04d}.txt"
        if not text_path.exists():
            continue
        text = text_path.read_text(encoding="utf-8", errors="ignore")

        ref = gap.get("reference") or ""
        note_match = NOTE_REF_RE.search(ref)
        note_num = note_match.group("num") if note_match else ""

        note_block_present = has_note_block(text, note_num) if note_num else False
        footnote_hint = footer_candidate(text)
        if note_block_present:
            continue

        spec_range = find_spec_range(ranges, page_idx)
        spec = spec_range["spec"] if spec_range else "UNMAPPED"
        toc_page = page_idx - spec_range["start"] + 1 if spec_range else ""

        source_pdf = gap.get("sourcePdf")
        source_page = gap.get("sourcePageNumber")
        pdf_path = pdf_map.get(pathlib.Path(source_pdf).name) if source_pdf else None
        if not pdf_path or not pdf_path.exists():
            continue

        page_dir = OUTPUT_DIR / spec
        page_dir.mkdir(parents=True, exist_ok=True)
        base_name = f"{spec}-page-{page_idx:04d}-src{source_page}"
        full_path = page_dir / f"{base_name}.png"
        footer_path = page_dir / f"{base_name}-footer.png"
        footer_txt = page_dir / f"{base_name}-footer.txt"
        footer_tsv = page_dir / f"{base_name}-footer.tsv"

        if not full_path.exists():
            full_path = raster_page(pdf_path, source_page, full_path)

        image = Image.open(full_path)
        footer = extract_footer(image)
        footer.save(footer_path)

        footer_text = pytesseract.image_to_string(footer, config="--psm 6")
        footer_txt.write_text(footer_text, encoding="utf-8")
        footer_tsv_text = pytesseract.image_to_data(
            footer, config="--psm 6", output_type=pytesseract.Output.STRING
        )
        footer_tsv.write_text(footer_tsv_text, encoding="utf-8")
        superscore = score_footer_superscripts(footer_tsv_text)

        row = {
            "Spec": spec,
            "TOC_Page": toc_page,
            "Global_Page": page_idx,
            "Reference": ref,
            "Note_Number": note_num,
            "Source_PDF": source_pdf,
            "Source_Page": source_page,
            "Footnote_Candidate": "yes" if footnote_hint else "no",
            "Superscript_Score": superscore["score"],
            "Superscript_Digits": superscore["digitSet"],
            "Superscript_Digit_Count": superscore["digitCount"],
            "Superscript_Small_Digit_Count": superscore["smallDigitCount"],
            "Superscript_Avg_Conf": superscore["avgConf"],
            "Footer_Image": str(footer_path.relative_to(DATA)),
            "Full_Image": str(full_path.relative_to(DATA)),
            "Footer_Text": footer_text.strip().replace("\n", " ")[:200],
        }
        report_rows.append(row)
        json_rows.append(row)

    report_rows.sort(key=lambda r: (r["Spec"], r["TOC_Page"] if r["TOC_Page"] != "" else 99999))

    with OUTPUT_REPORT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "Spec",
                "TOC_Page",
                "Global_Page",
                "Reference",
                "Note_Number",
                "Source_PDF",
                "Source_Page",
                "Footnote_Candidate",
                "Superscript_Score",
                "Superscript_Digits",
                "Superscript_Digit_Count",
                "Superscript_Small_Digit_Count",
                "Superscript_Avg_Conf",
                "Footer_Image",
                "Full_Image",
                "Footer_Text",
            ],
        )
        writer.writeheader()
        writer.writerows(report_rows)

    OUTPUT_INDEX.write_text(
        json.dumps(
            {
                "createdUtc": datetime.now(timezone.utc).isoformat(),
                "count": len(json_rows),
                "items": json_rows,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print("Footnote review report complete.")


if __name__ == "__main__":
    main()
