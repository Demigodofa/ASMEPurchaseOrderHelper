import json
import os
import pathlib
import re
from datetime import datetime, timezone
from difflib import SequenceMatcher

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / "sectionII_partA_data_digitized"

PDF_NAME = "2025 OCR SECT II PART A BEGINNING TO SA-450.pdf"
MANIFEST_PATH = DATA / "manifest.json"
DEFAULT_ABBYY_MANIFEST_PATH = DATA / "abbyy_docx" / "abbyy_docx_manifest.json"
ABBYY_MANIFEST_PATH = pathlib.Path(
    os.environ.get("ABBYY_DOCX_MANIFEST", DEFAULT_ABBYY_MANIFEST_PATH)
)
TESSERACT_LOG = DATA / "tesseract_abbyy" / "tesseract_abbyy_passA1.json"
SPEC_RANGE_PATH = DATA / "spec_range_pass11.json"
TOC_INDEX_PATH = DATA / "toc_index_pass10.json"

OUTPUT_DIR = DATA / os.environ.get("ABBYY_TRUTH_OUTPUT", "truth_abbyy")
PAGES_DIR = OUTPUT_DIR / "pages"
OUTPUT_LOG = OUTPUT_DIR / "truth_merge_passA2.json"

SIMILARITY_THRESHOLD = float(os.environ.get("ABBYY_TRUTH_SIM_THRESHOLD", "0.95"))
ALIGN_WINDOW = int(os.environ.get("ABBYY_ALIGN_WINDOW", "20"))
ALIGN_MIN_SIM = float(os.environ.get("ABBYY_ALIGN_MIN_SIM", "0.6"))
MAX_NORM_LEN = int(os.environ.get("ABBYY_SIM_MAX_CHARS", "8000"))


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_text(text):
    if not text:
        return ""
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if MAX_NORM_LEN > 0:
        return text[:MAX_NORM_LEN]
    return text


def similarity(a, b):
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def load_manifest_pages():
    manifest = load_json(MANIFEST_PATH)
    pages = [
        page
        for page in manifest.get("pages", [])
        if page.get("sourcePdf") == PDF_NAME
    ]
    return sorted(pages, key=lambda p: p["globalPageIndex"])


def load_abbyy_pages():
    manifest = load_json(ABBYY_MANIFEST_PATH)
    pages = []
    for page in manifest.get("pages", []):
        text_path = DATA / page["textPath"]
        text = text_path.read_text(encoding="utf-8") if text_path.exists() else ""
        pages.append(
            {
                "abbyyPageIndex": page["abbyyPageIndex"],
                "textPath": page["textPath"],
                "text": text,
                "norm": normalize_text(text),
            }
        )
    return pages


def load_tesseract_pages():
    log = load_json(TESSERACT_LOG)
    pages = {}
    for entry in log.get("pages", []):
        if "textPath" not in entry:
            continue
        text_path = DATA / entry["textPath"]
        text = text_path.read_text(encoding="utf-8") if text_path.exists() else ""
        pages[entry["globalPageIndex"]] = {
            "textPath": entry["textPath"],
            "text": text,
            "norm": normalize_text(text),
        }
    return pages


def build_spec_range_set():
    if not SPEC_RANGE_PATH.exists():
        return set()
    data = load_json(SPEC_RANGE_PATH)
    allowed = set()
    for item in data.get("ranges", []):
        start = item.get("startGlobalPage")
        end = item.get("endGlobalPage")
        if not start or not end or end < start:
            continue
        allowed.update(range(start, end + 1))
    return allowed


def load_toc_starts():
    if not TOC_INDEX_PATH.exists():
        return set(), set()
    data = load_json(TOC_INDEX_PATH)
    toc_starts = set()
    specs = set()
    for entry in data.get("entries", []):
        if entry.get("startSourcePdf") != PDF_NAME:
            continue
        if entry.get("startGlobalPage"):
            toc_starts.add(entry["startGlobalPage"])
        if entry.get("spec"):
            specs.add(entry["spec"].upper())
    return toc_starts, specs


def has_spec_header(text, expected_specs):
    if not text:
        return False
    sample = text[:800].upper()
    for spec in expected_specs:
        if spec in sample:
            return True
    return bool(re.search(r"\bSA-\d{1,4}[A-Z]?\b", sample))


def align_pages(pdf_pages, abbyy_pages, tesseract_pages):
    alignments = []
    abbyy_idx = 0
    skipped_abbyy = []
    for pdf_page in pdf_pages:
        if abbyy_idx >= len(abbyy_pages):
            alignments.append((pdf_page, None, 0.0))
            continue
        pdf_norm = tesseract_pages.get(pdf_page["globalPageIndex"], {}).get("norm", "")
        window_end = min(len(abbyy_pages), abbyy_idx + ALIGN_WINDOW)
        best_sim = -1.0
        best_offset = None
        for offset in range(0, window_end - abbyy_idx):
            abbyy_page = abbyy_pages[abbyy_idx + offset]
            sim = similarity(abbyy_page["norm"], pdf_norm)
            if sim > best_sim:
                best_sim = sim
                best_offset = offset
        if best_sim >= ALIGN_MIN_SIM and best_offset is not None:
            if best_offset > 0:
                skipped_abbyy.extend(abbyy_pages[abbyy_idx : abbyy_idx + best_offset])
            abbyy_page = abbyy_pages[abbyy_idx + best_offset]
            alignments.append((pdf_page, abbyy_page, best_sim))
            abbyy_idx = abbyy_idx + best_offset + 1
        else:
            alignments.append((pdf_page, None, best_sim if best_sim > 0 else 0.0))
    remaining_abbyy = abbyy_pages[abbyy_idx:]
    return alignments, skipped_abbyy, remaining_abbyy


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    PAGES_DIR.mkdir(parents=True, exist_ok=True)

    pdf_pages = load_manifest_pages()
    abbyy_pages = load_abbyy_pages()
    tesseract_pages = load_tesseract_pages()
    spec_range = build_spec_range_set()
    toc_starts, expected_specs = load_toc_starts()

    alignments, skipped_abbyy, remaining_abbyy = align_pages(
        pdf_pages, abbyy_pages, tesseract_pages
    )

    accepted = 0
    unresolved = 0
    output_entries = []

    for pdf_page, abbyy_page, align_sim in alignments:
        global_idx = pdf_page["globalPageIndex"]
        tesseract = tesseract_pages.get(global_idx)
        abbyy_text = abbyy_page["text"] if abbyy_page else ""
        tesseract_text = tesseract["text"] if tesseract else ""
        page_similarity = similarity(
            abbyy_page["norm"] if abbyy_page else "",
            tesseract["norm"] if tesseract else "",
        )
        anchors = []
        if global_idx in spec_range:
            anchors.append("specRange")
        if global_idx in toc_starts:
            anchors.append("tocStart")
        if has_spec_header(abbyy_text, expected_specs):
            anchors.append("specHeader")

        decision = "rejected"
        chosen_source = None
        if page_similarity >= SIMILARITY_THRESHOLD and len(anchors) >= 2:
            decision = "accepted"
            chosen_source = "abbyy"
            out_path = PAGES_DIR / f"page-{global_idx:04d}.txt"
            out_path.write_text(abbyy_text, encoding="utf-8")
            accepted += 1
        else:
            unresolved += 1

        output_entries.append(
            {
                "globalPageIndex": global_idx,
                "sourcePageNumber": pdf_page["sourcePageNumber"],
                "abbyyPageIndex": abbyy_page["abbyyPageIndex"] if abbyy_page else None,
                "abbyyTextPath": abbyy_page["textPath"] if abbyy_page else None,
                "tesseractTextPath": tesseract["textPath"] if tesseract else None,
                "alignSimilarity": round(align_sim, 4),
                "pageSimilarity": round(page_similarity, 4),
                "anchors": anchors,
                "decision": decision,
                "chosenSource": chosen_source,
            }
        )

    result = {
        "createdUtc": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "pdfPages": len(pdf_pages),
            "abbyyPages": len(abbyy_pages),
            "accepted": accepted,
            "unresolved": unresolved,
            "skippedAbbyyPages": len(skipped_abbyy),
            "remainingAbbyyPages": len(remaining_abbyy),
            "similarityThreshold": SIMILARITY_THRESHOLD,
            "alignWindow": ALIGN_WINDOW,
            "alignMinSimilarity": ALIGN_MIN_SIM,
        },
        "skippedAbbyyPages": [
            {"abbyyPageIndex": p["abbyyPageIndex"], "textPath": p["textPath"]}
            for p in skipped_abbyy
        ],
        "remainingAbbyyPages": [
            {"abbyyPageIndex": p["abbyyPageIndex"], "textPath": p["textPath"]}
            for p in remaining_abbyy
        ],
        "pages": output_entries,
    }
    OUTPUT_LOG.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print("Truth merge pass A2 complete.")


if __name__ == "__main__":
    main()
